#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the Ember MVP closed-cycle receipt spine.

This is intentionally narrow: it proves the local schema/linkage boundary
before the Windows runner, real GPU governor, or MLE-bench harness are wired.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import ember_mle_micro_harness as mle
import ember_mvp_cycle as mvp


def _write_external_receipt(path: Path, receipt: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _write_official_config(root: Path, task_id: str) -> None:
    task_root = root / "mlebench" / "competitions" / task_id
    task_root.mkdir(parents=True, exist_ok=True)
    (task_root / "config.yaml").write_text(
        f"id: {task_id}\n"
        "dataset:\n"
        f"  answers: {task_id}/prepared/private/test.csv\n"
        f"  sample_submission: {task_id}/prepared/public/sample_submission.csv\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_prepared_data(data_root: Path, task_id: str) -> None:
    private = data_root / task_id / "prepared" / "private"
    public = data_root / task_id / "prepared" / "public"
    private.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    (private / "test.csv").write_text("id,target\n1,0\n", encoding="utf-8", newline="\n")
    (public / "sample_submission.csv").write_text("id,target\n1,0\n", encoding="utf-8", newline="\n")


def _write_submission(submission_root: Path, task_id: str) -> None:
    path = submission_root / task_id / "submission.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("id,target\n1,0\n", encoding="utf-8", newline="\n")


def _score_factory(score: float):
    def factory(task_id: str, default_command: list[str]) -> list[str]:
        return [
            sys.executable,
            "-c",
            (
                "import json, sys; "
                "print(json.dumps({'competition_id': sys.argv[1], "
                f"'score': {score}, 'valid_submission': True, "
                "'is_lower_better': False}))"
            ),
            task_id,
        ]

    return factory


def test_cycle_spine_acceptance() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted")

        assert result.cycle["cycle_id"] == result.observation["cycle_id"]
        assert result.latent_branch["cycle_id"] == result.cycle["cycle_id"]
        assert result.state_commit["cycle_id"] == result.cycle["cycle_id"]
        assert result.state_commit["promotion"] == "accepted"
        assert result.state_commit["gc_enggible"] is False
        assert result.rollback["restored_state_hash"] == result.rollback["pre_cycle_state_hash"]
        assert result.cycle["benchmark_subset"]["official_leaderboard_comparable"] is False
        assert result.cycle["evidence"]["sandbox"]["verdict"] == "pass"
        assert result.cycle["hypothesis"]["text"]

        mvp.validate_cycle_bundle(
            result.observation,
            result.latent_branch,
            result.state_commit,
            result.cycle,
        )


def test_rejected_branch_requires_replay_and_rollback_for_gc() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="rejected")

        assert result.state_commit["promotion"] == "rejected"
        assert result.state_commit["gc_enggible"] is True
        assert result.replay["deterministic"] is True
        assert result.rollback["restored_state_hash"] == result.rollback["pre_cycle_state_hash"]


def test_promotion_without_required_receipts_is_invalid() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted")
        broken = dict(result.state_commit)
        broken["receipts"] = dict(broken["receipts"])
        del broken["receipts"]["governor"]

        try:
            mvp.validate_cycle_bundle(
                result.observation,
                result.latent_branch,
                broken,
                result.cycle,
            )
        except mvp.CycleValidationError as exc:
            assert "missing state commit receipt: governor" in str(exc)
        else:
            raise AssertionError("accepted promotion without governor receipt must fail")


def test_fixture_cycle_can_bind_windows_sandbox_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted", use_windows_sandbox=True)

        assert result.sandbox["mode"] == "windows-native-probe-battery"
        assert result.sandbox["windows_native_runner"] is True
        assert result.sandbox["summary"]["pass"] == result.sandbox["summary"]["total"]
        assert result.cycle["evidence"]["sandbox"]["mode"] == "windows-native-probe-battery"
        assert result.cycle["evidence"]["sandbox"]["verdict"] == "pass"


def test_fixture_cycle_can_bind_production_sandbox_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted", use_production_sandbox=True)

        assert result.sandbox["ticket"] == "EMBER-MVP-SANDBOX-PRODUCTION"
        assert result.sandbox["mode"] == "windows-native-production-candidate-runner"
        assert result.sandbox["verdict"] == "pass"
        assert result.sandbox["fresh_temp_root"] is True
        assert result.sandbox["brokered_filesystem"] is True
        assert result.sandbox["network_default_denied"] is True
        assert result.cycle["evidence"]["sandbox"]["mode"] == "windows-native-production-candidate-runner"


def test_fixture_cycle_can_bind_benchmark_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted", use_benchmark_fixture=True)

        assert result.benchmark["ticket"] == "EMBER-MLE-MICRO-FIXTURE"
        assert result.benchmark["fixture_only"] is True
        assert result.benchmark["real_mle_tasks_executed"] is False
        assert result.cycle["receipts"]["benchmark"] == "receipts/benchmark/cycle-20260617T000000Z-0001.json"
        assert result.cycle["evidence"]["benchmark"]["mode"] == "tiny-fixture-preflight"
        assert result.cycle["score"]["baseline_score"] == 0.5
        assert result.cycle["score"]["candidate_score"] == 0.75
        assert result.cycle["score"]["mean_normalized_improvement"] == 0.5


def test_fixture_cycle_can_bind_governor_artifact_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted", use_governor_binding=True)

        assert result.governor["ticket"] == "EMBER-GOVERNOR-BINDING-FIXTURE"
        assert result.governor["cycle_id"] == result.cycle["cycle_id"]
        assert result.governor["mode"] == "cpu-fixture-no-gpu-preflight"
        assert result.governor["gpu_preflight_called"] is False
        assert result.governor["artifact"]["checkpoint_hash"].startswith("sha256:")
        assert result.cycle["evidence"]["governor"]["mode"] == "cpu-fixture-no-gpu-preflight"
        assert result.cycle["evidence"]["governor"]["checkpoint_hash"] == result.governor["artifact"]["checkpoint_hash"]


def test_fixture_cycle_can_bind_real_governed_gpu_receipt_when_cuda_available() -> None:
    try:
        import torch
    except Exception:
        return
    if not torch.cuda.is_available():
        return

    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted", use_real_governor=True)

        assert result.governor["ticket"] == "EMBER-GOVERNOR-REAL-RUN"
        assert result.governor["mode"] == "governed-gpu-train-eval"
        assert result.governor["gpu_preflight_called"] is True
        assert result.governor["real_gpu_training"] is True
        assert result.governor["artifact"]["checkpoint_hash"].startswith("sha256:")
        assert result.cycle["evidence"]["governor"]["mode"] == "governed-gpu-train-eval"
        assert result.cycle["evidence"]["governor"]["real_gpu_training"] is True


def test_fixture_cycle_can_bind_equal_budget_wheel_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted", use_wheel_fixture=True)

        assert result.wheel is not None
        assert result.wheel["ticket"] == "EMBER-WHEEL-FIXTURE"
        assert result.wheel["equal_budget"] is True
        assert result.wheel["ordering"] == "C>B>A"
        assert result.wheel["growth_gate"]["growth_allowed"] is False
        assert result.cycle["receipts"]["wheel"] == "receipts/wheel/cycle-20260617T000000Z-0001.json"
        assert result.cycle["evidence"]["wheel"]["equal_budget"] is True
        assert result.cycle["evidence"]["wheel"]["ordering"] == "C>B>A"
        assert result.cycle["evidence"]["wheel"]["growth_allowed"] is False


def test_fixture_cycle_can_bind_local_state_substrate_receipts() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        result = mvp.run_fixture_cycle(root, promotion="accepted", use_state_substrate=True)

        assert result.state_substrate is not None
        assert result.state_substrate["commit"]["ticket"] == "EMBER-STATE-COMMIT"
        assert result.state_substrate["commit"]["promotion"] == "accepted"
        assert result.state_substrate["replay"]["deterministic"] is True
        assert result.state_substrate["rollback"]["restored_state_hash"] == (
            result.state_substrate["rollback"]["pre_cycle_state_hash"]
        )
        assert result.cycle["receipts"]["state_substrate"] == (
            "state-substrate/receipts/commits/statecommit-20260617T000000Z-0001.json"
        )
        assert result.cycle["receipts"]["replay"] == (
            "state-substrate/receipts/replay/statecommit-20260617T000000Z-0001.json"
        )
        assert result.cycle["receipts"]["rollback"] == (
            "state-substrate/receipts/rollback/statecommit-20260617T000000Z-0001.json"
        )
        assert result.cycle["evidence"]["state_substrate"]["local_inspectable"] is True
        assert result.cycle["evidence"]["state_substrate"]["replayable_from_commit"] is True
        assert result.cycle["evidence"]["state_substrate"]["rollback_restored"] is True


def test_fixture_cycle_can_bind_external_benchmark_and_wheel_receipts() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        benchmark_path = _write_external_receipt(
            root / "external" / "benchmark.json",
            {
                "ticket": "EMBER-MLE-MICRO-REAL-RUN",
                "ts": "20260617T000000Z",
                "cycle_id": "external-cycle",
                "fixture_only": False,
                "real_mle_tasks_executed": False,
                "benchmark_subset": {
                    "id": "mle-low-micro-v0",
                    "task_ids": mvp.MICRO_TASK_IDS,
                    "official_leaderboard_comparable": False,
                },
                "score": {
                    "baseline_score": None,
                    "candidate_score": None,
                    "mean_normalized_improvement": None,
                },
                "verdict": "BLOCKED",
            },
        )
        wheel_path = _write_external_receipt(
            root / "external" / "wheel.json",
            {
                "ticket": "EMBER-WHEEL-REAL-RUN",
                "ts": "20260617T000000Z",
                "cycle_id": "external-cycle",
                "fixture_only": False,
                "real_mle_tasks_executed": False,
                "equal_budget": True,
                "ordering": "not-C>B>A",
                "blocked_reason": "benchmark_receipts_not_real",
                "blocked_arms": ["A", "B", "C"],
                "benchmark_subset": {
                    "id": "mle-low-micro-v0",
                    "task_ids": mvp.MICRO_TASK_IDS,
                    "official_leaderboard_comparable": False,
                },
                "growth_gate": {
                    "growth_allowed": False,
                    "blocked_until_repeated_positive_cycles": 3,
                    "next_cycle_ceiling_hours": 24,
                },
                "verdict": "BLOCKED",
            },
        )

        result = mvp.run_fixture_cycle(
            root / "cycle",
            promotion="accepted",
            external_benchmark_receipt=benchmark_path,
            external_wheel_receipt=wheel_path,
        )

        assert result.benchmark["ticket"] == "EMBER-MLE-MICRO-REAL-RUN"
        assert result.benchmark["real_mle_tasks_executed"] is False
        assert result.wheel is not None
        assert result.wheel["ticket"] == "EMBER-WHEEL-REAL-RUN"
        assert result.cycle["receipts"]["benchmark"] == "receipts/benchmark/cycle-20260617T000000Z-0001.json"
        assert result.cycle["receipts"]["wheel"] == "receipts/wheel/cycle-20260617T000000Z-0001.json"
        assert result.cycle["evidence"]["benchmark"]["real_mle_tasks_executed"] is False
        assert result.cycle["evidence"]["wheel"]["blocked_reason"] == "benchmark_receipts_not_real"


def test_external_benchmark_without_fixture_field_summarizes_non_fixture() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        benchmark_path = _write_external_receipt(
            root / "external" / "benchmark.json",
            {
                "ticket": "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
                "ts": "20260618T000000Z",
                "cycle_id": "external-cycle",
                "lane": "kaggle_dataset_external_heldout",
                "real_mle_tasks_executed": False,
                "heldout_delta_ready": True,
                "benchmark_delta_claimed": True,
                "external_benchmark_delta_claimed": True,
                "benchmark_subset": {
                    "id": "kaggle-dataset-external-heldout-v0",
                    "task_ids": ["emotion-heldout"],
                    "official_leaderboard_comparable": False,
                },
                "score": {
                    "baseline_score": 0.4,
                    "candidate_score": 0.9,
                    "mean_normalized_improvement": 0.833333,
                },
                "verdict": "EXTERNAL_HELDOUT_DELTA_RECEIPTED",
            },
        )

        result = mvp.run_fixture_cycle(
            root / "cycle",
            promotion="accepted",
            external_benchmark_receipt=benchmark_path,
        )

        assert result.benchmark["fixture_only"] is False
        assert result.cycle["evidence"]["benchmark"]["fixture_only"] is False


def test_fixture_cycle_can_execute_official_abc_wheel_runner() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mvp-spine-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in mle.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_prepared_data(data_root, task_id)
            _write_submission(submission_root, task_id)

        result = mvp.run_fixture_cycle(
            root / "cycle",
            promotion="accepted",
            official_wheel_runner={
                "source_root": source_root,
                "data_root": data_root,
                "submission_root": submission_root,
                "command_factories": {
                    "A": _score_factory(0.1),
                    "B": _score_factory(0.2),
                    "C": _score_factory(0.3),
                },
            },
        )

        assert result.benchmark["ticket"] == "EMBER-MLE-MICRO-OFFICIAL-GRADE-RUN"
        assert result.benchmark["wheel_arm"]["id"] == "C"
        assert result.benchmark["real_mle_tasks_executed"] is True
        assert result.wheel is not None
        assert result.wheel["ticket"] == "EMBER-WHEEL-REAL-RUN"
        assert result.wheel["verdict"] == "PASS"
        assert result.cycle["score"]["mean_normalized_improvement"] == 0.3
        assert result.cycle["receipts"]["wheel_runner"] == (
            "official-wheel-runner/receipts/wheel-runner/"
            + Path(result.cycle["receipts"]["wheel_runner"]).name
        )
        assert result.cycle["evidence"]["wheel_runner"]["verdict"] == "PASS"
        assert result.cycle["evidence"]["wheel"]["ordering"] == "C>B>A"


def main() -> int:
    tests = [
        test_cycle_spine_acceptance,
        test_rejected_branch_requires_replay_and_rollback_for_gc,
        test_promotion_without_required_receipts_is_invalid,
        test_fixture_cycle_can_bind_windows_sandbox_receipt,
        test_fixture_cycle_can_bind_production_sandbox_receipt,
        test_fixture_cycle_can_bind_benchmark_receipt,
        test_fixture_cycle_can_bind_governor_artifact_receipt,
        test_fixture_cycle_can_bind_real_governed_gpu_receipt_when_cuda_available,
        test_fixture_cycle_can_bind_equal_budget_wheel_receipt,
        test_fixture_cycle_can_bind_local_state_substrate_receipts,
        test_fixture_cycle_can_bind_external_benchmark_and_wheel_receipts,
        test_external_benchmark_without_fixture_field_summarizes_non_fixture,
        test_fixture_cycle_can_execute_official_abc_wheel_runner,
    ]
    for test in tests:
        test()
    print("EMBER_MVP_CYCLE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
