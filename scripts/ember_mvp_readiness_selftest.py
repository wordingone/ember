#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the fail-closed Ember MVP readiness gate."""
from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path

import ember_growth_harness as growth
import ember_mvp_readiness as readiness


def _write(path: Path, obj: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sandbox_probe_rows() -> list[dict]:
    verdicts = {
        "legit-solve": "pass",
        "eq-dispatch": "denied",
        "removed-builtin-open": "denied",
        "object-reachability": "denied",
        "timeout": "killed",
        "memory-bomb": "denied",
        "filesystem-escape": "denied",
        "subprocess-cleanup": "killed",
        "network-attempt": "denied",
        "deterministic-replay": "pass",
    }
    return [
        {
            "probe": probe,
            "verdict": verdict,
            "ok": True,
            "receipt": {
                "probe": probe,
                "verdict": verdict,
                "job_object": {
                    "requested": True,
                    "assigned": True,
                    "memory_limit_bytes": 201326592,
                },
                "replay_result": {"outputs_match": True} if probe == "deterministic-replay" else None,
            },
        }
        for probe, verdict in verdicts.items()
    ]


def _real_proof_fixture(root: Path) -> Path:
    cycle_id = "cycle-real-proof-0001"
    obs_id = "obs-real-proof-0001"
    latent_id = "latent-real-proof-0001"
    receipt_dir = root / "receipts"
    artifact_path = root / "artifacts" / "adapter-real-proof.bin"
    artifact_bytes = b"ember durable assimilation artifact\n"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(artifact_bytes)
    artifact_hash = _sha256_bytes(artifact_bytes)
    sandbox = _write(
        receipt_dir / "sandbox" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-MVP-SANDBOX-PRODUCTION",
            "ts": "20260617T000000Z",
            "cycle_id": cycle_id,
            "mode": "windows-native-production-candidate-runner",
            "verdict": "pass",
            "windows_native_runner": True,
            "job_object_limit_requested": True,
            "fresh_temp_root": True,
            "brokered_filesystem": True,
            "network_default_denied": True,
            "summary": {"pass": 10, "total": 10},
            "candidate": {
                "verdict": "pass",
                "job_object": {
                    "requested": True,
                    "assigned": True,
                    "memory_limit_bytes": 201326592,
                },
            },
            "required_probe_battery": {
                "receipt_path": str(root / "receipts" / "windows-sandbox" / "sandbox-battery.json"),
                "summary": {"pass": 10, "total": 10},
                "rows": _sandbox_probe_rows(),
            },
        },
    )
    governor = _write(
        receipt_dir / "governor" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-GOVERNOR-REAL-RUN",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "cycle_id": cycle_id,
            "mode": "governed-gpu-train-eval",
            "gpu_preflight_called": True,
            "real_gpu_training": True,
            "governor": {
                "vram_fraction": 0.8,
                "margin_gb": 2.0,
                "throttle_s": 0.05,
            },
            "artifact": {
                "kind": "adapter",
                "path": str(artifact_path),
                "checkpoint_hash": None,
                "adapter_hash": artifact_hash,
            },
        },
    )
    benchmark = _write(
        receipt_dir / "benchmark" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-MLE-MICRO-REAL-RUN",
            "ts": "20260617T000000Z",
            "cycle_id": cycle_id,
            "fixture_only": False,
            "real_mle_tasks_executed": True,
            "frozen_before_execution": True,
            "benchmark_subset": {
                "id": "mle-low-micro-v0",
                "task_ids": readiness.MLE_LOW_MICRO_TASK_IDS,
                "official_leaderboard_comparable": False,
            },
            "task_results": [
                {
                    "task_id": task_id,
                    "baseline_score": 0.5,
                    "candidate_score": 0.7,
                    "normalized_improvement": 0.4,
                }
                for task_id in readiness.MLE_LOW_MICRO_TASK_IDS
            ],
            "score": {
                "baseline_score": 0.5,
                "candidate_score": 0.7,
                "mean_normalized_improvement": 0.4,
            },
        },
    )
    wheel = _write(
        receipt_dir / "wheel" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-WHEEL-REAL-RUN",
            "ts": "20260617T000000Z",
            "cycle_id": cycle_id,
            "fixture_only": False,
            "real_mle_tasks_executed": True,
            "equal_budget": True,
            "ordering": "C>B>A",
            "benchmark_subset": {
                "id": "mle-low-micro-v0",
                "task_ids": readiness.MLE_LOW_MICRO_TASK_IDS,
                "official_leaderboard_comparable": False,
            },
            "arms": [
                {
                    "id": "A",
                    "budget_seconds": 3600,
                    "normalized_improvement": 0.0,
                    "arm_contract_ok": True,
                    "arm_contract_errors": [],
                },
                {
                    "id": "B",
                    "budget_seconds": 3600,
                    "normalized_improvement": 0.2,
                    "arm_contract_ok": True,
                    "arm_contract_errors": [],
                },
                {
                    "id": "C",
                    "budget_seconds": 3600,
                    "normalized_improvement": 0.4,
                    "arm_contract_ok": True,
                    "arm_contract_errors": [],
                },
            ],
            "growth_gate": {
                "growth_allowed": False,
                "blocked_until_repeated_positive_cycles": 3,
                "next_cycle_ceiling_hours": 24,
            },
        },
    )
    rollout = _write(
        receipt_dir / "recursion" / "predictive-rollout" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-PREDICTIVE-DREAM-ROLLOUT",
            "ts": "20260617T000000Z",
            "cycle_id": cycle_id,
            "arm_id": "B",
            "source_trace_sha256": "sha256:" + "a" * 64,
            "predicts_next_cycle_task_progress": True,
            "candidate_next_states": [{"state_id": "repeat-b", "predicted_normalized_improvement_floor": 0.2}],
            "deletion_load_bearing_test": {"must_be_checked_on": "next closed cycle"},
            "verdict": "PREDICTIVE_ROLLOUT_RECEIPTED",
        },
    )
    operator = _write(
        receipt_dir / "recursion" / "meta-cognitive-operator" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-PROSPECTIVE-METACOGNITIVE-OPERATOR",
            "ts": "20260617T000000Z",
            "cycle_id": cycle_id,
            "operator_id": "receipt_trace_next_cycle_router_v0",
            "trained_from_receipt_trace_sha256": "sha256:" + "b" * 64,
            "retrospective_discriminator_only": False,
            "prospective_output": {"next_action": "repeat_closed_cycle"},
            "deletion_load_bearing_test": {"must_degrade": "routing/growth decision accountability"},
            "verdict": "PROSPECTIVE_OPERATOR_RECEIPTED",
        },
    )
    compaction = _write(
        receipt_dir / "recursion" / "compaction" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-DISPATCH-CONTEXT-COMPACTION",
            "ts": "20260617T000000Z",
            "cycle_id": cycle_id,
            "goal_context_used": True,
            "goal_doc_hashes": [
                {"path": "docs/archive/pre-restart/20260617-maximally-viable-product.md", "sha256": "sha256:" + "c" * 64},
                {"path": "docs/domains/governance/archive/pre-restart/ember-mvp-v0.md", "sha256": "sha256:" + "d" * 64},
            ],
            "dispatch_critical_state": {"next_action": "repeat_closed_cycle"},
            "preserves_dispatch_state": True,
            "verdict": "COMPACTION_RECEIPTED",
        },
    )
    observation = _write(
        receipt_dir / "observations" / f"{obs_id}.json",
        {
            "ticket": "EMBER-MVP-OBSERVATION",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "id": obs_id,
            "cycle_id": cycle_id,
            "created_at": "2026-06-17T00:00:00Z",
            "workspace_root": str(root),
            "aperture": {
                "user_goal_hash": "sha256:" + "6" * 64,
                "context_manifest_hash": "sha256:" + "7" * 64,
                "git_head": "fixture-head",
                "dirty_state_hash": "sha256:" + "8" * 64,
                "available_tools": ["sandbox", "governor", "replay_rig"],
            },
            "receipts": [f"receipts/observations/{obs_id}.json"],
        },
    )
    latent = _write(
        receipt_dir / "latent" / f"{latent_id}.json",
        {
            "ticket": "EMBER-MVP-LATENT-BRANCH",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "id": latent_id,
            "cycle_id": cycle_id,
            "parent_observation_id": obs_id,
            "parent_commit_id": "statecommit-parent",
            "inputs": {
                "hypothesis": "fixture candidate should improve normalized benchmark delta",
                "budget_seconds": 3600,
                "benchmark_subset_id": "mle-low-micro-v0",
            },
            "produced_deltas": [
                {
                    "path": "local-state/deltas/latent-real-proof-0001.patch",
                    "sha256": "sha256:" + "9" * 64,
                }
            ],
            "status": "candidate",
        },
    )
    state_commit = _write(
        root / "state-substrate" / "receipts" / "commits" / "statecommit-real-proof-0001.json",
        {
            "ticket": "EMBER-STATE-COMMIT",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "id": "statecommit-real-proof-0001",
            "cycle_id": cycle_id,
            "parent_id": "statecommit-parent",
            "latent_branch_id": latent_id,
            "diff": {"path": "local-state/diffs/statecommit-real-proof-0001.patch", "sha256": "sha256:" + "3" * 64},
            "pre_cycle_state_hash": "sha256:" + "4" * 64,
            "post_candidate_state_hash": "sha256:" + "5" * 64,
            "receipts": {
                "observation": str(observation),
                "branch": str(latent),
                "replay": str(root / "state-substrate" / "receipts" / "replay" / "statecommit-real-proof-0001.json"),
                "rollback": str(root / "state-substrate" / "receipts" / "rollback" / "statecommit-real-proof-0001.json"),
            },
            "replay_seed": 123456,
            "rollback_pointer": "statecommit-parent",
            "gc_enggible": False,
            "promotion": "accepted",
        },
    )
    _write(
        root / "state-substrate" / "receipts" / "replay" / "statecommit-real-proof-0001.json",
        {
            "ticket": "EMBER-STATE-REPLAY",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "cycle_id": cycle_id,
            "commit_id": "statecommit-real-proof-0001",
            "diff_sha256": "sha256:" + "3" * 64,
            "deterministic": True,
            "replayed_state_hash": "sha256:" + "5" * 64,
        },
    )
    _write(
        root / "state-substrate" / "receipts" / "rollback" / "statecommit-real-proof-0001.json",
        {
            "ticket": "EMBER-STATE-ROLLBACK",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "cycle_id": cycle_id,
            "commit_id": "statecommit-real-proof-0001",
            "pre_cycle_state_hash": "sha256:" + "4" * 64,
            "post_candidate_state_hash": "sha256:" + "5" * 64,
            "rollback_target": "statecommit-parent",
            "restored_state_hash": "sha256:" + "4" * 64,
            "replay_seed": 123456,
        },
    )
    cycle = _write(
        receipt_dir / "cycles" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-MVP-CYCLE",
            "ts": "20260617T000000Z",
            "cycle_id": cycle_id,
            "benchmark_subset": {
                "id": "mle-low-micro-v0",
                "task_ids": readiness.MLE_LOW_MICRO_TASK_IDS,
                "official_leaderboard_comparable": False,
            },
            "receipts": {
                "observation": observation.relative_to(root).as_posix(),
                "sandbox": sandbox.relative_to(root).as_posix(),
                "gpu_governor": governor.relative_to(root).as_posix(),
                "replay": "receipts/replay/cycle-real-proof-0001.json",
                "rollback": "receipts/rollback/cycle-real-proof-0001.json",
                "benchmark": benchmark.relative_to(root).as_posix(),
                "wheel": wheel.relative_to(root).as_posix(),
                "state_substrate": state_commit.relative_to(root).as_posix(),
                "predictive_rollout": rollout.relative_to(root).as_posix(),
                "meta_cognitive_operator": operator.relative_to(root).as_posix(),
                "context_compaction": compaction.relative_to(root).as_posix(),
            },
            "hypothesis": {
                "text": "fixture candidate should improve normalized benchmark delta",
                "latent_branch_id": latent_id,
            },
            "evidence": {
                "sandbox": {"mode": "windows-native-production-candidate-runner", "verdict": "pass"},
                "governor": {
                    "mode": "governed-gpu-train-eval",
                    "gpu_preflight_called": True,
                    "real_gpu_training": True,
                },
                "benchmark": {"fixture_only": False, "real_mle_tasks_executed": True},
                "wheel": {
                    "fixture_only": False,
                    "real_mle_tasks_executed": True,
                    "equal_budget": True,
                    "ordering": "C>B>A",
                    "growth_allowed": False,
                },
                "state_substrate": {
                    "local_inspectable": True,
                    "replayable_from_commit": True,
                    "rollback_restored": True,
                },
                "recursion": {
                    "required": True,
                    "predictive_rollout": rollout.relative_to(root).as_posix(),
                    "meta_cognitive_operator": operator.relative_to(root).as_posix(),
                    "context_compaction": compaction.relative_to(root).as_posix(),
                    "verdict": "recursion_layer_receipted",
                },
            },
            "score": {"mean_normalized_improvement": 0.4},
            "verdict": "accepted",
        },
    )
    _write(
        receipt_dir / "replay" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-MVP-REPLAY-FIXTURE",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "cycle_id": cycle_id,
            "replay_seed": 123456,
            "deterministic": True,
            "parent_observation_id": obs_id,
            "diff_sha256": "sha256:" + "9" * 64,
        },
    )
    _write(
        receipt_dir / "rollback" / f"{cycle_id}.json",
        {
            "ticket": "EMBER-MVP-ROLLBACK-FIXTURE",
            "ts": "20260617T000000Z",
            "sha_convention": readiness.SHA_CONVENTION,
            "cycle_id": cycle_id,
            "pre_cycle_state_hash": "sha256:" + "4" * 64,
            "post_candidate_state_hash": "sha256:" + "5" * 64,
            "rollback_target": "statecommit-parent",
            "restored_state_hash": "sha256:" + "4" * 64,
            "replay_seed": 123456,
            "verifier_result_before_rollback": "pass",
            "verifier_result_after_rollback": "absent",
        },
    )
    return cycle


def test_current_fixture_cycle_is_not_mvp_ready() -> None:
    fixture_cycle = Path(
        r"<local-path>"
    ) / "receipts" / "cycles" / "cycle-20260617T000000Z-0001.json"
    if not fixture_cycle.exists():
        return

    report = readiness.evaluate_cycle_receipt(fixture_cycle)
    assert report["verdict"] == "NOT_READY"
    assert "sandbox.production_runner" in report["failed_requirements"]
    assert "governor.real_gpu_training" in report["failed_requirements"]
    assert "benchmark.real_mle_tasks_executed" in report["failed_requirements"]
    assert "wheel.real_equal_budget_run" in report["failed_requirements"]


def test_real_proof_fixture_is_mvp_ready_but_growth_still_blocked() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        report = readiness.evaluate_cycle_receipt(cycle_path)

        assert report["verdict"] == "MVP_READY"
        assert report["failed_requirements"] == []
        assert report["growth_verdict"] == "GROWTH_BLOCKED"
        assert report["growth_failures"] == ["growth.receipt_missing", "growth.repeated_positive_cycles"]


def test_real_proof_fixture_with_growth_receipt_is_growth_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-growth-") as td:
        root = Path(td)
        cycle_paths = [
            _real_proof_fixture(root / "cycle-1"),
            _real_proof_fixture(root / "cycle-2"),
            _real_proof_fixture(root / "cycle-3"),
        ]
        growth_path = root / "growth" / "growth.json"
        growth.write_growth_receipt(growth_path, cycle_paths)

        report = readiness.evaluate_cycle_receipt(cycle_paths[-1], growth_path)

        assert report["verdict"] == "MVP_READY"
        assert report["failed_requirements"] == []
        assert report["growth_verdict"] == "GROWTH_READY"
        assert report["growth_failures"] == []
        assert report["growth_receipt"]["ready"] is True


def test_missing_state_substrate_receipt_is_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        del cycle["receipts"]["state_substrate"]
        cycle_path.write_text(json.dumps(cycle, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert report["verdict"] == "NOT_READY"
        assert "state_substrate.local_commit_replayable" in report["failed_requirements"]


def test_missing_observation_receipt_is_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        del cycle["receipts"]["observation"]
        cycle_path.write_text(json.dumps(cycle, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert "cycle.observation_and_latent_bound" in report["requirements"]
        assert report["verdict"] == "NOT_READY"
        assert "cycle.observation_and_latent_bound" in report["failed_requirements"]


def test_missing_cycle_replay_receipt_is_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        del cycle["receipts"]["replay"]
        cycle_path.write_text(json.dumps(cycle, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert "cycle.replay_and_rollback_bound" in report["requirements"]
        assert report["verdict"] == "NOT_READY"
        assert "cycle.replay_and_rollback_bound" in report["failed_requirements"]


def test_missing_named_sandbox_probe_is_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        sandbox_path = Path(td) / cycle["receipts"]["sandbox"]
        sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
        sandbox["required_probe_battery"]["rows"] = [
            row
            for row in sandbox["required_probe_battery"]["rows"]
            if row["probe"] != "deterministic-replay"
        ]
        sandbox["summary"] = {"pass": 10, "total": 10}
        sandbox_path.write_text(json.dumps(sandbox, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert report["verdict"] == "NOT_READY"
        assert "sandbox.required_probes_pass" in report["failed_requirements"]


def test_unassigned_sandbox_probe_job_object_is_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        sandbox_path = Path(td) / cycle["receipts"]["sandbox"]
        sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
        sandbox["required_probe_battery"]["rows"][0]["receipt"]["job_object"] = {
            "requested": True,
            "assigned": False,
            "memory_limit_bytes": 201326592,
        }
        sandbox_path.write_text(json.dumps(sandbox, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert report["verdict"] == "NOT_READY"
        assert "sandbox.required_probes_pass" in report["failed_requirements"]


def test_unassigned_production_candidate_job_object_is_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        sandbox_path = Path(td) / cycle["receipts"]["sandbox"]
        sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
        sandbox["candidate"] = {
            "verdict": "pass",
            "job_object": {
                "requested": True,
                "assigned": False,
                "memory_limit_bytes": 201326592,
            },
        }
        sandbox_path.write_text(json.dumps(sandbox, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert report["verdict"] == "NOT_READY"
        assert "sandbox.required_probes_pass" in report["failed_requirements"]


def test_missing_durable_assimilation_artifact_is_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        governor_path = Path(td) / cycle["receipts"]["gpu_governor"]
        governor = json.loads(governor_path.read_text(encoding="utf-8"))
        del governor["artifact"]["path"]
        governor_path.write_text(json.dumps(governor, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert "assimilation.durable_artifact" in report["requirements"]
        assert report["verdict"] == "NOT_READY"
        assert "assimilation.durable_artifact" in report["failed_requirements"]


def test_missing_per_task_benchmark_results_are_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        cycle_path = _real_proof_fixture(Path(td))
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        benchmark_path = Path(td) / cycle["receipts"]["benchmark"]
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        del benchmark["task_results"]
        benchmark_path.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert "benchmark.per_task_scores_present" in report["requirements"]
        assert report["verdict"] == "NOT_READY"
        assert "benchmark.per_task_scores_present" in report["failed_requirements"]


def test_public_test_proxy_delta_is_recorded_but_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        benchmark_path = root / cycle["receipts"]["benchmark"]
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        benchmark.update(
            {
                "ticket": "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-CANDIDATE-VS-BASELINE",
                "lane": "kaggle_benchmarks",
                "benchmark_family": "livecodebench/code_generation_lite",
                "question_id": "1873_A",
                "frozen_public_test_sha256": "sha256:" + "a" * 64,
                "baseline_public_pass": False,
                "candidate_public_pass": True,
                "public_test_delta": 1.0,
                "candidate_vs_baseline_ready": True,
                "benchmark_delta_claimed": False,
                "real_mle_tasks_executed": False,
                "task_results": [],
                "score": {"mean_normalized_improvement": None},
                "verdict": "PUBLIC_TEST_DELTA_RECEIPTED",
            }
        )
        benchmark_path.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8", newline="\n")
        wheel_path = root / cycle["receipts"]["wheel"]
        wheel = json.loads(wheel_path.read_text(encoding="utf-8"))
        wheel.update(
            {
                "ticket": "EMBER-WHEEL-PUBLIC-TEST-PROXY",
                "real_mle_tasks_executed": False,
                "benchmark_delta_claimed": False,
                "ordering": "public-test-candidate>baseline",
                "public_test_proxy": {
                    "ready": True,
                    "source_receipt": str(benchmark_path),
                    "lane": "kaggle_benchmarks",
                    "benchmark_family": "livecodebench/code_generation_lite",
                    "question_id": "1873_A",
                    "baseline_public_pass": False,
                    "candidate_public_pass": True,
                    "public_test_delta": 1.0,
                    "benchmark_delta_claimed": False,
                    "frozen_public_test_sha256": "sha256:" + "a" * 64,
                },
                "arms": [
                    {
                        "id": "A",
                        "budget_seconds": 3600,
                        "public_test_pass": False,
                        "normalized_improvement": None,
                        "arm_contract_ok": True,
                    },
                    {
                        "id": "B",
                        "budget_seconds": 3600,
                        "public_test_pass": None,
                        "normalized_improvement": None,
                        "arm_contract_ok": True,
                    },
                    {
                        "id": "C",
                        "budget_seconds": 3600,
                        "public_test_pass": True,
                        "normalized_improvement": None,
                        "arm_contract_ok": True,
                    },
                ],
                "verdict": "PROXY_DELTA_RECEIPTED",
            }
        )
        wheel_path.write_text(json.dumps(wheel, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)

        assert report["verdict"] == "NOT_READY"
        assert report["benchmark_public_test_proxy"] == {
            "ready": True,
            "lane": "kaggle_benchmarks",
            "benchmark_family": "livecodebench/code_generation_lite",
            "question_id": "1873_A",
            "baseline_public_pass": False,
            "candidate_public_pass": True,
            "public_test_delta": 1.0,
            "benchmark_delta_claimed": False,
            "frozen_public_test_sha256": "sha256:" + "a" * 64,
        }
        assert report["wheel_public_test_proxy"] == {
            "ready": True,
            "source_receipt": str(benchmark_path),
            "lane": "kaggle_benchmarks",
            "benchmark_family": "livecodebench/code_generation_lite",
            "question_id": "1873_A",
            "baseline_public_pass": False,
            "candidate_public_pass": True,
            "public_test_delta": 1.0,
            "benchmark_delta_claimed": False,
            "frozen_public_test_sha256": "sha256:" + "a" * 64,
        }
        assert "benchmark.real_mle_tasks_executed" in report["failed_requirements"]
        assert "benchmark.per_task_scores_present" in report["failed_requirements"]
        assert "benchmark.external_delta_positive" in report["failed_requirements"]
        assert "wheel.real_equal_budget_run" in report["failed_requirements"]
        assert "wheel.ordering_c_gt_b_gt_a" in report["failed_requirements"]


def test_frozen_heldout_delta_is_recorded_but_not_external_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        benchmark_path = root / cycle["receipts"]["benchmark"]
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        benchmark.update(
            {
                "ticket": "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-FROZEN-HELDOUT-DELTA",
                "lane": "kaggle_benchmarks",
                "benchmark_family": "livecodebench/code_generation_lite",
                "question_id": "1873_A",
                "heldout_source": "local-frozen-fixture",
                "external_source_certified": False,
                "frozen_heldout_sha256": "sha256:" + "b" * 64,
                "heldout_case_count": 2,
                "heldout_delta_ready": True,
                "benchmark_delta_claimed": True,
                "external_benchmark_delta_claimed": False,
                "real_mle_tasks_executed": False,
                "task_results": [],
                "score": {
                    "baseline_score": 0.0,
                    "candidate_score": 1.0,
                    "mean_normalized_improvement": 1.0,
                },
                "verdict": "HELDOUT_DELTA_RECEIPTED",
            }
        )
        benchmark_path.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)

        assert report["verdict"] == "NOT_READY"
        assert report["benchmark_frozen_heldout"] == {
            "ready": True,
            "lane": "kaggle_benchmarks",
            "benchmark_family": "livecodebench/code_generation_lite",
            "question_id": "1873_A",
            "heldout_source": "local-frozen-fixture",
            "external_source_certified": False,
            "frozen_heldout_sha256": "sha256:" + "b" * 64,
            "heldout_case_count": 2,
            "benchmark_delta_claimed": True,
            "external_benchmark_delta_claimed": False,
            "score": {
                "baseline_score": 0.0,
                "candidate_score": 1.0,
                "mean_normalized_improvement": 1.0,
            },
        }
        assert "benchmark.real_mle_tasks_executed" in report["failed_requirements"]
        assert "benchmark.per_task_scores_present" in report["failed_requirements"]
        assert "benchmark.external_delta_positive" in report["failed_requirements"]


def test_external_dataset_heldout_delta_is_recorded_and_clears_external_delta_only() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        benchmark_path = root / cycle["receipts"]["benchmark"]
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        benchmark.update(
            {
                "ticket": "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
                "lane": "kaggle_dataset_external_heldout",
                "dataset_ref": "abdallahwagih/emotion-dataset",
                "dataset_url": "https://www.kaggle.com/datasets/abdallahwagih/emotion-dataset",
                "license_name": "Apache 2.0",
                "source_file_hash_ok": True,
                "external_source_certified": True,
                "heldout_source": "kaggle-dataset:abdallahwagih/emotion-dataset",
                "frozen_heldout_sha256": "sha256:" + "c" * 64,
                "heldout_case_count": 32,
                "heldout_delta_ready": True,
                "benchmark_delta_claimed": True,
                "external_benchmark_delta_claimed": True,
                "candidate_prediction_source": "fixture_gold_label_echo",
                "real_mle_tasks_executed": False,
                "task_results": [],
                "score": {
                    "baseline_score": 0.40625,
                    "candidate_score": 1.0,
                    "mean_normalized_improvement": 1.0,
                },
                "verdict": "EXTERNAL_HELDOUT_DELTA_RECEIPTED",
            }
        )
        benchmark_path.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)

        assert report["verdict"] == "NOT_READY"
        assert report["benchmark_external_heldout"] == {
            "ready": True,
            "dataset_ref": "abdallahwagih/emotion-dataset",
            "heldout_source": "kaggle-dataset:abdallahwagih/emotion-dataset",
            "external_source_certified": True,
            "candidate_prediction_source": "fixture_gold_label_echo",
            "heldout_case_count": 32,
            "benchmark_delta_claimed": True,
            "external_benchmark_delta_claimed": True,
            "score": {
                "baseline_score": 0.40625,
                "candidate_score": 1.0,
                "mean_normalized_improvement": 1.0,
            },
        }
        assert "benchmark.real_mle_tasks_executed" in report["failed_requirements"]
        assert "benchmark.per_task_scores_present" in report["failed_requirements"]
        assert "benchmark.external_delta_positive" not in report["failed_requirements"]


def test_external_dataset_script_candidate_delta_is_recorded_without_fixture_source() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        benchmark_path = root / cycle["receipts"]["benchmark"]
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        benchmark.update(
            {
                "ticket": "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
                "lane": "kaggle_dataset_external_heldout",
                "dataset_ref": "abdallahwagih/emotion-dataset",
                "dataset_url": "https://www.kaggle.com/datasets/abdallahwagih/emotion-dataset",
                "license_name": "Apache 2.0",
                "source_file_hash_ok": True,
                "external_source_certified": True,
                "heldout_source": "kaggle-dataset:abdallahwagih/emotion-dataset",
                "frozen_heldout_sha256": "sha256:" + "d" * 64,
                "heldout_case_count": 32,
                "heldout_delta_ready": True,
                "benchmark_delta_claimed": True,
                "external_benchmark_delta_claimed": True,
                "candidate_prediction_source": "script:<local-path>",
                "candidate_script_sha256": "sha256:" + "e" * 64,
                "candidate_returncode": 0,
                "real_mle_tasks_executed": False,
                "task_results": [],
                "score": {
                    "baseline_score": 0.40625,
                    "candidate_score": 0.6875,
                    "mean_normalized_improvement": 0.473684,
                },
                "verdict": "EXTERNAL_HELDOUT_DELTA_RECEIPTED",
            }
        )
        benchmark_path.write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)

        assert report["verdict"] == "NOT_READY"
        assert report["benchmark_external_heldout"]["ready"] is True
        assert report["benchmark_external_heldout"]["candidate_prediction_source"] == "script:<local-path>"
        assert report["benchmark_external_heldout"]["score"]["candidate_score"] == 0.6875
        assert "benchmark.external_delta_positive" not in report["failed_requirements"]


def test_research_journal_loop_receipt_can_clear_benchmark_and_wheel_requirements() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-research-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        research_loop = {
            "ticket": "EMBER-RESEARCH-LOOP",
            "benchmark_id": "D3-Gym",
            "benchmark_family": "research_journal",
            "operator_routed": True,
            "budget_seconds_per_arm_per_task": 120,
            "equal_budget": True,
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
                {
                    "task_id": f"task_{i}",
                    "arm_a_passed": i == 3,
                    "arm_b_passed": i == 3,
                    "arm_c_passed": True,
                }
                for i in range(1, 9)
            ],
            "score": {
                "baseline_score": 0.125,
                "dream_loop_score": 0.125,
                "candidate_score": 1.0,
                "mean_normalized_improvement": 0.875,
            },
            "ordering": "C>B=A",
            "errors": [],
            "verdict": "RESEARCH_LOOP_ACCEPTED",
        }
        benchmark_path = root / cycle["receipts"]["benchmark"]
        wheel_path = root / cycle["receipts"]["wheel"]
        benchmark_path.write_text(json.dumps(research_loop, indent=2) + "\n", encoding="utf-8", newline="\n")
        wheel_path.write_text(json.dumps(research_loop, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)

        assert report["verdict"] == "MVP_READY"
        assert report["benchmark_mode"] == "research_journal_replacement"
        assert report["wheel_mode"] == "research_journal_replacement"
        assert report["benchmark_research_loop"]["ready"] is True
        assert report["wheel_research_loop"]["ready"] is True


def test_frozen_heldout_wheel_is_recorded_but_not_real_wheel_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        wheel_path = root / cycle["receipts"]["wheel"]
        wheel = json.loads(wheel_path.read_text(encoding="utf-8"))
        wheel.update(
            {
                "ticket": "EMBER-WHEEL-HELDOUT-RUN",
                "real_mle_tasks_executed": False,
                "heldout_delta_ready": True,
                "benchmark_delta_claimed": True,
                "external_benchmark_delta_claimed": False,
                "ordering": "C>B>A",
                "verdict": "HELDOUT_WHEEL_RECEIPTED",
                "arms": [
                    {
                        "id": "A",
                        "budget_seconds": 3600,
                        "heldout_delta_ready": True,
                        "heldout_source": "local-frozen-fixture",
                        "external_source_certified": False,
                        "external_benchmark_delta_claimed": False,
                        "normalized_improvement": 0.1,
                        "arm_contract_ok": True,
                    },
                    {
                        "id": "B",
                        "budget_seconds": 3600,
                        "heldout_delta_ready": True,
                        "heldout_source": "local-frozen-fixture",
                        "external_source_certified": False,
                        "external_benchmark_delta_claimed": False,
                        "normalized_improvement": 0.2,
                        "arm_contract_ok": True,
                    },
                    {
                        "id": "C",
                        "budget_seconds": 3600,
                        "heldout_delta_ready": True,
                        "heldout_source": "local-frozen-fixture",
                        "external_source_certified": False,
                        "external_benchmark_delta_claimed": False,
                        "normalized_improvement": 0.4,
                        "arm_contract_ok": True,
                    },
                ],
            }
        )
        wheel_path.write_text(json.dumps(wheel, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)

        assert report["verdict"] == "NOT_READY"
        assert report["wheel_frozen_heldout"] == {
            "ready": True,
            "benchmark_delta_claimed": True,
            "external_benchmark_delta_claimed": False,
            "ordering": "C>B>A",
            "arms": [
                {"id": "A", "normalized_improvement": 0.1, "external_benchmark_delta_claimed": False},
                {"id": "B", "normalized_improvement": 0.2, "external_benchmark_delta_claimed": False},
                {"id": "C", "normalized_improvement": 0.4, "external_benchmark_delta_claimed": False},
            ],
        }
        assert "wheel.real_equal_budget_run" in report["failed_requirements"]


def test_invalid_wheel_arm_contracts_are_not_mvp_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
        wheel_path = root / cycle["receipts"]["wheel"]
        wheel = json.loads(wheel_path.read_text(encoding="utf-8"))
        wheel["arms"][1]["arm_contract_ok"] = False
        wheel["arms"][1]["arm_contract_errors"] = ["B may not claim a state commit"]
        wheel_path.write_text(json.dumps(wheel, indent=2) + "\n", encoding="utf-8", newline="\n")

        report = readiness.evaluate_cycle_receipt(cycle_path)
        assert "wheel.arm_contracts_valid" in report["requirements"]
        assert report["verdict"] == "NOT_READY"
        assert "wheel.arm_contracts_valid" in report["failed_requirements"]


def test_readiness_report_can_be_written_as_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        out = root / "readiness.json"
        report = readiness.write_readiness_receipt(cycle_path, out)

        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["ticket"] == "EMBER-MVP-READINESS"
        assert loaded["cycle_id"] == report["cycle_id"]
        assert loaded["verdict"] == "MVP_READY"


def test_readiness_writer_creates_nested_output_directory() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-readiness-") as td:
        root = Path(td)
        cycle_path = _real_proof_fixture(root)
        out = root / "receipts" / "readiness" / "cycle-real-proof-0001.json"
        readiness.write_readiness_receipt(cycle_path, out)

        assert out.exists()


def main() -> int:
    tests = [
        test_current_fixture_cycle_is_not_mvp_ready,
        test_real_proof_fixture_is_mvp_ready_but_growth_still_blocked,
        test_real_proof_fixture_with_growth_receipt_is_growth_ready,
        test_missing_state_substrate_receipt_is_not_mvp_ready,
        test_missing_observation_receipt_is_not_mvp_ready,
        test_missing_cycle_replay_receipt_is_not_mvp_ready,
        test_missing_named_sandbox_probe_is_not_mvp_ready,
        test_unassigned_sandbox_probe_job_object_is_not_mvp_ready,
        test_unassigned_production_candidate_job_object_is_not_mvp_ready,
        test_missing_durable_assimilation_artifact_is_not_mvp_ready,
        test_missing_per_task_benchmark_results_are_not_mvp_ready,
        test_public_test_proxy_delta_is_recorded_but_not_mvp_ready,
        test_frozen_heldout_delta_is_recorded_but_not_external_mvp_ready,
        test_external_dataset_heldout_delta_is_recorded_and_clears_external_delta_only,
        test_external_dataset_script_candidate_delta_is_recorded_without_fixture_source,
        test_research_journal_loop_receipt_can_clear_benchmark_and_wheel_requirements,
        test_frozen_heldout_wheel_is_recorded_but_not_real_wheel_ready,
        test_invalid_wheel_arm_contracts_are_not_mvp_ready,
        test_readiness_report_can_be_written_as_receipt,
        test_readiness_writer_creates_nested_output_directory,
    ]
    for test in tests:
        test()
    print("EMBER_MVP_READINESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
