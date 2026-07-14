# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Sparse clean-genesis unified decoder for the authorized Ember 3B rung.

The production shape is meta-validatable but allocation-guarded. Every learned
parameter is freshly initialized: raw RGB patches and raw audio frames are
projected directly into decoder soft tokens, and a declared expert is selected
locally per episode/batch without pretrained encoders or learned external
routing signals.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.checkpoint as checkpoint_utils

EXPERT_NAMES = ("vision", "audio", "reasoning", "tool")


@dataclass(frozen=True)
class MultimodalSpan:
    """An explicit contiguous multimodal span and its attention policy."""

    start: int
    length: int
    modality: str
    attention_mode: str = "causal"

    def __post_init__(self) -> None:
        if self.start < 0 or self.length <= 0:
            raise ValueError("span start must be nonnegative and length must be positive")
        if self.modality not in {"image", "audio", "text"}:
            raise ValueError("span modality must be image, audio, or text")
        if self.attention_mode not in {"causal", "isolated"}:
            raise ValueError("span attention_mode must be causal or isolated")


@dataclass(frozen=True)
class RestartDecoderConfig:
    """Clean-genesis sparse decoder architecture and provenance contract."""

    hidden_size: int
    layers: int
    attention_heads: int
    vocab_size: int
    image_input_shape: tuple[int, int, int] = (48, 48, 3)
    audio_frame_samples: int = 640
    gradient_checkpointing: bool = True
    tied_embeddings: bool = True
    expert_names: tuple[str, ...] = EXPERT_NAMES
    default_active_expert: str = "reasoning"
    image_token_id: int | None = None
    audio_token_id: int | None = None
    contract_name: str = "ember-restart-3b"
    contract_version: int = 2
    production: bool = False
    declared_total_unique_trainable_parameters: int | None = None
    lineage: Mapping[str, Any] = field(
        default_factory=lambda: {
            "parent_checkpoint": None,
            "initialization": "random",
            "borrowed_weights": False,
            "teacher_outputs": False,
            "model_derived_data": False,
            "external_judges": False,
        }
    )

    def __post_init__(self) -> None:
        if self.hidden_size <= 0 or self.layers <= 0 or self.vocab_size < 3:
            raise ValueError("hidden_size, layers, and a vocab of at least three are required")
        if self.attention_heads <= 0 or self.hidden_size % self.attention_heads:
            raise ValueError("hidden_size must be divisible by attention_heads")
        if (self.hidden_size // self.attention_heads) % 4:
            raise ValueError("head dimension must be divisible by four for 2D RoPE")
        if not self.tied_embeddings:
            raise ValueError("the restart decoder requires tied input/output embeddings")
        if tuple(self.image_input_shape) != (48, 48, 3):
            raise ValueError("restart decoder image input must be a raw 48x48x3 patch")
        if self.audio_frame_samples != 640:
            raise ValueError("restart decoder audio input must be a raw 640-sample frame")
        if tuple(self.expert_names) != EXPERT_NAMES:
            raise ValueError("the four declared asymmetric expert banks are required")
        if self.default_active_expert not in self.expert_names:
            raise ValueError("default active expert must be declared")
        if self.image_token_id is None:
            object.__setattr__(self, "image_token_id", self.vocab_size - 2)
        if self.audio_token_id is None:
            object.__setattr__(self, "audio_token_id", self.vocab_size - 1)
        markers = (self.image_token_id, self.audio_token_id)
        if any(marker is None or marker < 0 or marker >= self.vocab_size for marker in markers):
            raise ValueError("modality marker IDs must be nonnegative vocabulary IDs")
        if self.image_token_id == self.audio_token_id:
            raise ValueError("image and audio marker IDs must be distinct")

    @classmethod
    def from_contract(cls, path: str | Path | None = None) -> "RestartDecoderConfig":
        contract_path = (
            Path(path)
            if path is not None
            else Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
        )
        with contract_path.open(encoding="utf-8") as handle:
            contract = json.load(handle)
        if contract.get("architecture_revision") != "ember-sparse-3b-v2":
            raise ValueError("production contract must declare ember-sparse-3b-v2")
        model = contract["model"]
        image = model["image_projection"]
        audio = model["audio_projection"]
        routing = model["expert_routing"]
        if routing.get("shared_text_ffn") != "always_active_SwiGLU_4H":
            raise ValueError("production contract must declare an always-active shared nonlinear text FFN")
        config = cls(
            hidden_size=int(model["hidden_size"]),
            layers=int(model["layers"]),
            attention_heads=int(model["attention_heads"]),
            vocab_size=int(model["vocab_size"]),
            image_input_shape=tuple(int(value) for value in image["input_shape"]),
            audio_frame_samples=int(audio["frame_samples"]),
            gradient_checkpointing=bool(contract["training"]["gradient_checkpointing"]),
            tied_embeddings=bool(model["tied_embeddings"]),
            expert_names=tuple(routing["expert_names"]),
            default_active_expert=str(routing["default_active_expert"]),
            contract_name=str(contract["contract_name"]),
            contract_version=int(contract["contract_version"]),
            production=True,
            declared_total_unique_trainable_parameters=int(model["total_unique_trainable_parameters"]),
            lineage=dict(contract["lineage"]),
        )
        declared = config.declared_total_unique_trainable_parameters
        if declared is None or declared < 3_000_000_000:
            raise ValueError("production contract must allocate at least 3,000,000,000 parameters")
        if declared != config.structural_parameter_count():
            raise ValueError("production contract total does not match the sparse architecture")
        if int(image["output_size"]) != config.hidden_size or int(audio["output_size"]) != config.hidden_size:
            raise ValueError("modality projectors must emit decoder-width soft tokens")
        return config

    @classmethod
    def small_for_tests(
        cls,
        *,
        hidden_size: int = 32,
        layers: int = 2,
        attention_heads: int = 4,
        vocab_size: int = 64,
        gradient_checkpointing: bool = True,
    ) -> "RestartDecoderConfig":
        return cls(
            hidden_size=hidden_size,
            layers=layers,
            attention_heads=attention_heads,
            vocab_size=vocab_size,
            gradient_checkpointing=gradient_checkpointing,
            contract_name="ember-restart-small-test",
            production=False,
        )

    @property
    def total_unique_trainable_parameters(self) -> int:
        return self.structural_parameter_count()

    def parameter_count(self) -> int:
        return self.total_unique_trainable_parameters

    def structural_parameter_count(self) -> int:
        hidden = self.hidden_size
        image_input = math.prod(self.image_input_shape)
        per_layer = 4 * hidden * hidden + (1 + len(self.expert_names)) * 12 * hidden * hidden + 2 * hidden
        return (
            self.vocab_size * hidden
            + self.layers * per_layer
            + image_input * hidden
            + self.audio_frame_samples * hidden
            + hidden
        )

    def calculate_unique_trainable_parameters(self) -> int:
        """Compatibility alias for the sparse structural count."""
        return self.structural_parameter_count()

    def genesis_metadata(self, seed: int | None = None) -> dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "seed": None if seed is None else int(seed),
            "parent_checkpoint": self.lineage.get("parent_checkpoint"),
            "initialization": self.lineage.get("initialization", "random"),
            "borrowed_weights": bool(self.lineage.get("borrowed_weights", False)),
            "teacher_outputs": bool(self.lineage.get("teacher_outputs", False)),
            "model_derived_data": bool(self.lineage.get("model_derived_data", False)),
            "external_judges": bool(self.lineage.get("external_judges", False)),
        }


class RMSNorm(nn.Module):
    def __init__(self, hidden_size: int, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(hidden_size, device=device))

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        scale = torch.rsqrt(hidden_states.pow(2).mean(dim=-1, keepdim=True) + 1e-6)
        return hidden_states * scale * self.weight


class RawPatchProjector(nn.Module):
    def __init__(self, config: RestartDecoderConfig, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.linear = nn.Linear(math.prod(config.image_input_shape), config.hidden_size, bias=False, device=device)

    def forward(self, patches: torch.Tensor) -> torch.Tensor:
        if tuple(patches.shape[-3:]) != (48, 48, 3):
            raise ValueError("image patches must end with [48, 48, 3]")
        raw = patches.reshape(*patches.shape[:-3], -1).to(dtype=self.linear.weight.dtype).div(255.0).sub(0.5)
        return F.layer_norm(self.linear(raw), (self.linear.out_features,))


class RawAudioProjector(nn.Module):
    def __init__(self, config: RestartDecoderConfig, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.linear = nn.Linear(config.audio_frame_samples, config.hidden_size, bias=False, device=device)

    def forward(self, frames: torch.Tensor) -> torch.Tensor:
        if frames.shape[-1] != 640:
            raise ValueError("audio frames must end with 640 raw samples")
        return F.layer_norm(self.linear(frames.to(dtype=self.linear.weight.dtype)), (self.linear.out_features,))


class RotaryCoordinates(nn.Module):
    """Parameter-free 1D text/audio and 2D image rotary coordinates."""

    def __init__(self, head_dim: int) -> None:
        super().__init__()
        self.head_dim = head_dim
        self.axis_dim = head_dim // 2

    def apply(self, values: torch.Tensor, coordinates: torch.Tensor) -> torch.Tensor:
        chunks = values.split(self.axis_dim, dim=-1)
        rotated: list[torch.Tensor] = []
        base = torch.arange(0, self.axis_dim, 2, device=values.device, dtype=torch.float32)
        frequencies = torch.pow(10000.0, -base / self.axis_dim)
        for axis, chunk in enumerate(chunks):
            angle = coordinates[..., axis].to(torch.float32).unsqueeze(-1) * frequencies
            cos = angle.cos().to(chunk.dtype).unsqueeze(1)
            sin = angle.sin().to(chunk.dtype).unsqueeze(1)
            even = chunk[..., 0::2]
            odd = chunk[..., 1::2]
            rotated_axis = torch.stack((even * cos - odd * sin, even * sin + odd * cos), dim=-1)
            rotated.append(rotated_axis.flatten(-2))
        return torch.cat(rotated, dim=-1)


class SharedAttention(nn.Module):
    def __init__(self, config: RestartDecoderConfig, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.heads = config.attention_heads
        self.head_dim = config.hidden_size // config.attention_heads
        self.qkv = nn.Linear(config.hidden_size, 3 * config.hidden_size, bias=False, device=device)
        self.output = nn.Linear(config.hidden_size, config.hidden_size, bias=False, device=device)
        self.rope = RotaryCoordinates(self.head_dim)

    def forward(self, hidden_states: torch.Tensor, coordinates: torch.Tensor, allowed: torch.Tensor) -> torch.Tensor:
        batch, sequence, width = hidden_states.shape
        qkv = self.qkv(hidden_states).view(batch, sequence, 3, self.heads, self.head_dim)
        query, key, value = qkv.unbind(dim=2)
        query = self.rope.apply(query.transpose(1, 2), coordinates)
        key = self.rope.apply(key.transpose(1, 2), coordinates)
        value = value.transpose(1, 2)
        attended = F.scaled_dot_product_attention(query, key, value, attn_mask=allowed.unsqueeze(1), is_causal=False)
        return self.output(attended.transpose(1, 2).reshape(batch, sequence, width))


class SwiGLUExpert(nn.Module):
    """One independently trainable 4H SwiGLU expert bank."""

    def __init__(self, hidden_size: int, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.up_gate = nn.Linear(hidden_size, 8 * hidden_size, bias=False, device=device)
        self.down = nn.Linear(4 * hidden_size, hidden_size, bias=False, device=device)

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        up, gate = self.up_gate(hidden_states).chunk(2, dim=-1)
        return self.down(F.silu(gate) * up)


class _DecoderLayer(nn.Module):
    def __init__(self, config: RestartDecoderConfig, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.pre_attention_norm = RMSNorm(config.hidden_size, device=device)
        self.attention = SharedAttention(config, device=device)
        self.pre_ffn_norm = RMSNorm(config.hidden_size, device=device)
        self.shared_ffn = SwiGLUExpert(config.hidden_size, device=device)
        self.experts = nn.ModuleDict({name: SwiGLUExpert(config.hidden_size, device=device) for name in config.expert_names})

    def forward(self, hidden_states: torch.Tensor, coordinates: torch.Tensor, allowed: torch.Tensor, active_expert: str) -> torch.Tensor:
        hidden_states = hidden_states + self.attention(self.pre_attention_norm(hidden_states), coordinates, allowed)
        hidden_states = hidden_states + self.shared_ffn(self.pre_ffn_norm(hidden_states))
        if active_expert == "shared":
            return hidden_states
        return hidden_states + self.experts[active_expert](self.pre_ffn_norm(hidden_states))


class UnifiedDecoder(nn.Module):
    """Routed causal decoder with raw multimodal soft-token injection."""

    def __init__(self, config: RestartDecoderConfig, *, device: str | torch.device | None = None, allow_production_allocation: bool = False, genesis_seed: int | None = None) -> None:
        super().__init__()
        target_device = torch.device(device) if device is not None else torch.device("cpu")
        if genesis_seed is not None:
            if not isinstance(genesis_seed, int) or genesis_seed < 0:
                raise ValueError("genesis_seed must be a nonnegative integer")
            torch.manual_seed(genesis_seed)
            if target_device.type == "cuda":
                torch.cuda.manual_seed_all(genesis_seed)
        if config.production and target_device.type != "meta" and not allow_production_allocation:
            raise ValueError("production allocation requires explicit measured-launch authorization")
        self.config = config
        self.token_embedding = nn.Embedding(config.vocab_size, config.hidden_size, device=target_device)
        self.image_projector = RawPatchProjector(config, device=target_device)
        self.audio_projector = RawAudioProjector(config, device=target_device)
        self.layers = nn.ModuleList([_DecoderLayer(config, device=target_device) for _ in range(config.layers)])
        self.final_norm = RMSNorm(config.hidden_size, device=target_device)
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False, device=target_device)
        self.lm_head.weight = self.token_embedding.weight
        self._initialize_clean_genesis()
        self.active_expert = config.default_active_expert
        self._activate_expert(self.active_expert)
        self.genesis_metadata = config.genesis_metadata(genesis_seed)

    def _initialize_clean_genesis(self) -> None:
        """Use transformer-scale random init instead of framework embedding defaults."""
        for module in self.modules():
            if isinstance(module, (nn.Linear, nn.Embedding)) and module.weight.device.type != "meta":
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
            elif isinstance(module, RMSNorm) and module.weight.device.type != "meta":
                nn.init.ones_(module.weight)
    def _activate_expert(self, active_expert: str) -> None:
        if active_expert != "shared" and active_expert not in self.config.expert_names:
            raise ValueError(f"unknown declared expert: {active_expert}")
        self.active_expert = active_expert
        for layer in self.layers:
            for parameter in layer.shared_ffn.parameters():
                parameter.requires_grad_(True)
            for name, expert in layer.experts.items():
                for parameter in expert.parameters():
                    parameter.requires_grad_(active_expert != "shared" and name == active_expert)

    def count_unique_trainable_parameters(self, *, include_frozen: bool = False) -> int:
        return count_unique_trainable_parameters(self, include_frozen=include_frozen)

    def expert_bank_genesis_hashes(self) -> dict[str, str]:
        """Hash the freshly initialized parameters for each declared expert bank."""

        hashes: dict[str, str] = {}
        for name in self.config.expert_names:
            digest = hashlib.sha256()
            for layer in self.layers:
                for parameter in layer.experts[name].parameters():
                    if parameter.device.type == "meta":
                        raise ValueError("expert genesis hashes require materialized parameters")
                    digest.update(parameter.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
            hashes[name] = digest.hexdigest()
        if len(set(hashes.values())) != len(hashes):
            raise RuntimeError("random genesis produced non-distinct expert-bank hashes")
        return hashes

    def build_attention_mask(
        self,
        *,
        batch_size: int,
        sequence_length: int,
        spans: Sequence[MultimodalSpan] | None,
        device: torch.device,
    ) -> torch.Tensor:
        positions = torch.arange(sequence_length, device=device)
        allowed = positions.unsqueeze(0) <= positions.unsqueeze(1)
        allowed = allowed.expand(batch_size, -1, -1).clone()
        for span in spans or ():
            end = span.start + span.length
            if end > sequence_length:
                raise ValueError("multimodal span exceeds sequence length")
            if span.attention_mode == "isolated":
                allowed[:, span.start:end, span.start:end] = True
        return allowed

    def _inject_modality(
        self,
        hidden_states: torch.Tensor,
        input_ids: torch.Tensor,
        *,
        marker_id: int,
        raw_values: torch.Tensor | None,
        projector: nn.Module,
        name: str,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        mask = input_ids.eq(marker_id)
        count = int(mask.sum().item())
        if raw_values is None:
            if count:
                raise ValueError(f"{name} marker requires corresponding raw modality values")
            return hidden_states, mask
        if not count:
            raise ValueError(f"raw {name} values were supplied but no {name} marker is present")
        projected = projector(raw_values).reshape(-1, self.config.hidden_size)
        if projected.shape[0] != count:
            raise ValueError(f"{name} value count does not match {name} marker count")
        flat = hidden_states.reshape(-1, self.config.hidden_size)
        flat = flat.index_copy(0, mask.reshape(-1).nonzero(as_tuple=False).flatten(), projected.to(hidden_states.dtype))
        return flat.reshape_as(hidden_states), mask

    def _coordinates(
        self,
        input_ids: torch.Tensor,
        image_mask: torch.Tensor,
        image_coordinates: torch.Tensor | None,
        position_ids: torch.Tensor | None,
    ) -> torch.Tensor:
        batch, sequence = input_ids.shape
        if position_ids is None:
            position_ids = torch.arange(sequence, device=input_ids.device).expand(batch, -1)
        if position_ids.shape != input_ids.shape:
            raise ValueError("position_ids must match input_ids")
        coordinates = torch.stack((position_ids, torch.zeros_like(position_ids)), dim=-1)
        count = int(image_mask.sum().item())
        if not count:
            if image_coordinates is not None and image_coordinates.numel() != 0:
                raise ValueError("nonempty image coordinates were supplied without image markers")
            return coordinates
        if image_coordinates is None:
            ordinal = torch.arange(count, device=input_ids.device)
            image_coordinates = torch.stack((ordinal.remainder(48), ordinal.div(48, rounding_mode="floor")), dim=-1)
        if image_coordinates.reshape(-1, 2).shape[0] != count:
            raise ValueError("image_coordinates must provide one [x, y] pair per image marker")
        flat = coordinates.reshape(-1, 2)
        return flat.index_copy(0, image_mask.reshape(-1).nonzero(as_tuple=False).flatten(), image_coordinates.reshape(-1, 2).to(coordinates.device)).reshape_as(coordinates)

    def forward(
        self,
        input_ids: torch.Tensor,
        image_patches: torch.Tensor | None = None,
        audio_frames: torch.Tensor | None = None,
        *,
        image_coordinates: torch.Tensor | None = None,
        position_ids: torch.Tensor | None = None,
        spans: Sequence[MultimodalSpan] | None = None,
        active_expert: str | None = None,
    ) -> torch.Tensor:
        if input_ids.ndim != 2:
            raise ValueError("input_ids must have shape [batch, sequence]")
        selected = active_expert or self.active_expert
        self._activate_expert(selected)
        hidden_states = self.token_embedding(input_ids)
        hidden_states, image_mask = self._inject_modality(hidden_states, input_ids, marker_id=self.config.image_token_id, raw_values=image_patches, projector=self.image_projector, name="image")
        hidden_states, _ = self._inject_modality(hidden_states, input_ids, marker_id=self.config.audio_token_id, raw_values=audio_frames, projector=self.audio_projector, name="audio")
        coordinates = self._coordinates(input_ids, image_mask, image_coordinates, position_ids)
        allowed = self.build_attention_mask(batch_size=input_ids.shape[0], sequence_length=input_ids.shape[1], spans=spans, device=input_ids.device)
        for layer in self.layers:
            if self.config.gradient_checkpointing and self.training:
                hidden_states = checkpoint_utils.checkpoint(lambda states, current_layer=layer: current_layer(states, coordinates, allowed, selected), hidden_states, use_reentrant=False)
            else:
                hidden_states = layer(hidden_states, coordinates, allowed, selected)
        return self.lm_head(self.final_norm(hidden_states))


def count_unique_trainable_parameters(subject: nn.Module | RestartDecoderConfig, *, include_frozen: bool = False) -> int:
    """Count unique parameter storage, optionally including episode-frozen banks."""

    if isinstance(subject, RestartDecoderConfig):
        return subject.total_unique_trainable_parameters
    unique = {id(parameter): parameter for parameter in subject.parameters()}
    return sum(parameter.numel() for parameter in unique.values() if include_frozen or parameter.requires_grad)
