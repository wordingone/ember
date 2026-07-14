# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Small-test and guarded production shape for the owned restart decoder.

The production shape is deliberately constructed only when explicitly allowed,
or on the ``meta`` device for shape/count validation.  All parameters are
freshly initialized by PyTorch; no checkpoint or teacher state is accepted.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.checkpoint as checkpoint_utils


@dataclass(frozen=True)
class RestartDecoderConfig:
    """Architecture and clean-genesis metadata for the unified decoder."""

    hidden_size: int
    layers: int
    attention_heads: int
    vocab_size: int
    image_input_shape: tuple[int, int, int] = (48, 48, 3)
    audio_frame_samples: int = 640
    gradient_checkpointing: bool = True
    tied_embeddings: bool = True
    image_token_id: int | None = None
    audio_token_id: int | None = None
    contract_name: str = "ember-restart-3b"
    contract_version: int = 1
    production: bool = False
    declared_unique_trainable_parameters: int | None = None
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
        if self.hidden_size <= 0 or self.layers <= 0 or self.vocab_size <= 0:
            raise ValueError("hidden_size, layers, and vocab_size must be positive")
        if self.attention_heads <= 0 or self.hidden_size % self.attention_heads:
            raise ValueError("hidden_size must be divisible by attention_heads")
        if not self.tied_embeddings:
            raise ValueError("the restart decoder requires tied input/output embeddings")
        if tuple(self.image_input_shape) != (48, 48, 3):
            raise ValueError("restart decoder image input must be a raw 48x48x3 patch")
        if self.audio_frame_samples != 640:
            raise ValueError("restart decoder audio input must be a raw 640-sample frame")
        if self.image_token_id is None:
            object.__setattr__(self, "image_token_id", self.vocab_size - 2)
        if self.audio_token_id is None:
            object.__setattr__(self, "audio_token_id", self.vocab_size - 1)
        marker_ids = (self.image_token_id, self.audio_token_id)
        if any(marker_id is None or marker_id < 0 or marker_id >= self.vocab_size for marker_id in marker_ids):
            raise ValueError("modality marker IDs must be nonnegative vocabulary IDs")
        if self.image_token_id == self.audio_token_id:
            raise ValueError("image and audio marker IDs must be distinct")

    @classmethod
    def from_contract(cls, path: str | Path | None = None) -> "RestartDecoderConfig":
        """Load the role-named production JSON contract and verify its count."""

        contract_path = (
            Path(path)
            if path is not None
            else Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
        )
        with contract_path.open(encoding="utf-8") as handle:
            contract = json.load(handle)

        model = contract["model"]
        image = model["image_projection"]
        audio = model["audio_projection"]
        config = cls(
            hidden_size=int(model["hidden_size"]),
            layers=int(model["layers"]),
            attention_heads=int(model["attention_heads"]),
            vocab_size=int(model["vocab_size"]),
            image_input_shape=tuple(int(v) for v in image["input_shape"]),
            audio_frame_samples=int(audio["frame_samples"]),
            gradient_checkpointing=bool(contract["training"]["gradient_checkpointing"]),
            tied_embeddings=bool(model["tied_embeddings"]),
            contract_name=str(contract["contract_name"]),
            contract_version=int(contract["contract_version"]),
            production=True,
            declared_unique_trainable_parameters=int(model["unique_trainable_parameters"]),
            lineage=dict(contract["lineage"]),
        )
        if config.calculate_unique_trainable_parameters() != config.declared_unique_trainable_parameters:
            raise ValueError("production contract parameter count does not match its formula")
        if config.declared_unique_trainable_parameters < int(
            model["assertion_minimum_unique_trainable_parameters"]
        ):
            raise ValueError("production contract is below its declared parameter floor")
        if config.declared_unique_trainable_parameters < 3_000_000_000:
            raise ValueError("production contract must allocate at least 3,000,000,000 parameters")
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
        """Return a CPU-cheap shape that preserves production input contracts."""

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
    def num_layers(self) -> int:
        return self.layers

    @property
    def num_heads(self) -> int:
        return self.attention_heads

    @property
    def image_patch_size(self) -> tuple[int, int, int]:
        return self.image_input_shape

    @property
    def unique_trainable_parameters(self) -> int:
        return self.calculate_unique_trainable_parameters()

    def parameter_count(self) -> int:
        return self.unique_trainable_parameters

    def calculate_unique_trainable_parameters(self) -> int:
        """Recompute the contract's tied-embedding + decoder + projector count."""

        hidden = self.hidden_size
        image_input = math.prod(self.image_input_shape)
        return (
            self.vocab_size * hidden
            + self.layers * (4 * hidden * hidden + 12 * hidden * hidden)
            + image_input * hidden
            + self.audio_frame_samples * hidden
        )

    def genesis_metadata(self, seed: int = 0) -> dict[str, Any]:
        """Return deterministic metadata describing clean random initialization."""

        return {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "seed": int(seed),
            "parent_checkpoint": self.lineage.get("parent_checkpoint"),
            "initialization": self.lineage.get("initialization", "random"),
            "borrowed_weights": bool(self.lineage.get("borrowed_weights", False)),
            "teacher_outputs": bool(self.lineage.get("teacher_outputs", False)),
            "model_derived_data": bool(self.lineage.get("model_derived_data", False)),
            "external_judges": bool(self.lineage.get("external_judges", False)),
        }


class _RawProjector(nn.Module):
    """Bias-free linear projection that preserves leading sample dimensions."""

    input_shape: tuple[int, ...]

    def __init__(self, config: RestartDecoderConfig, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        input_size = math.prod(self.input_shape)
        self.linear = nn.Linear(input_size, config.hidden_size, bias=False, device=device)

    @property
    def weight(self) -> nn.Parameter:
        return self.linear.weight

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        if not torch.is_tensor(values):
            raise TypeError("raw modality values must be torch tensors")
        input_size = math.prod(self.input_shape)
        suffix_size = len(self.input_shape)
        if values.ndim >= suffix_size and tuple(values.shape[-suffix_size:]) == self.input_shape:
            leading = tuple(values.shape[:-suffix_size])
        elif values.ndim >= 1 and values.shape[-1] == input_size:
            leading = tuple(values.shape[:-1])
        elif values.numel() == input_size:
            leading = ()
        else:
            raise ValueError(
                f"expected raw input ending in {self.input_shape} or flattened size {input_size}, "
                f"got {tuple(values.shape)}"
            )
        projected = self.linear(values.reshape(-1, input_size))
        return projected.reshape(*leading, projected.shape[-1]) if leading else projected.reshape(-1)


class RawPatchProjector(_RawProjector):
    """Trainable bias-free projector for raw 48x48x3 RGB patches."""

    input_shape = (48, 48, 3)


class RawAudioProjector(_RawProjector):
    """Trainable bias-free projector for raw 640-sample audio frames."""

    input_shape = (640,)


class _DecoderLayer(nn.Module):
    def __init__(self, config: RestartDecoderConfig, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        hidden = config.hidden_size
        intermediate = 4 * hidden
        self.heads = config.attention_heads
        self.head_dim = hidden // self.heads
        self.q_proj = nn.Linear(hidden, hidden, bias=False, device=device)
        self.k_proj = nn.Linear(hidden, hidden, bias=False, device=device)
        self.v_proj = nn.Linear(hidden, hidden, bias=False, device=device)
        self.o_proj = nn.Linear(hidden, hidden, bias=False, device=device)
        self.gate_proj = nn.Linear(hidden, intermediate, bias=False, device=device)
        self.up_proj = nn.Linear(hidden, intermediate, bias=False, device=device)
        self.down_proj = nn.Linear(intermediate, hidden, bias=False, device=device)

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        batch, sequence, hidden = hidden_states.shape
        q = self.q_proj(hidden_states).view(batch, sequence, self.heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(hidden_states).view(batch, sequence, self.heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(hidden_states).view(batch, sequence, self.heads, self.head_dim).transpose(1, 2)
        attended = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        attended = attended.transpose(1, 2).contiguous().view(batch, sequence, hidden)
        hidden_states = hidden_states + self.o_proj(attended)
        gated = F.silu(self.gate_proj(hidden_states)) * self.up_proj(hidden_states)
        return hidden_states + self.down_proj(gated)


class UnifiedDecoder(nn.Module):
    """Causal decoder accepting text IDs plus raw image/audio marker values."""

    def __init__(
        self,
        config: RestartDecoderConfig,
        *,
        allow_production_materialization: bool = False,
        device: torch.device | str | None = None,
    ) -> None:
        super().__init__()
        target_device = torch.device("cpu" if device is None else device)
        if config.production and target_device.type != "meta" and not allow_production_materialization:
            raise ValueError(
                "production decoder materialization is guarded; pass "
                "allow_production_materialization=True or use device='meta'"
            )

        self.config = config
        self.image_token_id = int(config.image_token_id)
        self.audio_token_id = int(config.audio_token_id)
        self.token_embedding = nn.Embedding(config.vocab_size, config.hidden_size, device=target_device)
        self.layers = nn.ModuleList(
            [_DecoderLayer(config, device=target_device) for _ in range(config.layers)]
        )
        self.image_projector = RawPatchProjector(config, device=target_device)
        self.audio_projector = RawAudioProjector(config, device=target_device)
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False, device=target_device)
        if config.tied_embeddings:
            self.lm_head.weight = self.token_embedding.weight
        self.genesis_metadata = config.genesis_metadata()

    def count_unique_trainable_parameters(self) -> int:
        """Count trainable Parameter objects once, including tied embeddings once."""

        seen: set[int] = set()
        count = 0
        for parameter in self.parameters():
            if parameter.requires_grad and id(parameter) not in seen:
                seen.add(id(parameter))
                count += parameter.numel()
        return count

    def _inject_modality(
        self,
        hidden_states: torch.Tensor,
        input_ids: torch.Tensor,
        *,
        marker_id: int,
        raw_values: torch.Tensor | None,
        projector: _RawProjector,
        name: str,
    ) -> torch.Tensor:
        marker_mask = input_ids.eq(marker_id)
        marker_count = int(marker_mask.sum().item())
        if raw_values is None:
            if marker_count:
                raise ValueError(f"{name} marker requires corresponding raw modality values")
            return hidden_states
        if marker_count == 0:
            raise ValueError(f"raw {name} values were supplied but no {name} marker is present")
        projected = projector(raw_values).reshape(-1, self.config.hidden_size)
        if projected.shape[0] != marker_count:
            raise ValueError(
                f"{name} value count ({projected.shape[0]}) does not match marker count ({marker_count})"
            )
        flat_hidden = hidden_states.reshape(-1, self.config.hidden_size)
        flat_mask = marker_mask.reshape(-1)
        marker_indices = flat_mask.nonzero(as_tuple=False).flatten()
        flat_hidden = flat_hidden.index_copy(
            0, marker_indices, projected.to(device=flat_hidden.device, dtype=flat_hidden.dtype)
        )
        return flat_hidden.reshape_as(hidden_states)

    def forward(
        self,
        input_ids: torch.Tensor,
        image_patches: torch.Tensor | None = None,
        audio_frames: torch.Tensor | None = None,
    ) -> torch.Tensor:
        if input_ids.ndim != 2:
            raise ValueError("input_ids must have shape [batch, sequence]")
        hidden_states = self.token_embedding(input_ids)
        hidden_states = self._inject_modality(
            hidden_states,
            input_ids,
            marker_id=self.image_token_id,
            raw_values=image_patches,
            projector=self.image_projector,
            name="image",
        )
        hidden_states = self._inject_modality(
            hidden_states,
            input_ids,
            marker_id=self.audio_token_id,
            raw_values=audio_frames,
            projector=self.audio_projector,
            name="audio",
        )
        for layer in self.layers:
            if self.config.gradient_checkpointing and self.training:
                hidden_states = checkpoint_utils.checkpoint(layer, hidden_states, use_reentrant=False)
            else:
                hidden_states = layer(hidden_states)
        return self.lm_head(hidden_states)


def count_unique_trainable_parameters(subject: nn.Module | RestartDecoderConfig) -> int:
    """Return the unique trainable parameter count for a config or module."""

    if isinstance(subject, RestartDecoderConfig):
        return subject.parameter_count()
    unique = {id(parameter): parameter for parameter in subject.parameters()}
    return sum(parameter.numel() for parameter in unique.values() if parameter.requires_grad)
