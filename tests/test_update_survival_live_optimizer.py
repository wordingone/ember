# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest

import torch

from src.ember.governance.scripts.preflight.update_survival import (
    LiveTensorBinding,
    run_live_optimizer_update_survival_preflight,
)


class _ForeignOptimizer(torch.optim.Optimizer):
    def __init__(self, params) -> None:
        super().__init__(params, {"lr": 1.0})

    @torch.no_grad()
    def step(self, closure=None):
        for group in self.param_groups:
            for parameter in group["params"]:
                if parameter.grad is not None:
                    parameter.add_(parameter.grad, alpha=-group["lr"])


def _binding(
    name: str,
    parameter: torch.nn.Parameter,
    *,
    tensor_class: str,
) -> LiveTensorBinding:
    return LiveTensorBinding(
        name=name,
        tensor_class=tensor_class,
        parameter=parameter,
        required_survival=True,
    )


class UpdateSurvivalLiveOptimizerTests(unittest.TestCase):
    def test_live_optimizer_preserves_realized_split_groups(self) -> None:
        fast = torch.nn.Parameter(torch.ones(16, dtype=torch.bfloat16))
        slow = torch.nn.Parameter(torch.ones(16, dtype=torch.bfloat16))
        fast.grad = torch.full_like(fast, 1.0e-2)
        slow.grad = torch.full_like(slow, 1.0e-2)
        optimizer = torch.optim.SGD(
            [
                {"params": [fast], "lr": 1.0},
                {"params": [slow], "lr": 0.5},
            ],
            momentum=0.0,
            dampening=0.0,
            weight_decay=0.0,
            nesterov=False,
            maximize=False,
            foreach=False,
            differentiable=False,
            fused=False,
        )

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[
                _binding("fast.weight", fast, tensor_class="fast"),
                _binding("slow.weight", slow, tensor_class="slow"),
            ],
            optimizer=optimizer,
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"fast": 0.0, "slow": 0.0},
            gradient_source={"kind": "captured", "source_id": "split-groups"},
        )

        self.assertNotEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["optimizer"]["family"], "sgd")
        self.assertEqual(
            [
                group["parameter_names"]
                for group in receipt["optimizer"]["param_groups"]
            ],
            [["fast.weight"], ["slow.weight"]],
        )
        self.assertEqual(
            [group["options"]["lr"] for group in receipt["optimizer"]["param_groups"]],
            [1.0, 0.5],
        )
        self.assertGreater(
            receipt["steps"][0]["tensor_classes"]["fast"]["causal_rms"],
            receipt["steps"][0]["tensor_classes"]["slow"]["causal_rms"],
        )

    def test_live_optimizer_rejects_incomplete_parameter_coverage(self) -> None:
        included = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        omitted = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        included.grad = torch.ones_like(included)
        omitted.grad = torch.ones_like(omitted)
        optimizer = torch.optim.SGD([included, omitted], lr=1.0)

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[_binding("included", included, tensor_class="weight")],
            optimizer=optimizer,
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "incomplete-map"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_REFERENCE")

    def test_live_optimizer_requires_captured_non_none_gradients(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        optimizer = torch.optim.AdamW([parameter], lr=0.01)

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[_binding("weight", parameter, tensor_class="weight")],
            optimizer=optimizer,
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "missing-grad"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_INPUT")

    def test_unrecognized_optimizer_class_fails_closed(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        parameter.grad = torch.ones_like(parameter)
        optimizer = _ForeignOptimizer([parameter])

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[_binding("weight", parameter, tensor_class="weight")],
            optimizer=optimizer,
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "foreign"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_REFERENCE")


if __name__ == "__main__":
    unittest.main()
