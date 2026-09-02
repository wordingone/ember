# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned CUDA projected-gradient optimizer with block-quantized state."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

import torch

from a1_dense import A1Refusal, A1RefusalCode
from a1_optimizer import FullGradientNormAccumulator


SIGNED_INT4 = "SIGNED_INT4_SYMMETRIC"
SIGNED_INT8 = "SIGNED_INT8_SYMMETRIC"
UNSIGNED_UINT8 = "UNSIGNED_UINT8"
_FORMATS = {SIGNED_INT4, SIGNED_INT8, UNSIGNED_UINT8}


def _invalid(detail: str) -> None:
    raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_CONTRACT_INVALID, detail)


@dataclass(frozen=True)
class QuantizedTensor:
    format_name: str
    block_size: int
    shape: tuple[int, ...]
    numel: int
    payload: torch.Tensor
    scales: torch.Tensor


def _validate_quantized(record: QuantizedTensor) -> None:
    if not isinstance(record, QuantizedTensor) or record.format_name not in _FORMATS:
        _invalid("quantized tensor record is invalid")
    if type(record.block_size) is not int or record.block_size < 1:
        _invalid("quantized tensor block size is invalid")
    if type(record.numel) is not int or record.numel < 1:
        _invalid("quantized tensor numel is invalid")
    if math.prod(record.shape) != record.numel:
        _invalid("quantized tensor shape is invalid")
    blocks = (record.numel + record.block_size - 1) // record.block_size
    if record.scales.dtype is not torch.float32 or record.scales.numel() != blocks:
        _invalid("quantized tensor scales are invalid")
    expected_payload = (record.numel + 1) // 2 if record.format_name == SIGNED_INT4 else record.numel
    expected_dtype = torch.int8 if record.format_name == SIGNED_INT8 else torch.uint8
    if record.payload.dtype is not expected_dtype or record.payload.numel() != expected_payload:
        _invalid("quantized tensor payload is invalid")
    if record.payload.device != record.scales.device:
        _invalid("quantized tensor payload and scales span devices")
    if not bool(torch.isfinite(record.scales).all().item()) or bool((record.scales <= 0).any().item()):
        _invalid("quantized tensor scales are non-finite or non-positive")


def quantize_blocks(
    value: torch.Tensor,
    format_name: str,
    *,
    block_size: int = 256,
) -> QuantizedTensor:
    if not isinstance(value, torch.Tensor) or value.is_sparse or value.numel() < 1:
        _invalid("quantization requires a non-empty dense tensor")
    if format_name not in _FORMATS or type(block_size) is not int or block_size < 1:
        _invalid("quantization format or block size is invalid")
    source = value.detach().to(dtype=torch.float32).contiguous().reshape(-1)
    if not bool(torch.isfinite(source).all().item()):
        _invalid("quantization input is non-finite")
    if format_name == UNSIGNED_UINT8 and bool((source < 0).any().item()):
        _invalid("unsigned quantization input is negative")
    padded_numel = ((source.numel() + block_size - 1) // block_size) * block_size
    if padded_numel != source.numel():
        source_blocks = torch.cat((source, source.new_zeros(padded_numel - source.numel())))
    else:
        source_blocks = source
    source_blocks = source_blocks.reshape(-1, block_size)
    maximum = (
        source_blocks.max(dim=1).values
        if format_name == UNSIGNED_UINT8
        else source_blocks.abs().max(dim=1).values
    )
    divisor = 255.0 if format_name == UNSIGNED_UINT8 else (7.0 if format_name == SIGNED_INT4 else 127.0)
    scales = torch.where(maximum == 0, torch.ones_like(maximum), maximum / divisor)
    lower = 0 if format_name == UNSIGNED_UINT8 else (-7 if format_name == SIGNED_INT4 else -127)
    upper = 255 if format_name == UNSIGNED_UINT8 else (7 if format_name == SIGNED_INT4 else 127)
    dtype = torch.uint8 if format_name == UNSIGNED_UINT8 else torch.int8
    unpacked = (
        torch.round(source_blocks / scales[:, None])
        .clamp(lower, upper)
        .to(dtype=dtype)
        .reshape(-1)[:source.numel()]
    )
    if format_name == SIGNED_INT4:
        nibbles = torch.bitwise_and(unpacked.to(torch.int16), 15).to(torch.uint8)
        if nibbles.numel() % 2:
            nibbles = torch.cat((nibbles, torch.zeros(1, dtype=torch.uint8, device=nibbles.device)))
        payload = nibbles[0::2] | (nibbles[1::2] << 4)
    else:
        payload = unpacked
    record = QuantizedTensor(
        format_name=format_name,
        block_size=block_size,
        shape=tuple(value.shape),
        numel=value.numel(),
        payload=payload.contiguous(),
        scales=scales.to(dtype=torch.float32),
    )
    _validate_quantized(record)
    return record


def dequantize_blocks(record: QuantizedTensor) -> torch.Tensor:
    _validate_quantized(record)
    if record.format_name == SIGNED_INT4:
        low = torch.bitwise_and(record.payload, 15).to(torch.int16)
        high = (record.payload >> 4).to(torch.int16)
        unpacked = torch.empty(record.payload.numel() * 2, dtype=torch.int16, device=record.payload.device)
        unpacked[0::2] = low
        unpacked[1::2] = high
        unpacked = torch.where(unpacked >= 8, unpacked - 16, unpacked)[:record.numel]
        values = unpacked.to(torch.float32)
    else:
        values = record.payload.to(torch.float32)
    scale_values = record.scales.repeat_interleave(record.block_size)[:record.numel]
    return (values * scale_values).reshape(record.shape)


@dataclass(frozen=True)
class Projection:
    direction: str
    rank: int
    basis: torch.Tensor | None
    projected_gradient: torch.Tensor


def _canonicalize_vectors(basis: torch.Tensor, direction: str) -> torch.Tensor:
    result = basis.clone()
    vectors = result if direction == "RIGHT" else result.transpose(0, 1)
    indices = torch.argmax(torch.abs(vectors), dim=1)
    selected = vectors[torch.arange(vectors.shape[0], device=vectors.device), indices]
    signs = torch.where(selected < 0, -torch.ones_like(selected), torch.ones_like(selected))
    if direction == "RIGHT":
        result.mul_(signs[:, None])
    else:
        result.mul_(signs[None, :])
    return result


def build_projection(gradient: torch.Tensor, *, max_rank: int = 512) -> Projection:
    if (
        not isinstance(gradient, torch.Tensor)
        or gradient.is_sparse
        or gradient.numel() < 1
        or type(max_rank) is not int
        or max_rank < 1
    ):
        _invalid("projection input is invalid")
    source = gradient.detach().to(dtype=torch.float32)
    if not bool(torch.isfinite(source).all().item()):
        _invalid("projection gradient is non-finite")
    if source.ndim != 2 or min(source.shape) <= max_rank:
        return Projection("UNPROJECTED", min(source.shape) if source.ndim == 2 else 0, None, source)
    try:
        left, _, right = torch.linalg.svd(source, full_matrices=False)
    except RuntimeError as error:
        raise A1Refusal(
            A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE,
            "deterministic FP32 SVD could not execute",
        ) from error
    rank = min(max_rank, min(source.shape))
    if source.shape[0] >= source.shape[1]:
        direction = "RIGHT"
        basis = _canonicalize_vectors(right[:rank, :], direction)
        projected = source @ basis.transpose(0, 1)
    else:
        direction = "LEFT"
        basis = _canonicalize_vectors(left[:, :rank], direction)
        projected = basis.transpose(0, 1) @ source
    return Projection(direction, rank, basis.contiguous(), projected.contiguous())


def reconstruct_projection(
    projected: torch.Tensor,
    basis: torch.Tensor | None,
    direction: str,
) -> torch.Tensor:
    if direction == "UNPROJECTED":
        if basis is not None:
            _invalid("unprojected update cannot carry a basis")
        return projected
    if not isinstance(basis, torch.Tensor) or basis.dtype is not torch.float32:
        _invalid("projected update basis is invalid")
    if direction == "RIGHT":
        return projected @ basis
    if direction == "LEFT":
        return basis @ projected
    _invalid("projection direction is invalid")


@dataclass(frozen=True)
class Tier2OptimizerContract:
    learning_rate: float = 0.00001
    beta1: float = 0.9
    beta2: float = 0.999
    epsilon: float = 1e-8
    weight_decay: float = 0.01
    max_rank: int = 512
    refresh_gap: int = 200
    projection_scale: float = 0.25
    block_size: int = 256
    state_format: str = "ember-a1-tier2-q-galore-cuda-v1"

    @classmethod
    def for_tests(cls, *, max_rank: int = 2, refresh_gap: int = 2) -> "Tier2OptimizerContract":
        return cls(max_rank=max_rank, refresh_gap=refresh_gap)


class ProjectedQuantizedAdamWCUDA(torch.optim.Optimizer):
    """Fused AdamW whose persistent moments and projectors remain quantized on CUDA."""

    def __init__(
        self,
        named_parameters: Iterable[tuple[str, torch.nn.Parameter]],
        *,
        contract: Tier2OptimizerContract,
    ) -> None:
        pairs = list(named_parameters)
        if (
            not pairs
            or any(not isinstance(name, str) or not name or not isinstance(parameter, torch.nn.Parameter) for name, parameter in pairs)
            or len({name for name, _ in pairs}) != len(pairs)
            or len({id(parameter) for _, parameter in pairs}) != len(pairs)
        ):
            _invalid("Tier-2 optimizer requires unique named parameters")
        if any(parameter.device.type != "cuda" for _, parameter in pairs):
            _invalid("Tier-2 optimizer parameters must reside on CUDA")
        if (
            contract.max_rank < 1
            or contract.refresh_gap < 1
            or contract.block_size != 256
            or contract.projection_scale <= 0
        ):
            _invalid("Tier-2 optimizer contract is invalid")
        self.contract = contract
        self.parameter_names = {id(parameter): name for name, parameter in pairs}
        self._ordered_parameters = [parameter for _, parameter in pairs]
        self._gradient_norm = FullGradientNormAccumulator()
        self._fused_backward_enabled = False
        self._hook_handles: list[Any] = []
        super().__init__(self._ordered_parameters, defaults={
            "lr": contract.learning_rate,
            "betas": (contract.beta1, contract.beta2),
            "eps": contract.epsilon,
            "weight_decay": contract.weight_decay,
        })
        self._group_by_parameter_id = {
            id(parameter): group
            for group in self.param_groups
            for parameter in group["params"]
        }

    def _state_shape(self, parameter: torch.nn.Parameter) -> tuple[tuple[int, ...], str, int]:
        shape = tuple(parameter.shape)
        if parameter.ndim != 2 or min(shape) <= self.contract.max_rank:
            return shape, "UNPROJECTED", min(shape) if parameter.ndim == 2 else 0
        rank = min(self.contract.max_rank, min(shape))
        if shape[0] >= shape[1]:
            return (shape[0], rank), "RIGHT", rank
        return (rank, shape[1]), "LEFT", rank

    def ordered_named_parameters(self) -> list[tuple[str, torch.nn.Parameter]]:
        return [(self.parameter_names[id(parameter)], parameter) for parameter in self._ordered_parameters]

    @torch.no_grad()
    def initialize_state(self) -> None:
        if self.state:
            self._require_complete_state()
            return
        for parameter in self._ordered_parameters:
            moment_shape, direction, rank = self._state_shape(parameter)
            zero = torch.zeros(moment_shape, device=parameter.device, dtype=torch.float32)
            self.state[parameter] = {
                "step": 0,
                "direction": direction,
                "rank": rank,
                "refresh_ordinal": 0,
                "basis": None,
                "exp_avg": quantize_blocks(zero, SIGNED_INT8, block_size=self.contract.block_size),
                "exp_avg_sq": quantize_blocks(zero, UNSIGNED_UINT8, block_size=self.contract.block_size),
            }
        self._require_complete_state()

    def _require_complete_state(self) -> None:
        if len(self.state) != len(self._ordered_parameters):
            raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "Tier-2 state coverage is incomplete")
        fields = {"step", "direction", "rank", "refresh_ordinal", "basis", "exp_avg", "exp_avg_sq"}
        for parameter in self._ordered_parameters:
            state = self.state.get(parameter)
            if not isinstance(state, dict) or set(state) != fields:
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "Tier-2 state schema is incomplete")
            if type(state["step"]) is not int or state["step"] < 0:
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "Tier-2 step is invalid")
            if type(state["refresh_ordinal"]) is not int or state["refresh_ordinal"] < 0:
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "Tier-2 refresh ordinal is invalid")
            for field in ("exp_avg", "exp_avg_sq"):
                _validate_quantized(state[field])
                if state[field].payload.device.type != "cuda":
                    raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "Tier-2 moments left CUDA")
            basis = state["basis"]
            if basis is not None:
                _validate_quantized(basis)
                if basis.format_name != SIGNED_INT4 or basis.payload.device.type != "cuda":
                    raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "Tier-2 projector state is invalid")

    def state_inventory(self) -> dict[str, object]:
        complete = True
        try:
            self._require_complete_state()
        except A1Refusal:
            complete = False
        initialized = [parameter for parameter in self._ordered_parameters if parameter in self.state]
        payload_bytes = 0
        scale_bytes = 0
        for parameter in initialized:
            for field in ("basis", "exp_avg", "exp_avg_sq"):
                record = self.state[parameter][field]
                if record is not None:
                    payload_bytes += record.payload.numel() * record.payload.element_size()
                    scale_bytes += record.scales.numel() * record.scales.element_size()
        return {
            "schema_version": "ember-a1-tier2-state-inventory-v1",
            "state_format": self.contract.state_format,
            "registered_parameters": len(self._ordered_parameters),
            "registered_numel": sum(parameter.numel() for parameter in self._ordered_parameters),
            "initialized_parameters": len(initialized),
            "quantized_payload_bytes": payload_bytes,
            "fp32_scale_bytes": scale_bytes,
            "persistent_state_device": "cuda",
            "cpu_persistent_state_bytes": 0,
            "complete": complete,
        }

    def _project_with_state(self, gradient: torch.Tensor, state: dict[str, Any]) -> torch.Tensor:
        if state["direction"] == "UNPROJECTED":
            return gradient
        basis = dequantize_blocks(state["basis"])
        if state["direction"] == "RIGHT":
            return gradient @ basis.transpose(0, 1)
        if state["direction"] == "LEFT":
            return basis.transpose(0, 1) @ gradient
        _invalid("Tier-2 projection direction is invalid")

    @torch.no_grad()
    def _apply_parameter_update(self, parameter: torch.nn.Parameter, group: dict[str, Any]) -> None:
        gradient = parameter.grad
        if gradient is None:
            return
        if gradient.is_sparse or not bool(torch.isfinite(gradient).all().item()):
            _invalid("Tier-2 gradient is sparse or non-finite")
        state = self.state[parameter]
        next_step = state["step"] + 1
        if next_step == 1 or next_step % self.contract.refresh_gap == 0:
            if not torch.are_deterministic_algorithms_enabled():
                _invalid("Tier-2 deterministic algorithms are not enabled")
            projection = build_projection(gradient, max_rank=self.contract.max_rank)
            if projection.direction != state["direction"] or projection.rank != state["rank"]:
                _invalid("Tier-2 projection geometry drifted")
            state["basis"] = (
                None
                if projection.basis is None
                else quantize_blocks(projection.basis, SIGNED_INT4, block_size=self.contract.block_size)
            )
            state["refresh_ordinal"] += 1
            projected_gradient = self._project_with_state(gradient.to(torch.float32), state)
        else:
            projected_gradient = self._project_with_state(gradient.to(torch.float32), state)
        first = dequantize_blocks(state["exp_avg"])
        second = dequantize_blocks(state["exp_avg_sq"])
        beta1, beta2 = group["betas"]
        first.mul_(beta1).add_(projected_gradient, alpha=1.0 - beta1)
        second.mul_(beta2).addcmul_(projected_gradient, projected_gradient, value=1.0 - beta2)
        state["step"] = next_step
        correction1 = 1.0 - beta1**next_step
        correction2 = 1.0 - beta2**next_step
        update = (first / correction1) / (torch.sqrt(second / correction2) + float(group["eps"]))
        if state["direction"] != "UNPROJECTED":
            update = reconstruct_projection(
                update,
                dequantize_blocks(state["basis"]),
                state["direction"],
            )
            update.mul_(self.contract.projection_scale)
        parameter.mul_(1.0 - float(group["lr"]) * float(group["weight_decay"]))
        parameter.add_(update.to(dtype=parameter.dtype), alpha=-float(group["lr"]))
        state["exp_avg"] = quantize_blocks(first, SIGNED_INT8, block_size=self.contract.block_size)
        state["exp_avg_sq"] = quantize_blocks(second, UNSIGNED_UINT8, block_size=self.contract.block_size)

    def enable_fused_backward(self) -> None:
        if self._fused_backward_enabled:
            return
        self._require_complete_state()
        for parameter in self._ordered_parameters:
            self._hook_handles.append(parameter.register_post_accumulate_grad_hook(self._fused_backward_hook))
        self._fused_backward_enabled = True

    def _fused_backward_hook(self, parameter: torch.nn.Parameter) -> None:
        if parameter.grad is None:
            return
        self._gradient_norm.accumulate(parameter.grad)
        group = self._group_by_parameter_id[id(parameter)]
        self._apply_parameter_update(parameter, group)
        parameter.grad = None

    def finish_gradient_norm(self) -> float:
        return self._gradient_norm.finish_step()

    @torch.no_grad()
    def step(self, closure: Any | None = None) -> Any | None:
        self._require_complete_state()
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()
        if self._fused_backward_enabled:
            if any(parameter.grad is not None for parameter in self._ordered_parameters):
                raise A1Refusal(
                    A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE,
                    "Tier-2 fused backward left an unconsumed gradient",
                )
            return loss
        for group in self.param_groups:
            for parameter in group["params"]:
                if parameter.grad is None:
                    continue
                self._gradient_norm.accumulate(parameter.grad)
                self._apply_parameter_update(parameter, group)
        return loss
