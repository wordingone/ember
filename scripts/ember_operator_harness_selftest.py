#!/usr/bin/env python3
"""Selftest for Ember's load-bearing self-growth operator."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_operator_harness as operator


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _readiness(root: Path) -> Path:
    return _write(
        root / "readiness.json",
        {
            "ticket": "EMBER-MVP-READINESS",
            "verdict": "MVP_READY",
            "growth_verdict": "GROWTH_READY",
            "growth_receipt": {
                "ready": True,
                "receipt": {
                    "benchmark_subset_id": "kaggle-dataset-external-heldout-v0",
                    "frozen_heldout_sha256": "sha256:test-heldout",
                    "repeated_positive_cycles": 3,
                },
            },
        },
    )


def _scale_receipt(root: Path) -> Path:
    return _write(
        root / "scale.json",
        {
            "ticket": "EMBER-SCALE-UP-HARNESS",
            "verdict": "SCALE_UP_READY",
            "scale_allowed": True,
            "scale_factor": 3.0,
            "next_cycle_ceiling": {"fits_24h": True},
            "benchmark_continuity": {"same_subset_as_growth": True},
            "operator_decision": {"ready": True},
        },
    )


def test_operator_selects_research_benchmark_when_growth_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-operator-") as td:
        readiness_path = _readiness(Path(td))
        receipt = operator.build_operator_decision(readiness_path)

        action = receipt["selected_next_action"]
        assert receipt["verdict"] == "SELF_GROWTH_OPERATOR_READY"
        assert action["kind"] == "stronger_external_benchmark"
        assert action["benchmark_family"] == "research_journal"
        assert action["preferred_candidate"] == "ScienceAgentBench"
        assert receipt["deletion_load_bearing_test"]["degrades_without_operator"] is True
        assert operator.validate_operator_decision(receipt) == []


def test_operator_selects_research_benchmark_after_scale_up_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-operator-") as td:
        root = Path(td)
        readiness_path = _readiness(root)
        scale_path = _scale_receipt(root)
        receipt = operator.build_operator_decision(readiness_path, scale_receipt_path=scale_path)

        action = receipt["selected_next_action"]
        assert receipt["verdict"] == "SELF_GROWTH_OPERATOR_READY"
        assert action["kind"] == "stronger_external_benchmark"
        assert action["benchmark_family"] == "research_journal"
        assert action["preferred_candidate"] == "ScienceAgentBench"
        assert "research-benchmark-admission" in action["required_next_receipts"]
        assert receipt["scale_receipt_path"] == str(scale_path)
        assert operator.validate_operator_decision(receipt) == []


def test_deleted_operator_blocks_next_action() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-operator-") as td:
        readiness_path = _readiness(Path(td))
        receipt = operator.build_operator_decision(readiness_path, operator_deleted=True)

        assert receipt["verdict"] == "SELF_GROWTH_OPERATOR_BLOCKED"
        assert receipt["selected_next_action"]["kind"] == "blocked_manual_selection_forbidden"
        assert "operator.deleted" in receipt["errors"]


def main() -> int:
    tests = [
        test_operator_selects_research_benchmark_when_growth_ready,
        test_operator_selects_research_benchmark_after_scale_up_ready,
        test_deleted_operator_blocks_next_action,
    ]
    for test in tests:
        test()
    print("EMBER_OPERATOR_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
