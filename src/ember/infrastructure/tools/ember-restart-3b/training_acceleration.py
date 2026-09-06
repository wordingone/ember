# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed, disabled-by-default source carrier for issue #1413 accelerators.

Stage 1 deliberately cannot activate either mechanism.  It freezes the native
FP8 operand/update contract, the future graph-signature census boundary, and
the receipt validators needed before a separately reviewed Stage 2 real-path
measurement may enable them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_POLICY_KEYS = {"schema_version", "enabled", "activation_gate", "fp8", "cuda_graph", "close_gate"}
_FP8_KEYS = {"enabled", "format", "kernel", "required_compute_capability", "sites", "fallback"}
_GRAPH_KEYS = {
    "enabled", "capture_region", "fallback", "signature_census_sha256",
    "checkpoint_rng_policy", "checkpoint_recompute_identity",
}
_CLOSE_KEYS = {"minimum_tokens_per_second_exclusive", "require_both_mechanisms", "maximum_fallbacks"}
_KERNEL_RECEIPT_KEYS = {
    "schema_version", "kernel", "compute_capability", "activation_dtype", "weight_dtype", "output_dtype",
    "activation_operand_layout", "weight_operand_layout", "per_forward_weight_materialization_copies",
    "native_kernel_scaling", "activation_scaling", "weight_scaling", "accumulation_mode",
    "weight_refreshes", "dispatches", "fallbacks",
}
_FP8_INSTALLATION_SCOPE = "final_decoder_layer_shared_swiglu_down_4h_to_h"
_FP8_W2_INSTALLATION_SCOPE = (
    "final_decoder_layer_shared_and_selected_expert_swiglu_down_4h_to_h"
)
_FP8_W2_EXPERT_NAMES = ("vision", "audio", "reasoning", "tool")
_FP8_W2_FINAL_LAYER_INDEX = 13
# issue #2167 (W5): the shared SwiGLU up+gate projection of every decoder layer (weight [8H, H], bias-free).
_FP8_W5_INSTALLATION_SCOPE = "all_decoder_layers_shared_swiglu_up_gate_h_to_8h"
_FP8_W5_LAYER_COUNT = 14
_FP8_ARMS = ("fp8", "bf16")
_CHECKPOINT_IDENTITY_KEYS = {
    "graph_signature_sha256", "fp8_kernel_receipt_sha256", "checkpoint_region_sha256",
}
_STAGE1_POLICY_CONTRACT: dict[str, object] = {
    "schema_version": "ember-training-acceleration-v1",
    "enabled": False,
    "activation_gate": "stage2_real_path_receipt_required",
    "fp8": {
        "enabled": False,
        "format": "float8_e4m3fn",
        "kernel": "torch._scaled_mm",
        "required_compute_capability": "8.9",
        "sites": _FP8_INSTALLATION_SCOPE,
        "fallback": "refuse",
    },
    "cuda_graph": {
        "enabled": False,
        "capture_region": "forward_loss_backward",
        "fallback": "refuse",
        "signature_census_sha256": None,
        "checkpoint_rng_policy": "preserve_rng_state",
        "checkpoint_recompute_identity": "exact_signature_and_kernel_receipts",
    },
    "close_gate": {
        "minimum_tokens_per_second_exclusive": 1000,
        "require_both_mechanisms": True,
        "maximum_fallbacks": 0,
    },
}


def _closed_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} must use the closed key set {sorted(expected)}")


def _sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 64hex")
    return value


@dataclass(frozen=True)
class Stage1Policy:
    enabled: bool
    fp8_enabled: bool
    cuda_graph_enabled: bool
    signature_census_sha256: str | None
    contract: dict[str, object]


def parse_stage1_policy(value: Mapping[str, object]) -> Stage1Policy:
    """Validate the exact Stage 1 config and refuse every activation attempt."""

    if not isinstance(value, Mapping):
        raise ValueError("training acceleration policy must be an object")
    _closed_keys(value, _POLICY_KEYS, label="training acceleration policy")
    fp8 = value["fp8"]
    graph = value["cuda_graph"]
    close = value["close_gate"]
    if not isinstance(fp8, Mapping) or not isinstance(graph, Mapping) or not isinstance(close, Mapping):
        raise ValueError("training acceleration nested policies must be objects")
    _closed_keys(fp8, _FP8_KEYS, label="FP8 policy")
    _closed_keys(graph, _GRAPH_KEYS, label="CUDA graph policy")
    _closed_keys(close, _CLOSE_KEYS, label="close gate")
    if value["schema_version"] != "ember-training-acceleration-v1":
        raise ValueError("training acceleration schema_version must be ember-training-acceleration-v1")
    if value["activation_gate"] != "stage2_real_path_receipt_required":
        raise ValueError("training acceleration activation gate must require a Stage 2 real-path receipt")
    if fp8["format"] != "float8_e4m3fn" or fp8["kernel"] != "torch._scaled_mm":
        raise ValueError("FP8 policy must bind float8_e4m3fn through torch._scaled_mm")
    if fp8["required_compute_capability"] != "8.9" or fp8["sites"] != _FP8_INSTALLATION_SCOPE:
        raise ValueError("FP8 policy must bind the final decoder layer shared SwiGLU 4H-to-H down projection")
    if fp8["fallback"] != "refuse" or graph["fallback"] != "refuse":
        raise ValueError("accelerator fallback policy must refuse")
    if graph["capture_region"] != "forward_loss_backward":
        raise ValueError("CUDA graph capture region must be forward_loss_backward")
    if graph["checkpoint_rng_policy"] != "preserve_rng_state":
        raise ValueError("checkpoint capture must preserve RNG state")
    if graph["checkpoint_recompute_identity"] != "exact_signature_and_kernel_receipts":
        raise ValueError("checkpoint capture must bind exact recompute identity")
    census = graph["signature_census_sha256"]
    if census is not None:
        census = _sha256(census, label="signature census sha256")
    if close != {
        "minimum_tokens_per_second_exclusive": 1000,
        "require_both_mechanisms": True,
        "maximum_fallbacks": 0,
    }:
        raise ValueError("close gate must require both mechanisms, zero fallbacks, and greater than 1000 tok/s")
    if type(value["enabled"]) is not bool or type(fp8["enabled"]) is not bool or type(graph["enabled"]) is not bool:
        raise ValueError("accelerator enabled fields must be booleans")
    if value["enabled"] or fp8["enabled"] or graph["enabled"]:
        raise ValueError("Stage 2 real-path review is required before accelerator activation")
    return Stage1Policy(
        enabled=False,
        fp8_enabled=False,
        cuda_graph_enabled=False,
        signature_census_sha256=census,
        contract=dict(value),
    )


def stage1_policy() -> Stage1Policy:
    """Return the immutable source-bound disabled policy for production preflight."""

    return parse_stage1_policy(copy.deepcopy(_STAGE1_POLICY_CONTRACT))


_SIGNATURE_TENSOR_KEYS = (
    "input_ids",
    "target_ids",
    "image_patches",
    "audio_frames",
    "image_coordinates",
)
_SIGNATURE_CONTRACT_KEYS = {
    "capture_region",
    "gradient_checkpointing",
    "active_expert",
    "tensors",
    "spans",
}
_CENSUS_KEYS = {
    "schema_version",
    "status",
    "source_commit",
    "model_config_sha256",
    "input_identity_sha256",
    "runner_source_sha256",
    "capture_region",
    "activation_enabled",
    "fallbacks",
    "observed_steps",
    "signature_count",
    "approved_signatures",
    "signatures",
    "self_sha256",
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _tensor_descriptor(value: object, *, label: str) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, torch.Tensor):
        raise ValueError(f"{label} must be a tensor or null")
    return {
        "shape": list(value.shape),
        "dtype": str(value.dtype).removeprefix("torch."),
        "device_type": value.device.type,
        "device_index": value.device.index,
        "stride": list(value.stride()),
        "requires_grad": bool(value.requires_grad),
    }


def _span_descriptor(value: object) -> dict[str, object]:
    fields = ("start", "length", "modality", "attention_mode")
    if isinstance(value, Mapping):
        descriptor = {field: value.get(field) for field in fields}
    else:
        descriptor = {field: getattr(value, field, None) for field in fields}
    if (
        type(descriptor["start"]) is not int
        or type(descriptor["length"]) is not int
        or descriptor["start"] < 0
        or descriptor["length"] < 1
        or not isinstance(descriptor["modality"], str)
        or not descriptor["modality"]
        or not isinstance(descriptor["attention_mode"], str)
        or not descriptor["attention_mode"]
    ):
        raise ValueError("training signature span is invalid")
    return descriptor


def _training_step_contract(
    batch: Mapping[str, object], *, gradient_checkpointing: bool,
) -> dict[str, object]:
    """Build the one canonical static contract used by census and activation."""

    if not isinstance(batch, Mapping):
        raise ValueError("training signature batch must be an object")
    active_expert = batch.get("active_expert")
    if not isinstance(active_expert, str) or not active_expert:
        raise ValueError("training signature requires an active expert")
    if type(gradient_checkpointing) is not bool:
        raise ValueError("training signature gradient_checkpointing must be boolean")
    spans = batch.get("spans")
    if not isinstance(spans, Sequence) or isinstance(spans, (str, bytes, bytearray)):
        raise ValueError("training signature spans must be a sequence")
    return {
        "capture_region": "forward_loss_backward",
        "gradient_checkpointing": gradient_checkpointing,
        "active_expert": active_expert,
        "tensors": {
            key: _tensor_descriptor(batch.get(key), label=key)
            for key in _SIGNATURE_TENSOR_KEYS
        },
        "spans": [_span_descriptor(span) for span in spans],
    }


def training_step_signature(
    batch: Mapping[str, object], *, gradient_checkpointing: bool,
) -> dict[str, object]:
    """Hash the static real-batch facts that determine one capture region."""

    contract = _training_step_contract(
        batch, gradient_checkpointing=gradient_checkpointing,
    )
    return {
        "schema_version": "ember-training-step-signature-v1",
        "signature_sha256": hashlib.sha256(_canonical_json(contract)).hexdigest(),
        "contract": contract,
    }


class TrainingSignatureCensus:
    """Observation-only real-path census; it carries no activation authority."""

    def __init__(
        self,
        *,
        source_commit: str,
        model_config_sha256: str,
        input_identity_sha256: str,
        runner_source_sha256: str,
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise ValueError("source commit must be lowercase 40hex")
        self.source_commit = source_commit
        self.model_config_sha256 = _sha256(model_config_sha256, label="model config sha256")
        self.input_identity_sha256 = _sha256(input_identity_sha256, label="input identity sha256")
        self.runner_source_sha256 = _sha256(runner_source_sha256, label="runner source sha256")
        self._observations: dict[str, dict[str, object]] = {}

    def observe(self, value: Mapping[str, object]) -> None:
        if not isinstance(value, Mapping) or set(value) != {"schema_version", "signature_sha256", "contract"}:
            raise ValueError("training step signature must use the closed v1 shape")
        if value["schema_version"] != "ember-training-step-signature-v1":
            raise ValueError("training step signature schema mismatch")
        signature = _sha256(value["signature_sha256"], label="training step signature sha256")
        contract = value["contract"]
        if not isinstance(contract, Mapping) or set(contract) != _SIGNATURE_CONTRACT_KEYS:
            raise ValueError("training step signature contract is not closed")
        if hashlib.sha256(_canonical_json(contract)).hexdigest() != signature:
            raise ValueError("training step signature hash mismatch")
        existing = self._observations.get(signature)
        if existing is None:
            self._observations[signature] = {"signature_sha256": signature, "count": 1, "contract": dict(contract)}
        else:
            existing["count"] = int(existing["count"]) + 1

    def receipt(self) -> dict[str, object]:
        if not self._observations:
            raise RuntimeError("training signature census has no observed real-path steps")
        signatures = [self._observations[key] for key in sorted(self._observations)]
        receipt: dict[str, object] = {
            "schema_version": "ember-training-signature-census-v1",
            "status": "OBSERVED_NOT_ACTIVATED",
            "source_commit": self.source_commit,
            "model_config_sha256": self.model_config_sha256,
            "input_identity_sha256": self.input_identity_sha256,
            "runner_source_sha256": self.runner_source_sha256,
            "capture_region": "forward_loss_backward",
            "activation_enabled": False,
            "fallbacks": 0,
            "observed_steps": sum(int(row["count"]) for row in signatures),
            "signature_count": len(signatures),
            "approved_signatures": [str(row["signature_sha256"]) for row in signatures],
            "signatures": signatures,
        }
        receipt["self_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
        return receipt

    def write_receipt(self, path: Path) -> dict[str, object]:
        receipt = self.receipt()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(receipt, handle, sort_keys=True, indent=2)
                handle.write("\n")
        except FileExistsError as error:
            raise FileExistsError(f"refusing to overwrite training signature census: {path}") from error
        return receipt


def _load_training_signature_census_bytes(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("training signature census is not readable strict JSON") from error
    if not isinstance(value, dict) or set(value) != _CENSUS_KEYS:
        raise ValueError("training signature census must use the closed v1 key set")
    claimed_self = _sha256(value["self_sha256"], label="training signature census self sha256")
    unsigned = dict(value)
    del unsigned["self_sha256"]
    if hashlib.sha256(_canonical_json(unsigned)).hexdigest() != claimed_self:
        raise ValueError("training signature census self hash mismatch")
    if (
        value["schema_version"] != "ember-training-signature-census-v1"
        or value["status"] != "OBSERVED_NOT_ACTIVATED"
        or value["capture_region"] != "forward_loss_backward"
    ):
        raise ValueError("training signature census status is invalid")
    if value["activation_enabled"] is not False or value["fallbacks"] != 0:
        raise ValueError("training signature census cannot activate or fall back")
    signatures = value["signatures"]
    approved = value["approved_signatures"]
    if not isinstance(signatures, list) or not signatures or not isinstance(approved, list):
        raise ValueError("training signature census has no admitted signatures")
    if approved != sorted(approved) or len(set(approved)) != len(approved):
        raise ValueError("training signature census approved signatures are not unique and sorted")
    if value["signature_count"] != len(signatures) or value["signature_count"] != len(approved):
        raise ValueError("training signature census count mismatch")
    observed_steps = 0
    for row, signature in zip(signatures, approved, strict=True):
        if not isinstance(row, dict) or set(row) != {"signature_sha256", "count", "contract"}:
            raise ValueError("training signature census row is not closed")
        if row["signature_sha256"] != signature or type(row["count"]) is not int or row["count"] < 1:
            raise ValueError("training signature census row identity is invalid")
        if hashlib.sha256(_canonical_json(row["contract"])).hexdigest() != signature:
            raise ValueError("training signature census row hash mismatch")
        observed_steps += row["count"]
    if value["observed_steps"] != observed_steps:
        raise ValueError("training signature census observed-step count mismatch")
    return value


def load_training_signature_census(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError("training signature census is not readable strict JSON") from error
    return _load_training_signature_census_bytes(raw)


class Stage2SignatureRegistry:
    """A census-bound set, intentionally capable of carrying multiple signatures."""

    def __init__(self, *, census_sha256: str | None, approved_signatures: Sequence[str]) -> None:
        if census_sha256 is None:
            raise ValueError("Stage 2 requires a signature census before graph capture")
        self.census_sha256 = _sha256(census_sha256, label="signature census sha256")
        signatures = tuple(_sha256(item, label="approved graph signature") for item in approved_signatures)
        if not signatures or len(set(signatures)) != len(signatures):
            raise ValueError("approved graph signatures must be a nonempty unique census")
        self.approved_signatures = frozenset(signatures)

    def require(self, signature_sha256: str) -> str:
        signature = _sha256(signature_sha256, label="graph signature")
        if signature not in self.approved_signatures:
            raise RuntimeError("CUDA graph signature is outside the approved signature census")
        return signature


def _freeze_static(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple((key, _freeze_static(value[key])) for key in sorted(value))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_static(item) for item in value)
    return value


@dataclass(frozen=True)
class Stage2ActivationAuthority:
    census_path: Path
    census_raw_sha256: str
    census_self_sha256: str
    registry: Stage2SignatureRegistry
    signatures_by_static_key: Mapping[object, str]

    def resolve(
        self, batch: Mapping[str, object], *, gradient_checkpointing: bool,
    ) -> str:
        key = _freeze_static(
            _training_step_contract(
                batch, gradient_checkpointing=gradient_checkpointing,
            )
        )
        signature = self.signatures_by_static_key.get(key)
        if signature is None:
            raise RuntimeError("CUDA graph signature is outside the approved signature census")
        return self.registry.require(signature)


def load_stage2_activation_authority(
    path: Path, *, expected_raw_sha256: str,
) -> Stage2ActivationAuthority:
    """Reopen exact census bytes; never let an activating run mint authority."""

    expected = _sha256(expected_raw_sha256, label="training signature census expected raw sha256")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError("training signature census is not readable strict JSON") from error
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError("training signature census raw hash mismatch")
    value = _load_training_signature_census_bytes(raw)
    claimed_self = str(value["self_sha256"])
    approved = value["approved_signatures"]
    signatures = value["signatures"]
    signatures_by_static_key: dict[object, str] = {}
    for row, signature in zip(signatures, approved, strict=True):
        static_key = _freeze_static(row["contract"])
        prior = signatures_by_static_key.setdefault(static_key, signature)
        if prior != signature:
            raise ValueError("training signature census static key maps to multiple signatures")
    return Stage2ActivationAuthority(
        census_path=path.resolve(),
        census_raw_sha256=actual,
        census_self_sha256=claimed_self,
        registry=Stage2SignatureRegistry(
            census_sha256=actual,
            approved_signatures=approved,
        ),
        signatures_by_static_key=signatures_by_static_key,
    )


class TorchCudaGraphBackend:
    """Thin production backend; Stage 1 config cannot call it."""

    preparation_regions_per_signature = 4

    def __init__(self) -> None:
        self._pool: object | None = None

    def warmup(
        self,
        region: Callable[[], None],
        zero_grad: Callable[[], None],
    ) -> None:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA graph warmup requires CUDA")
        current = torch.cuda.current_stream()
        warmup_stream = torch.cuda.Stream()
        warmup_stream.wait_stream(current)
        with torch.cuda.stream(warmup_stream):
            for _ in range(3):
                zero_grad()
                region()
        current.wait_stream(warmup_stream)
        zero_grad()

    def capture(self, region: Callable[[], None]) -> torch.cuda.CUDAGraph:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA graph capture requires CUDA")
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph, pool=self._pool):
            region()
        if self._pool is None:
            self._pool = graph.pool()
        return graph


class CudaGraphTrainingStepPool:
    """Census-bound graph pool without an assumed number of real signatures.

    Stage 2 must first measure and approve its signature census. Capture owns
    only forward/loss/backward: identity callbacks prove that neither optimizer
    state nor the authoritative cursor moved during warmup/capture.
    """

    def __init__(self, *, registry: Stage2SignatureRegistry, backend: object | None = None) -> None:
        self.registry = registry
        self.backend = TorchCudaGraphBackend() if backend is None else backend
        capture = getattr(self.backend, "capture", None)
        if not callable(capture):
            raise ValueError("CUDA graph backend must expose capture(region)")
        self._graphs: dict[str, object] = {}
        self._captures = 0
        self._replays = 0
        self._fallbacks = 0

    def contains(self, signature_sha256: str) -> bool:
        signature = self.registry.require(signature_sha256)
        return signature in self._graphs

    def capture(
        self,
        *,
        signature_sha256: str,
        region: Callable[[], None],
        optimizer_identity: Callable[[], str],
        cursor_identity: Callable[[], str],
    ) -> None:
        signature = self.registry.require(signature_sha256)
        if signature in self._graphs:
            raise RuntimeError("CUDA graph signature was already captured")
        optimizer_before = _sha256(optimizer_identity(), label="optimizer identity before capture")
        cursor_before = _sha256(cursor_identity(), label="cursor identity before capture")
        graph = self.backend.capture(region)
        optimizer_after = _sha256(optimizer_identity(), label="optimizer identity after capture")
        cursor_after = _sha256(cursor_identity(), label="cursor identity after capture")
        if optimizer_before != optimizer_after or cursor_before != cursor_after:
            raise RuntimeError("CUDA graph warmup/capture mutated optimizer or cursor identity")
        replay = getattr(graph, "replay", None)
        if not callable(replay):
            raise RuntimeError("captured CUDA graph does not expose replay")
        self._graphs[signature] = graph
        self._captures += 1

    def replay(self, signature_sha256: str) -> None:
        signature = self.registry.require(signature_sha256)
        graph = self._graphs.get(signature)
        if graph is None:
            raise RuntimeError("approved CUDA graph signature has not been captured")
        graph.replay()
        self._replays += 1

    def receipt(self) -> dict[str, object]:
        return {
            "schema_version": "ember-cuda-graph-training-step-receipt-v1",
            "signature_census_sha256": self.registry.census_sha256,
            "signature_count": len(self._graphs),
            "captures": self._captures,
            "replays": self._replays,
            "fallbacks": self._fallbacks,
        }


def verify_checkpoint_recompute_capture(
    *,
    initial_identity: Mapping[str, object],
    recompute_identity: Mapping[str, object],
    preserve_rng_state: bool,
    use_reentrant: bool,
) -> dict[str, object]:
    """Prove the checkpoint recompute traverses the identical captured region."""

    if not preserve_rng_state:
        raise RuntimeError("CUDA graph checkpoint capture requires RNG preservation")
    if use_reentrant:
        raise RuntimeError("CUDA graph checkpoint capture requires non-reentrant checkpointing")
    _closed_keys(initial_identity, _CHECKPOINT_IDENTITY_KEYS, label="initial checkpoint identity")
    _closed_keys(recompute_identity, _CHECKPOINT_IDENTITY_KEYS, label="recompute checkpoint identity")
    initial = {key: _sha256(initial_identity[key], label=key) for key in sorted(_CHECKPOINT_IDENTITY_KEYS)}
    recompute = {key: _sha256(recompute_identity[key], label=key) for key in sorted(_CHECKPOINT_IDENTITY_KEYS)}
    if initial != recompute:
        raise RuntimeError("checkpoint recompute identity drift makes graph capture unprovable")
    return {
        "schema_version": "ember-cuda-graph-checkpoint-recompute-receipt-v1",
        "rng_policy": "preserve_rng_state",
        "checkpoint_mode": "non_reentrant",
        "checkpoint_recompute_identity": "MATCH",
        "identity": initial,
    }


ScaledMmKernel = Callable[..., torch.Tensor]


class _DynamicFp8ScaledMm(torch.autograd.Function):
    @staticmethod
    def forward(
        ctx: Any,
        activation: torch.Tensor,
        weight: torch.Tensor,
        weight_fp8: torch.Tensor,
        weight_scale: torch.Tensor,
        unit_scale: torch.Tensor,
        kernel: ScaledMmKernel,
    ) -> torch.Tensor:
        if activation.shape[-1] != weight.shape[1]:
            raise RuntimeError("FP8 down projection input width does not match the live weight")
        flat = activation.reshape(-1, activation.shape[-1])
        absolute_max = flat.detach().abs().amax(dim=1, keepdim=True).float()
        # Keep the captured region free of tensor-to-host branching. A non-finite
        # activation remains fail-closed at the authoritative loss check after
        # replay; persistent master-weight scaling is checked outside capture.
        scale_a = torch.where(absolute_max > 0, absolute_max / 448.0, torch.ones_like(absolute_max))
        activation_fp8 = (flat / scale_a).clamp(-448.0, 448.0).to(torch.float8_e4m3fn).contiguous()
        weight_transposed = weight_fp8.transpose(0, 1)
        if (
            not activation_fp8.is_contiguous()
            or weight_transposed.stride() != (1, weight_fp8.shape[1])
            or weight_transposed.untyped_storage().data_ptr() != weight_fp8.untyped_storage().data_ptr()
        ):
            raise RuntimeError("FP8 operands do not satisfy the reviewed SM89 memory layout")
        output = kernel(
            activation_fp8,
            weight_transposed,
            unit_scale,
            unit_scale,
            out_dtype=activation.dtype,
            use_fast_accum=True,
        )
        if isinstance(output, tuple):
            output = output[0]
        output = output.float().mul_(scale_a).mul_(weight_scale).to(activation.dtype)
        ctx.save_for_backward(flat, weight)
        ctx.input_shape = activation.shape
        return output.reshape(*activation.shape[:-1], weight.shape[0])

    @staticmethod
    def backward(ctx: Any, grad_output: torch.Tensor) -> tuple[torch.Tensor | None, ...]:
        flat, weight = ctx.saved_tensors
        grad = grad_output.reshape(-1, grad_output.shape[-1]).to(weight.dtype)
        grad_input = grad.matmul(weight).reshape(ctx.input_shape)
        grad_weight = grad.transpose(0, 1).matmul(flat.to(weight.dtype))
        return grad_input, grad_weight, None, None, None, None


class DynamicFp8Projection(nn.Module):
    """Live-master FP8 projection with a stable captured weight operand.

    The persistent FP8 buffer is refreshed once after each optimizer update.
    Forward only takes a transposed view, so it performs zero weight
    materialization copies and keeps the graph operand address stable.

    Subclasses bind one closed shape rule (``_shape_holds``); the FP8 forward,
    the BF16 backward, the refresh discipline and the kernel receipt are shared.
    The ``arm`` switch (#2167) selects the forward kernel at an installed site:
    ``fp8`` dispatches ``torch._scaled_mm``; ``bf16`` runs ``F.linear`` on the
    same BF16 master weight, which is the original module computation, so a
    paired matched-loss harness can alternate arms on one model state.
    """

    SITE_CLASS = "abstract"
    _SHAPE_REFUSAL = "FP8 site shape rule is abstract"

    @staticmethod
    def _shape_holds(weight: torch.Tensor) -> bool:
        raise NotImplementedError

    def __init__(
        self,
        *,
        weight: nn.Parameter,
        bias: nn.Parameter | None,
        kernel: ScaledMmKernel | None = None,
        allow_test_device: bool = False,
    ) -> None:
        super().__init__()
        if bias is not None:
            raise ValueError("issue #1413 FP8 down projections must be bias-free")
        if not self._shape_holds(weight):
            raise ValueError(self._SHAPE_REFUSAL)
        if weight.dtype is not torch.bfloat16:
            raise ValueError("issue #1413 FP8 site requires a BF16 master weight")
        self.weight = weight
        self.bias = None
        self._kernel = kernel if kernel is not None else torch._scaled_mm
        self._test_device = bool(allow_test_device)
        if not self._test_device:
            if weight.device.type != "cuda":
                raise RuntimeError("native FP8 down projection requires a CUDA device")
            major, minor = torch.cuda.get_device_capability(weight.device)
            if (major, minor) != (8, 9):
                raise RuntimeError("native FP8 down projection requires exact SM89 compute capability")
        self.register_buffer(
            "_weight_fp8",
            torch.empty_like(weight, dtype=torch.float8_e4m3fn),
            persistent=False,
        )
        self.register_buffer(
            "_weight_scale",
            torch.ones((1, weight.shape[0]), device=weight.device, dtype=torch.float32),
            persistent=False,
        )
        self.register_buffer(
            "_unit_scale", torch.ones((), device=weight.device, dtype=torch.float32),
            persistent=False,
        )
        self._dispatches = 0
        self._fallbacks = 0
        self._weight_refreshes = 0
        self._refreshed_weight_version = -1
        self._arm = "fp8"
        self._bf16_dispatches = 0
        self.refresh_after_optimizer_step()

    @classmethod
    def from_linear(
        cls,
        linear: nn.Linear,
        *,
        kernel: ScaledMmKernel | None = None,
        allow_test_device: bool = False,
    ) -> "DynamicFp8Projection":
        return cls(weight=linear.weight, bias=linear.bias, kernel=kernel, allow_test_device=allow_test_device)

    @property
    def arm(self) -> str:
        return self._arm

    def set_arm(self, arm: str) -> None:
        if arm not in _FP8_ARMS:
            raise ValueError("FP8 site arm must be one of fp8, bf16")
        self._arm = arm

    def arm_receipt(self) -> dict[str, object]:
        return {
            "site_class": self.SITE_CLASS,
            "arm": self._arm,
            "fp8_dispatches": self._dispatches,
            "bf16_dispatches": self._bf16_dispatches,
        }

    def refresh_after_optimizer_step(self) -> None:
        with torch.no_grad():
            absolute_max = self.weight.detach().abs().amax(dim=1, keepdim=True).float()
            if not bool(torch.isfinite(absolute_max).all()):
                raise RuntimeError("FP8 weight scale is non-finite")
            scale = torch.where(absolute_max > 0, absolute_max / 448.0, torch.ones_like(absolute_max))
            quantized = (self.weight.detach() / scale).clamp(-448.0, 448.0).to(torch.float8_e4m3fn)
            self._weight_fp8.copy_(quantized)
            self._weight_scale.copy_(scale.transpose(0, 1))
        self._refreshed_weight_version = self.weight._version
        self._weight_refreshes += 1

    def refresh_if_stale_after_optimizer_step(self) -> bool:
        if self.weight._version == self._refreshed_weight_version:
            return False
        self.refresh_after_optimizer_step()
        return True

    def forward(self, activation: torch.Tensor) -> torch.Tensor:
        if activation.dtype is not torch.bfloat16:
            raise RuntimeError("issue #1413 FP8 site requires a BF16 activation")
        if self._arm == "bf16":
            self._bf16_dispatches += 1
            return torch.nn.functional.linear(activation, self.weight)
        if self.weight._version != self._refreshed_weight_version:
            raise RuntimeError("stale FP8 weight: refresh_after_optimizer_step is required after every update")
        output = _DynamicFp8ScaledMm.apply(
            activation, self.weight, self._weight_fp8, self._weight_scale,
            self._unit_scale, self._kernel,
        )
        self._dispatches += 1
        return output

    def kernel_receipt(self) -> dict[str, object]:
        capability = "TEST_ONLY"
        if not self._test_device:
            major, minor = torch.cuda.get_device_capability(self.weight.device)
            capability = f"{major}.{minor}"
        return {
            "schema_version": "ember-fp8-scaled-mm-kernel-receipt-v2",
            "kernel": "torch._scaled_mm",
            "compute_capability": capability,
            "activation_dtype": "float8_e4m3fn",
            "weight_dtype": "float8_e4m3fn",
            "output_dtype": "bfloat16",
            "activation_operand_layout": "row_major_contiguous",
            "weight_operand_layout": "column_major_transposed_view",
            "per_forward_weight_materialization_copies": 0,
            "native_kernel_scaling": "tensorwise_unit",
            "activation_scaling": "emulated_rowwise_per_token",
            "weight_scaling": "emulated_columnwise_per_output_channel",
            "accumulation_mode": "fast_accum",
            "weight_refreshes": self._weight_refreshes,
            "dispatches": self._dispatches,
            "fallbacks": self._fallbacks,
        }


class DynamicFp8DownProjection(DynamicFp8Projection):
    """Issue #1413 site class: SwiGLU down projection, weight [H, 4H]."""

    SITE_CLASS = "swiglu_down_4h_to_h"
    _SHAPE_REFUSAL = "issue #1413 FP8 site must be a 4H-to-H down projection"

    @staticmethod
    def _shape_holds(weight: torch.Tensor) -> bool:
        return weight.ndim == 2 and weight.shape[1] == 4 * weight.shape[0]


class DynamicFp8UpGateProjection(DynamicFp8Projection):
    """Issue #2167 (W5) site class: SwiGLU up+gate projection, weight [8H, H].

    Output width is 8H so the caller ``chunk(2, dim=-1)`` into up / gate is untouched.
    """

    SITE_CLASS = "shared_swiglu_up_gate_h_to_8h"
    _SHAPE_REFUSAL = "issue #2167 FP8 site must be an H-to-8H up+gate projection"

    @staticmethod
    def _shape_holds(weight: torch.Tensor) -> bool:
        return weight.ndim == 2 and weight.shape[0] == 8 * weight.shape[1]


def iter_fp8_down_projections(model: nn.Module) -> Sequence[DynamicFp8Projection]:
    """Every installed FP8 site of any class (the name predates the W5 site class)."""

    return tuple(
        module
        for module in model.modules()
        if isinstance(module, DynamicFp8Projection)
    )


iter_fp8_projections = iter_fp8_down_projections


def set_fp8_arm(model: nn.Module, arm: str) -> int:
    """Switch every installed FP8 site to ``arm`` (#2167); returns the site count."""

    if arm not in _FP8_ARMS:
        raise ValueError("FP8 site arm must be one of fp8, bf16")
    sites = iter_fp8_down_projections(model)
    for site in sites:
        site.set_arm(arm)
    return len(sites)


def fp8_arm_receipt(model: nn.Module) -> dict[str, object]:
    sites = iter_fp8_down_projections(model)
    return {
        "sites": len(sites),
        "arms": sorted({site.arm for site in sites}),
        "fp8_dispatches": sum(int(site.arm_receipt()["fp8_dispatches"]) for site in sites),
        "bf16_dispatches": sum(int(site.arm_receipt()["bf16_dispatches"]) for site in sites),
        "fallbacks": sum(int(site.kernel_receipt()["fallbacks"]) for site in sites),
    }


def disabled_fp8_installation_receipt() -> dict[str, object]:
    return {
        "schema_version": "ember-fp8-down-projection-installation-v2",
        "scope": "NONE",
        "layer_indexes": [],
        "installed_sites": 0,
        "sites": [],
        "fallbacks": 0,
    }


def install_fp8_down_projections(
    model: nn.Module,
    *,
    kernel: ScaledMmKernel | None = None,
    allow_test_device: bool = False,
    installation_scope: str | None = None,
) -> dict[str, object]:
    """Install the default shared site or the explicit W2 selected-expert treatment."""

    treatment = installation_scope == _FP8_W2_INSTALLATION_SCOPE
    if installation_scope not in (None, _FP8_INSTALLATION_SCOPE, _FP8_W2_INSTALLATION_SCOPE):
        raise ValueError("issue #1945 FP8 installation scope is not recognized")

    layers = getattr(model, "layers", None)
    if not isinstance(layers, nn.ModuleList) or not layers:
        raise ValueError("issue #1413 FP8 installation requires decoder layers")
    final_layer_index = len(layers) - 1
    if treatment and (
        len(layers) != _FP8_W2_FINAL_LAYER_INDEX + 1
        or final_layer_index != _FP8_W2_FINAL_LAYER_INDEX
    ):
        raise ValueError("issue #1945 W2 requires exactly 14 decoder layers with layer 13 final")
    if treatment and tuple(getattr(layers[final_layer_index], "experts", {})) != _FP8_W2_EXPERT_NAMES:
        raise ValueError("issue #1945 W2 requires exact expert keys in canonical order")

    targets: list[tuple[str, nn.Module, nn.Linear]] = []
    existing_target_names: list[str] = []
    for index, layer in enumerate(layers):
        shared = getattr(layer, "shared_ffn", None)
        experts = getattr(layer, "experts", None)
        if shared is None or not isinstance(experts, nn.ModuleDict):
            raise ValueError("issue #1413 FP8 installation requires closed SwiGLU expert sites")
        candidates = [(f"layers.{index}.shared_ffn.down", shared)]
        candidates.extend(
            (f"layers.{index}.experts.{name}.down", expert)
            for name, expert in experts.items()
        )
        for name, owner in candidates:
            down = getattr(owner, "down", None)
            if isinstance(down, DynamicFp8DownProjection):
                supported_existing_shared = (
                    treatment
                    and index == final_layer_index
                    and owner is shared
                    and name == f"layers.{_FP8_W2_FINAL_LAYER_INDEX}.shared_ffn.down"
                )
                if supported_existing_shared:
                    existing_target_names.append(name)
                    continue
                if treatment and index == final_layer_index and owner is not shared:
                    raise RuntimeError("issue #1945 W2 expert down projection is already installed")
                raise RuntimeError("issue #1413 FP8 down projections are already installed")
            if not isinstance(down, nn.Linear):
                if treatment and index == final_layer_index and owner is not shared:
                    raise ValueError("issue #1945 W2 expert down projection is not linear")
                raise ValueError("issue #1413 FP8 site is not a linear down projection")
            if index == final_layer_index and (owner is shared or treatment):
                targets.append((name, owner, down))
    expected_total = 5 if treatment else 1
    if len(targets) + len(existing_target_names) != expected_total:
        raise RuntimeError(
            f"issue #1945 W2 scope must resolve exactly {expected_total} final down projections"
            if treatment
            else "issue #1413 FP8 scope must resolve exactly one final shared down projection"
        )
    if not treatment and len(targets) != 1:
        raise RuntimeError("issue #1413 FP8 scope must resolve exactly one final shared down projection")
    replacements = [
        (
            owner,
            DynamicFp8DownProjection.from_linear(
                down,
                kernel=kernel,
                allow_test_device=allow_test_device,
            ),
        )
        for _name, owner, down in targets
    ]
    for owner, replacement in replacements:
        owner.down = replacement
    receipt = {
        "schema_version": "ember-fp8-down-projection-installation-v2",
        "scope": _FP8_W2_INSTALLATION_SCOPE if treatment else _FP8_INSTALLATION_SCOPE,
        "layer_indexes": [final_layer_index],
        "installed_sites": expected_total,
        "sites": [
            f"layers.{final_layer_index}.shared_ffn.down",
            *(
                f"layers.{final_layer_index}.experts.{name}.down"
                for name in _FP8_W2_EXPERT_NAMES
            ),
        ] if treatment else [name for name, _owner, _down in targets],
        "fallbacks": 0,
    }
    if treatment:
        receipt["newly_installed_sites"] = len(targets)
    return receipt


def install_fp8_up_gate_projections(
    model: nn.Module,
    *,
    kernel: ScaledMmKernel | None = None,
    allow_test_device: bool = False,
    installation_scope: str | None = None,
) -> dict[str, object]:
    """Install the explicit W5 scope (#2167): ``layers.{i}.shared_ffn.up_gate`` in all 14 layers.

    Every refusal fires before any module is replaced. Expert up+gate sites stay
    BF16 ``nn.Linear`` (W2 governs experts); a pre-installed expert site, a
    pre-installed shared site, a non-linear or biased or non-[8H, H] site, an
    unknown scope string, or any layer count other than 14 is refused.
    """

    if installation_scope != _FP8_W5_INSTALLATION_SCOPE:
        raise ValueError("issue #2167 FP8 up+gate installation requires the explicit W5 scope")
    layers = getattr(model, "layers", None)
    if not isinstance(layers, nn.ModuleList) or len(layers) != _FP8_W5_LAYER_COUNT:
        raise ValueError("issue #2167 W5 requires exactly 14 decoder layers")
    targets: list[tuple[str, nn.Module, nn.Linear]] = []
    for index, layer in enumerate(layers):
        shared = getattr(layer, "shared_ffn", None)
        experts = getattr(layer, "experts", None)
        if shared is None or not isinstance(experts, nn.ModuleDict):
            raise ValueError("issue #2167 W5 requires closed SwiGLU expert sites")
        for expert_name, expert in experts.items():
            expert_up_gate = getattr(expert, "up_gate", None)
            if isinstance(expert_up_gate, DynamicFp8Projection):
                raise RuntimeError(
                    "issue #2167 W5 refuses an installed expert up+gate site: "
                    f"layers.{index}.experts.{expert_name}.up_gate"
                )
            if not isinstance(expert_up_gate, nn.Linear):
                raise ValueError("issue #2167 W5 expert up+gate site is not linear")
        up_gate = getattr(shared, "up_gate", None)
        if isinstance(up_gate, DynamicFp8Projection):
            raise RuntimeError("issue #2167 FP8 up+gate projections are already installed")
        if not isinstance(up_gate, nn.Linear):
            raise ValueError("issue #2167 FP8 site is not a linear up+gate projection")
        if up_gate.bias is not None:
            raise ValueError("issue #2167 FP8 up+gate projections must be bias-free")
        if not DynamicFp8UpGateProjection._shape_holds(up_gate.weight):
            raise ValueError("issue #2167 FP8 site must be an H-to-8H up+gate projection")
        if up_gate.weight.dtype is not torch.bfloat16:
            raise ValueError("issue #2167 FP8 site requires a BF16 master weight")
        targets.append((f"layers.{index}.shared_ffn.up_gate", shared, up_gate))
    if len(targets) != _FP8_W5_LAYER_COUNT:
        raise RuntimeError("issue #2167 W5 scope must resolve exactly 14 shared up+gate projections")
    replacements = [
        (
            owner,
            DynamicFp8UpGateProjection.from_linear(
                up_gate,
                kernel=kernel,
                allow_test_device=allow_test_device,
            ),
        )
        for _name, owner, up_gate in targets
    ]
    for owner, replacement in replacements:
        owner.up_gate = replacement
    return {
        "schema_version": "ember-fp8-down-projection-installation-v2",
        "scope": _FP8_W5_INSTALLATION_SCOPE,
        "layer_indexes": list(range(_FP8_W5_LAYER_COUNT)),
        "installed_sites": _FP8_W5_LAYER_COUNT,
        "sites": [name for name, _owner, _up_gate in targets],
        "fallbacks": 0,
    }


def fp8_installation_group_receipt(
    model: nn.Module,
    installation_receipt: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Return W2-only live counters separated by shared and selected-expert sites."""

    if installation_receipt.get("scope") != _FP8_W2_INSTALLATION_SCOPE:
        raise ValueError("issue #1945 grouped FP8 evidence requires the explicit W2 scope")
    named_modules = dict(model.named_modules())
    groups = {
        "existing_shared": [f"layers.{_FP8_W2_FINAL_LAYER_INDEX}.shared_ffn.down"],
        "new_active_expert": [
            f"layers.{_FP8_W2_FINAL_LAYER_INDEX}.experts.{name}.down"
            for name in _FP8_W2_EXPERT_NAMES
        ],
    }
    result: dict[str, dict[str, object]] = {}
    for group_name, paths in groups.items():
        modules = [named_modules.get(path) for path in paths]
        if any(not isinstance(module, DynamicFp8DownProjection) for module in modules):
            raise RuntimeError("issue #1945 W2 grouped FP8 site identity drifted")
        receipts = [module.kernel_receipt() for module in modules if module is not None]
        result[group_name] = {
            "installed_sites": len(paths),
            "sites": paths,
            "dispatches": sum(int(item["dispatches"]) for item in receipts),
            "fallbacks": sum(int(item["fallbacks"]) for item in receipts),
            "weight_refreshes": sum(int(item["weight_refreshes"]) for item in receipts),
        }
    return result


def refresh_fp8_after_optimizer_step(model: nn.Module) -> int:
    """Re-quantize every installed site's FP8 weight buffer; returns the site count.

    Always forced (#2167 real-path probe finding): the production optimizer, bitsandbytes
    AdamW8bit, writes parameter storage from its CUDA kernel without bumping the tensor version
    counter, so a version-based staleness test observes no update and every site keeps
    forwarding buffers quantized from an older weight. The version check in ``forward`` stays
    as a guard for optimizers that do bump the counter; this function is the contract that
    every optimizer step is followed by one refresh per installed site.
    """
    sites = iter_fp8_down_projections(model)
    for site in sites:
        site.refresh_after_optimizer_step()
    return len(sites)


def validate_fp8_refresh_count(*, installed_sites: int, optimizer_steps: int, weight_refreshes: int) -> int:
    """Refuse a run whose receipted refresh count is not one install refresh plus one per step per site."""
    expected = int(installed_sites) * (int(optimizer_steps) + 1)
    if int(weight_refreshes) != expected:
        raise RuntimeError(f"FP8_REFRESH_COUNT_REFUSED:{int(weight_refreshes)}!={expected}")
    return expected


def validate_fp8_kernel_receipt(value: Mapping[str, object]) -> dict[str, object]:
    _closed_keys(value, _KERNEL_RECEIPT_KEYS, label="FP8 kernel receipt")
    if value["schema_version"] != "ember-fp8-scaled-mm-kernel-receipt-v2" or value["kernel"] != "torch._scaled_mm":
        raise ValueError("FP8 kernel receipt must bind torch._scaled_mm")
    if value["compute_capability"] != "8.9":
        raise ValueError("FP8 kernel receipt requires exact SM89 compute capability")
    if (value["activation_dtype"], value["weight_dtype"], value["output_dtype"]) != (
        "float8_e4m3fn", "float8_e4m3fn", "bfloat16",
    ):
        raise ValueError("FP8 kernel receipt dtypes do not match the reviewed contract")
    if value["activation_operand_layout"] != "row_major_contiguous" or value["weight_operand_layout"] != "column_major_transposed_view":
        raise ValueError("FP8 kernel receipt operand layout does not match the reviewed SM89 contract")
    if value["per_forward_weight_materialization_copies"] != 0:
        raise ValueError("FP8 kernel receipt must prove zero per-forward weight materialization copies")
    if (
        value["native_kernel_scaling"] != "tensorwise_unit"
        or value["activation_scaling"] != "emulated_rowwise_per_token"
        or value["weight_scaling"] != "emulated_columnwise_per_output_channel"
    ):
        raise ValueError("FP8 kernel receipt must bind emulated rowwise scaling")
    if value["accumulation_mode"] != "fast_accum":
        raise ValueError("FP8 kernel receipt must pin torch._scaled_mm fast accumulation")
    for key in ("weight_refreshes", "dispatches", "fallbacks"):
        if type(value[key]) is not int or int(value[key]) < 0:
            raise ValueError(f"FP8 kernel receipt {key} must be a nonnegative integer")
    if value["fallbacks"] != 0:
        raise ValueError("FP8 kernel receipt fallback count must be zero")
    return dict(value)


def validate_close_evidence(value: Mapping[str, object]) -> dict[str, object]:
    expected = {
        "fp8_dispatches", "cuda_graph_replays", "fp8_fallbacks", "cuda_graph_fallbacks",
        "tokens_per_second", "real_training_path",
    }
    _closed_keys(value, expected, label="issue #1413 close evidence")
    if value["real_training_path"] is not True:
        raise ValueError("issue #1413 close evidence must come from the real training path")
    if type(value["fp8_dispatches"]) is not int or type(value["cuda_graph_replays"]) is not int or value["fp8_dispatches"] <= 0 or value["cuda_graph_replays"] <= 0:
        raise ValueError("issue #1413 close evidence requires both mechanisms")
    if value["fp8_fallbacks"] != 0 or value["cuda_graph_fallbacks"] != 0:
        raise ValueError("issue #1413 close evidence requires zero fallback events")
    tokens_per_second = value["tokens_per_second"]
    if not isinstance(tokens_per_second, (int, float)) or isinstance(tokens_per_second, bool) or float(tokens_per_second) <= 1000.0:
        raise ValueError("issue #1413 close evidence must be greater than 1000 tok/s")
    return dict(value)


_STAGE2_ARM_KEYS = {
    "schema_version", "arm", "source_commit", "runner_source_sha256", "model_config_sha256",
    "input_identity_sha256", "record_order_sha256", "checkpoint_lineage_sha256",
    "census_raw_sha256", "seed", "initial_cursor",
    "steps", "tokens", "losses", "step_timings_seconds", "step_elapsed_seconds", "tokens_per_second",
    "max_memory_allocated_bytes", "max_memory_reserved_bytes", "mechanisms",
    "preparation_regions_per_signature", "preparation_signature_count",
    "preparation_region_count", "optimizer_state_preinitialized_parameters",
    "capture_gradient_zeroing", "preparation_memory_allocated_bytes_by_signature",
    "captures_during_preparation",
    "captures_during_measured_window", "no_capture_in_measured_window",
}
_STAGE2_MECHANISM_KEYS = {
    "fp8_dispatches", "fp8_fallbacks", "cuda_graph_captures",
    "cuda_graph_replays", "cuda_graph_fallbacks",
    "shared_trunk_gradient_parameters", "shared_trunk_gradient_bytes",
    "expert_bank_gradient_workspace_parameters", "gradient_workspace_bytes",
    "gradient_workspace_rebinds", "inactive_grad_none_assertions",
}
_STAGE2_MATCHED_LOSS_RELATIVE_TOLERANCE = 0.01
_STAGE2_DIAGNOSTIC_IDENTITY_KEYS = {
    "claim_boundary", "production_accelerated_arm_self_sha256",
}
_STAGE2_GRAPH_ONLY_DIAGNOSTIC_KEYS = (
    _STAGE2_ARM_KEYS | _STAGE2_DIAGNOSTIC_IDENTITY_KEYS | {"pre_optimizer_sync"}
)
_STAGE2_GRAPH_ONLY_DIAGNOSTIC_SCHEMA = "ember-stage2-graph-only-diagnostic-v1"
_STAGE2_GRAPH_ONLY_DIAGNOSTIC_CLAIM_BOUNDARY = "DIAGNOSTIC_ONLY_NOT_CLOSE_EVIDENCE"
_STAGE2_EAGER_WORKSPACE_DIAGNOSTIC_SCHEMA = "ember-stage2-eager-workspace-diagnostic-v1"
_STAGE2_EAGER_WORKSPACE_DIAGNOSTIC_KEYS = (
    _STAGE2_ARM_KEYS | _STAGE2_DIAGNOSTIC_IDENTITY_KEYS
    | {"post_step1_parameter_delta_l2"}
)


def _validate_post_step1_parameter_delta_l2(value: object) -> dict[str, float]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"active_expert_bank", "trunk"}
        or any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
            or float(item) < 0.0
            for item in value.values()
        )
    ):
        raise ValueError("Stage-2 diagnostic post-step1 parameter delta L2 evidence is invalid")
    return {key: float(value[key]) for key in ("active_expert_bank", "trunk")}


def _validate_stage2_arm(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _STAGE2_ARM_KEYS:
        raise ValueError("Stage-2 arm receipt must use the closed v2 key set")
    arm = value["arm"]
    if value["schema_version"] != "ember-stage2-training-arm-v2" or arm not in {
        "bf16_baseline", "census_bound_stage2",
    }:
        raise ValueError("Stage-2 arm receipt identity is invalid")
    if re.fullmatch(r"[0-9a-f]{40}", str(value["source_commit"])) is None:
        raise ValueError("Stage-2 arm source commit is invalid")
    for key in (
        "runner_source_sha256", "model_config_sha256", "input_identity_sha256",
        "record_order_sha256", "checkpoint_lineage_sha256",
    ):
        _sha256(value[key], label=key.replace("_", " "))
    census_raw_sha256 = value["census_raw_sha256"]
    if arm == "bf16_baseline" and census_raw_sha256 is not None:
        raise ValueError("BF16 baseline cannot carry Stage-2 census authority")
    if arm == "census_bound_stage2":
        _sha256(census_raw_sha256, label="Stage-2 census raw sha256")
    if type(value["seed"]) is not int or value["seed"] < 0:
        raise ValueError("Stage-2 arm seed is invalid")
    cursor = value["initial_cursor"]
    if (
        not isinstance(cursor, Mapping)
        or set(cursor) != {"record_index", "global_step", "tokens_seen"}
        or any(type(item) is not int or item < 0 for item in cursor.values())
    ):
        raise ValueError("Stage-2 arm initial cursor is invalid")
    steps, tokens = value["steps"], value["tokens"]
    if type(steps) is not int or steps < 1 or type(tokens) is not int or tokens < 1:
        raise ValueError("Stage-2 arm training extent is invalid")
    losses = value["losses"]
    if (
        not isinstance(losses, list)
        or len(losses) != steps
        or any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
            for item in losses
        )
    ):
        raise ValueError("Stage-2 arm losses are invalid")
    timings = value["step_timings_seconds"]
    if (
        not isinstance(timings, list)
        or len(timings) != steps
        or any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
            or float(item) <= 0.0
            for item in timings
        )
    ):
        raise ValueError("Stage-2 arm raw step timings are invalid")
    for key in ("step_elapsed_seconds", "tokens_per_second"):
        metric = value[key]
        if (
            not isinstance(metric, (int, float))
            or isinstance(metric, bool)
            or not math.isfinite(float(metric))
            or float(metric) <= 0.0
        ):
            raise ValueError(f"Stage-2 arm {key} is invalid")
    elapsed = sum(float(item) for item in timings)
    if not math.isclose(
        float(value["step_elapsed_seconds"]), elapsed, rel_tol=1e-9, abs_tol=1e-12,
    ):
        raise ValueError("Stage-2 arm elapsed time does not match raw step timings")
    recomputed_rate = tokens / elapsed
    if not math.isclose(
        float(value["tokens_per_second"]), recomputed_rate,
        rel_tol=1e-9, abs_tol=1e-9,
    ):
        raise ValueError("Stage-2 arm throughput does not match raw step timings")
    for key in ("max_memory_allocated_bytes", "max_memory_reserved_bytes"):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError(f"Stage-2 arm {key} is invalid")
    mechanisms = value["mechanisms"]
    if (
        not isinstance(mechanisms, Mapping)
        or set(mechanisms) != _STAGE2_MECHANISM_KEYS
        or any(type(item) is not int or item < 0 for item in mechanisms.values())
    ):
        raise ValueError("Stage-2 arm mechanisms are invalid")
    if mechanisms["fp8_fallbacks"] != 0 or mechanisms["cuda_graph_fallbacks"] != 0:
        raise ValueError("Stage-2 arm mechanism fallback count must be zero")
    active_counts = (
        mechanisms["fp8_dispatches"], mechanisms["cuda_graph_captures"],
        mechanisms["cuda_graph_replays"],
    )
    if arm == "bf16_baseline" and any(active_counts):
        raise ValueError("BF16 baseline cannot activate Stage-2 mechanisms")
    if arm == "census_bound_stage2" and any(count < 1 for count in active_counts):
        raise ValueError("census-bound Stage-2 arm requires both mechanisms")
    workspace_counts = tuple(
        mechanisms[key]
        for key in (
            "shared_trunk_gradient_parameters", "shared_trunk_gradient_bytes",
            "expert_bank_gradient_workspace_parameters", "gradient_workspace_bytes",
            "gradient_workspace_rebinds", "inactive_grad_none_assertions",
        )
    )
    if arm == "bf16_baseline" and any(workspace_counts):
        raise ValueError("BF16 baseline cannot activate a Stage-2 gradient workspace")
    if arm == "census_bound_stage2" and any(count < 1 for count in workspace_counts):
        raise ValueError("census-bound Stage-2 arm requires gradient workspace evidence")
    regions_per_signature = value["preparation_regions_per_signature"]
    signature_count = value["preparation_signature_count"]
    region_count = value["preparation_region_count"]
    optimizer_state_parameters = value["optimizer_state_preinitialized_parameters"]
    if (
        type(regions_per_signature) is not int
        or regions_per_signature < 1
        or type(signature_count) is not int
        or signature_count < 1
        or type(region_count) is not int
        or region_count != regions_per_signature * signature_count
        or type(optimizer_state_parameters) is not int
        or optimizer_state_parameters < 1
    ):
        raise ValueError("Stage-2 arm preparation or optimizer state methodology is invalid")
    captures_during_preparation = value["captures_during_preparation"]
    captures_during_measured_window = value["captures_during_measured_window"]
    if (
        type(captures_during_preparation) is not int
        or captures_during_preparation < 0
        or type(captures_during_measured_window) is not int
        or captures_during_measured_window < 0
    ):
        raise ValueError("Stage-2 arm capture accounting is invalid")
    if (
        value["no_capture_in_measured_window"] is not True
        or captures_during_measured_window != 0
    ):
        raise ValueError("Stage-2 accelerated arm captured inside the measured window")
    if arm == "bf16_baseline" and captures_during_preparation != 0:
        raise ValueError("BF16 baseline cannot capture during preparation")
    if arm == "census_bound_stage2":
        if captures_during_preparation != signature_count:
            raise ValueError("Stage-2 preparation must capture every admitted signature once")
        if mechanisms["cuda_graph_captures"] != captures_during_preparation:
            raise ValueError("Stage-2 preparation capture accounting mismatch")
    zeroing = value["capture_gradient_zeroing"]
    preparation_memory = value["preparation_memory_allocated_bytes_by_signature"]
    if arm == "bf16_baseline":
        if zeroing != "NOT_APPLICABLE" or preparation_memory != {}:
            raise ValueError("BF16 baseline cannot carry Stage-2 gradient preparation evidence")
    else:
        if zeroing != "eager_default_stream_outside_capture":
            raise ValueError("Stage-2 capture gradient zeroing is invalid")
        if (
            not isinstance(preparation_memory, Mapping)
            or len(preparation_memory) != signature_count
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(signature)) is None
                or type(allocated) is not int
                or allocated < 1
                for signature, allocated in preparation_memory.items()
            )
        ):
            raise ValueError("Stage-2 per-signature preparation memory evidence is invalid")
    return dict(value)


def _write_json_no_overwrite(path: Path, value: Mapping[str, object], *, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError as error:
        raise FileExistsError(f"refusing to overwrite {label}: {path}") from error


def write_stage2_arm_receipt(
    path: Path, value: Mapping[str, object],
) -> dict[str, object]:
    receipt = _validate_stage2_arm(value)
    receipt["self_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
    _write_json_no_overwrite(path, receipt, label="Stage-2 arm receipt")
    return receipt


def _validate_stage2_graph_only_diagnostic(
    value: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _STAGE2_GRAPH_ONLY_DIAGNOSTIC_KEYS:
        raise ValueError("Stage-2 graph-only diagnostic must use its closed v1 key set")
    if (
        value["schema_version"] != _STAGE2_GRAPH_ONLY_DIAGNOSTIC_SCHEMA
        or value["arm"] != "graph_only_bf16_down"
    ):
        raise ValueError("Stage-2 graph-only diagnostic identity is invalid")
    if value["claim_boundary"] != _STAGE2_GRAPH_ONLY_DIAGNOSTIC_CLAIM_BOUNDARY:
        raise ValueError("Stage-2 graph-only diagnostic claim boundary is invalid")
    _sha256(
        value["production_accelerated_arm_self_sha256"],
        label="production accelerated arm self sha256",
    )
    if value["pre_optimizer_sync"] not in {"NONE", "current_stream_synchronize"}:
        raise ValueError("Stage-2 graph-only diagnostic pre-optimizer sync is invalid")
    mechanisms = value["mechanisms"]
    if not isinstance(mechanisms, Mapping) or mechanisms.get("fp8_dispatches") != 0:
        raise ValueError("Stage-2 graph-only diagnostic requires zero FP8 dispatches")
    if mechanisms.get("fp8_fallbacks") != 0:
        raise ValueError("Stage-2 graph-only diagnostic requires zero FP8 fallbacks")

    # Reuse the production arm's closed identity, timing, graph, workspace, and
    # preparation validators. The proxy's synthetic positive FP8 count exists
    # only to pass the production arm's mechanism-presence clause; the truthful
    # diagnostic count above is independently pinned to zero and is what is
    # signed and persisted.
    production_proxy = {
        key: value[key]
        for key in _STAGE2_ARM_KEYS
    }
    production_proxy["schema_version"] = "ember-stage2-training-arm-v2"
    production_proxy["arm"] = "census_bound_stage2"
    production_proxy["mechanisms"] = dict(mechanisms, fp8_dispatches=1)
    _validate_stage2_arm(production_proxy)
    return dict(value)


def write_stage2_graph_only_diagnostic_receipt(
    path: Path, value: Mapping[str, object],
) -> dict[str, object]:
    receipt = _validate_stage2_graph_only_diagnostic(value)
    receipt["self_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
    _write_json_no_overwrite(path, receipt, label="Stage-2 graph-only diagnostic receipt")
    return receipt


def load_stage2_graph_only_diagnostic_receipt(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Stage-2 graph-only diagnostic receipt is not readable strict JSON") from error
    if (
        not isinstance(value, dict)
        or set(value) != _STAGE2_GRAPH_ONLY_DIAGNOSTIC_KEYS | {"self_sha256"}
    ):
        raise ValueError("Stage-2 graph-only diagnostic must use its closed v1 key set")
    claimed = _sha256(value["self_sha256"], label="graph-only diagnostic self sha256")
    unsigned = dict(value)
    del unsigned["self_sha256"]
    if hashlib.sha256(_canonical_json(unsigned)).hexdigest() != claimed:
        raise ValueError("Stage-2 graph-only diagnostic self hash mismatch")
    return _validate_stage2_graph_only_diagnostic(unsigned)


def _validate_stage2_eager_workspace_diagnostic(
    value: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _STAGE2_EAGER_WORKSPACE_DIAGNOSTIC_KEYS:
        raise ValueError("Stage-2 eager-workspace diagnostic must use its closed v1 key set")
    if (
        value["schema_version"] != _STAGE2_EAGER_WORKSPACE_DIAGNOSTIC_SCHEMA
        or value["arm"] != "eager_workspace_bf16"
        or value["claim_boundary"] != _STAGE2_GRAPH_ONLY_DIAGNOSTIC_CLAIM_BOUNDARY
    ):
        raise ValueError("Stage-2 eager-workspace diagnostic identity or claim boundary is invalid")
    _sha256(
        value["production_accelerated_arm_self_sha256"],
        label="production accelerated arm self sha256",
    )
    _validate_post_step1_parameter_delta_l2(value["post_step1_parameter_delta_l2"])
    mechanisms = value["mechanisms"]
    if not isinstance(mechanisms, Mapping):
        raise ValueError("Stage-2 eager-workspace diagnostic mechanisms are invalid")
    if mechanisms.get("fp8_dispatches") != 0 or mechanisms.get("fp8_fallbacks") != 0:
        raise ValueError("Stage-2 eager-workspace diagnostic cannot engage FP8")
    if any(mechanisms.get(key) != 0 for key in (
        "cuda_graph_captures", "cuda_graph_replays", "cuda_graph_fallbacks",
    )):
        raise ValueError("Stage-2 eager-workspace diagnostic cannot engage CUDA graphs")
    if (
        value["captures_during_preparation"] != 0
        or value["captures_during_measured_window"] != 0
    ):
        raise ValueError("Stage-2 eager-workspace diagnostic cannot carry CUDA graph evidence")
    preparation_memory = value["preparation_memory_allocated_bytes_by_signature"]
    signature_count = value["preparation_signature_count"]
    if (
        type(signature_count) is not int
        or signature_count < 1
        or not isinstance(preparation_memory, Mapping)
        or len(preparation_memory) != signature_count
        or any(
            re.fullmatch(r"[0-9a-f]{64}", str(signature)) is None
            or type(allocated) is not int
            or allocated < 1
            for signature, allocated in preparation_memory.items()
        )
    ):
        raise ValueError("Stage-2 eager-workspace preparation memory evidence is invalid")

    proxy = {key: value[key] for key in _STAGE2_ARM_KEYS}
    proxy["schema_version"] = "ember-stage2-training-arm-v2"
    proxy["arm"] = "census_bound_stage2"
    proxy["mechanisms"] = dict(
        mechanisms,
        fp8_dispatches=1,
        cuda_graph_captures=signature_count,
        cuda_graph_replays=value["steps"],
    )
    proxy["captures_during_preparation"] = signature_count
    _validate_stage2_arm(proxy)
    return dict(value)


def write_stage2_eager_workspace_diagnostic_receipt(
    path: Path, value: Mapping[str, object],
) -> dict[str, object]:
    receipt = _validate_stage2_eager_workspace_diagnostic(value)
    receipt["self_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
    _write_json_no_overwrite(path, receipt, label="Stage-2 eager-workspace diagnostic receipt")
    return receipt


def load_stage2_eager_workspace_diagnostic_receipt(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Stage-2 eager-workspace diagnostic is not readable strict JSON") from error
    if (
        not isinstance(value, dict)
        or set(value) != _STAGE2_EAGER_WORKSPACE_DIAGNOSTIC_KEYS | {"self_sha256"}
    ):
        raise ValueError("Stage-2 eager-workspace diagnostic must use its closed v1 key set")
    claimed = _sha256(value["self_sha256"], label="eager-workspace diagnostic self sha256")
    unsigned = dict(value)
    del unsigned["self_sha256"]
    if hashlib.sha256(_canonical_json(unsigned)).hexdigest() != claimed:
        raise ValueError("Stage-2 eager-workspace diagnostic self hash mismatch")
    return _validate_stage2_eager_workspace_diagnostic(unsigned)


def _load_stage2_arm_receipt_bytes(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Stage-2 arm receipt is not readable strict JSON") from error
    if not isinstance(value, dict) or set(value) != _STAGE2_ARM_KEYS | {"self_sha256"}:
        raise ValueError("Stage-2 arm receipt must use the closed v2 key set")
    claimed = _sha256(value["self_sha256"], label="Stage-2 arm receipt self sha256")
    unsigned = dict(value)
    del unsigned["self_sha256"]
    if hashlib.sha256(_canonical_json(unsigned)).hexdigest() != claimed:
        raise ValueError("Stage-2 arm receipt self hash mismatch")
    return _validate_stage2_arm(unsigned)


def build_stage2_ab_comparison(
    baseline: Mapping[str, object], accelerated: Mapping[str, object],
) -> dict[str, object]:
    baseline_value = _validate_stage2_arm(baseline)
    accelerated_value = _validate_stage2_arm(accelerated)
    if baseline_value["arm"] != "bf16_baseline" or accelerated_value["arm"] != "census_bound_stage2":
        raise ValueError("Stage-2 comparison arm order is invalid")
    identity_keys = (
        "source_commit", "runner_source_sha256", "model_config_sha256",
        "input_identity_sha256", "record_order_sha256", "checkpoint_lineage_sha256",
        "seed", "initial_cursor", "steps", "tokens",
        "preparation_regions_per_signature", "preparation_signature_count",
        "preparation_region_count", "optimizer_state_preinitialized_parameters",
        "captures_during_measured_window",
        "no_capture_in_measured_window",
    )
    if any(baseline_value[key] != accelerated_value[key] for key in identity_keys):
        raise ValueError("Stage-2 comparison identity mismatch")
    loss_pairs = zip(baseline_value["losses"], accelerated_value["losses"], strict=True)
    deltas = [
        (
            abs(float(candidate) - float(control)),
            abs(float(candidate) - float(control)) / max(abs(float(control)), 1e-12),
        )
        for control, candidate in loss_pairs
    ]
    max_absolute = max(item[0] for item in deltas)
    max_relative = max(item[1] for item in deltas)
    if max_relative >= _STAGE2_MATCHED_LOSS_RELATIVE_TOLERANCE:
        raise ValueError("Stage-2 matched loss tolerance was not met")
    mechanisms = accelerated_value["mechanisms"]
    close = validate_close_evidence({
        "fp8_dispatches": mechanisms["fp8_dispatches"],
        "cuda_graph_replays": mechanisms["cuda_graph_replays"],
        "fp8_fallbacks": mechanisms["fp8_fallbacks"],
        "cuda_graph_fallbacks": mechanisms["cuda_graph_fallbacks"],
        "tokens_per_second": accelerated_value["tokens_per_second"],
        "real_training_path": True,
    })
    baseline_rate = float(baseline_value["tokens_per_second"])
    accelerated_rate = float(accelerated_value["tokens_per_second"])
    receipt: dict[str, object] = {
        "schema_version": "ember-stage2-training-ab-v1",
        "status": "PASS",
        "baseline_receipt_sha256": hashlib.sha256(_canonical_json(baseline_value)).hexdigest(),
        "accelerated_receipt_sha256": hashlib.sha256(_canonical_json(accelerated_value)).hexdigest(),
        "matched_identity": {key: baseline_value[key] for key in identity_keys},
        "matched_loss_relative_tolerance": _STAGE2_MATCHED_LOSS_RELATIVE_TOLERANCE,
        "max_absolute_loss_delta": max_absolute,
        "max_relative_loss_delta": max_relative,
        "baseline_tokens_per_second": baseline_rate,
        "accelerated_tokens_per_second": accelerated_rate,
        "throughput_speedup": accelerated_rate / baseline_rate,
        "close_evidence": close,
    }
    receipt["self_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
    return receipt


def compare_stage2_ab_receipts(
    baseline_path: Path, accelerated_path: Path, output_path: Path,
) -> dict[str, object]:
    try:
        baseline_raw = baseline_path.read_bytes()
        accelerated_raw = accelerated_path.read_bytes()
    except OSError as error:
        raise ValueError("Stage-2 arm receipt is not readable") from error
    comparison = build_stage2_ab_comparison(
        _load_stage2_arm_receipt_bytes(baseline_raw),
        _load_stage2_arm_receipt_bytes(accelerated_raw),
    )
    comparison["baseline_raw_sha256"] = hashlib.sha256(baseline_raw).hexdigest()
    comparison["accelerated_raw_sha256"] = hashlib.sha256(accelerated_raw).hexdigest()
    comparison["self_sha256"] = hashlib.sha256(
        _canonical_json({key: value for key, value in comparison.items() if key != "self_sha256"})
    ).hexdigest()
    _write_json_no_overwrite(output_path, comparison, label="Stage-2 A/B comparison receipt")
    return comparison
