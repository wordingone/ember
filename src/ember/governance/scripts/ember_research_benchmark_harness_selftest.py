#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for docs/research/journal benchmark admission receipts."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_research_benchmark_harness as harness

# A fully-resolved OWNED_CANDIDATE ember_01_identity manifest (cond3 GAP-4 SUBJECT
# fixture). OWNED_CANDIDATE avoids the OWNED_ADMITTED bundle requirements (receipt
# bundle/tensor manifest/artifact bundle/checkpoint bytes) while still exercising the
# REAL validator's require_resolved gate and the checkpoint/evaluation hash-identity
# invariants unconditionally enforced regardless of disposition.
_SUBJECT_CHECKPOINT_SHA256 = "9" * 63 + "1"
_SUBJECT_MANIFEST_PAYLOAD: dict = {
    "authority": {
        "goal_id": "EMBER-01",
        "workstream_id": "EMBER-01C",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    },
    "schema": "ember-model-experiment-identity-v1",
    "identity": {
        "model_id": "ember-candidate-selftest",
        "experiment_id": "experiment-selftest-001",
        "run_id": "run-selftest-001",
        "checkpoint_id": "checkpoint-selftest-001",
        "disposition": "OWNED_CANDIDATE",
        "selected_as_owned_ember": False,
    },
    "architecture": {"source": "architecture/selftest.py", "sha256": "a" * 64},
    "checkpoint": {
        "format": "synthetic-bytes-v1",
        "byte_sha256": _SUBJECT_CHECKPOINT_SHA256,
        "tensors": [
            {"name": "fixture.weight", "shape": [2, 2], "dtype": "float32", "sha256": "b" * 64}
        ],
        "ancestry": [{"checkpoint_sha256": "c" * 64, "relationship": "clean_genesis_parent"}],
        "recovery_state": "CLEAN",
    },
    "tokenizer": {"id": "owned-tokenizer-selftest", "sha256": "d" * 64},
    "data": {
        "corpus_id": "owned-corpus-selftest",
        "sha256": "e" * 64,
        "ordering_sha256": "f" * 64,
        "curriculum_sha256": "1" * 64,
        "verifier_sha256": "2" * 64,
        "clean_genesis": True,
        "accepted_input": {
            "input_id": "github-issue-selftest",
            "authority_id": "ember-02-issue-selftest",
            "authority_record_sha256": "3" * 64,
            "authority": "CURRENT_EXECUTABLE",
            "shard_manifest_sha256": "4" * 64,
            "caller_sha256": "5" * 64,
            "gate_sha256": "6" * 64,
            "validator_sha256": "7" * 64,
            "forwarding_receipt_sha256": "8" * 64,
        },
    },
    "parameters": {
        "allocated": 1,
        "unique": 1,
        "active": 1,
        "trainable": 1,
        "served": 1,
        "actually_trained": 1,
        "evidence_receipts": {
            "allocated": [], "unique": [], "active": [], "trainable": [],
            "served": [], "actually_trained": [],
        },
    },
    "training": {
        "steps": 100,
        "effective_tokens": 1000000,
        "modality_mixture": {"text": 0.5, "image": 0.25, "audio": 0.25},
        "optimizer_state_sha256": "9" * 64,
        "numerics": {"profile": "bf16-activations-fp32-master", "sha256": "a" * 64},
        "stopping_rule": {
            "criterion_id": "sufficient-pretraining-v1",
            "result": "NOT_REACHED",
            "receipt_sha256": "b" * 64,
        },
    },
    "capabilities": {
        "native_modalities": {
            modality: {"state": "UNVERIFIED", "evidence_receipts": []}
            for modality in ("text", "image", "audio")
        },
        "reasoning": {"state": "UNVERIFIED", "evidence_receipts": []},
        "structured_tool_use": {"state": "UNVERIFIED", "evidence_receipts": []},
    },
    "mechanisms": {
        "experts": [], "router": [], "temporary_adapters": [], "permanent_merges": [],
        "memory_substrates": [], "world_models": [], "dreaming_updates": [], "deletion_objects": [],
    },
    "backend": {
        "executable_sha256": "c" * 64,
        "process_identity": {
            "pid": 1, "start_time_utc": "2026-07-24T00:00:00Z",
            "executable_sha256": "d" * 64, "command_sha256": "e" * 64, "nonce": "selftest",
        },
        "process_receipt_sha256": "f" * 64,
        "protocol": "selftest-v1",
        "device": "cpu",
        "runtime_dependencies": [],
        "resource_lease_id": "selftest-lease",
    },
    "evaluation": {
        "benchmark_id": "terminal-bench-2.1",
        "version": "v1",
        "split": "selftest",
        "harness_sha256": "1" * 64,
        "subject_checkpoint_sha256": _SUBJECT_CHECKPOINT_SHA256,
        "comparator_identity": "selftest-comparator",
        "comparator_sha256": "2" * 64,
        "score": {"value": 1.0, "unit": "selftest-score"},
        "uncertainty": {"value": 0.0, "unit": "selftest-score"},
        "receipt_sha256": "3" * 64,
        "counts_toward_owned_completion": False,
    },
    "provenance": {
        "ownership": "OWNED_CLEAN_GENESIS",
        "exclusion_reasons": [],
        "learned_signal_sources": ["owned_training_data"],
        "neural_capability_credit_sources": ["owned_checkpoint"],
    },
    "unresolved": [],
}


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _subject_manifest(root: Path) -> Path:
    """cond3 GAP-4: a resolved OWNED_CANDIDATE subject manifest every selftest binds to."""
    return _write(root / "subject.json", _SUBJECT_MANIFEST_PAYLOAD)


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

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root), _subject_manifest(root))

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

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root), _subject_manifest(root))

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

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root), _subject_manifest(root))

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

        receipt = harness.build_admission_receipt(manifest, _operator_receipt(root), _subject_manifest(root))

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
