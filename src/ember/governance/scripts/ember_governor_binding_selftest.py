#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the Ember MVP governor/artifact binding receipt."""
from __future__ import annotations

import tempfile
from pathlib import Path

import ember_governor_binding as binding


def test_fixture_governor_binding_records_cycle_and_artifact_hash() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-governor-binding-") as td:
        root = Path(td)
        receipt = binding.run_fixture_binding(root, cycle_id="cycle-test-0001")

        assert receipt["ticket"] == "EMBER-GOVERNOR-BINDING-FIXTURE"
        assert receipt["cycle_id"] == "cycle-test-0001"
        assert receipt["mode"] == "cpu-fixture-no-gpu-preflight"
        assert receipt["gpu_preflight_called"] is False
        assert receipt["real_gpu_training"] is False
        assert receipt["governor"]["vram_fraction"] <= 0.85
        assert receipt["governor"]["margin_gb"] >= 1.5
        assert receipt["governor"]["throttle_s"] >= 0.0
        assert receipt["artifact"]["kind"] == "checkpoint-fixture"
        assert receipt["artifact"]["checkpoint_hash"].startswith("sha256:")
        assert Path(receipt["artifact"]["path"]).exists()
        assert Path(receipt["receipt_path"]).exists()

        loaded = binding.load_receipt(Path(receipt["receipt_path"]))
        binding.validate_governor_receipt(loaded)


def test_real_preflight_claim_requires_gpu_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-governor-binding-") as td:
        root = Path(td)
        receipt = binding.run_fixture_binding(root, cycle_id="cycle-test-0002")
        broken = dict(receipt)
        broken["gpu_preflight_called"] = True

        try:
            binding.validate_governor_receipt(broken)
        except binding.GovernorBindingValidationError as exc:
            assert "fixture receipt cannot claim GPU preflight" in str(exc)
        else:
            raise AssertionError("fixture receipt must not claim GPU preflight")


def test_real_governor_receipt_shape_is_accepted() -> None:
    receipt = {
        "ticket": "EMBER-GOVERNOR-REAL-RUN",
        "ts": "20260617T000000Z",
        "cycle_id": "cycle-test-real",
        "mode": "governed-gpu-train-eval",
        "gpu_preflight_called": True,
        "real_gpu_training": True,
        "governor": {
            "vram_fraction": 0.8,
            "margin_gb": 2.0,
            "throttle_s": 0.05,
            "free_gb": 10.0,
            "total_gb": 24.0,
        },
        "train_eval": {
            "device": "cuda:0",
            "steps": 2,
            "loss_before": 1.0,
            "loss_after": 0.5,
        },
        "artifact": {
            "kind": "checkpoint",
            "path": __file__,
            "checkpoint_hash": "sha256:" + "1" * 64,
            "adapter_hash": None,
        },
        "failure_mode": None,
    }

    binding.validate_governor_receipt(receipt)


def test_real_governed_gpu_smoke_writes_hashable_artifact() -> None:
    try:
        import torch
    except Exception:
        return
    if not torch.cuda.is_available():
        return

    with tempfile.TemporaryDirectory(prefix="ember-governor-real-") as td:
        receipt = binding.run_real_governed_smoke(Path(td), cycle_id="cycle-test-real")

        assert receipt["ticket"] == "EMBER-GOVERNOR-REAL-RUN"
        assert receipt["mode"] == "governed-gpu-train-eval"
        assert receipt["gpu_preflight_called"] is True
        assert receipt["real_gpu_training"] is True
        assert receipt["train_eval"]["steps"] >= 1
        assert receipt["train_eval"]["device"].startswith("cuda")
        assert receipt["artifact"]["checkpoint_hash"].startswith("sha256:")
        assert Path(receipt["artifact"]["path"]).exists()
        binding.validate_governor_receipt(receipt)


def main() -> int:
    test_fixture_governor_binding_records_cycle_and_artifact_hash()
    test_real_preflight_claim_requires_gpu_mode()
    test_real_governor_receipt_shape_is_accepted()
    test_real_governed_gpu_smoke_writes_hashable_artifact()
    print("EMBER_GOVERNOR_BINDING_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
