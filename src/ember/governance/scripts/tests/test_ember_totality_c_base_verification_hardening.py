#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
RECEIPTS = REPO_ROOT / "receipts"
TARGET = REPO_ROOT / "scripts" / "ember_totality" / "test_c_base.py"


def _load_target():
    spec = importlib.util.spec_from_file_location("ember_totality_test_c_base", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()


def _receipt(name: str) -> dict:
    return json.loads((RECEIPTS / name).read_text(encoding="utf-8"))


class VerificationHardeningTest(unittest.TestCase):
    def test_void2_random_logits_fixture_is_rejected(self) -> None:
        receipt = _receipt("cbase-gpu-verify-hardened-20260707T053613Z.json")
        self.assertEqual(target._verification_receipt_disposition(receipt), "REJECTED")

    def test_void3_pass_diagnosis_contradiction_is_rejected(self) -> None:
        receipt = _receipt("cbase-gpu-verify-REAL-20260707T063919Z.json")
        self.assertEqual(target._verification_receipt_disposition(receipt), "REJECTED")

    def test_real_nonbaseline_verification_fixture_is_verified(self) -> None:
        receipt = _receipt("cbase-verify-attempt3-20260707T073843.json")
        self.assertEqual(target._verification_receipt_disposition(receipt), "VERIFIED")

    def test_honest_failure_without_verdict_is_non_verdict(self) -> None:
        receipt = {
            "mode": "gpu_verify_checkpoint",
            "status": "LOAD_FAILED",
            "diagnosis": "checkpoint load failure; no verification verdict",
            "model": {"vocab": 32000, "estimated_params_m": 718},
        }
        self.assertEqual(target._verification_receipt_disposition(receipt), "NON_VERDICT")

    def test_gpu_claim_below_parameter_storage_floor_is_rejected(self) -> None:
        receipt = _receipt("cbase-verify-attempt3-20260707T073843.json")
        receipt = copy.deepcopy(receipt)
        receipt["device"] = "cuda"
        receipt["model_params_m"] = 718
        receipt["vram_peak_max_gb"] = 0.033
        self.assertEqual(target._verification_receipt_disposition(receipt), "REJECTED")

    def test_random_logits_text_is_rejected_even_away_from_random_level(self) -> None:
        receipt = _receipt("cbase-verify-attempt3-20260707T073843.json")
        receipt = copy.deepcopy(receipt)
        receipt["loss_function"] = "CrossEntropyLoss on random logits"
        self.assertEqual(target._verification_receipt_disposition(receipt), "REJECTED")


if __name__ == "__main__":
    unittest.main()
