#!/usr/bin/env python3
"""Selftest for bounded Ember scale-up receipts."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_scale_harness as scale


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _bundle(root: Path, *, budget_seconds: int = 10800) -> tuple[Path, Path, Path, Path]:
    subset = {
        "id": "kaggle-dataset-external-heldout-v0",
        "frozen_heldout_sha256": "sha256:test-heldout",
    }
    wheel = {
        "ticket": "EMBER-WHEEL-HELDOUT-RUN",
        "equal_budget": True,
        "ordering": "C>B>A",
        "external_benchmark_delta_claimed": True,
        "arms": [
            {"id": "A", "budget_seconds": budget_seconds, "normalized_improvement": 0.1, "arm_contract_ok": True},
            {"id": "B", "budget_seconds": budget_seconds, "normalized_improvement": 0.4, "arm_contract_ok": True},
            {"id": "C", "budget_seconds": budget_seconds, "normalized_improvement": 0.8, "arm_contract_ok": True},
        ],
    }
    wheel_path = _write(root / "scale" / "receipts" / "wheel" / "wheel.json", wheel)
    cycle = {
        "ticket": "EMBER-MVP-CYCLE",
        "cycle_id": "cycle-scale-0001",
        "verdict": "accepted",
        "budget": {"wall_seconds": budget_seconds, "train_seconds": budget_seconds, "eval_seconds": budget_seconds},
        "benchmark_subset": subset,
        "score": {"baseline_score": 0.4, "candidate_score": 0.9, "mean_normalized_improvement": 0.8},
        "receipts": {"wheel": "receipts/wheel/wheel.json"},
    }
    cycle_path = _write(root / "scale" / "receipts" / "cycles" / "cycle.json", cycle)
    growth = {
        "ticket": "EMBER-GROWTH-CONTRACTION-STABILITY",
        "verdict": "GROWTH_READY",
        "growth_allowed": True,
        "repeated_positive_cycles": 3,
        "benchmark_subset_id": subset["id"],
        "frozen_heldout_sha256": subset["frozen_heldout_sha256"],
        "contraction_stability": {
            "monotone_non_decreasing": True,
            "within_declared_movement_bound": True,
        },
        "next_cycle_ceiling": {"fits_24h": True},
        "cycles": [{"cycle_receipt_path": str(cycle_path)}] * 3,
    }
    growth_path = _write(root / "growth.json", growth)
    operator_path = _write(
        root / "operator.json",
        {
            "ticket": "EMBER-SELF-GROWTH-OPERATOR-DECISION",
            "verdict": "SELF_GROWTH_OPERATOR_READY",
            "manual_selection": False,
            "selected_next_action": {
                "kind": "bounded_scale_up",
                "target_budget_seconds": budget_seconds,
                "selected_by": "receipt_trace_next_cycle_router_v1",
            },
            "deletion_load_bearing_test": {
                "degrades_without_operator": True,
                "deleted_action": {"kind": "blocked_manual_selection_forbidden"},
            },
        },
    )
    return cycle_path, wheel_path, growth_path, operator_path


def test_scale_up_receipt_accepts_3h_cycle_after_growth_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-scale-") as td:
        cycle_path, _, growth_path, operator_path = _bundle(Path(td))
        receipt = scale.build_scale_receipt(
            cycle_path,
            growth_path,
            operator_path,
            target_budget_seconds=10800,
        )

        assert receipt["verdict"] == "SCALE_UP_READY"
        assert receipt["scale_allowed"] is True
        assert receipt["scale_factor"] == 3.0
        assert receipt["next_cycle_ceiling"]["fits_24h"] is True
        assert receipt["benchmark_continuity"]["same_subset_as_growth"] is True
        assert scale.validate_scale_receipt(receipt) == []


def test_scale_up_receipt_rejects_cycle_over_24h() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-scale-") as td:
        cycle_path, _, growth_path, operator_path = _bundle(Path(td), budget_seconds=90000)
        receipt = scale.build_scale_receipt(
            cycle_path,
            growth_path,
            operator_path,
            target_budget_seconds=90000,
        )

        assert receipt["verdict"] == "SCALE_UP_BLOCKED"
        assert "scale.next_cycle_ceiling" in receipt["errors"]


def test_scale_up_receipt_rejects_manual_scale_without_operator() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-scale-") as td:
        cycle_path, _, growth_path, _ = _bundle(Path(td))
        receipt = scale.build_scale_receipt(cycle_path, growth_path, None, target_budget_seconds=10800)

        assert receipt["verdict"] == "SCALE_UP_BLOCKED"
        assert "scale.operator_decision" in receipt["errors"]


def main() -> int:
    tests = [
        test_scale_up_receipt_accepts_3h_cycle_after_growth_ready,
        test_scale_up_receipt_rejects_cycle_over_24h,
        test_scale_up_receipt_rejects_manual_scale_without_operator,
    ]
    for test in tests:
        test()
    print("EMBER_SCALE_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
