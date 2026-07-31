# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import torch

from scripts.preflight.update_survival import (
    OptimizerSpec,
    TensorProbe,
    run_update_survival_preflight,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "preflight" / "update_survival.py"


def _adamw_spec() -> OptimizerSpec:
    return OptimizerSpec(
        family="adamw",
        kwargs={
            "lr": 0.01,
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


class UpdateSurvivalStateAndCliTests(unittest.TestCase):
    def test_existing_optimizer_state_is_cloned_and_receipted(self) -> None:
        source = torch.nn.Parameter(torch.ones(8, dtype=torch.float32))
        optimizer = torch.optim.AdamW([source], **dict(_adamw_spec().kwargs))
        source.grad = torch.full_like(source, 0.1)
        optimizer.step()

        receipt = run_update_survival_preflight(
            probes=[
                TensorProbe(
                    name="weight",
                    tensor_class="weight",
                    initial=source.detach(),
                    gradient=torch.full_like(source, 0.1),
                    required_survival=True,
                )
            ],
            optimizer_spec=_adamw_spec(),
            optimizer_state_dict=optimizer.state_dict(),
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "stateful-adamw"},
        )

        self.assertNotEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["reference_identity"]["status"], "CLEAR")
        self.assertRegex(
            receipt["reference_identity"]["optimizer_state_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertTrue(receipt["steps"][0]["optimizer_state_dtypes"])

    def test_cpu_selftest_cli_writes_content_addressed_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-survival-cli-") as raw:
            receipt_path = Path(raw) / "selftest.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(CLI),
                    "--selftest",
                    "--receipt",
                    str(receipt_path),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("UPDATE_SURVIVAL_SELFTEST_PASS", completed.stdout)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["schema"],
                "ember-update-survival-selftest/v1",
            )
            self.assertEqual(receipt["verdict"], "SELFTEST_PASS")
            self.assertEqual(
                {
                    case["case_id"]: case["observed_verdict"]
                    for case in receipt["cases"]
                },
                {
                    "weight-decay-causal-confound": "PREFLIGHT_FAIL",
                    "bitnet-15-of-24-bf16": "PREFLIGHT_FAIL",
                    "bitnet-fp32-master": "PREFLIGHT_PASS",
                    "adafactor-implicit-eps": "PREFLIGHT_INVALID",
                },
            )
            self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
