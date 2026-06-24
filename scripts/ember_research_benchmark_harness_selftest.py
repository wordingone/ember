#!/usr/bin/env python3
"""Selftest for docs/research/journal benchmark admission receipts."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_research_benchmark_harness as harness


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _operator_receipt(root: Path) -> Path:
    return _write(
        root / "operator.json",
        {
            "ticket": "EMBER-SELF-GROWTH-OPERATOR-DECISION",
            "verdict": "SELF_GROWTH_OPERATOR_READY",
            "manual_selection": False,
            "selected_next_action": {
                "kind": "stronger_external_benchmark",
                "benchmark_family": "research_journal",
                "preferred_candidate": "ScienceAgentBench",
            },
        },
    )


def test_admits_manifest_with_external_tasks_and_evaluator() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-") as td:
        root = Path(td)
        evaluator = root / "eval.py"
        evaluator.write_text("print('ok')\n", encoding="utf-8")
        tasks = _write(
            root / "tasks.json",
            {
                "tasks": [
                    {
                        "id": "sab-fixture-001",
                        "paper_source": "peer-reviewed-publication",
                        "heldout_input_sha256": "sha256:input",
                        "expected_output_sha256": "sha256:output",
                    }
                ]
            },
        )
        manifest = _write(
            root / "manifest.json",
            {
                "benchmark_id": "ScienceAgentBench",
                "family": "research_journal",
                "source_url": "https://arxiv.org/abs/2410.05080",
                "license_or_access_basis": "public research benchmark",
                "tasks_path": str(tasks),
                "evaluator_path": str(evaluator),
                "scoring_metric": "execution_accuracy",
                "heldout_frozen": True,
            },
        )

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root))

        assert receipt["verdict"] == "RESEARCH_BENCHMARK_ADMITTED"
        assert receipt["benchmark_id"] == "ScienceAgentBench"
        assert receipt["operator_routed"] is True
        assert receipt["real_external_heldout_ready"] is True
        assert receipt["errors"] == []
        assert harness.validate_admission_receipt(receipt) == []


def test_blocks_when_evaluator_is_missing() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-") as td:
        root = Path(td)
        tasks = _write(root / "tasks.json", {"tasks": [{"id": "sab-fixture-001"}]})
        manifest = _write(
            root / "manifest.json",
            {
                "benchmark_id": "ScienceAgentBench",
                "family": "research_journal",
                "source_url": "https://arxiv.org/abs/2410.05080",
                "license_or_access_basis": "public research benchmark",
                "tasks_path": str(tasks),
                "evaluator_path": str(root / "missing_eval.py"),
                "scoring_metric": "execution_accuracy",
                "heldout_frozen": True,
            },
        )

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root))

        assert receipt["verdict"] == "RESEARCH_BENCHMARK_BLOCKED"
        assert "evaluator_path.missing" in receipt["errors"]
        assert receipt["missing_artifacts"] == ["evaluator_path"]


def test_admits_d3_gym_as_research_journal_replacement() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-") as td:
        root = Path(td)
        evaluator = root / "d3_eval_adapter.py"
        evaluator.write_text("print('docker adapter')\n", encoding="utf-8")
        tasks = _write(
            root / "d3_tasks.json",
            {
                "tasks": [
                    {
                        "id": "task_1",
                        "source_dataset": "osunlp/D3-Gym",
                        "paper_source": "arxiv:2604.27977",
                        "evaluator_kind": "docker_run_and_eval",
                    }
                ]
            },
        )
        manifest = _write(
            root / "manifest.json",
            {
                "benchmark_id": "D3-Gym",
                "family": "research_journal",
                "source_url": "https://huggingface.co/datasets/osunlp/D3-Gym",
                "license_or_access_basis": "public HF dataset plus source repo license metadata",
                "tasks_path": str(tasks),
                "evaluator_path": str(evaluator),
                "scoring_metric": "docker_eval_pass_rate",
                "heldout_frozen": True,
                "requires_docker": True,
                "docker_daemon_ready": True,
            },
        )

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root))

        assert receipt["verdict"] == "RESEARCH_BENCHMARK_ADMITTED"
        assert receipt["benchmark_id"] == "D3-Gym"
        assert receipt["operator_routed"] is True
        assert harness.validate_admission_receipt(receipt) == []


def test_blocks_d3_gym_when_docker_daemon_is_not_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-research-bench-") as td:
        root = Path(td)
        evaluator = root / "d3_eval_adapter.py"
        evaluator.write_text("print('docker adapter')\n", encoding="utf-8")
        tasks = _write(root / "d3_tasks.json", {"tasks": [{"id": "task_1"}]})
        manifest = _write(
            root / "manifest.json",
            {
                "benchmark_id": "D3-Gym",
                "family": "research_journal",
                "source_url": "https://huggingface.co/datasets/osunlp/D3-Gym",
                "license_or_access_basis": "public HF dataset plus source repo license metadata",
                "tasks_path": str(tasks),
                "evaluator_path": str(evaluator),
                "scoring_metric": "docker_eval_pass_rate",
                "heldout_frozen": True,
                "requires_docker": True,
                "docker_daemon_ready": False,
            },
        )

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root))

        assert receipt["verdict"] == "RESEARCH_BENCHMARK_BLOCKED"
        assert "docker_daemon.not_ready" in receipt["errors"]
        assert "docker_daemon" in receipt["missing_artifacts"]


def main() -> int:
    tests = [
        test_admits_manifest_with_external_tasks_and_evaluator,
        test_blocks_when_evaluator_is_missing,
        test_admits_d3_gym_as_research_journal_replacement,
        test_blocks_d3_gym_when_docker_daemon_is_not_ready,
    ]
    for test in tests:
        test()
    print("EMBER_RESEARCH_BENCHMARK_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
