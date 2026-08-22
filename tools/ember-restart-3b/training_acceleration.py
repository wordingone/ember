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

import re
import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
    "accumulation_mode", "weight_refreshes", "dispatches", "fallbacks",
}
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
        "sites": "swiglu_down_4h_to_h",
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
    if fp8["required_compute_capability"] != "8.9" or fp8["sites"] != "swiglu_down_4h_to_h":
        raise ValueError("FP8 policy must bind SM89 SwiGLU 4H-to-H down projections")
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


class TorchCudaGraphBackend:
    """Thin production backend; Stage 1 config cannot call it."""

    def capture(self, region: Callable[[], None]) -> torch.cuda.CUDAGraph:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA graph capture requires CUDA")
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            region()
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
        kernel: ScaledMmKernel,
    ) -> torch.Tensor:
        if activation.shape[-1] != weight.shape[1]:
            raise RuntimeError("FP8 down projection input width does not match the live weight")
        flat = activation.reshape(-1, activation.shape[-1])
        absolute_max = flat.detach().abs().amax().float()
        if not bool(torch.isfinite(absolute_max)):
            raise RuntimeError("FP8 activation scale is non-finite")
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
            scale_a,
            weight_scale,
            out_dtype=activation.dtype,
            use_fast_accum=True,
        )
        if isinstance(output, tuple):
            output = output[0]
        ctx.save_for_backward(flat, weight)
        ctx.input_shape = activation.shape
        return output.reshape(*activation.shape[:-1], weight.shape[0])

    @staticmethod
    def backward(ctx: Any, grad_output: torch.Tensor) -> tuple[torch.Tensor | None, ...]:
        flat, weight = ctx.saved_tensors
        grad = grad_output.reshape(-1, grad_output.shape[-1]).to(weight.dtype)
        grad_input = grad.matmul(weight).reshape(ctx.input_shape)
        grad_weight = grad.transpose(0, 1).matmul(flat.to(weight.dtype))
        return grad_input, grad_weight, None, None, None


class DynamicFp8DownProjection(nn.Module):
    """Live-master FP8 down projection with a stable captured weight operand.

    The persistent FP8 buffer is refreshed once after each optimizer update.
    Forward only takes a transposed view, so it performs zero weight
    materialization copies and keeps the graph operand address stable.
    """

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
        if weight.ndim != 2 or weight.shape[1] != 4 * weight.shape[0]:
            raise ValueError("issue #1413 FP8 site must be a 4H-to-H down projection")
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
        self.register_buffer("_weight_scale", torch.ones((), device=weight.device, dtype=torch.float32), persistent=False)
        self._dispatches = 0
        self._fallbacks = 0
        self._weight_refreshes = 0
        self._refreshed_weight_version = -1
        self.refresh_after_optimizer_step()

    @classmethod
    def from_linear(
        cls,
        linear: nn.Linear,
        *,
        kernel: ScaledMmKernel | None = None,
        allow_test_device: bool = False,
    ) -> "DynamicFp8DownProjection":
        return cls(weight=linear.weight, bias=linear.bias, kernel=kernel, allow_test_device=allow_test_device)

    def refresh_after_optimizer_step(self) -> None:
        with torch.no_grad():
            absolute_max = self.weight.detach().abs().amax().float()
            if not bool(torch.isfinite(absolute_max)):
                raise RuntimeError("FP8 weight scale is non-finite")
            scale = torch.where(absolute_max > 0, absolute_max / 448.0, torch.ones_like(absolute_max))
            quantized = (self.weight.detach() / scale).clamp(-448.0, 448.0).to(torch.float8_e4m3fn)
            self._weight_fp8.copy_(quantized)
            self._weight_scale.copy_(scale)
        self._refreshed_weight_version = self.weight._version
        self._weight_refreshes += 1

    def forward(self, activation: torch.Tensor) -> torch.Tensor:
        if activation.dtype is not torch.bfloat16:
            raise RuntimeError("issue #1413 FP8 site requires a BF16 activation")
        if self.weight._version != self._refreshed_weight_version:
            raise RuntimeError("stale FP8 weight: refresh_after_optimizer_step is required after every update")
        output = _DynamicFp8ScaledMm.apply(
            activation, self.weight, self._weight_fp8, self._weight_scale, self._kernel,
        )
        self._dispatches += 1
        return output

    def kernel_receipt(self) -> dict[str, object]:
        capability = "TEST_ONLY"
        if not self._test_device:
            major, minor = torch.cuda.get_device_capability(self.weight.device)
            capability = f"{major}.{minor}"
        return {
            "schema_version": "ember-fp8-scaled-mm-kernel-receipt-v1",
            "kernel": "torch._scaled_mm",
            "compute_capability": capability,
            "activation_dtype": "float8_e4m3fn",
            "weight_dtype": "float8_e4m3fn",
            "output_dtype": "bfloat16",
            "activation_operand_layout": "row_major_contiguous",
            "weight_operand_layout": "column_major_transposed_view",
            "per_forward_weight_materialization_copies": 0,
            "accumulation_mode": "fast_accum",
            "weight_refreshes": self._weight_refreshes,
            "dispatches": self._dispatches,
            "fallbacks": self._fallbacks,
        }


def validate_fp8_kernel_receipt(value: Mapping[str, object]) -> dict[str, object]:
    _closed_keys(value, _KERNEL_RECEIPT_KEYS, label="FP8 kernel receipt")
    if value["schema_version"] != "ember-fp8-scaled-mm-kernel-receipt-v1" or value["kernel"] != "torch._scaled_mm":
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
