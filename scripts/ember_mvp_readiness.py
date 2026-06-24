#!/usr/bin/env python3
"""Fail-closed readiness gate for Ember MVP v0 cycle receipts."""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ember_growth_harness as growth_harness
from receipt_write import checked_write

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
MLE_LOW_MICRO_TASK_IDS = [
    "detecting-insults-in-social-commentary",
    "random-acts-of-pizza",
    "spooky-author-identification",
    "nomad2018-predict-transparent-conductors",
    "leaf-classification",
]
REQUIRED_SANDBOX_PROBES = {
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

MVP_REQUIREMENTS = [
    "cycle.accepted",
    "cycle.observation_and_latent_bound",
    "cycle.replay_and_rollback_bound",
    "sandbox.production_runner",
    "sandbox.required_probes_pass",
    "governor.real_gpu_training",
    "governor.hashable_artifact",
    "assimilation.durable_artifact",
    "state_substrate.local_commit_replayable",
    "benchmark.real_mle_tasks_executed",
    "benchmark.per_task_scores_present",
    "benchmark.external_delta_positive",
    "wheel.real_equal_budget_run",
    "wheel.arm_contracts_valid",
    "wheel.ordering_c_gt_b_gt_a",
    "recursion.predictive_rollout",
    "recursion.prospective_meta_operator",
    "recursion.context_compaction",
]


class ReadinessError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _receipt_path(cycle_path: Path, rel_path: str) -> Path:
    root = cycle_path.parent.parent.parent
    return root / rel_path


def _load_linked(cycle_path: Path, cycle: dict[str, Any], key: str) -> dict[str, Any]:
    rel = cycle.get("receipts", {}).get(key)
    if not rel:
        return {"_missing": True}
    path = _receipt_path(cycle_path, rel)
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    receipt = load_json(path)
    receipt["_path"] = str(path)
    return receipt


def _load_cycle_relative(cycle_path: Path, rel_path: str | None) -> dict[str, Any]:
    if not rel_path:
        return {"_missing": True}
    path = _receipt_path(cycle_path, rel_path)
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    receipt = load_json(path)
    receipt["_path"] = str(path)
    return receipt


def _load_receipt_path(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {"_missing": True}
    path = Path(path_value)
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    receipt = load_json(path)
    receipt["_path"] = str(path)
    return receipt


def _fail_if(condition: bool, failures: list[str], requirement: str) -> None:
    if condition:
        failures.append(requirement)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _artifact_hash_matches(artifact: dict[str, Any]) -> bool:
    artifact_path = artifact.get("path")
    if not artifact_path:
        return False
    path = Path(artifact_path)
    if not path.exists() or not path.is_file():
        return False
    recorded_hashes = [
        artifact.get("checkpoint_hash"),
        artifact.get("adapter_hash"),
        artifact.get("model_hash"),
    ]
    actual_hash = _sha256_file(path)
    return any(value == actual_hash for value in recorded_hashes)


def _load_sandbox_probe_rows(sandbox: dict[str, Any]) -> list[dict[str, Any]]:
    battery = sandbox.get("required_probe_battery", {})
    rows = battery.get("rows")
    if isinstance(rows, list):
        return rows
    receipt_path = battery.get("receipt_path")
    if not receipt_path:
        return []
    path = Path(receipt_path)
    if not path.exists():
        return []
    receipt = load_json(path)
    loaded_rows = receipt.get("rows")
    return loaded_rows if isinstance(loaded_rows, list) else []


def _sandbox_required_probes_pass(sandbox: dict[str, Any]) -> bool:
    rows = _load_sandbox_probe_rows(sandbox)
    by_probe = {row.get("probe"): row for row in rows if isinstance(row, dict)}
    if set(by_probe) != set(REQUIRED_SANDBOX_PROBES):
        return False
    for probe, verdict in REQUIRED_SANDBOX_PROBES.items():
        row = by_probe[probe]
        if row.get("verdict") != verdict or row.get("ok") is not True:
            return False
        receipt = row.get("receipt", {})
        if not isinstance(receipt, dict) or receipt.get("probe") != probe or receipt.get("verdict") != verdict:
            return False
        job_object = receipt.get("job_object", {})
        if not isinstance(job_object, dict) or job_object.get("assigned") is not True:
            return False
    replay_receipt = by_probe["deterministic-replay"].get("receipt", {})
    return replay_receipt.get("replay_result", {}).get("outputs_match") is True


def _cycle_observation_and_latent_bound(
    cycle_path: Path,
    cycle: dict[str, Any],
    state_substrate: dict[str, Any],
) -> bool:
    cycle_id = cycle.get("cycle_id")
    observation = _load_cycle_relative(cycle_path, cycle.get("receipts", {}).get("observation"))
    latent_id = cycle.get("hypothesis", {}).get("latent_branch_id")
    latent = _load_cycle_relative(cycle_path, f"receipts/latent/{latent_id}.json" if latent_id else None)
    if observation.get("_missing") or latent.get("_missing"):
        return False
    if observation.get("cycle_id") != cycle_id or latent.get("cycle_id") != cycle_id:
        return False
    if not observation.get("id") or latent.get("parent_observation_id") != observation.get("id"):
        return False
    if latent.get("id") != latent_id:
        return False
    if latent.get("inputs", {}).get("hypothesis") != cycle.get("hypothesis", {}).get("text"):
        return False
    produced_deltas = latent.get("produced_deltas")
    if not isinstance(produced_deltas, list) or not produced_deltas:
        return False
    if not all(isinstance(row.get("sha256"), str) and row["sha256"].startswith("sha256:") for row in produced_deltas):
        return False
    if state_substrate.get("latent_branch_id") != latent_id:
        return False
    receipts = state_substrate.get("receipts", {})
    substrate_observation = _load_receipt_path(receipts.get("observation"))
    if receipts.get("observation"):
        if substrate_observation.get("_missing") or substrate_observation.get("id") != observation.get("id"):
            return False
        if substrate_observation.get("cycle_id") != cycle_id:
            return False
    substrate_branch = _load_receipt_path(receipts.get("branch") or receipts.get("latent_branch"))
    if receipts.get("branch") or receipts.get("latent_branch"):
        if substrate_branch.get("_missing") or substrate_branch.get("id") != latent_id:
            return False
        if substrate_branch.get("cycle_id") != cycle_id:
            return False
        if substrate_branch.get("parent_observation_id") != observation.get("id"):
            return False
    return True


def _cycle_replay_and_rollback_bound(
    cycle_path: Path,
    cycle: dict[str, Any],
    state_substrate: dict[str, Any],
) -> bool:
    cycle_id = cycle.get("cycle_id")
    replay = _load_cycle_relative(cycle_path, cycle.get("receipts", {}).get("replay"))
    rollback = _load_cycle_relative(cycle_path, cycle.get("receipts", {}).get("rollback"))
    if replay.get("_missing") or rollback.get("_missing"):
        return False
    if replay.get("cycle_id") != cycle_id or rollback.get("cycle_id") != cycle_id:
        return False
    if replay.get("deterministic") is not True:
        return False
    observation = _load_cycle_relative(cycle_path, cycle.get("receipts", {}).get("observation"))
    if observation.get("_missing"):
        return False
    latent_id = cycle.get("hypothesis", {}).get("latent_branch_id")
    latent = _load_cycle_relative(cycle_path, f"receipts/latent/{latent_id}.json" if latent_id else None)
    produced_deltas = latent.get("produced_deltas") if not latent.get("_missing") else None
    if not isinstance(produced_deltas, list) or not produced_deltas:
        return False
    latent_delta_hashes = {row.get("sha256") for row in produced_deltas if isinstance(row, dict)}
    expected_diff_hashes = set(latent_delta_hashes)
    if isinstance(state_substrate.get("diff", {}).get("sha256"), str):
        expected_diff_hashes.add(state_substrate["diff"]["sha256"])
    if replay.get("diff_sha256") not in expected_diff_hashes:
        return False
    if replay.get("parent_observation_id") and replay.get("parent_observation_id") != observation.get("id"):
        return False
    if replay.get("commit_id") and replay.get("commit_id") != state_substrate.get("id"):
        return False
    if replay.get("replayed_state_hash") and replay.get("replayed_state_hash") != state_substrate.get("post_candidate_state_hash"):
        return False
    if rollback.get("restored_state_hash") != rollback.get("pre_cycle_state_hash"):
        return False
    if rollback.get("pre_cycle_state_hash") != state_substrate.get("pre_cycle_state_hash"):
        return False
    if rollback.get("post_candidate_state_hash") != state_substrate.get("post_candidate_state_hash"):
        return False
    if rollback.get("rollback_target") != state_substrate.get("parent_id"):
        return False
    if rollback.get("commit_id") and rollback.get("commit_id") != state_substrate.get("id"):
        return False
    if replay.get("replay_seed") is not None and rollback.get("replay_seed") != replay.get("replay_seed"):
        return False
    if rollback.get("verifier_result_before_rollback") not in {None, "pass"}:
        return False
    if rollback.get("verifier_result_after_rollback") not in {None, "absent", "reverted"}:
        return False
    return True


def _valid_per_task_benchmark_results(benchmark: dict[str, Any]) -> bool:
    task_results = benchmark.get("task_results")
    if not isinstance(task_results, list) or len(task_results) != len(MLE_LOW_MICRO_TASK_IDS):
        return False
    if [row.get("task_id") for row in task_results] != MLE_LOW_MICRO_TASK_IDS:
        return False
    improvements: list[float] = []
    for row in task_results:
        for key in ("baseline_score", "candidate_score", "normalized_improvement"):
            if not isinstance(row.get(key), (int, float)):
                return False
        improvements.append(float(row["normalized_improvement"]))
    score = benchmark.get("score", {})
    mean = score.get("mean_normalized_improvement")
    if not isinstance(mean, (int, float)):
        return False
    expected_mean = round(sum(improvements) / len(improvements), 6)
    return round(float(mean), 6) == expected_mean


def _artifact_by_name(receipt: dict[str, Any], name: str) -> dict[str, Any] | None:
    artifacts = receipt.get("artifact_files")
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("name") == name:
            return artifact
    return None


def _jsonl_row_count(path_value: str | None) -> int | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return None
    rows = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                json.loads(line)
                rows += 1
    return rows


def _external_trained_prediction_rows_present(benchmark: dict[str, Any]) -> bool:
    heldout_count = benchmark.get("heldout_case_count")
    if not isinstance(heldout_count, int) or heldout_count <= 0:
        return False
    for name in (
        "external_heldout_cases.jsonl",
        "baseline_predictions.jsonl",
        "candidate_predictions.jsonl",
    ):
        artifact = _artifact_by_name(benchmark, name)
        if not artifact:
            return False
        recorded_hash = artifact.get("sha256")
        path_value = artifact.get("path")
        if not isinstance(recorded_hash, str) or not recorded_hash.startswith("sha256:"):
            return False
        path = Path(path_value) if path_value else None
        if path is None or not path.exists() or _sha256_file(path) != recorded_hash:
            return False
        if _jsonl_row_count(path_value) != heldout_count:
            return False

    model_artifact = _artifact_by_name(benchmark, "trained_candidate_model.json")
    training = benchmark.get("candidate_training", {})
    if not isinstance(training, dict) or not model_artifact:
        return False
    model_path = model_artifact.get("path")
    model_hash = model_artifact.get("sha256")
    if not isinstance(model_hash, str) or not model_hash.startswith("sha256:"):
        return False
    if not model_path or not Path(model_path).exists() or _sha256_file(Path(model_path)) != model_hash:
        return False
    return (
        training.get("model_artifact_path") == model_path
        and training.get("model_artifact_sha256") == model_hash
        and training.get("heldout_case_count") == heldout_count
        and isinstance(training.get("training_case_count"), int)
        and training.get("training_case_count") > heldout_count
    )


def _benchmark_public_test_proxy(benchmark: dict[str, Any]) -> dict[str, Any]:
    ready = bool(
        benchmark.get("ticket") == "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-CANDIDATE-VS-BASELINE"
        and benchmark.get("lane") == "kaggle_benchmarks"
        and benchmark.get("candidate_vs_baseline_ready") is True
        and benchmark.get("benchmark_delta_claimed") is False
        and benchmark.get("baseline_public_pass") is False
        and benchmark.get("candidate_public_pass") is True
        and isinstance(benchmark.get("public_test_delta"), (int, float))
        and benchmark.get("public_test_delta") > 0
        and isinstance(benchmark.get("frozen_public_test_sha256"), str)
        and benchmark.get("frozen_public_test_sha256", "").startswith("sha256:")
    )
    if not ready:
        return {"ready": False}
    return {
        "ready": True,
        "lane": benchmark.get("lane"),
        "benchmark_family": benchmark.get("benchmark_family"),
        "question_id": benchmark.get("question_id"),
        "baseline_public_pass": benchmark.get("baseline_public_pass"),
        "candidate_public_pass": benchmark.get("candidate_public_pass"),
        "public_test_delta": benchmark.get("public_test_delta"),
        "benchmark_delta_claimed": benchmark.get("benchmark_delta_claimed"),
        "frozen_public_test_sha256": benchmark.get("frozen_public_test_sha256"),
    }


def _benchmark_frozen_heldout(benchmark: dict[str, Any]) -> dict[str, Any]:
    score = benchmark.get("score", {})
    ready = bool(
        benchmark.get("ticket") == "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-FROZEN-HELDOUT-DELTA"
        and benchmark.get("lane") == "kaggle_benchmarks"
        and benchmark.get("heldout_delta_ready") is True
        and benchmark.get("benchmark_delta_claimed") is True
        and benchmark.get("external_benchmark_delta_claimed") is bool(benchmark.get("external_source_certified"))
        and isinstance(benchmark.get("heldout_case_count"), int)
        and benchmark.get("heldout_case_count") > 0
        and isinstance(benchmark.get("frozen_heldout_sha256"), str)
        and benchmark.get("frozen_heldout_sha256", "").startswith("sha256:")
        and isinstance(score.get("baseline_score"), (int, float))
        and isinstance(score.get("candidate_score"), (int, float))
        and isinstance(score.get("mean_normalized_improvement"), (int, float))
        and score.get("mean_normalized_improvement") > 0
    )
    if not ready:
        return {"ready": False}
    return {
        "ready": True,
        "lane": benchmark.get("lane"),
        "benchmark_family": benchmark.get("benchmark_family"),
        "question_id": benchmark.get("question_id"),
        "heldout_source": benchmark.get("heldout_source"),
        "external_source_certified": benchmark.get("external_source_certified"),
        "frozen_heldout_sha256": benchmark.get("frozen_heldout_sha256"),
        "heldout_case_count": benchmark.get("heldout_case_count"),
        "benchmark_delta_claimed": benchmark.get("benchmark_delta_claimed"),
        "external_benchmark_delta_claimed": benchmark.get("external_benchmark_delta_claimed"),
        "score": {
            "baseline_score": score.get("baseline_score"),
            "candidate_score": score.get("candidate_score"),
            "mean_normalized_improvement": score.get("mean_normalized_improvement"),
        },
    }


def _benchmark_external_heldout(benchmark: dict[str, Any]) -> dict[str, Any]:
    score = benchmark.get("score", {})
    candidate_source = str(benchmark.get("candidate_prediction_source", ""))
    candidate_source_valid = candidate_source == "fixture_gold_label_echo" or (
        candidate_source.startswith("script:")
        and benchmark.get("candidate_returncode") == 0
        and str(benchmark.get("candidate_script_sha256", "")).startswith("sha256:")
    ) or (
        candidate_source == "trained_sklearn_text_classifier"
        and benchmark.get("candidate_returncode") == 0
        and _external_trained_prediction_rows_present(benchmark)
    )
    ready = bool(
        benchmark.get("ticket") == "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA"
        and benchmark.get("lane") == "kaggle_dataset_external_heldout"
        and benchmark.get("heldout_delta_ready") is True
        and benchmark.get("external_source_certified") is True
        and benchmark.get("source_file_hash_ok") is True
        and benchmark.get("benchmark_delta_claimed") is True
        and benchmark.get("external_benchmark_delta_claimed") is True
        and candidate_source_valid
        and isinstance(benchmark.get("heldout_case_count"), int)
        and benchmark.get("heldout_case_count") > 0
        and isinstance(score.get("baseline_score"), (int, float))
        and isinstance(score.get("candidate_score"), (int, float))
        and isinstance(score.get("mean_normalized_improvement"), (int, float))
        and score.get("mean_normalized_improvement") > 0
    )
    if not ready:
        return {"ready": False}
    return {
        "ready": True,
        "dataset_ref": benchmark.get("dataset_ref"),
        "heldout_source": benchmark.get("heldout_source"),
        "external_source_certified": benchmark.get("external_source_certified"),
        "candidate_prediction_source": benchmark.get("candidate_prediction_source"),
        "heldout_case_count": benchmark.get("heldout_case_count"),
        "benchmark_delta_claimed": benchmark.get("benchmark_delta_claimed"),
        "external_benchmark_delta_claimed": benchmark.get("external_benchmark_delta_claimed"),
        "score": {
            "baseline_score": score.get("baseline_score"),
            "candidate_score": score.get("candidate_score"),
            "mean_normalized_improvement": score.get("mean_normalized_improvement"),
        },
    }


def _benchmark_external_replacement_ready(benchmark: dict[str, Any]) -> bool:
    return bool(
        _benchmark_external_heldout(benchmark).get("ready") is True
        and benchmark.get("candidate_prediction_source") == "trained_sklearn_text_classifier"
        and _external_trained_prediction_rows_present(benchmark)
    )


def _research_loop_replacement(bench_or_wheel: dict[str, Any]) -> dict[str, Any]:
    score = bench_or_wheel.get("score", {})
    arms = bench_or_wheel.get("arms", {})
    arm_c = arms.get("arm_c") if isinstance(arms, dict) else {}
    rows = bench_or_wheel.get("per_task_rows")
    if not isinstance(rows, list):
        rows = []
    task_count = bench_or_wheel.get("task_count")
    c_pass_count = sum(1 for row in rows if isinstance(row, dict) and row.get("arm_c_passed") is True)
    ready = bool(
        bench_or_wheel.get("ticket") == "EMBER-RESEARCH-LOOP"
        and bench_or_wheel.get("benchmark_family") == "research_journal"
        and bench_or_wheel.get("operator_routed") is True
        and bench_or_wheel.get("equal_budget") is True
        and bench_or_wheel.get("verdict") == "RESEARCH_LOOP_ACCEPTED"
        and bench_or_wheel.get("ordering") == "C>B=A"
        and isinstance(task_count, int)
        and task_count > 0
        and len(rows) == task_count
        and c_pass_count == task_count
        and isinstance(score.get("baseline_score"), (int, float))
        and isinstance(score.get("dream_loop_score"), (int, float))
        and isinstance(score.get("candidate_score"), (int, float))
        and isinstance(score.get("mean_normalized_improvement"), (int, float))
        and score.get("candidate_score") > score.get("baseline_score")
        and score.get("candidate_score") > score.get("dream_loop_score")
        and score.get("mean_normalized_improvement") > 0
        and isinstance(arm_c, dict)
        and arm_c.get("manual_solution") is False
        and arm_c.get("generator_load_bearing") is True
    )
    return {
        "ready": ready,
        "benchmark_id": bench_or_wheel.get("benchmark_id"),
        "benchmark_family": bench_or_wheel.get("benchmark_family"),
        "operator_routed": bench_or_wheel.get("operator_routed"),
        "equal_budget": bench_or_wheel.get("equal_budget"),
        "task_count": task_count,
        "c_pass_count": c_pass_count,
        "ordering": bench_or_wheel.get("ordering"),
        "score": {
            "baseline_score": score.get("baseline_score"),
            "dream_loop_score": score.get("dream_loop_score"),
            "candidate_score": score.get("candidate_score"),
            "mean_normalized_improvement": score.get("mean_normalized_improvement"),
        },
    }


def _wheel_public_test_proxy(wheel: dict[str, Any]) -> dict[str, Any]:
    proxy = wheel.get("public_test_proxy")
    if not isinstance(proxy, dict):
        return {"ready": False}
    ready = bool(
        wheel.get("ticket") == "EMBER-WHEEL-PUBLIC-TEST-PROXY"
        and wheel.get("real_mle_tasks_executed") is False
        and wheel.get("benchmark_delta_claimed") is False
        and wheel.get("verdict") == "PROXY_DELTA_RECEIPTED"
        and wheel.get("ordering") == "public-test-candidate>baseline"
        and proxy.get("ready") is True
        and proxy.get("benchmark_delta_claimed") is False
        and isinstance(proxy.get("public_test_delta"), (int, float))
        and proxy.get("public_test_delta") > 0
    )
    if not ready:
        return {"ready": False}
    return {
        "ready": True,
        "source_receipt": proxy.get("source_receipt"),
        "lane": proxy.get("lane"),
        "benchmark_family": proxy.get("benchmark_family"),
        "question_id": proxy.get("question_id"),
        "baseline_public_pass": proxy.get("baseline_public_pass"),
        "candidate_public_pass": proxy.get("candidate_public_pass"),
        "public_test_delta": proxy.get("public_test_delta"),
        "benchmark_delta_claimed": proxy.get("benchmark_delta_claimed"),
        "frozen_public_test_sha256": proxy.get("frozen_public_test_sha256"),
    }


def _wheel_frozen_heldout(wheel: dict[str, Any]) -> dict[str, Any]:
    arms = wheel.get("arms")
    if not isinstance(arms, list):
        return {"ready": False}
    improvements = {arm.get("id"): arm.get("normalized_improvement") for arm in arms if isinstance(arm, dict)}
    ready = bool(
        wheel.get("ticket") == "EMBER-WHEEL-HELDOUT-RUN"
        and wheel.get("heldout_delta_ready") is True
        and wheel.get("benchmark_delta_claimed") is True
        and wheel.get("verdict") == "HELDOUT_WHEEL_RECEIPTED"
        and wheel.get("ordering") == "C>B>A"
        and [arm.get("id") for arm in arms] == ["A", "B", "C"]
        and all(arm.get("arm_contract_ok") is True for arm in arms if isinstance(arm, dict))
        and isinstance(improvements.get("A"), (int, float))
        and isinstance(improvements.get("B"), (int, float))
        and isinstance(improvements.get("C"), (int, float))
        and improvements["C"] > improvements["B"] > improvements["A"]
    )
    if not ready:
        return {"ready": False}
    return {
        "ready": True,
        "benchmark_delta_claimed": wheel.get("benchmark_delta_claimed"),
        "external_benchmark_delta_claimed": wheel.get("external_benchmark_delta_claimed"),
        "ordering": wheel.get("ordering"),
        "arms": [
            {
                "id": arm.get("id"),
                "normalized_improvement": arm.get("normalized_improvement"),
                "external_benchmark_delta_claimed": arm.get("external_benchmark_delta_claimed"),
            }
            for arm in arms
        ],
    }


def _wheel_external_replacement_ready(wheel: dict[str, Any]) -> bool:
    arms = wheel.get("arms")
    if not isinstance(arms, list):
        return False
    budgets = {arm.get("budget_seconds") for arm in arms if isinstance(arm, dict)}
    return bool(
        _wheel_frozen_heldout(wheel).get("ready") is True
        and wheel.get("fixture_only") is False
        and wheel.get("real_mle_tasks_executed") is False
        and wheel.get("external_benchmark_delta_claimed") is True
        and wheel.get("equal_budget") is True
        and budgets == {3600}
        and all(arm.get("external_source_certified") is True for arm in arms if isinstance(arm, dict))
        and all(arm.get("external_benchmark_delta_claimed") is True for arm in arms if isinstance(arm, dict))
    )


def _recursion_receipts_ready(cycle_path: Path, cycle: dict[str, Any]) -> dict[str, Any]:
    rollout = _load_cycle_relative(cycle_path, cycle.get("receipts", {}).get("predictive_rollout"))
    operator = _load_cycle_relative(cycle_path, cycle.get("receipts", {}).get("meta_cognitive_operator"))
    compaction = _load_cycle_relative(cycle_path, cycle.get("receipts", {}).get("context_compaction"))
    rollout_ready = bool(
        rollout.get("ticket") == "EMBER-PREDICTIVE-DREAM-ROLLOUT"
        and rollout.get("arm_id") == "B"
        and rollout.get("predicts_next_cycle_task_progress") is True
        and isinstance(rollout.get("candidate_next_states"), list)
        and len(rollout.get("candidate_next_states", [])) > 0
        and rollout.get("deletion_load_bearing_test", {}).get("must_be_checked_on")
        and rollout.get("verdict") == "PREDICTIVE_ROLLOUT_RECEIPTED"
    )
    operator_ready = bool(
        operator.get("ticket") == "EMBER-PROSPECTIVE-METACOGNITIVE-OPERATOR"
        and operator.get("retrospective_discriminator_only") is False
        and operator.get("prospective_output", {}).get("next_action")
        and isinstance(operator.get("trained_from_receipt_trace_sha256"), str)
        and operator.get("trained_from_receipt_trace_sha256", "").startswith("sha256:")
        and operator.get("deletion_load_bearing_test", {}).get("must_degrade")
        and operator.get("verdict") == "PROSPECTIVE_OPERATOR_RECEIPTED"
    )
    compaction_ready = bool(
        compaction.get("ticket") == "EMBER-DISPATCH-CONTEXT-COMPACTION"
        and compaction.get("goal_context_used") is True
        and compaction.get("preserves_dispatch_state") is True
        and isinstance(compaction.get("goal_doc_hashes"), list)
        and len(compaction.get("goal_doc_hashes", [])) >= 2
        and compaction.get("dispatch_critical_state", {}).get("next_action")
        and compaction.get("verdict") == "COMPACTION_RECEIPTED"
    )
    return {
        "ready": rollout_ready and operator_ready and compaction_ready,
        "predictive_rollout": {
            "ready": rollout_ready,
            "path": rollout.get("_path"),
        },
        "prospective_meta_operator": {
            "ready": operator_ready,
            "path": operator.get("_path"),
        },
        "context_compaction": {
            "ready": compaction_ready,
            "path": compaction.get("_path"),
        },
    }


def _growth_receipt_status(growth_receipt_path: Path | None, cycle_path: Path) -> dict[str, Any]:
    if growth_receipt_path is None:
        return {"ready": False, "path": None, "errors": ["growth.receipt_missing"]}
    if not growth_receipt_path.exists():
        return {"ready": False, "path": str(growth_receipt_path), "errors": ["growth.receipt_missing"]}
    receipt = load_json(growth_receipt_path)
    errors = growth_harness.validate_growth_receipt(receipt)
    cycle_paths = {str(Path(row.get("cycle_receipt_path", "")).resolve()) for row in receipt.get("cycles", [])}
    if str(cycle_path.resolve()) not in cycle_paths:
        errors.append("growth.receipt_missing_current_cycle")
    return {
        "ready": not errors,
        "path": str(growth_receipt_path),
        "errors": errors,
        "receipt": {
            "ticket": receipt.get("ticket"),
            "verdict": receipt.get("verdict"),
            "repeated_positive_cycles": receipt.get("repeated_positive_cycles"),
            "growth_allowed": receipt.get("growth_allowed"),
            "benchmark_subset_id": receipt.get("benchmark_subset_id"),
            "frozen_heldout_sha256": receipt.get("frozen_heldout_sha256"),
            "contraction_stability": receipt.get("contraction_stability"),
            "next_cycle_ceiling": receipt.get("next_cycle_ceiling"),
        },
    }


def evaluate_cycle_receipt(cycle_path: Path, growth_receipt_path: Path | None = None) -> dict[str, Any]:
    cycle_path = Path(cycle_path)
    cycle = load_json(cycle_path)
    sandbox = _load_linked(cycle_path, cycle, "sandbox")
    governor = _load_linked(cycle_path, cycle, "gpu_governor")
    state_substrate = _load_linked(cycle_path, cycle, "state_substrate")
    benchmark = _load_linked(cycle_path, cycle, "benchmark")
    wheel = _load_linked(cycle_path, cycle, "wheel")

    failures: list[str] = []
    _fail_if(cycle.get("verdict") != "accepted", failures, "cycle.accepted")
    _fail_if(
        not _cycle_observation_and_latent_bound(cycle_path, cycle, state_substrate),
        failures,
        "cycle.observation_and_latent_bound",
    )
    _fail_if(
        not _cycle_replay_and_rollback_bound(cycle_path, cycle, state_substrate),
        failures,
        "cycle.replay_and_rollback_bound",
    )

    sandbox_mode = sandbox.get("mode")
    _fail_if(
        sandbox_mode != "windows-native-production-candidate-runner",
        failures,
        "sandbox.production_runner",
    )
    summary = sandbox.get("summary", {})
    _fail_if(
        sandbox.get("verdict") != "pass"
        or summary.get("pass") != summary.get("total")
        or summary.get("total", 0) < len(REQUIRED_SANDBOX_PROBES)
        or sandbox.get("windows_native_runner") is not True
        or sandbox.get("job_object_limit_requested") is not True
        or sandbox.get("candidate", {}).get("job_object", {}).get("assigned") is not True
        or sandbox.get("fresh_temp_root") is not True
        or sandbox.get("brokered_filesystem") is not True
        or sandbox.get("network_default_denied") is not True
        or not _sandbox_required_probes_pass(sandbox),
        failures,
        "sandbox.required_probes_pass",
    )

    gov = governor.get("governor", {})
    artifact = governor.get("artifact", {})
    _fail_if(
        governor.get("gpu_preflight_called") is not True
        or governor.get("real_gpu_training") is not True
        or governor.get("mode") != "governed-gpu-train-eval"
        or gov.get("vram_fraction", 99) > 0.85
        or gov.get("margin_gb", 0) < 1.5
        or gov.get("throttle_s", -1) < 0,
        failures,
        "governor.real_gpu_training",
    )
    hashes = [artifact.get("checkpoint_hash"), artifact.get("adapter_hash")]
    _fail_if(
        not any(isinstance(value, str) and value.startswith("sha256:") for value in hashes),
        failures,
        "governor.hashable_artifact",
    )
    _fail_if(
        not _artifact_hash_matches(artifact),
        failures,
        "assimilation.durable_artifact",
    )

    state_replay = _load_receipt_path(state_substrate.get("receipts", {}).get("replay"))
    state_rollback = _load_receipt_path(state_substrate.get("receipts", {}).get("rollback"))
    _fail_if(
        state_substrate.get("ticket") != "EMBER-STATE-COMMIT"
        or state_substrate.get("promotion") != "accepted"
        or state_substrate.get("gc_eligible") is not False
        or not isinstance(state_substrate.get("diff", {}).get("sha256"), str)
        or not state_substrate.get("diff", {}).get("sha256", "").startswith("sha256:")
        or state_replay.get("deterministic") is not True
        or state_replay.get("diff_sha256") != state_substrate.get("diff", {}).get("sha256")
        or state_replay.get("replayed_state_hash") != state_substrate.get("post_candidate_state_hash")
        or state_rollback.get("restored_state_hash") != state_rollback.get("pre_cycle_state_hash")
        or state_rollback.get("pre_cycle_state_hash") != state_substrate.get("pre_cycle_state_hash"),
        failures,
        "state_substrate.local_commit_replayable",
    )

    official_benchmark_ready = bool(
        benchmark.get("fixture_only") is False
        and benchmark.get("real_mle_tasks_executed") is True
        and benchmark.get("frozen_before_execution") is True
        and benchmark.get("benchmark_subset", {}).get("task_ids") == MLE_LOW_MICRO_TASK_IDS
        and benchmark.get("benchmark_subset", {}).get("official_leaderboard_comparable") is False
    )
    official_per_task_ready = _valid_per_task_benchmark_results(benchmark)
    external_benchmark_replacement_ready = _benchmark_external_replacement_ready(benchmark)
    research_benchmark = _research_loop_replacement(benchmark)
    research_benchmark_ready = research_benchmark.get("ready") is True
    _fail_if(
        not (official_benchmark_ready or external_benchmark_replacement_ready or research_benchmark_ready),
        failures,
        "benchmark.real_mle_tasks_executed",
    )
    _fail_if(
        not (official_per_task_ready or external_benchmark_replacement_ready or research_benchmark_ready),
        failures,
        "benchmark.per_task_scores_present",
    )
    score = benchmark.get("score", {})
    _fail_if(
        not isinstance(score.get("mean_normalized_improvement"), (int, float))
        or score.get("mean_normalized_improvement") <= 0
        or (benchmark.get("external_benchmark_delta_claimed", True) is False and not research_benchmark_ready),
        failures,
        "benchmark.external_delta_positive",
    )

    arms = wheel.get("arms", [])
    arm_rows = arms if isinstance(arms, list) else []
    arm_budgets = {arm.get("budget_seconds") for arm in arm_rows if isinstance(arm, dict)}
    arm_contract_status = {arm.get("id"): arm.get("arm_contract_ok") for arm in arm_rows if isinstance(arm, dict)}
    external_wheel_replacement_ready = _wheel_external_replacement_ready(wheel)
    research_wheel = _research_loop_replacement(wheel)
    research_wheel_ready = research_wheel.get("ready") is True
    _fail_if(
        not (
            (
                wheel.get("fixture_only") is False
                and wheel.get("real_mle_tasks_executed") is True
                and wheel.get("equal_budget") is True
                and arm_budgets == {3600}
            )
            or external_wheel_replacement_ready
            or research_wheel_ready
        ),
        failures,
        "wheel.real_equal_budget_run",
    )
    _fail_if(
        arm_contract_status != {"A": True, "B": True, "C": True} and not research_wheel_ready,
        failures,
        "wheel.arm_contracts_valid",
    )
    improvements = {arm.get("id"): arm.get("normalized_improvement") for arm in arm_rows if isinstance(arm, dict)}
    _fail_if(
        (
            wheel.get("ordering") != "C>B>A"
            or not (
                isinstance(improvements.get("A"), (int, float))
                and isinstance(improvements.get("B"), (int, float))
                and isinstance(improvements.get("C"), (int, float))
                and improvements["C"] > improvements["B"] > improvements["A"]
            )
        )
        and not research_wheel_ready,
        failures,
        "wheel.ordering_c_gt_b_gt_a",
    )

    recursion = _recursion_receipts_ready(cycle_path, cycle)
    recursion_required = official_benchmark_ready or external_benchmark_replacement_ready or research_benchmark_ready
    if recursion_required:
        _fail_if(
            recursion["predictive_rollout"]["ready"] is not True,
            failures,
            "recursion.predictive_rollout",
        )
        _fail_if(
            recursion["prospective_meta_operator"]["ready"] is not True,
            failures,
            "recursion.prospective_meta_operator",
        )
        _fail_if(
            recursion["context_compaction"]["ready"] is not True,
            failures,
            "recursion.context_compaction",
        )

    growth_status = _growth_receipt_status(growth_receipt_path, cycle_path)
    growth_failures: list[str] = []
    if growth_status["ready"] is not True:
        growth_failures.extend(growth_status["errors"])
        if wheel.get("growth_gate", {}).get("blocked_until_repeated_positive_cycles") != 0:
            growth_failures.append("growth.repeated_positive_cycles")
        if wheel.get("growth_gate", {}).get("next_cycle_ceiling_hours", 99) > 24:
            growth_failures.append("growth.next_cycle_ceiling")

    benchmark_mode = "official_mle" if official_benchmark_ready else (
        "external_trained_heldout_replacement" if external_benchmark_replacement_ready else (
            "research_journal_replacement" if research_benchmark_ready else "not_ready"
        )
    )
    wheel_mode = "official_mle" if wheel.get("real_mle_tasks_executed") is True else (
        "external_trained_heldout_replacement" if external_wheel_replacement_ready else (
            "research_journal_replacement" if research_wheel_ready else "not_ready"
        )
    )

    return {
        "ticket": "EMBER-MVP-READINESS",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle.get("cycle_id"),
        "cycle_receipt_path": str(cycle_path),
        "requirements": MVP_REQUIREMENTS,
        "failed_requirements": failures,
        "benchmark_public_test_proxy": _benchmark_public_test_proxy(benchmark),
        "benchmark_frozen_heldout": _benchmark_frozen_heldout(benchmark),
        "benchmark_external_heldout": _benchmark_external_heldout(benchmark),
        "benchmark_research_loop": research_benchmark,
        "benchmark_mode": benchmark_mode,
        "wheel_public_test_proxy": _wheel_public_test_proxy(wheel),
        "wheel_frozen_heldout": _wheel_frozen_heldout(wheel),
        "wheel_research_loop": research_wheel,
        "wheel_mode": wheel_mode,
        "recursion_layer": recursion,
        "verdict": "MVP_READY" if not failures else "NOT_READY",
        "growth_receipt": growth_status,
        "growth_failures": growth_failures,
        "growth_verdict": "GROWTH_READY" if not growth_failures else "GROWTH_BLOCKED",
        "linked_receipts": {
            "sandbox": sandbox.get("_path"),
            "gpu_governor": governor.get("_path"),
            "state_substrate": state_substrate.get("_path"),
            "observation": _receipt_path(cycle_path, cycle.get("receipts", {}).get("observation", "")).as_posix()
            if cycle.get("receipts", {}).get("observation")
            else None,
            "benchmark": benchmark.get("_path"),
            "wheel": wheel.get("_path"),
        },
    }


def write_readiness_receipt(cycle_path: Path, out_path: Path, growth_receipt_path: Path | None = None) -> dict[str, Any]:
    report = evaluate_cycle_receipt(cycle_path, growth_receipt_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), report)
    return report


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cycle-receipt", help="top-level cycle receipt to evaluate")
    ap.add_argument("--growth-receipt", help="optional repeated-cycle growth receipt")
    ap.add_argument("--out", help="optional path for readiness receipt")
    args = ap.parse_args()

    if args.selftest:
        import ember_mvp_readiness_selftest

        return ember_mvp_readiness_selftest.main()

    if not args.cycle_receipt:
        ap.print_help()
        return 1

    growth_receipt_path = Path(args.growth_receipt) if args.growth_receipt else None
    if args.out:
        report = write_readiness_receipt(Path(args.cycle_receipt), Path(args.out), growth_receipt_path)
    else:
        report = evaluate_cycle_receipt(Path(args.cycle_receipt), growth_receipt_path)
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "MVP_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
