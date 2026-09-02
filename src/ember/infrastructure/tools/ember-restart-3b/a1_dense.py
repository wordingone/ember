# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Dense A1 comparator identity and architecture carrier."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.checkpoint as checkpoint_utils

from model import RMSNorm, RawAudioProjector, RawPatchProjector, SharedAttention


class A1Tier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class A1Mechanism(str, Enum):
    FULL_STATE_ADAMW_CPU_OFFLOAD = "FULL_STATE_ADAMW_CPU_OFFLOAD"
    OWNED_Q_GALORE_PROJECTED_GRADIENT = "OWNED_Q_GALORE_PROJECTED_GRADIENT"


class A1RefusalCode(str, Enum):
    A1_TIER_TYPE_INVALID = "A1_TIER_TYPE_INVALID"
    A1_MECHANISM_TYPE_INVALID = "A1_MECHANISM_TYPE_INVALID"
    A1_TIER_MECHANISM_MISMATCH = "A1_TIER_MECHANISM_MISMATCH"
    A1_PARAMETER_COUNT_TYPE_INVALID = "A1_PARAMETER_COUNT_TYPE_INVALID"
    A1_PARAMETER_FLOOR_NOT_MET = "A1_PARAMETER_FLOOR_NOT_MET"
    A1_PARAMETER_INVENTORY_MISMATCH = "A1_PARAMETER_INVENTORY_MISMATCH"
    A1_THRESHOLD_DOC_SHA_MISMATCH = "A1_THRESHOLD_DOC_SHA_MISMATCH"
    A1_THRESHOLD_SCHEMA_INVALID = "A1_THRESHOLD_SCHEMA_INVALID"
    A1_THRESHOLD_VALUE_TYPE_INVALID = "A1_THRESHOLD_VALUE_TYPE_INVALID"
    A1_T09_STEPS_MISMATCH = "A1_T09_STEPS_MISMATCH"
    A1_CONFIG_SHA_MISMATCH = "A1_CONFIG_SHA_MISMATCH"
    A1_OPTIMIZER_CONTRACT_INVALID = "A1_OPTIMIZER_CONTRACT_INVALID"
    A1_OPTIMIZER_STATE_INCOMPLETE = "A1_OPTIMIZER_STATE_INCOMPLETE"


class A1Refusal(ValueError):
    def __init__(self, code: A1RefusalCode, detail: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {detail}")


_MECHANISM_BY_TIER = {
    A1Tier.TIER_1: A1Mechanism.FULL_STATE_ADAMW_CPU_OFFLOAD,
    A1Tier.TIER_2: A1Mechanism.OWNED_Q_GALORE_PROJECTED_GRADIENT,
}


def require_tier_mechanism(tier: object, mechanism: object) -> tuple[A1Tier, A1Mechanism]:
    if not isinstance(tier, A1Tier):
        raise A1Refusal(A1RefusalCode.A1_TIER_TYPE_INVALID, "tier must be an A1Tier")
    if not isinstance(mechanism, A1Mechanism):
        raise A1Refusal(
            A1RefusalCode.A1_MECHANISM_TYPE_INVALID,
            "mechanism must be an A1Mechanism",
        )
    if _MECHANISM_BY_TIER[tier] is not mechanism:
        raise A1Refusal(
            A1RefusalCode.A1_TIER_MECHANISM_MISMATCH,
            "mechanism is not authorized for the selected tier",
        )
    return tier, mechanism


_CONTRACT_FIELDS = {
    "goal_id",
    "workstream_id",
    "next_executed_outcome",
    "schema_version",
    "architecture_revision",
    "comparison_arm",
    "model",
    "training_state",
    "thresholds",
    "lineage",
    "authority",
}
_MODEL_FIELDS = {
    "hidden_size",
    "layers",
    "attention_heads",
    "vocab_size",
    "image_input_shape",
    "audio_frame_samples",
    "gradient_checkpointing",
    "tied_embeddings",
    "total_unique_trainable_parameters",
    "assertion_minimum_unique_trainable_parameters",
}
_THRESHOLD_FIELDS = {"path", "sha256", "required_ids"}
_AUTHORITY_FIELDS = {
    "goal_id",
    "workstream_id",
    "next_executed_outcome",
    "execution_authority",
    "claim_boundary",
}
_EXPECTED_THRESHOLD_PATH = "docs/domains/governance/spec/ember02-preregistration-thresholds-v1.json"
_EXPECTED_THRESHOLD_IDS = ("T-08", "T-09", "T-20")
A1_CONFIG_SHA256 = "563331b746619788f01900f4d951df29e4c6549c937a4662bac76234f5d71edc"
_LINEAGE_FIELDS = {
    "parent_checkpoint",
    "initialization",
    "borrowed_weights",
    "teacher_outputs",
    "model_derived_data",
    "external_judges",
}
_CLEAN_LINEAGE = {
    "parent_checkpoint": None,
    "initialization": "random",
    "borrowed_weights": False,
    "teacher_outputs": False,
    "model_derived_data": False,
    "external_judges": False,
}


def _refuse(code: A1RefusalCode, detail: str) -> None:
    raise A1Refusal(code, detail)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise A1Refusal(
            A1RefusalCode.A1_THRESHOLD_DOC_SHA_MISMATCH,
            "canonical threshold bytes are unavailable",
        ) from error


def require_a1_config_sha256(path: Path) -> None:
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise A1Refusal(A1RefusalCode.A1_CONFIG_SHA_MISMATCH, "A1 config bytes are unavailable") from error
    if actual != A1_CONFIG_SHA256:
        _refuse(A1RefusalCode.A1_CONFIG_SHA_MISMATCH, "A1 config bytes drifted from the consuming-code pin")


def require_clean_a1_lineage(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != _LINEAGE_FIELDS or value != _CLEAN_LINEAGE:
        _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "A1 clean-random lineage drifted")


def _closed_mapping(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        _refuse(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, f"{label} has an invalid closed schema")
    return value


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int:
        _refuse(A1RefusalCode.A1_PARAMETER_COUNT_TYPE_INVALID, f"{field} must be an integer")
    if value < 1:
        _refuse(A1RefusalCode.A1_PARAMETER_FLOOR_NOT_MET, f"{field} must be positive")
    return value


def _threshold_decimal(value: object, threshold_id: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _refuse(
            A1RefusalCode.A1_THRESHOLD_VALUE_TYPE_INVALID,
            f"{threshold_id} must be a JSON number",
        )
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as error:
        raise A1Refusal(
            A1RefusalCode.A1_THRESHOLD_VALUE_TYPE_INVALID,
            f"{threshold_id} is not a finite decimal",
        ) from error
    if not decimal.is_finite():
        _refuse(A1RefusalCode.A1_THRESHOLD_VALUE_TYPE_INVALID, f"{threshold_id} is not finite")
    return format(decimal, "f")


def _load_thresholds(repo_root: Path, contract: Mapping[str, Any]) -> tuple[str, int, str]:
    threshold = _closed_mapping(contract, _THRESHOLD_FIELDS, "threshold binding")
    if threshold["path"] != _EXPECTED_THRESHOLD_PATH or threshold["required_ids"] != list(_EXPECTED_THRESHOLD_IDS):
        _refuse(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, "threshold identity or required IDs drifted")
    path = repo_root / _EXPECTED_THRESHOLD_PATH
    expected_sha = threshold["sha256"]
    if not isinstance(expected_sha, str) or _sha256(path) != expected_sha:
        _refuse(A1RefusalCode.A1_THRESHOLD_DOC_SHA_MISMATCH, "canonical threshold digest drifted")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise A1Refusal(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, "threshold document is not JSON") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "ember02-preregistration-thresholds-v1" or payload.get("frozen") is not True:
        _refuse(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, "threshold document authority drifted")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        _refuse(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, "threshold entries are missing")
    indexed: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("id"), str) or entry["id"] in indexed:
            _refuse(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, "threshold entries are not uniquely keyed")
        indexed[entry["id"]] = entry
    if any(identifier not in indexed for identifier in _EXPECTED_THRESHOLD_IDS):
        _refuse(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, "required A1 thresholds are absent")
    t08 = _threshold_decimal(indexed["T-08"].get("value"), "T-08")
    t09_value = indexed["T-09"].get("value")
    if type(t09_value) is not int or t09_value < 1:
        _refuse(A1RefusalCode.A1_THRESHOLD_VALUE_TYPE_INVALID, "T-09 must be a positive integer")
    t20 = _threshold_decimal(indexed["T-20"].get("value"), "T-20")
    return t08, t09_value, t20


@dataclass(frozen=True)
class DenseA1Config:
    hidden_size: int
    layers: int
    attention_heads: int
    vocab_size: int
    image_input_shape: tuple[int, int, int] = (48, 48, 3)
    audio_frame_samples: int = 640
    gradient_checkpointing: bool = True
    tied_embeddings: bool = True
    production: bool = False
    declared_total_unique_trainable_parameters: int | None = None
    assertion_minimum_unique_trainable_parameters: int = 3_000_000_000
    t08_liveness_floor: str = "0.33"
    t09_matched_steps: int = 100
    t20_sigma_multiplier: str = "2"

    def __post_init__(self) -> None:
        for field, value in (
            ("hidden_size", self.hidden_size),
            ("layers", self.layers),
            ("attention_heads", self.attention_heads),
            ("vocab_size", self.vocab_size),
            ("assertion_minimum_unique_trainable_parameters", self.assertion_minimum_unique_trainable_parameters),
        ):
            _positive_int(value, field)
        if self.hidden_size % self.attention_heads or (self.hidden_size // self.attention_heads) % 4:
            _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "dense attention geometry is invalid")
        if tuple(self.image_input_shape) != (48, 48, 3) or self.audio_frame_samples != 640:
            _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "raw modality geometry drifted")
        if not self.tied_embeddings:
            _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "dense A1 requires tied embeddings")
        if self.production:
            declared = self.declared_total_unique_trainable_parameters
            if type(declared) is not int:
                _refuse(A1RefusalCode.A1_PARAMETER_COUNT_TYPE_INVALID, "declared total must be an integer")
            if declared < self.assertion_minimum_unique_trainable_parameters:
                _refuse(A1RefusalCode.A1_PARAMETER_FLOOR_NOT_MET, "dense A1 is below the 3B floor")
            if declared != self.structural_parameter_count():
                _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "declared total differs from dense structure")

    def structural_parameter_count(self) -> int:
        hidden = self.hidden_size
        head_dim = hidden // self.attention_heads
        per_layer = 4 * hidden * hidden + 12 * hidden * hidden + 2 * hidden + 2 * head_dim
        return (
            self.vocab_size * hidden
            + self.layers * per_layer
            + math.prod(self.image_input_shape) * hidden
            + self.audio_frame_samples * hidden
            + hidden
        )

    @classmethod
    def from_contract(cls, path: str | Path | None = None, *, repo_root: Path | None = None) -> "DenseA1Config":
        contract_path = Path(path) if path is not None else Path(__file__).with_name("ember-restart-3b-a1.json")
        root = Path(repo_root) if repo_root is not None else next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
        try:
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise A1Refusal(A1RefusalCode.A1_THRESHOLD_SCHEMA_INVALID, "A1 contract is unavailable or invalid") from error
        contract = _closed_mapping(payload, _CONTRACT_FIELDS, "A1 contract")
        if (
            contract["goal_id"] != "EMBER-02"
            or contract["workstream_id"] != "EMBER-02B"
            or contract["next_executed_outcome"] != "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
            or contract["schema_version"] != "ember-restart-3b-a1-dense-v1"
            or contract["architecture_revision"] != "ember-dense-a1-3b-v1"
            or contract["comparison_arm"] != "A1"
        ):
            _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "A1 architecture identity drifted")
        authority = _closed_mapping(contract["authority"], _AUTHORITY_FIELDS, "A1 authority")
        if (
            authority["goal_id"] != contract["goal_id"]
            or authority["workstream_id"] != contract["workstream_id"]
            or authority["next_executed_outcome"] != contract["next_executed_outcome"]
            or authority["execution_authority"] != "certified_launch_only"
            or authority["claim_boundary"] != "source_carrier_only_until_real_dense_execution"
        ):
            _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "A1 authority binding drifted")
        require_clean_a1_lineage(contract["lineage"])
        model = _closed_mapping(contract["model"], _MODEL_FIELDS, "A1 model")
        declared = model["total_unique_trainable_parameters"]
        if type(declared) is not int:
            _refuse(A1RefusalCode.A1_PARAMETER_COUNT_TYPE_INVALID, "declared total must be an integer")
        t08, t09, t20 = _load_thresholds(root, contract["thresholds"])
        if model["gradient_checkpointing"] is not True:
            _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "dense A1 requires gradient checkpointing enabled")
        config = cls(
            hidden_size=_positive_int(model["hidden_size"], "hidden_size"),
            layers=_positive_int(model["layers"], "layers"),
            attention_heads=_positive_int(model["attention_heads"], "attention_heads"),
            vocab_size=_positive_int(model["vocab_size"], "vocab_size"),
            image_input_shape=tuple(model["image_input_shape"]),
            audio_frame_samples=_positive_int(model["audio_frame_samples"], "audio_frame_samples"),
            gradient_checkpointing=True,
            tied_embeddings=model["tied_embeddings"] is True,
            production=True,
            declared_total_unique_trainable_parameters=declared,
            assertion_minimum_unique_trainable_parameters=_positive_int(model["assertion_minimum_unique_trainable_parameters"], "assertion_minimum_unique_trainable_parameters"),
            t08_liveness_floor=t08,
            t09_matched_steps=t09,
            t20_sigma_multiplier=t20,
        )
        require_a1_config_sha256(contract_path)
        return config

    @classmethod
    def small_for_tests(cls) -> "DenseA1Config":
        return cls(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)


class DenseSwiGLU(nn.Module):
    """Owned ancestry-clean dense FFN with matched 4H SwiGLU math."""

    def __init__(self, hidden_size: int, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.up_gate = nn.Linear(hidden_size, 8 * hidden_size, bias=False, device=device)
        self.down = nn.Linear(4 * hidden_size, hidden_size, bias=False, device=device)

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        up, gate = self.up_gate(hidden_states).chunk(2, dim=-1)
        return self.down(F.silu(gate) * up)


class _DenseA1Layer(nn.Module):
    def __init__(self, config: DenseA1Config, *, device: torch.device | str | None = None) -> None:
        super().__init__()
        self.pre_attention_norm = RMSNorm(config.hidden_size, device=device)
        self.attention = SharedAttention(config, device=device)
        self.pre_ffn_norm = RMSNorm(config.hidden_size, device=device)
        self.ffn = DenseSwiGLU(config.hidden_size, device=device)

    def forward(self, hidden_states: torch.Tensor, coordinates: torch.Tensor, allowed: torch.Tensor) -> torch.Tensor:
        hidden_states = hidden_states + self.attention(self.pre_attention_norm(hidden_states), coordinates, allowed)
        return hidden_states + self.ffn(self.pre_ffn_norm(hidden_states))


class DenseA1Decoder(nn.Module):
    """Owned dense comparator; every decoder layer and FFN is active every step."""

    def __init__(self, config: DenseA1Config, *, device: str | torch.device | None = None, allow_production_allocation: bool = False, genesis_seed: int | None = None) -> None:
        super().__init__()
        target_device = torch.device(device) if device is not None else torch.device("cpu")
        if config.production and target_device.type != "meta" and not allow_production_allocation:
            _refuse(A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH, "production allocation requires certified launch authority")
        if genesis_seed is not None:
            if type(genesis_seed) is not int or genesis_seed < 0:
                _refuse(A1RefusalCode.A1_PARAMETER_COUNT_TYPE_INVALID, "genesis seed must be a nonnegative integer")
            torch.manual_seed(genesis_seed)
        self.config = config
        self.token_embedding = nn.Embedding(config.vocab_size, config.hidden_size, device=target_device)
        self.image_projector = RawPatchProjector(config, device=target_device)
        self.audio_projector = RawAudioProjector(config, device=target_device)
        self.layers = nn.ModuleList([_DenseA1Layer(config, device=target_device) for _ in range(config.layers)])
        self.final_norm = RMSNorm(config.hidden_size, device=target_device)
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False, device=target_device)
        self.lm_head.weight = self.token_embedding.weight
        if target_device.type != "meta":
            for module in self.modules():
                if isinstance(module, (nn.Linear, nn.Embedding)):
                    nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        if input_ids.ndim != 2:
            raise ValueError("input_ids must have shape [batch, sequence]")
        batch, sequence = input_ids.shape
        positions = torch.arange(sequence, device=input_ids.device)
        coordinates = torch.stack((positions, positions), dim=-1).expand(batch, -1, -1)
        allowed = (positions.unsqueeze(0) <= positions.unsqueeze(1)).expand(batch, -1, -1)
        hidden_states = self.token_embedding(input_ids)
        for layer in self.layers:
            if self.config.gradient_checkpointing and self.training:
                hidden_states = checkpoint_utils.checkpoint(
                    lambda states, current=layer: current(states, coordinates, allowed),
                    hidden_states,
                    use_reentrant=False,
                )
            else:
                hidden_states = layer(hidden_states, coordinates, allowed)
        return self.lm_head(self.final_norm(hidden_states))
