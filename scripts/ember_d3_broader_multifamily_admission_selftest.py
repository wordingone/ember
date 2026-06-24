#!/usr/bin/env python3
"""Selftest for broader D3 multi-family admission receipts."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_d3_broader_multifamily_admission as d3


def _write_fixture(root: Path) -> Path:
    old = root / "D3-Gym-admission-v1"
    old.mkdir(parents=True)
    (old / "d3-gym-tasks-frozen-v1.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "task_id": "task_1",
                        "discipline": "Chemistry",
                        "original_repo": "aaaa/stale-old-family",
                        "docker_image": "hananemoussa/d3-gym:task_1",
                        "evaluator_kind": "docker_run_and_eval",
                        "source_row_idx": 0,
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    bench = root / "D3-Gym-heldout-v3"
    bench.mkdir(parents=True)
    rows = [
        {
            "task_id": "task_17",
            "discipline": "Chemistry",
            "original_repo": "fenggo/I-ReaxFF",
            "docker_image": "hananemoussa/d3-gym:task_17",
            "evaluator_kind": "docker_run_and_eval",
            "source_row_idx": 16,
        },
        {
            "task_id": "task_18",
            "discipline": "Chemistry",
            "original_repo": "Jonas-Verhellen/Bayesian-Illumination",
            "docker_image": "hananemoussa/d3-gym:task_18",
            "evaluator_kind": "docker_run_and_eval",
            "source_row_idx": 17,
        },
        {
            "task_id": "task_19",
            "discipline": "Chemistry",
            "original_repo": "TheJacksonLab/OpenMacromolecularGenome",
            "docker_image": "hananemoussa/d3-gym:task_19",
            "evaluator_kind": "docker_run_and_eval",
            "source_row_idx": 18,
        },
        {
            "task_id": "task_20",
            "discipline": "Chemistry",
            "original_repo": "chenruduan/OAReactDiff",
            "docker_image": "hananemoussa/d3-gym:task_20",
            "evaluator_kind": "docker_run_and_eval",
            "source_row_idx": 19,
        },
        {
            "task_id": "task_9",
            "discipline": "Chemistry",
            "original_repo": "fenggo/I-ReaxFF",
            "docker_image": "hananemoussa/d3-gym:task_9",
            "evaluator_kind": "docker_run_and_eval",
            "source_row_idx": 8,
        },
    ]
    (bench / "d3-gym-tasks-frozen-offset16-length8-v1.json").write_text(
        json.dumps({"rows": rows}, indent=2),
        encoding="utf-8",
    )
    (bench / "d3-gym-admission-offset16-length8-20260619T-v1.json").write_text(
        json.dumps({"verdict": "RESEARCH_BENCHMARK_ADMITTED", "sources": {"hf": "https://huggingface.co/datasets/MLE-bench/D3-Gym"}}),
        encoding="utf-8",
    )
    return bench


def test_admits_fresh_multifamily_slice_without_reusing_solved_tasks() -> None:
    with tempfile.TemporaryDirectory(prefix="d3-broader-admission-") as td:
        state_root = Path(td) / "research-benchmarks"
        _write_fixture(state_root)
        out = Path(td) / "receipt.json"
        receipt = d3.build_admission_receipt(repo=Path.cwd(), state_root=state_root, out=out)
        rows = receipt["frozen_heldout_slice"]["rows"]
        ids = {row["task_id"] for row in rows}
        repos = {row["original_repo"] for row in rows}
        assert receipt["verdict"] == "D3_BROADER_MULTIFAMILY_ADMITTED"
        assert "task_9" not in ids
        assert ids == {"task_17", "task_18", "task_19", "task_20"}
        assert len(repos) == 4
        assert receipt["benchmark_facts"]["domain_diversity"]["discipline_count"] == 1
        assert receipt["benchmark_facts"]["domain_diversity"]["honest_limitation"] == "single_discipline_chemistry"
        assert receipt["native_operator_routing"]["selected"] == "d3-broader-multifamily"
        assert receipt["deleted_selector_routing"]["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"
        assert receipt["deletion_sensitive"] is True
        assert "--task-id task_17" in receipt["next_executable_command"]
        assert "--task-id task_18" in receipt["next_executable_command"]
        assert "--execute" in receipt["next_executable_command"]
        assert out.exists()


def main() -> int:
    test_admits_fresh_multifamily_slice_without_reusing_solved_tasks()
    print("EMBER_D3_BROADER_MULTIFAMILY_ADMISSION_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
