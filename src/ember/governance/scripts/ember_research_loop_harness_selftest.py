#!/usr/bin/env python3
"""Selftest for Ember docs/research/journal A/B/C loop harness."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_research_loop_harness as harness


def _write(path: Path, payload: str | dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        path.write_text(payload, encoding="utf-8", newline="\n")
    return path


def _admission(root: Path, adapter: Path, tasks: Path) -> Path:
    return _write(
        root / "admission.json",
        {
            "ticket": "EMBER-RESEARCH-BENCHMARK-ADMISSION",
            "verdict": "RESEARCH_BENCHMARK_ADMITTED",
            "benchmark_id": "D3-Gym",
            "tasks_path": str(tasks),
            "evaluator_path": str(adapter),
            "operator_routed": True,
            "real_external_heldout_ready": True,
            "tasks_sha256": "sha256:tasks",
            "evaluator_sha256": "sha256:evaluator",
        },
    )


def _candidate_receipt(root: Path, candidate: Path) -> Path:
    return _write(
        root / "candidate.json",
        {
            "ticket": "EMBER-CANDIDATE-GENERATOR",
            "verdict": "CANDIDATE_GENERATED",
            "manual_solution": False,
            "candidate_path": str(candidate),
            "candidate_sha256": "sha256:test",
            "deletion_load_bearing_test": {"degrades_without_generator": True},
        },
    )


def test_research_loop_scores_abc_and_accepts_positive_delta() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-loop-") as td:
        root = Path(td)
        adapter = _write(
            root / "adapter.py",
            "import argparse, sys\n"
            "ap=argparse.ArgumentParser(); ap.add_argument('--task-id'); ap.add_argument('--solution'); args=ap.parse_args()\n"
            "sys.exit(0 if 'arm_c' in args.solution else 1)\n",
        )
        tasks = _write(root / "tasks.json", {"tasks": [{"id": "task_1"}]})
        arms = {arm: _write(root / f"{arm}.py", "# solution\n") for arm in ["arm_a", "arm_b", "arm_c"]}

        receipt = harness.build_research_loop_receipt(
            _admission(root, adapter, tasks),
            arms["arm_a"],
            arms["arm_b"],
            arms["arm_c"],
            budget_seconds=30,
            arm_c_candidate_receipt_path=_candidate_receipt(root, arms["arm_c"]),
        )

        assert receipt["verdict"] == "RESEARCH_LOOP_ACCEPTED"
        assert receipt["arms"]["arm_c"]["candidate_generation_receipt_path"].endswith("candidate.json")
        assert receipt["arms"]["arm_c"]["manual_solution"] is False
        assert receipt["arms"]["arm_c"]["generator_load_bearing"] is True
        assert receipt["reproducibility"]["rerun_command"]
        assert receipt["reproducibility"]["tasks_sha256"] == "sha256:tasks"
        assert receipt["reproducibility"]["evaluator_sha256"] == "sha256:evaluator"
        assert receipt["equal_budget"] is True
        assert receipt["ordering"] == "C>B=A"
        assert receipt["score"]["candidate_score"] == 1.0
        assert receipt["score"]["baseline_score"] == 0.0
        assert receipt["per_task_rows"][0]["arm_c_passed"] is True
        assert harness.validate_research_loop_receipt(receipt) == []


def test_research_loop_blocks_without_positive_delta() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-loop-") as td:
        root = Path(td)
        adapter = _write(
            root / "adapter.py",
            "import argparse, sys\n"
            "ap=argparse.ArgumentParser(); ap.add_argument('--task-id'); ap.add_argument('--solution'); ap.parse_args()\n"
            "sys.exit(1)\n",
        )
        tasks = _write(root / "tasks.json", {"tasks": [{"id": "task_1"}]})
        arms = {arm: _write(root / f"{arm}.py", "# solution\n") for arm in ["arm_a", "arm_b", "arm_c"]}

        receipt = harness.build_research_loop_receipt(
            _admission(root, adapter, tasks),
            arms["arm_a"],
            arms["arm_b"],
            arms["arm_c"],
            budget_seconds=30,
        )

        assert receipt["verdict"] == "RESEARCH_LOOP_BLOCKED"
        assert "positive_delta.missing" in receipt["errors"]


def test_research_loop_treats_d3_result_false_as_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-loop-") as td:
        root = Path(td)
        adapter = _write(
            root / "adapter.py",
            "import argparse\n"
            "ap=argparse.ArgumentParser(); ap.add_argument('--task-id'); ap.add_argument('--solution'); ap.parse_args()\n"
            "print('Result: False')\n"
            "print('Reason: Missing predicted file')\n",
        )
        tasks = _write(root / "tasks.json", {"tasks": [{"id": "task_1"}]})
        arms = {arm: _write(root / f"{arm}.py", "# solution\n") for arm in ["arm_a", "arm_b", "arm_c"]}

        receipt = harness.build_research_loop_receipt(
            _admission(root, adapter, tasks),
            arms["arm_a"],
            arms["arm_b"],
            arms["arm_c"],
            budget_seconds=30,
        )

        row = receipt["per_task_rows"][0]
        assert row["arm_a_passed"] is False
        assert row["arm_b_passed"] is False
        assert row["arm_c_passed"] is False
        assert receipt["score"]["candidate_score"] == 0.0


def test_research_loop_treats_failed_and_pass_false_as_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-loop-") as td:
        root = Path(td)
        adapter = _write(
            root / "adapter.py",
            "import argparse\n"
            "ap=argparse.ArgumentParser(); ap.add_argument('--task-id'); ap.add_argument('--solution'); args=ap.parse_args()\n"
            "print('FAILED: Missing predicted output file' if args.task_id == 'task_1' else 'Pass: False')\n",
        )
        tasks = _write(root / "tasks.json", {"tasks": [{"id": "task_1"}, {"id": "task_2"}]})
        arms = {arm: _write(root / f"{arm}.py", "# solution\n") for arm in ["arm_a", "arm_b", "arm_c"]}

        receipt = harness.build_research_loop_receipt(
            _admission(root, adapter, tasks),
            arms["arm_a"],
            arms["arm_b"],
            arms["arm_c"],
            budget_seconds=30,
        )

        assert all(row["arm_c_passed"] is False for row in receipt["per_task_rows"])
        assert receipt["score"]["candidate_score"] == 0.0


def main() -> int:
    tests = [
        test_research_loop_scores_abc_and_accepts_positive_delta,
        test_research_loop_blocks_without_positive_delta,
        test_research_loop_treats_d3_result_false_as_failure,
        test_research_loop_treats_failed_and_pass_false_as_failure,
    ]
    for test in tests:
        test()
    print("EMBER_RESEARCH_LOOP_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
