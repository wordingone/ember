#!/usr/bin/env python3
"""Selftest for repeated-cycle Ember growth receipts."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_growth_harness as growth


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _cycle(root: Path, index: int, c_delta: float) -> Path:
    cycle_id = f"cycle-20260619T000000Z-{index:04d}"
    wheel = {
        "ticket": "EMBER-WHEEL-HELDOUT-RUN",
        "cycle_id": cycle_id,
        "equal_budget": True,
        "ordering": "C>B>A",
        "external_benchmark_delta_claimed": True,
        "arms": [
            {"id": "A", "normalized_improvement": 0.1},
            {"id": "B", "normalized_improvement": 0.4},
            {"id": "C", "normalized_improvement": c_delta},
        ],
    }
    _write_json(root / "receipts" / "wheel" / f"wheel-{index}.json", wheel)
    cycle = {
        "ticket": "EMBER-MVP-CYCLE",
        "cycle_id": cycle_id,
        "verdict": "accepted",
        "budget": {"wall_seconds": 3600},
        "benchmark_subset": {
            "id": "kaggle-dataset-external-heldout-v0",
            "frozen_heldout_sha256": "sha256:test-heldout",
        },
        "score": {
            "baseline_score": 0.4,
            "candidate_score": 0.9,
            "mean_normalized_improvement": c_delta,
        },
        "receipts": {"wheel": f"receipts/wheel/wheel-{index}.json"},
    }
    return _write_json(root / "receipts" / "cycles" / f"cycle-{index}.json", cycle)


def _research_cycle(root: Path, index: int, c_score: float = 1.0) -> Path:
    cycle_id = f"cycle-20260619T010000Z-{index:04d}"
    loop = {
        "ticket": "EMBER-RESEARCH-LOOP",
        "benchmark_id": "D3-Gym",
        "benchmark_family": "research_journal",
        "operator_routed": True,
        "equal_budget": True,
        "budget_seconds_per_arm_per_task": 120,
        "arms": {
            "arm_a": {"budget_seconds": 120},
            "arm_b": {"budget_seconds": 120},
            "arm_c": {
                "budget_seconds": 120,
                "manual_solution": False,
                "generator_load_bearing": True,
            },
        },
        "task_count": 8,
        "per_task_rows": [
            {"task_id": f"task_{i}", "arm_a_passed": i == 3, "arm_b_passed": i == 3, "arm_c_passed": True}
            for i in range(1, 9)
        ],
        "score": {
            "baseline_score": 0.125,
            "dream_loop_score": 0.125,
            "candidate_score": c_score,
            "mean_normalized_improvement": c_score - 0.125,
        },
        "ordering": "C>B=A",
        "verdict": "RESEARCH_LOOP_ACCEPTED",
        "errors": [],
    }
    _write_json(root / "receipts" / "wheel" / f"research-wheel-{index}.json", loop)
    _write_json(root / "receipts" / "benchmark" / f"research-benchmark-{index}.json", loop)
    cycle = {
        "ticket": "EMBER-MVP-CYCLE",
        "cycle_id": cycle_id,
        "verdict": "accepted",
        "budget": {"wall_seconds": 120},
        "benchmark_subset": {
            "id": "research-journal-D3-Gym-frozen-v1",
            "benchmark_id": "D3-Gym",
            "benchmark_family": "research_journal",
            "task_count": 8,
        },
        "score": loop["score"],
        "receipts": {
            "wheel": f"receipts/wheel/research-wheel-{index}.json",
            "benchmark": f"receipts/benchmark/research-benchmark-{index}.json",
        },
    }
    return _write_json(root / "receipts" / "cycles" / f"research-cycle-{index}.json", cycle)


def test_three_stable_positive_cycles_are_growth_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-growth-") as td:
        root = Path(td)
        paths = [_cycle(root, 1, 0.8), _cycle(root, 2, 0.8), _cycle(root, 3, 0.81)]
        receipt = growth.build_growth_receipt(paths, max_cycle_to_cycle_delta_movement=0.05)

        assert receipt["verdict"] == "GROWTH_READY"
        assert receipt["growth_allowed"] is True
        assert receipt["repeated_positive_cycles"] == 3
        assert receipt["blocked_until_repeated_positive_cycles"] == 0
        assert receipt["contraction_stability"]["monotone_non_decreasing"] is True
        assert receipt["contraction_stability"]["within_declared_movement_bound"] is True
        assert growth.validate_growth_receipt(receipt) == []


def test_three_research_journal_cycles_are_growth_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-growth-research-") as td:
        root = Path(td)
        paths = [_research_cycle(root, 1), _research_cycle(root, 2), _research_cycle(root, 3)]
        receipt = growth.build_growth_receipt(paths, max_cycle_to_cycle_delta_movement=0.05)

        assert receipt["verdict"] == "GROWTH_READY"
        assert receipt["benchmark_subset_id"] == "research-journal-D3-Gym-frozen-v1"
        assert receipt["cycles"][0]["arm_improvements"] == {"A": 0.125, "B": 0.125, "C": 1.0}
        assert receipt["contraction_stability"]["monotone_non_decreasing"] is True
        assert growth.validate_growth_receipt(receipt) == []


def test_two_cycles_are_not_growth_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-growth-") as td:
        root = Path(td)
        paths = [_cycle(root, 1, 0.8), _cycle(root, 2, 0.8)]
        receipt = growth.build_growth_receipt(paths)

        assert receipt["verdict"] == "GROWTH_BLOCKED"
        assert receipt["growth_allowed"] is False
        assert "repeated_positive_cycles.count" in receipt["errors"]


def test_non_monotone_cycles_are_not_growth_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-growth-") as td:
        root = Path(td)
        paths = [_cycle(root, 1, 0.82), _cycle(root, 2, 0.8), _cycle(root, 3, 0.81)]
        receipt = growth.build_growth_receipt(paths)

        assert receipt["verdict"] == "GROWTH_BLOCKED"
        assert "contraction_stability.monotone_non_decreasing" in receipt["errors"]


def main() -> int:
    tests = [
        test_three_stable_positive_cycles_are_growth_ready,
        test_three_research_journal_cycles_are_growth_ready,
        test_two_cycles_are_not_growth_ready,
        test_non_monotone_cycles_are_not_growth_ready,
    ]
    for test in tests:
        test()
    print("EMBER_GROWTH_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
