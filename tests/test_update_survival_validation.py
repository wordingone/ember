# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest

import torch

from src.ember.governance.scripts.preflight.update_survival import (
    OptimizerSpec,
    TensorProbe,
    run_update_survival_preflight,
)


def _adamw_spec(*, lr: float = 0.01) -> OptimizerSpec:
    return OptimizerSpec(
        family="adamw",
        kwargs={
            "lr": lr,
            "betas": (0.9, 0.999),
            "eps": 1.0e-8,
            "weight_decay": 0.0,
            "amsgrad": False,
            "maximize": False,
            "foreach": False,
            "capturable": False,
            "differentiable": False,
            "fused": False,
        },
    )


def _probe() -> TensorProbe:
    return TensorProbe(
        name="weight",
        tensor_class="weight",
        initial=torch.ones(8, dtype=torch.float32),
        gradient=torch.full((8,), 0.1, dtype=torch.float32),
        required_survival=True,
    )


class UpdateSurvivalValidationTests(unittest.TestCase):
    def test_nonfinite_optimizer_input_returns_invalid_receipt(self) -> None:
        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(lr=float("nan")),
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "synthetic", "source_id": "nan-lr"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_INPUT")
        self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")

    def test_malformed_gradient_source_returns_invalid_receipt(self) -> None:
        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(),
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_INPUT")
        self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")

    def test_state_hyperparameters_cannot_override_declared_optimizer(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(8, dtype=torch.float32))
        source = torch.optim.AdamW(
            [parameter],
            lr=0.02,
            betas=(0.9, 0.999),
            eps=1.0e-8,
            weight_decay=0.0,
            amsgrad=False,
            maximize=False,
            foreach=False,
            capturable=False,
            differentiable=False,
            fused=False,
        )
        parameter.grad = torch.full_like(parameter, 0.1)
        source.step()

        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(lr=0.01),
            optimizer_state_dict=source.state_dict(),
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "state-lr-drift"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_REFERENCE")

    def test_pre_step_optimizer_state_mapping_is_receipted(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(8, dtype=torch.float32))
        source = torch.optim.AdamW(
            [parameter],
            **dict(_adamw_spec().kwargs),
        )
        parameter.grad = torch.full_like(parameter, 0.1)
        source.step()

        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(),
            optimizer_state_dict=source.state_dict(),
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "state-map"},
        )

        identity = receipt["steps"][0]["pre_step_optimizer_state_identity"]
        self.assertEqual(identity["status"], "CLEAR")
        self.assertGreater(identity["tensor_state_count"], 0)
        self.assertRegex(identity["mapping_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
