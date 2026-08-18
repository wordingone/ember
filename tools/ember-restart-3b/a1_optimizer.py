# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned full-state AdamW with FP32 optimizer state offloaded to CPU."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import torch

from a1_dense import (
    A1Mechanism,
    A1Refusal,
    A1RefusalCode,
    A1Tier,
    require_a1_config_sha256,
    require_clean_a1_lineage,
    require_tier_mechanism,
)


_TRAINING_STATE_FIELDS = {"default_tier", "default_mechanism", "tier_mechanism", "optimizer"}
_OPTIMIZER_FIELDS = {"name", "implementation", "placement", "state_format", "hyperparameters"}
_HYPERPARAMETER_FIELDS = {"learning_rate", "betas", "epsilon", "weight_decay"}
_EXPECTED_TIER_MECHANISM = {
    "TIER_1": "FULL_STATE_ADAMW_CPU_OFFLOAD",
    "TIER_2": "OWNED_Q_GALORE_PROJECTED_GRADIENT",
}


def _invalid(detail: str) -> None:
    raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_CONTRACT_INVALID, detail)


def _number(value: object, field: str, *, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(f"{field} must be a JSON number")
    result = float(value)
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        _invalid(f"{field} is outside its admitted range")
    return result


@dataclass(frozen=True)
class A1OptimizerContract:
    learning_rate: float
    beta1: float
    beta2: float
    epsilon: float
    weight_decay: float
    state_format: str
    tier: A1Tier = A1Tier.TIER_1
    mechanism: A1Mechanism = A1Mechanism.FULL_STATE_ADAMW_CPU_OFFLOAD


def load_a1_optimizer_contract(path: str | Path | None = None) -> A1OptimizerContract:
    contract_path = Path(path) if path is not None else Path(__file__).with_name("ember-restart-3b-a1.json")
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_CONTRACT_INVALID, "A1 contract is unavailable or invalid") from error
    training_state = payload.get("training_state") if isinstance(payload, Mapping) else None
    require_clean_a1_lineage(payload.get("lineage") if isinstance(payload, Mapping) else None)
    if not isinstance(training_state, Mapping) or set(training_state) != _TRAINING_STATE_FIELDS:
        _invalid("training_state has an invalid closed schema")
    if training_state["tier_mechanism"] != _EXPECTED_TIER_MECHANISM:
        _invalid("tier-to-mechanism mapping drifted")
    try:
        tier = A1Tier(training_state["default_tier"])
    except (TypeError, ValueError) as error:
        raise A1Refusal(A1RefusalCode.A1_TIER_TYPE_INVALID, "default tier is invalid") from error
    try:
        mechanism = A1Mechanism(training_state["default_mechanism"])
    except (TypeError, ValueError) as error:
        raise A1Refusal(A1RefusalCode.A1_MECHANISM_TYPE_INVALID, "default mechanism is invalid") from error
    require_tier_mechanism(tier, mechanism)
    optimizer = training_state["optimizer"]
    if not isinstance(optimizer, Mapping) or set(optimizer) != _OPTIMIZER_FIELDS:
        _invalid("optimizer has an invalid closed schema")
    expected_identity = {
        "name": "full_state_adamw_cpu_offload",
        "implementation": "owned.FullStateAdamWCPUOffload",
        "placement": "cpu_fp32_master_and_moments",
        "state_format": "ember-a1-full-state-adamw-cpu-offload-v1",
    }
    if any(optimizer.get(field) != value for field, value in expected_identity.items()):
        _invalid("optimizer identity drifted")
    hyperparameters = optimizer["hyperparameters"]
    if not isinstance(hyperparameters, Mapping) or set(hyperparameters) != _HYPERPARAMETER_FIELDS:
        _invalid("optimizer hyperparameters have an invalid closed schema")
    betas = hyperparameters["betas"]
    if not isinstance(betas, list) or len(betas) != 2:
        _invalid("optimizer betas must contain two JSON numbers")
    beta1 = _number(betas[0], "beta1", positive=False)
    beta2 = _number(betas[1], "beta2", positive=False)
    if not 0 <= beta1 < 1 or not 0 <= beta2 < 1:
        _invalid("optimizer betas must be in [0, 1)")
    contract = A1OptimizerContract(
        learning_rate=_number(hyperparameters["learning_rate"], "learning_rate", positive=True),
        beta1=beta1,
        beta2=beta2,
        epsilon=_number(hyperparameters["epsilon"], "epsilon", positive=True),
        weight_decay=_number(hyperparameters["weight_decay"], "weight_decay", positive=False),
        state_format=optimizer["state_format"],
        tier=tier,
        mechanism=mechanism,
    )
    require_a1_config_sha256(contract_path)
    return contract


class FullStateAdamWCPUOffload(torch.optim.Optimizer):
    """AdamW with complete FP32 master/moment state resident on CPU.

    State allocation is an explicit atomic phase so Packet B2 can perform host
    resource admission before committing the production-sized allocation.
    ``step`` refuses until every registered parameter has complete state.
    """

    def __init__(self, params: Iterable[torch.nn.Parameter], *, contract: A1OptimizerContract) -> None:
        require_tier_mechanism(contract.tier, contract.mechanism)
        parameters = list(params)
        if not parameters or any(not isinstance(parameter, torch.nn.Parameter) for parameter in parameters):
            _invalid("optimizer requires at least one torch Parameter")
        if len({id(parameter) for parameter in parameters}) != len(parameters):
            _invalid("optimizer parameter inventory contains aliases")
        self.contract = contract
        super().__init__(parameters, defaults={
            "lr": contract.learning_rate,
            "betas": (contract.beta1, contract.beta2),
            "eps": contract.epsilon,
            "weight_decay": contract.weight_decay,
        })

    def _parameters(self) -> list[torch.nn.Parameter]:
        return [parameter for group in self.param_groups for parameter in group["params"]]

    @torch.no_grad()
    def initialize_state(self) -> None:
        parameters = self._parameters()
        if self.state:
            self._require_complete_state()
            return
        pending: list[tuple[torch.nn.Parameter, dict[str, Any]]] = []
        for parameter in parameters:
            if parameter.device.type == "meta":
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "optimizer state cannot materialize from meta parameters")
            master = parameter.detach().to(device="cpu", dtype=torch.float32).clone()
            pending.append((parameter, {
                "step": 0,
                "master_copy": master,
                "exp_avg": torch.zeros_like(master, device="cpu", dtype=torch.float32),
                "exp_avg_sq": torch.zeros_like(master, device="cpu", dtype=torch.float32),
            }))
        for parameter, state in pending:
            self.state[parameter] = state
        self._require_complete_state()

    def _require_complete_state(self) -> None:
        parameters = self._parameters()
        if len(self.state) != len(parameters):
            raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "optimizer state does not cover every parameter")
        for parameter in parameters:
            state = self.state.get(parameter)
            if not isinstance(state, Mapping) or set(state) != {"step", "master_copy", "exp_avg", "exp_avg_sq"} or type(state["step"]) is not int or state["step"] < 0:
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "optimizer state schema is incomplete")
            for field in ("master_copy", "exp_avg", "exp_avg_sq"):
                tensor = state[field]
                if not isinstance(tensor, torch.Tensor) or tensor.device.type != "cpu" or tensor.dtype is not torch.float32 or tensor.shape != parameter.shape:
                    raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, f"optimizer {field} is not complete CPU FP32 state")

    def state_inventory(self) -> dict[str, object]:
        parameters = self._parameters()
        complete = True
        try:
            self._require_complete_state()
        except A1Refusal:
            complete = False
        initialized = [parameter for parameter in parameters if parameter in self.state]
        return {
            "schema_version": "ember-a1-adamw-state-inventory-v1",
            "state_format": self.contract.state_format,
            "registered_parameters": len(parameters),
            "registered_numel": sum(parameter.numel() for parameter in parameters),
            "initialized_parameters": len(initialized),
            "cpu_fp32_master_numel": sum(self.state[parameter]["master_copy"].numel() for parameter in initialized if "master_copy" in self.state[parameter]),
            "cpu_fp32_first_moment_numel": sum(self.state[parameter]["exp_avg"].numel() for parameter in initialized if "exp_avg" in self.state[parameter]),
            "cpu_fp32_second_moment_numel": sum(self.state[parameter]["exp_avg_sq"].numel() for parameter in initialized if "exp_avg_sq" in self.state[parameter]),
            "complete": complete,
        }

    def load_state_dict(self, state_dict: Mapping[str, Any]) -> None:
        """Load only a complete closed state without ever staging it on CUDA."""

        if not isinstance(state_dict, Mapping) or set(state_dict) != {"state", "param_groups"}:
            raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer state has an invalid schema")
        serialized_state = state_dict["state"]
        serialized_groups = state_dict["param_groups"]
        if not isinstance(serialized_state, Mapping) or not isinstance(serialized_groups, list) or len(serialized_groups) != len(self.param_groups):
            raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer groups do not match the registered inventory")
        pending: dict[torch.nn.Parameter, dict[str, Any]] = {}
        consumed_ids: set[object] = set()
        group_fields = {"lr", "betas", "eps", "weight_decay", "params"}
        for serialized_group, current_group in zip(serialized_groups, self.param_groups):
            if not isinstance(serialized_group, Mapping) or set(serialized_group) != group_fields:
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer group schema drifted")
            for field in ("lr", "betas", "eps", "weight_decay"):
                if serialized_group[field] != current_group[field]:
                    raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, f"serialized optimizer {field} drifted")
            identifiers = serialized_group["params"]
            parameters = current_group["params"]
            if not isinstance(identifiers, list) or len(identifiers) != len(parameters):
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer parameter inventory drifted")
            try:
                identifier_set = set(identifiers)
            except TypeError as error:
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer parameter identifiers are invalid") from error
            if len(identifier_set) != len(identifiers) or identifier_set & consumed_ids:
                raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer parameter identifiers are not globally unique")
            consumed_ids.update(identifier_set)
            for identifier, parameter in zip(identifiers, parameters):
                serialized = serialized_state.get(identifier)
                if not isinstance(serialized, Mapping) or set(serialized) != {"step", "master_copy", "exp_avg", "exp_avg_sq"} or type(serialized["step"]) is not int or serialized["step"] < 0:
                    raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer parameter state is incomplete")
                restored: dict[str, Any] = {"step": serialized["step"]}
                for field in ("master_copy", "exp_avg", "exp_avg_sq"):
                    tensor = serialized[field]
                    if not isinstance(tensor, torch.Tensor) or tensor.shape != parameter.shape:
                        raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, f"serialized optimizer {field} is invalid")
                    restored[field] = tensor.detach().to(device="cpu", dtype=torch.float32).clone()
                pending[parameter] = restored
        if set(serialized_state) != consumed_ids:
            raise A1Refusal(A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE, "serialized optimizer state has unbound entries")
        self.state.clear()
        self.state.update(pending)
        self._require_complete_state()

    @torch.no_grad()
    def step(self, closure: Any | None = None) -> Any | None:
        self._require_complete_state()
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()
        for group in self.param_groups:
            learning_rate = float(group["lr"])
            beta1, beta2 = group["betas"]
            epsilon = float(group["eps"])
            weight_decay = float(group["weight_decay"])
            for parameter in group["params"]:
                if parameter.grad is None:
                    continue
                if parameter.grad.is_sparse:
                    _invalid("sparse gradients are not admitted by full-state AdamW")
                state = self.state[parameter]
                gradient = parameter.grad.detach().to(device="cpu", dtype=torch.float32)
                state["step"] += 1
                step = state["step"]
                master = state["master_copy"]
                exp_avg = state["exp_avg"]
                exp_avg_sq = state["exp_avg_sq"]
                master.mul_(1.0 - learning_rate * weight_decay)
                exp_avg.mul_(beta1).add_(gradient, alpha=1.0 - beta1)
                exp_avg_sq.mul_(beta2).addcmul_(gradient, gradient, value=1.0 - beta2)
                bias_correction1 = 1.0 - beta1**step
                bias_correction2 = 1.0 - beta2**step
                denominator = exp_avg_sq.sqrt().div_(math.sqrt(bias_correction2)).add_(epsilon)
                master.addcdiv_(exp_avg, denominator, value=-(learning_rate / bias_correction1))
                parameter.copy_(master.to(device=parameter.device, dtype=parameter.dtype))
        return loss
