#!/usr/bin/env python3
"""Selftest for the Ember MVP MLE-bench Low micro-subset harness."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import ember_mle_micro_harness as harness


def test_freeze_manifest_preserves_mle_low_micro_subset() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
        root = Path(td)
        manifest = harness.freeze_micro_subset(root)

        assert manifest["id"] == "mle-low-micro-v0"
        assert manifest["official_leaderboard_comparable"] is False
        assert manifest["real_mle_tasks_executed"] is False
        assert manifest["fixture_task_id"] == "fixture-tiny-mle-score-v0"
        assert manifest["budget"]["wall_seconds"] == 3600
        assert manifest["budget"]["train_seconds"] == 3600
        assert manifest["budget"]["eval_seconds"] == 3600
        assert manifest["seeds"] == [123456]
        assert manifest["task_ids"] == harness.MLE_LOW_MICRO_TASK_IDS
        assert set(manifest["scoring_commands"]) == set(harness.MLE_LOW_MICRO_TASK_IDS)
        assert set(manifest["baseline_scripts"]) == set(harness.MLE_LOW_MICRO_TASK_IDS)
        assert manifest["freeze_manifest_sha256"].startswith("sha256:")


def test_tiny_fixture_scores_mean_normalized_improvement() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
        root = Path(td)
        receipt = harness.run_tiny_fixture(root)

        assert receipt["ticket"] == "EMBER-MLE-MICRO-FIXTURE"
        assert receipt["benchmark_subset"]["id"] == "mle-low-micro-v0"
        assert receipt["benchmark_subset"]["official_leaderboard_comparable"] is False
        assert receipt["fixture_only"] is True
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["frozen_before_execution"] is True
        assert receipt["score"]["baseline_score"] == 0.5
        assert receipt["score"]["candidate_score"] == 0.75
        assert receipt["score"]["mean_normalized_improvement"] == 0.5
        assert receipt["verdict"] == "fixture-pass"
        assert Path(receipt["receipt_path"]).exists()

        loaded = harness.load_receipt(Path(receipt["receipt_path"]))
        harness.validate_micro_receipt(loaded)


def _write_ready_task(root: Path, task_id: str) -> None:
    task_root = root / task_id
    task_root.mkdir(parents=True, exist_ok=True)
    (task_root / "dataset").mkdir(exist_ok=True)
    (task_root / "score.py").write_text(
        "import json\n"
        "print(json.dumps({'baseline_score': 0.5, 'candidate_score': 0.75, 'max_score': 1.0}))\n",
        encoding="utf-8",
        newline="\n",
    )
    baseline = task_root / "baselines" / "starter.py"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("print('baseline')\n", encoding="utf-8", newline="\n")


def _write_candidate(root: Path, task_id: str) -> None:
    candidate = root / task_id / "candidate.py"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("print('candidate')\n", encoding="utf-8", newline="\n")


def test_hydration_preflight_reports_ready_local_assets() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
        root = Path(td)
        mle_root = root / "mle-low"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_ready_task(mle_root, task_id)

        receipt = harness.run_hydration_preflight(root / "out", mle_root, cycle_id="cycle-test")

        assert receipt["ticket"] == "EMBER-MLE-MICRO-HYDRATION-PREFLIGHT"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["fixture_only"] is False
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["frozen_before_execution"] is True
        assert receipt["hydration_ready"] is True
        assert receipt["missing_assets"] == []
        assert receipt["verdict"] == "READY"
        harness.validate_hydration_preflight_receipt(receipt)


def test_hydration_preflight_blocks_missing_local_assets() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
        root = Path(td)
        mle_root = root / "mle-low"
        _write_ready_task(mle_root, harness.MLE_LOW_MICRO_TASK_IDS[0])

        receipt = harness.run_hydration_preflight(root / "out", mle_root, cycle_id="cycle-test")

        assert receipt["hydration_ready"] is False
        assert receipt["verdict"] == "BLOCKED"
        assert receipt["real_mle_tasks_executed"] is False
        assert any(item["task_id"] == harness.MLE_LOW_MICRO_TASK_IDS[1] for item in receipt["missing_assets"])
        harness.validate_hydration_preflight_receipt(receipt)


def _write_official_source_task(root: Path, task_id: str) -> None:
    task_root = root / "mlebench" / "competitions" / task_id
    task_root.mkdir(parents=True, exist_ok=True)
    for name in ("grade.py", "config.yaml", "checksums.yaml"):
        (task_root / name).write_text(f"# {task_id} {name}\n", encoding="utf-8", newline="\n")


def test_official_source_preflight_reports_ready_source_without_execution() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-source-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        low_split = source_root / "experiments" / "splits" / "low.txt"
        low_split.parent.mkdir(parents=True, exist_ok=True)
        low_split.write_text("\n".join(harness.MLE_LOW_MICRO_TASK_IDS) + "\n", encoding="utf-8", newline="\n")
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_source_task(source_root, task_id)

        receipt = harness.run_official_source_preflight(root / "out", source_root, cycle_id="cycle-test")

        assert receipt["ticket"] == "EMBER-MLE-MICRO-SOURCE-PREFLIGHT"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["source_ready"] is True
        assert receipt["hydration_ready"] is False
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["verdict"] == "SOURCE_READY"
        assert receipt["missing_source_assets"] == []
        harness.validate_official_source_preflight_receipt(receipt)


def _write_official_config(root: Path, task_id: str) -> None:
    task_root = root / "mlebench" / "competitions" / task_id
    task_root.mkdir(parents=True, exist_ok=True)
    (task_root / "config.yaml").write_text(
        f"id: {task_id}\n"
        "dataset:\n"
        f"  answers: {task_id}/prepared/private/test.csv\n"
        f"  gold_submission: {task_id}/prepared/private/gold_submission.csv\n"
        f"  sample_submission: {task_id}/prepared/public/sample_submission.csv\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_official_config_without_gold(root: Path, task_id: str) -> None:
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
    (private / "gold_submission.csv").write_text("id,target\n1,0\n", encoding="utf-8", newline="\n")
    (public / "sample_submission.csv").write_text("id,target\n1,0\n", encoding="utf-8", newline="\n")


def _write_submission(submission_root: Path, task_id: str) -> None:
    path = submission_root / task_id / "submission.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("id,target\n1,0\n", encoding="utf-8", newline="\n")


def test_official_grading_preflight_reports_ready_commands_without_execution() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-grading-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_prepared_data(data_root, task_id)
            _write_submission(submission_root, task_id)

        receipt = harness.run_official_grading_preflight(
            root / "out",
            source_root,
            data_root,
            submission_root,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-MLE-MICRO-OFFICIAL-GRADING-PREFLIGHT"
        assert receipt["prepared_data_ready"] is True
        assert receipt["candidate_submissions_ready"] is True
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["verdict"] == "READY_TO_GRADE"
        assert len(receipt["official_grade_commands"]) == len(harness.MLE_LOW_MICRO_TASK_IDS)
        assert all("grade-sample" in " ".join(row["command"]) for row in receipt["official_grade_commands"])
        harness.validate_official_grading_preflight_receipt(receipt)


def test_official_grading_preflight_blocks_missing_prepared_data() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-grading-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_submission(submission_root, task_id)

        receipt = harness.run_official_grading_preflight(root / "out", source_root, data_root, submission_root)

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["prepared_data_ready"] is False
        assert receipt["candidate_submissions_ready"] is True
        assert receipt["missing_prepared_assets"]
        harness.validate_official_grading_preflight_receipt(receipt)


def test_official_grading_preflight_does_not_require_blank_gold_submission() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-grading-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config_without_gold(source_root, task_id)
            _write_prepared_data(data_root, task_id)
            _write_submission(submission_root, task_id)

        receipt = harness.run_official_grading_preflight(root / "out", source_root, data_root, submission_root)

        assert receipt["prepared_data_ready"] is True
        assert receipt["candidate_submissions_ready"] is True
        assert receipt["missing_prepared_assets"] == []
        assert receipt["verdict"] == "READY_TO_GRADE"
        harness.validate_official_grading_preflight_receipt(receipt)


def test_official_grade_execution_runs_ready_grade_commands_and_scores_delta() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-grade-run-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_prepared_data(data_root, task_id)
            _write_submission(submission_root, task_id)

        def command_factory(task_id: str, default_command: list[str]) -> list[str]:
            return [
                sys.executable,
                "-c",
                (
                    "import json, sys; "
                    "print(json.dumps({'competition_id': sys.argv[1], 'score': 0.75, "
                    "'valid_submission': True, 'is_lower_better': False}))"
                ),
                task_id,
            ]

        receipt = harness.run_official_grade_execution(
            root / "out",
            source_root,
            data_root,
            submission_root,
            cycle_id="cycle-test",
            wheel_arm="A",
            command_factory=command_factory,
        )

        assert receipt["ticket"] == "EMBER-MLE-MICRO-OFFICIAL-GRADE-RUN"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["preflight"]["verdict"] == "READY_TO_GRADE"
        assert receipt["real_mle_tasks_executed"] is True
        assert receipt["wheel_arm"]["id"] == "A"
        assert receipt["wheel_arm"]["uses_dream_loop"] is False
        assert receipt["wheel_arm"]["uses_state_commit"] is False
        assert len(receipt["task_results"]) == len(harness.MLE_LOW_MICRO_TASK_IDS)
        assert receipt["score"]["baseline_score"] == 0.0
        assert receipt["score"]["candidate_score"] == 0.75
        assert receipt["score"]["mean_normalized_improvement"] == 0.75
        assert receipt["verdict"] == "PASS"
        harness.validate_official_grade_execution_receipt(receipt)


def test_official_grade_execution_can_auto_materialize_sample_submissions() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-grade-run-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_prepared_data(data_root, task_id)

        def command_factory(task_id: str, default_command: list[str]) -> list[str]:
            return [
                sys.executable,
                "-c",
                (
                    "import json, pathlib, sys; "
                    "assert pathlib.Path(sys.argv[2]).is_file(); "
                    "print(json.dumps({'competition_id': sys.argv[1], 'score': 0.25, "
                    "'valid_submission': True, 'is_lower_better': False}))"
                ),
                task_id,
                str(submission_root / task_id / "submission.csv"),
            ]

        receipt = harness.run_official_grade_execution(
            root / "out",
            source_root,
            data_root,
            submission_root,
            cycle_id="cycle-test",
            wheel_arm="B",
            command_factory=command_factory,
            auto_sample_submission=True,
        )

        assert receipt["verdict"] == "PASS"
        assert receipt["preflight"]["verdict"] == "READY_TO_GRADE"
        assert receipt["preflight"]["auto_sample_submission"] is True
        assert receipt["preflight"]["bootstrap_receipt_path"]
        assert receipt["missing_candidate_submissions"] == []
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            submission_path = submission_root / task_id / "submission.csv"
            assert submission_path.is_file()
        harness.validate_official_grade_execution_receipt(receipt)


def test_official_grade_execution_blocks_when_preflight_not_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-grade-run-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_submission(submission_root, task_id)

        receipt = harness.run_official_grade_execution(
            root / "out",
            source_root,
            data_root,
            submission_root,
            wheel_arm="C",
        )

        assert receipt["ticket"] == "EMBER-MLE-MICRO-OFFICIAL-GRADE-RUN"
        assert receipt["verdict"] == "BLOCKED"
        assert receipt["blocked_reason"] == "official_grading_preflight_failed"
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["wheel_arm"]["id"] == "C"
        assert receipt["wheel_arm"]["uses_latent_branch"] is True
        assert receipt["wheel_arm"]["uses_replay"] is True
        assert receipt["task_results"] == []
        assert receipt["preflight"]["verdict"] == "BLOCKED"
        harness.validate_official_grade_execution_receipt(receipt)


def test_sample_submission_bootstrap_copies_prepared_samples_to_submission_root() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-bootstrap-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_prepared_data(data_root, task_id)

        receipt = harness.run_sample_submission_bootstrap(
            root / "out",
            source_root,
            data_root,
            submission_root,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-MLE-MICRO-SAMPLE-SUBMISSION-BOOTSTRAP"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["prepared_data_ready"] is True
        assert receipt["candidate_submissions_ready"] is True
        assert receipt["copied_count"] == len(harness.MLE_LOW_MICRO_TASK_IDS)
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["verdict"] == "BOOTSTRAPPED"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            sample_path = data_root / task_id / "prepared" / "public" / "sample_submission.csv"
            submission_path = submission_root / task_id / "submission.csv"
            assert submission_path.read_text(encoding="utf-8") == sample_path.read_text(encoding="utf-8")
        harness.validate_sample_submission_bootstrap_receipt(receipt)


def test_sample_submission_bootstrap_blocks_missing_samples() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-bootstrap-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)

        receipt = harness.run_sample_submission_bootstrap(root / "out", source_root, data_root, submission_root)

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["prepared_data_ready"] is False
        assert receipt["candidate_submissions_ready"] is False
        assert receipt["copied_count"] == 0
        assert receipt["missing_prepared_assets"]
        assert receipt["missing_sample_submissions"]
        harness.validate_sample_submission_bootstrap_receipt(receipt)


def test_raw_data_audit_reports_missing_prepare_inputs() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-raw-audit-") as td:
        root = Path(td)
        data_root = root / "data"
        receipt = harness.run_raw_data_audit(root / "out", data_root, cycle_id="cycle-test")

        assert receipt["ticket"] == "EMBER-MLE-MICRO-RAW-DATA-AUDIT"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["raw_data_ready"] is False
        assert receipt["verdict"] == "BLOCKED"
        assert len(receipt["task_assets"]) == len(harness.MLE_LOW_MICRO_TASK_IDS)
        assert all(row["missing_raw_assets"] for row in receipt["task_assets"])
        assert any(
            row["task_id"] == "detecting-insults-in-social-commentary"
            and "raw/test_with_solutions.csv" in row["missing_raw_assets"]
            for row in receipt["task_assets"]
        )
        harness.validate_raw_data_audit_receipt(receipt)


def test_raw_data_audit_passes_when_prepare_inputs_exist() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-raw-audit-") as td:
        root = Path(td)
        data_root = root / "data"
        for task_id, required in harness.RAW_PREPARE_ASSETS.items():
            for rel_path in required:
                path = data_root / task_id / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8", newline="\n")

        receipt = harness.run_raw_data_audit(root / "out", data_root)

        assert receipt["raw_data_ready"] is True
        assert receipt["verdict"] == "READY"
        assert receipt["missing_raw_assets"] == []
        harness.validate_raw_data_audit_receipt(receipt)


def test_kaggle_auth_preflight_records_credential_shape_without_secret() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-auth-") as td:
        root = Path(td)
        cred = root / "kaggle.json"
        cred.write_text(
            '{"username":"ember-user","key":"secret-value-that-must-not-leak"}\n',
            encoding="utf-8",
            newline="\n",
        )

        receipt = harness.run_kaggle_auth_preflight(root / "out", cred, live_check=False, cycle_id="cycle-test")

        assert receipt["ticket"] == "EMBER-MLE-KAGGLE-AUTH-PREFLIGHT"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["credential_file_present"] is True
        assert receipt["credential_json_parseable"] is True
        assert receipt["username_present"] is True
        assert receipt["key_present"] is True
        assert receipt["key_sha256"].startswith("sha256:")
        assert "secret-value" not in str(receipt)
        assert receipt["live_auth_checked"] is False
        assert receipt["verdict"] == "AUTH_SHAPE_READY"
        harness.validate_kaggle_auth_preflight_receipt(receipt)


def test_kaggle_auth_preflight_records_access_token_surface_without_secret() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-auth-") as td:
        root = Path(td)
        cred = root / "kaggle.json"
        access_token = root / "access_token"
        cred.write_text(
            '{"username":"ember-user","key":"classic-secret-that-must-not-leak"}\n',
            encoding="utf-8",
            newline="\n",
        )
        access_token.write_text("KGAT_secret-value-that-must-not-leak\n", encoding="utf-8", newline="\n")

        receipt = harness.run_kaggle_auth_preflight(
            root / "out",
            cred,
            access_token_path=access_token,
            live_check=False,
            cycle_id="cycle-test",
        )

        assert receipt["access_token_path"] == str(access_token)
        assert receipt["access_token_file_present"] is True
        assert receipt["access_token_shape"] == "KGAT"
        assert receipt["access_token_sha256"].startswith("sha256:")
        assert receipt["legacy_kaggle_client_accepts_access_token"] is False
        assert receipt["legacy_kaggle_client_required_credentials"] == ["username", "key"]
        assert "secret-value" not in str(receipt)
        assert "classic-secret" not in str(receipt)
        assert receipt["verdict"] == "AUTH_SHAPE_READY"
        harness.validate_kaggle_auth_preflight_receipt(receipt)


def test_kaggle_auth_preflight_blocks_malformed_credential_file() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-auth-") as td:
        root = Path(td)
        cred = root / "kaggle.json"
        cred.write_text('{"username":"ember-user"}\n', encoding="utf-8", newline="\n")

        receipt = harness.run_kaggle_auth_preflight(root / "out", cred, live_check=False)

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["credential_file_present"] is True
        assert receipt["username_present"] is True
        assert receipt["key_present"] is False
        assert receipt["blocked_reason"] == "credential_shape_invalid"
        harness.validate_kaggle_auth_preflight_receipt(receipt)


def test_kaggle_auth_preflight_uses_explicit_live_command_and_redacts_error() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-auth-") as td:
        root = Path(td)
        cred = root / "kaggle.json"
        cred.write_text('{"username":"ember-user","key":"secret-value"}\n', encoding="utf-8", newline="\n")
        command = [
            "python",
            "-c",
            "import sys; sys.stderr.write('HTTP 401 Unauthorized secret-value'); sys.exit(1)",
        ]

        receipt = harness.run_kaggle_auth_preflight(
            root / "out",
            cred,
            live_check=True,
            live_auth_command=command,
        )

        assert receipt["live_auth_checked"] is True
        assert receipt["live_auth_status"] == "AUTH_FAILED"
        assert receipt["blocked_reason"] == "kaggle_auth_unauthorized"
        assert "secret-value" not in str(receipt)
        harness.validate_kaggle_auth_preflight_receipt(receipt)


def test_acquisition_status_prefers_local_raw_files_over_missing_auth() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-acquisition-") as td:
        root = Path(td)
        data_root = root / "data"
        for task_id, required in harness.RAW_PREPARE_ASSETS.items():
            for rel_path in required:
                path = data_root / task_id / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8", newline="\n")

        receipt = harness.run_benchmark_acquisition_status(root / "out", data_root, credential_path=None)

        assert receipt["ticket"] == "EMBER-MLE-MICRO-ACQUISITION-STATUS"
        assert receipt["raw_data_ready"] is True
        assert receipt["kaggle_auth_ready"] is False
        assert receipt["selected_route"] == "local_raw_files"
        assert receipt["verdict"] == "READY_TO_PREPARE"
        assert receipt["next_action"] == "run_official_prepare_from_raw"
        harness.validate_benchmark_acquisition_status_receipt(receipt)


def test_acquisition_status_blocks_when_raw_missing_and_live_auth_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-acquisition-") as td:
        root = Path(td)
        data_root = root / "data"
        cred = root / "kaggle.json"
        cred.write_text('{"username":"ember-user","key":"secret-value"}\n', encoding="utf-8", newline="\n")
        command = [
            "python",
            "-c",
            "import sys; sys.stderr.write('HTTP 401 Unauthorized secret-value'); sys.exit(1)",
        ]

        receipt = harness.run_benchmark_acquisition_status(
            root / "out",
            data_root,
            credential_path=cred,
            live_auth=True,
            live_auth_command=command,
            cycle_id="cycle-test",
        )

        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["raw_data_ready"] is False
        assert receipt["kaggle_auth_ready"] is False
        assert receipt["selected_route"] is None
        assert receipt["verdict"] == "BLOCKED"
        assert receipt["blocked_reason"] == "raw_data_missing_and_kaggle_auth_not_ready"
        assert "refresh_kaggle_credentials" in receipt["critical_path"]
        assert "secret-value" not in str(receipt)
        harness.validate_benchmark_acquisition_status_receipt(receipt)


class _FakeKaggleRedirect:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakeKaggleCompetitionClient:
    def __init__(self, urls_by_competition: dict[str, str]) -> None:
        self.urls_by_competition = urls_by_competition
        self.requested_competitions: list[str] = []

    def download_data_files(self, request: object) -> _FakeKaggleRedirect:
        competition_name = getattr(request, "competition_name")
        self.requested_competitions.append(competition_name)
        return _FakeKaggleRedirect(self.urls_by_competition[competition_name])


def test_kaggle_sdk_raw_download_extracts_required_assets_without_secret() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-sdk-download-") as td:
        root = Path(td)
        data_root = root / "data"
        token_path = root / "access_token"
        token_path.write_text("KGAT_secret-value-that-must-not-leak\n", encoding="utf-8", newline="\n")
        zip_path = root / "bundle.zip"
        import zipfile

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("train.csv", "id,text\n1,hello\n")
            zf.writestr("test_with_solutions.csv", "id,label\n1,0\n")

        client = _FakeKaggleCompetitionClient(
            {"detecting-insults-in-social-commentary": zip_path.as_uri()}
        )

        receipt = harness.run_kaggle_sdk_raw_download(
            root / "out",
            data_root,
            token_path=token_path,
            task_ids=["detecting-insults-in-social-commentary"],
            competition_client=client,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-MLE-KAGGLE-SDK-RAW-DOWNLOAD"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["token_file_present"] is True
        assert receipt["token_sha256"].startswith("sha256:")
        assert "secret-value" not in str(receipt)
        assert receipt["downloaded_task_count"] == 1
        assert receipt["raw_data_ready"] is True
        assert receipt["verdict"] == "DOWNLOADED"
        assert client.requested_competitions == ["detecting-insults-in-social-commentary"]
        assert (data_root / "detecting-insults-in-social-commentary" / "raw" / "train.csv").is_file()
        assert (data_root / "detecting-insults-in-social-commentary" / "raw" / "test_with_solutions.csv").is_file()
        assert all(row["sha256"].startswith("sha256:") for row in receipt["extracted_assets"])
        harness.validate_kaggle_sdk_raw_download_receipt(receipt)


def test_kaggle_sdk_raw_download_blocks_missing_token_file() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-sdk-download-") as td:
        root = Path(td)

        receipt = harness.run_kaggle_sdk_raw_download(
            root / "out",
            root / "data",
            token_path=root / "missing_access_token",
            task_ids=["detecting-insults-in-social-commentary"],
        )

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["blocked_reason"] == "token_file_missing"
        assert receipt["raw_data_ready"] is False
        harness.validate_kaggle_sdk_raw_download_receipt(receipt)


class _ForbiddenKaggleCompetitionClient:
    def download_data_files(self, request: object) -> object:
        raise RuntimeError("403 Client Error: Forbidden for url")


def test_kaggle_sdk_raw_download_records_forbidden_without_crashing() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-sdk-download-") as td:
        root = Path(td)
        token_path = root / "access_token"
        token_path.write_text("KGAT_secret-value-that-must-not-leak\n", encoding="utf-8", newline="\n")

        receipt = harness.run_kaggle_sdk_raw_download(
            root / "out",
            root / "data",
            token_path=token_path,
            task_ids=["detecting-insults-in-social-commentary"],
            competition_client=_ForbiddenKaggleCompetitionClient(),
        )

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["blocked_reason"] == "kaggle_download_forbidden"
        assert receipt["raw_data_ready"] is False
        assert "secret-value" not in str(receipt)
        harness.validate_kaggle_sdk_raw_download_receipt(receipt)


def test_kaggle_benchmarks_sdk_probe_blocks_python_below_required_version() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-") as td:
        root = Path(td)
        sdk_root = root / "kaggle-benchmarks"
        sdk_root.mkdir()
        (sdk_root / "pyproject.toml").write_text(
            '[project]\nname = "kaggle_benchmarks"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
            newline="\n",
        )
        (sdk_root / "README.md").write_text(
            "Kaggle Benchmarks supports task file and run files.\n",
            encoding="utf-8",
            newline="\n",
        )

        receipt = harness.run_kaggle_benchmarks_sdk_probe(
            root / "out",
            sdk_root=sdk_root,
            python_version=(3, 10, 12),
            import_check=lambda: False,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-KAGGLE-BENCHMARKS-SDK-PROBE"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["sdk_source_present"] is True
        assert receipt["python_version"] == "3.10.12"
        assert receipt["requires_python"] == ">=3.11"
        assert receipt["python_runtime_ready"] is False
        assert receipt["kaggle_benchmarks_importable"] is False
        assert receipt["task_run_file_execution_ready"] is False
        assert receipt["blocked_reason"] == "python_runtime_below_kaggle_benchmarks_requirement"
        assert receipt["verdict"] == "BLOCKED"
        harness.validate_kaggle_benchmarks_sdk_probe_receipt(receipt)


def test_kaggle_benchmarks_sdk_probe_reports_ready_shape_when_runtime_and_import_exist() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-") as td:
        root = Path(td)
        sdk_root = root / "kaggle-benchmarks"
        sdk_root.mkdir()
        (sdk_root / "pyproject.toml").write_text(
            '[project]\nname = "kaggle_benchmarks"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
            newline="\n",
        )
        (sdk_root / "README.md").write_text(
            "Dataset Evaluation and task file plus run files are supported.\n",
            encoding="utf-8",
            newline="\n",
        )

        receipt = harness.run_kaggle_benchmarks_sdk_probe(
            root / "out",
            sdk_root=sdk_root,
            python_version=(3, 11, 6),
            import_check=lambda: True,
        )

        assert receipt["python_runtime_ready"] is True
        assert receipt["kaggle_benchmarks_importable"] is True
        assert receipt["task_run_file_execution_ready"] is True
        assert receipt["blocked_reason"] is None
        assert receipt["verdict"] == "READY_TO_RUN_PROBE_TASK"
        harness.validate_kaggle_benchmarks_sdk_probe_receipt(receipt)


def test_kaggle_benchmarks_task_probe_records_task_and_run_artifacts_without_score_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-task-") as td:
        root = Path(td)

        def fake_runner(workdir: Path) -> dict[str, object]:
            workdir.mkdir(parents=True, exist_ok=True)
            task_file = workdir / "Ember_Probe_No_LLM.task.json"
            run_file = workdir / "Ember_Probe_No_LLM-run_id_Run_1.run.json"
            task_file.write_text('{"name":"Ember Probe No LLM"}\n', encoding="utf-8", newline="\n")
            run_file.write_text(
                '{"state":"BENCHMARK_TASK_RUN_STATE_COMPLETED","results":[{"booleanResult":true}]}\n',
                encoding="utf-8",
                newline="\n",
            )
            return {
                "returncode": 0,
                "stdout": "EMBER_KAGGLE_BENCHMARKS_TASK_PROBE_PASS\n",
                "stderr": "",
            }

        receipt = harness.run_kaggle_benchmarks_task_file_probe(
            root / "out",
            root / "probe-workdir",
            python_executable=Path("python"),
            runner=fake_runner,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-KAGGLE-BENCHMARKS-TASK-FILE-PROBE"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["verdict"] == "TASK_RUN_FILES_MATERIALIZED"
        assert receipt["blocked_reason"] is None
        assert receipt["task_file_count"] == 1
        assert receipt["run_file_count"] == 1
        assert receipt["task_run_files_materialized"] is True
        assert receipt["score"]["mean_normalized_improvement"] is None
        assert receipt["artifact_files"][0]["sha256"].startswith("sha256:")
        harness.validate_kaggle_benchmarks_task_file_probe_receipt(receipt)


def test_kaggle_benchmarks_task_probe_accepts_completed_run_file_despite_cleanup_exit() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-task-") as td:
        root = Path(td)

        def cleanup_error_runner(workdir: Path) -> dict[str, object]:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "Ember_Probe_No_LLM.task.json").write_text(
                '{"name":"Ember Probe No LLM"}\n',
                encoding="utf-8",
                newline="\n",
            )
            (workdir / "Ember_Probe_No_LLM-run_id_Run_1.run.json").write_text(
                '{"state":"BENCHMARK_TASK_RUN_STATE_COMPLETED","results":[{"booleanResult":true}],'
                '"assertions":[{"status":"BENCHMARK_TASK_RUN_ASSERTION_STATUS_PASSED"}]}\n',
                encoding="utf-8",
                newline="\n",
            )
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": "PermissionError: [WinError 5] Access is denied during tempfile cleanup",
            }

        receipt = harness.run_kaggle_benchmarks_task_file_probe(
            root / "out",
            root / "probe-workdir",
            python_executable=Path("python"),
            runner=cleanup_error_runner,
            cycle_id="cycle-test",
        )

        assert receipt["verdict"] == "TASK_RUN_FILES_MATERIALIZED"
        assert receipt["task_run_files_materialized"] is True
        assert receipt["cleanup_error_observed"] is True
        assert receipt["blocked_reason"] is None
        harness.validate_kaggle_benchmarks_task_file_probe_receipt(receipt)


def test_kaggle_benchmarks_task_probe_runner_routes_temp_dirs_into_workdir() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-task-") as td:
        root = Path(td)
        workdir = root / "probe-workdir"
        captured: dict[str, object] = {}
        original_run = harness.subprocess.run

        def fake_run(*args: object, **kwargs: object) -> object:
            captured["args"] = args
            captured["kwargs"] = kwargs

            class Result:
                returncode = 0
                stdout = "ok"
                stderr = ""

            return Result()

        try:
            harness.subprocess.run = fake_run  # type: ignore[assignment]
            harness._default_kaggle_benchmarks_task_probe_runner(workdir, Path("python"))
        finally:
            harness.subprocess.run = original_run  # type: ignore[assignment]

        env = captured["kwargs"]["env"]  # type: ignore[index]
        assert env["TMP"] == str(workdir / "tmp")
        assert env["TEMP"] == str(workdir / "tmp")
        assert (workdir / "tmp").is_dir()


def test_kaggle_benchmarks_task_probe_runner_sets_python_tempfile_dir_in_child_script() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-task-") as td:
        root = Path(td)
        workdir = root / "probe-workdir"
        original_run = harness.subprocess.run

        def fake_run(*args: object, **kwargs: object) -> object:
            class Result:
                returncode = 0
                stdout = "ok"
                stderr = ""

            return Result()

        try:
            harness.subprocess.run = fake_run  # type: ignore[assignment]
            harness._default_kaggle_benchmarks_task_probe_runner(workdir, Path("python"))
        finally:
            harness.subprocess.run = original_run  # type: ignore[assignment]

        script_text = (workdir / "ember_kaggle_benchmarks_task_probe.py").read_text(encoding="utf-8")
        assert "tempfile.tempdir = str(out / 'tmp')" in script_text
        assert "ignore_cleanup_errors" in script_text
        assert "InternalUnsafeLocalEnvironment.close" in script_text


def test_kaggle_benchmarks_score_shape_probe_receipts_local_metric_without_delta_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-score-") as td:
        root = Path(td)

        def fake_runner(workdir: Path) -> dict[str, object]:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "Ember_Score_Shape_No_LLM.task.json").write_text(
                '{"name":"Ember Score Shape No LLM"}\n',
                encoding="utf-8",
                newline="\n",
            )
            for idx in range(3):
                (workdir / f"Ember_Score_Shape_No_LLM-run_param_id_{idx}.run.json").write_text(
                    '{"state":"BENCHMARK_TASK_RUN_STATE_COMPLETED","results":[{"booleanResult":true}]}\n',
                    encoding="utf-8",
                    newline="\n",
                )
            (workdir / "ember_score_shape_summary.json").write_text(
                '{"metric_name":"accuracy","metric_value":1.0,"sample_count":3,'
                '"completed_count":3,"errored_count":0}\n',
                encoding="utf-8",
                newline="\n",
            )
            return {
                "returncode": 0,
                "stdout": "EMBER_KAGGLE_BENCHMARKS_SCORE_SHAPE_PASS\n",
                "stderr": "",
            }

        receipt = harness.run_kaggle_benchmarks_score_shape_probe(
            root / "out",
            root / "probe-workdir",
            python_executable=Path("python"),
            runner=fake_runner,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-KAGGLE-BENCHMARKS-SCORE-SHAPE-PROBE"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["verdict"] == "SCORE_SHAPE_RECEIPTED"
        assert receipt["score_shape_ready"] is True
        assert receipt["local_score_shape"]["metric_name"] == "accuracy"
        assert receipt["local_score_shape"]["metric_value"] == 1.0
        assert receipt["local_score_shape"]["sample_count"] == 3
        assert receipt["benchmark_delta_claimed"] is False
        assert receipt["score"]["mean_normalized_improvement"] is None
        assert receipt["run_file_count"] == 3
        harness.validate_kaggle_benchmarks_score_shape_probe_receipt(receipt)


def test_kaggle_benchmarks_livecodebench_public_test_pilot_receipts_smoke_without_delta_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-lcb-") as td:
        root = Path(td)

        def fake_runner(workdir: Path) -> dict[str, object]:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "LiveCodeBench_Demo_Public_Test.task.json").write_text(
                '{"name":"LiveCodeBench Demo Public Test"}\n',
                encoding="utf-8",
                newline="\n",
            )
            (workdir / "LiveCodeBench_Demo_Public_Test-run_param_id_1873_A_public.run.json").write_text(
                '{"state":"BENCHMARK_TASK_RUN_STATE_COMPLETED","results":[{"booleanResult":true}]}\n',
                encoding="utf-8",
                newline="\n",
            )
            (workdir / "livecodebench_public_test_summary.json").write_text(
                '{"benchmark_family":"livecodebench/code_generation_lite","question_id":"1873_A",'
                '"public_test_passed":true,"sample_count":1}\n',
                encoding="utf-8",
                newline="\n",
            )
            return {
                "returncode": 0,
                "stdout": "EMBER_KAGGLE_BENCHMARKS_LCB_PUBLIC_TEST_PASS\n",
                "stderr": "",
            }

        receipt = harness.run_kaggle_benchmarks_livecodebench_public_test_pilot(
            root / "out",
            root / "probe-workdir",
            python_executable=Path("python"),
            sdk_root=root / "kaggle-benchmarks",
            runner=fake_runner,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-PUBLIC-TEST-PILOT"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["verdict"] == "PILOT_PUBLIC_TEST_RECEIPTED"
        assert receipt["pilot_ready"] is True
        assert receipt["benchmark_family"] == "livecodebench/code_generation_lite"
        assert receipt["question_id"] == "1873_A"
        assert receipt["public_test_passed"] is True
        assert receipt["benchmark_delta_claimed"] is False
        assert receipt["score"]["mean_normalized_improvement"] is None
        harness.validate_kaggle_benchmarks_livecodebench_public_test_pilot_receipt(receipt)


def test_kaggle_benchmarks_livecodebench_public_test_pilot_accepts_completed_run_file_when_cleanup_drops_summary() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-lcb-") as td:
        root = Path(td)

        def cleanup_runner(workdir: Path) -> dict[str, object]:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "LiveCodeBench_Demo_Public_Test.task.json").write_text(
                '{"name":"LiveCodeBench Demo Public Test"}\n',
                encoding="utf-8",
                newline="\n",
            )
            (workdir / "LiveCodeBench_Demo_Public_Test-run_param_id_1873_A_public.run.json").write_text(
                '{"state":"BENCHMARK_TASK_RUN_STATE_COMPLETED","results":[{"booleanResult":true}]}\n',
                encoding="utf-8",
                newline="\n",
            )
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": "PermissionError: temp cleanup failed",
            }

        receipt = harness.run_kaggle_benchmarks_livecodebench_public_test_pilot(
            root / "out",
            root / "probe-workdir",
            python_executable=Path("python"),
            runner=cleanup_runner,
            cycle_id="cycle-test",
        )

        assert receipt["verdict"] == "PILOT_PUBLIC_TEST_RECEIPTED"
        assert receipt["pilot_ready"] is True
        assert receipt["public_test_passed"] is True
        assert receipt["cleanup_error_observed"] is True
        assert receipt["blocked_reason"] is None
        harness.validate_kaggle_benchmarks_livecodebench_public_test_pilot_receipt(receipt)


def test_kaggle_benchmarks_livecodebench_candidate_vs_baseline_receipts_frozen_public_test_delta_without_external_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-lcb-delta-") as td:
        root = Path(td)

        def fake_runner(workdir: Path) -> dict[str, object]:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "LiveCodeBench_Public_Test_Candidate_Vs_Baseline.task.json").write_text(
                '{"name":"LiveCodeBench Public Test Candidate Vs Baseline"}\n',
                encoding="utf-8",
                newline="\n",
            )
            for name, result in (("baseline", False), ("candidate", True)):
                (workdir / f"LiveCodeBench_Public_Test_Candidate_Vs_Baseline-run_param_id_{name}.run.json").write_text(
                    '{"state":"BENCHMARK_TASK_RUN_STATE_COMPLETED","results":[{"booleanResult":'
                    + str(result).lower()
                    + "}]}\n",
                    encoding="utf-8",
                    newline="\n",
                )
            (workdir / "livecodebench_candidate_vs_baseline_summary.json").write_text(
                '{"baseline_public_pass":false,"candidate_public_pass":true,'
                '"public_test_delta":1.0,"frozen_public_test_sha256":"sha256:abc",'
                '"question_id":"1873_A","benchmark_family":"livecodebench/code_generation_lite"}\n',
                encoding="utf-8",
                newline="\n",
            )
            return {
                "returncode": 0,
                "stdout": "EMBER_KAGGLE_BENCHMARKS_LCB_CANDIDATE_VS_BASELINE_PASS\n",
                "stderr": "",
            }

        receipt = harness.run_kaggle_benchmarks_livecodebench_candidate_vs_baseline(
            root / "out",
            root / "probe-workdir",
            python_executable=Path("python"),
            sdk_root=root / "kaggle-benchmarks",
            runner=fake_runner,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-CANDIDATE-VS-BASELINE"
        assert receipt["verdict"] == "PUBLIC_TEST_DELTA_RECEIPTED"
        assert receipt["candidate_vs_baseline_ready"] is True
        assert receipt["baseline_public_pass"] is False
        assert receipt["candidate_public_pass"] is True
        assert receipt["public_test_delta"] == 1.0
        assert receipt["frozen_public_test_sha256"].startswith("sha256:")
        assert receipt["benchmark_delta_claimed"] is False
        assert receipt["score"]["mean_normalized_improvement"] is None
        harness.validate_kaggle_benchmarks_livecodebench_candidate_vs_baseline_receipt(receipt)


def test_kaggle_benchmarks_livecodebench_candidate_vs_baseline_runner_imports_sys_for_arm_arg() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-lcb-delta-") as td:
        root = Path(td)
        workdir = root / "probe-workdir"
        original_run = harness.subprocess.run

        def fake_run(*args: object, **kwargs: object) -> object:
            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        try:
            harness.subprocess.run = fake_run  # type: ignore[assignment]
            harness._default_kaggle_benchmarks_livecodebench_candidate_vs_baseline_runner(workdir, Path("python"))
        finally:
            harness.subprocess.run = original_run  # type: ignore[assignment]

        script_text = (workdir / "ember_kaggle_benchmarks_livecodebench_candidate_vs_baseline.py").read_text(encoding="utf-8")
        assert "import sys" in script_text
        assert "kind = sys.argv[1]" in script_text


def test_kaggle_benchmarks_frozen_heldout_delta_receipts_numeric_score_without_external_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-benchmarks-heldout-") as td:
        root = Path(td)

        def fake_runner(workdir: Path) -> dict[str, object]:
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "frozen_heldout_cases.jsonl").write_text(
                '{"case_id":"hidden-001","input":"3\\n","expected":"YES\\n"}\n'
                '{"case_id":"hidden-002","input":"4\\n","expected":"NO\\n"}\n',
                encoding="utf-8",
                newline="\n",
            )
            (workdir / "LiveCodeBench_Frozen_Heldout_Candidate_Vs_Baseline.task.json").write_text(
                '{"name":"LiveCodeBench Frozen Heldout Candidate Vs Baseline"}\n',
                encoding="utf-8",
                newline="\n",
            )
            for name, score in (("baseline", 0.0), ("candidate", 1.0)):
                (workdir / f"LiveCodeBench_Frozen_Heldout_Candidate_Vs_Baseline-run_param_id_{name}.run.json").write_text(
                    '{"state":"BENCHMARK_TASK_RUN_STATE_COMPLETED","results":[{"score":'
                    + str(score)
                    + "}]}\n",
                    encoding="utf-8",
                    newline="\n",
                )
            (workdir / "livecodebench_frozen_heldout_summary.json").write_text(
                '{"benchmark_family":"livecodebench/code_generation_lite",'
                '"question_id":"1873_A","heldout_case_count":2,'
                '"baseline_score":0.0,"candidate_score":1.0,'
                '"mean_normalized_improvement":1.0,'
                '"external_source_certified":false,'
                '"heldout_source":"local-frozen-fixture"}\n',
                encoding="utf-8",
                newline="\n",
            )
            return {
                "returncode": 0,
                "stdout": "EMBER_KAGGLE_BENCHMARKS_FROZEN_HELDOUT_DELTA_PASS\n",
                "stderr": "",
            }

        receipt = harness.run_kaggle_benchmarks_livecodebench_frozen_heldout_delta(
            root / "out",
            root / "probe-workdir",
            python_executable=Path("python"),
            sdk_root=root / "kaggle-benchmarks",
            runner=fake_runner,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-FROZEN-HELDOUT-DELTA"
        assert receipt["verdict"] == "HELDOUT_DELTA_RECEIPTED"
        assert receipt["heldout_delta_ready"] is True
        assert receipt["heldout_case_count"] == 2
        assert receipt["frozen_heldout_sha256"].startswith("sha256:")
        assert receipt["score"]["baseline_score"] == 0.0
        assert receipt["score"]["candidate_score"] == 1.0
        assert receipt["score"]["mean_normalized_improvement"] == 1.0
        assert receipt["benchmark_delta_claimed"] is True
        assert receipt["external_benchmark_delta_claimed"] is False
        assert receipt["heldout_source"] == "local-frozen-fixture"
        harness.validate_kaggle_benchmarks_livecodebench_frozen_heldout_delta_receipt(receipt)


def test_cli_exposes_kaggle_benchmarks_frozen_heldout_delta() -> None:
    script = Path(__file__).resolve().with_name("ember_mle_micro_harness.py")
    proc = subprocess.run([sys.executable, str(script), "--help"], text=True, capture_output=True, timeout=30)

    assert proc.returncode == 0
    assert "--kaggle-benchmarks-livecodebench-frozen-heldout-delta" in proc.stdout


def test_kaggle_dataset_external_heldout_delta_certifies_source_but_marks_fixture_candidate() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-dataset-heldout-") as td:
        root = Path(td)
        dataset_root = root / "dataset"
        csv_path = dataset_root / "raw" / "Emotion_classify_Data.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "Comment,Emotion\n"
            "i am afraid,fear\n"
            "i am angry,anger\n"
            "i am joyful,joy\n"
            "i feel afraid again,fear\n",
            encoding="utf-8",
            newline="\n",
        )
        dataset_receipt = {
            "ticket": "EMBER-KAGGLE-DATASET-LANE-MATERIALIZATION",
            "ts": "20260618T000000Z",
            "dataset_ref": "abdallahwagih/emotion-dataset",
            "dataset_url": "https://www.kaggle.com/datasets/abdallahwagih/emotion-dataset",
            "license_name": "Apache 2.0",
            "source": "kaggle_datasets_api",
            "root": str(dataset_root),
            "files": [
                {
                    "path": str(csv_path),
                    "relative_path": "raw/Emotion_classify_Data.csv",
                    "bytes": csv_path.stat().st_size,
                    "sha256": harness.sha256_bytes(csv_path.read_bytes()),
                }
            ],
            "file_count": 1,
            "total_bytes": csv_path.stat().st_size,
            "verdict": "MATERIALIZED",
        }
        dataset_receipt_path = root / "dataset-receipt.json"
        dataset_receipt_path.write_text(json.dumps(dataset_receipt, indent=2) + "\n", encoding="utf-8", newline="\n")

        receipt = harness.run_kaggle_dataset_external_heldout_delta(
            root / "out",
            dataset_receipt_path,
            cycle_id="cycle-test",
        )

        assert receipt["ticket"] == "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA"
        assert receipt["verdict"] == "EXTERNAL_HELDOUT_DELTA_RECEIPTED"
        assert receipt["dataset_ref"] == "abdallahwagih/emotion-dataset"
        assert receipt["external_source_certified"] is True
        assert receipt["external_benchmark_delta_claimed"] is True
        assert receipt["candidate_prediction_source"] == "fixture_gold_label_echo"
        assert receipt["heldout_case_count"] == 4
        assert receipt["score"]["baseline_score"] == 0.5
        assert receipt["score"]["candidate_score"] == 1.0
        assert receipt["score"]["mean_normalized_improvement"] == 1.0
        assert receipt["frozen_heldout_sha256"].startswith("sha256:")
        harness.validate_kaggle_dataset_external_heldout_delta_receipt(receipt)


def test_kaggle_dataset_external_heldout_delta_runs_candidate_script_without_gold_echo() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-dataset-heldout-candidate-") as td:
        root = Path(td)
        dataset_root = root / "dataset"
        csv_path = dataset_root / "raw" / "Emotion_classify_Data.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "Comment,Emotion\n"
            "i am afraid,fear\n"
            "i feel scared,fear\n"
            "i am angry,anger\n"
            "i feel joy,joy\n",
            encoding="utf-8",
            newline="\n",
        )
        dataset_receipt = {
            "ticket": "EMBER-KAGGLE-DATASET-LANE-MATERIALIZATION",
            "ts": "20260618T000000Z",
            "dataset_ref": "abdallahwagih/emotion-dataset",
            "dataset_url": "https://www.kaggle.com/datasets/abdallahwagih/emotion-dataset",
            "license_name": "Apache 2.0",
            "source": "kaggle_datasets_api",
            "root": str(dataset_root),
            "files": [
                {
                    "path": str(csv_path),
                    "relative_path": "raw/Emotion_classify_Data.csv",
                    "bytes": csv_path.stat().st_size,
                    "sha256": harness.sha256_bytes(csv_path.read_bytes()),
                }
            ],
            "file_count": 1,
            "total_bytes": csv_path.stat().st_size,
            "verdict": "MATERIALIZED",
        }
        dataset_receipt_path = root / "dataset-receipt.json"
        dataset_receipt_path.write_text(json.dumps(dataset_receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        candidate_script = root / "candidate.py"
        candidate_script.write_text(
            "import json, sys\n"
            "heldout_path, out_path = sys.argv[1], sys.argv[2]\n"
            "with open(heldout_path, encoding='utf-8') as f, open(out_path, 'w', encoding='utf-8', newline='\\n') as out:\n"
            "    for line in <local-path>"
            "        row = json.loads(line)\n"
            "        text = row['text'].lower()\n"
            "        if 'afraid' in text or 'scared' in text:\n"
            "            pred = 'fear'\n"
            "        elif 'angry' in text:\n"
            "            pred = 'anger'\n"
            "        elif 'joy' in text:\n"
            "            pred = 'joy'\n"
            "        else:\n"
            "            pred = 'fear'\n"
            "        out.write(json.dumps({'case_id': row['case_id'], 'prediction': pred}, sort_keys=True) + '\\n')\n",
            encoding="utf-8",
            newline="\n",
        )

        receipt = harness.run_kaggle_dataset_external_heldout_delta(
            root / "out",
            dataset_receipt_path,
            cycle_id="cycle-test",
            candidate_script_path=candidate_script,
            python_executable=Path(sys.executable),
        )

        assert receipt["verdict"] == "EXTERNAL_HELDOUT_DELTA_RECEIPTED"
        assert receipt["external_source_certified"] is True
        assert receipt["external_benchmark_delta_claimed"] is True
        assert receipt["candidate_prediction_source"] == f"script:{candidate_script}"
        assert receipt["candidate_script_sha256"] == harness.sha256_bytes(candidate_script.read_bytes())
        assert receipt["candidate_returncode"] == 0
        assert receipt["score"]["baseline_score"] == 0.5
        assert receipt["score"]["candidate_score"] == 1.0
        assert receipt["score"]["mean_normalized_improvement"] == 1.0
        harness.validate_kaggle_dataset_external_heldout_delta_receipt(receipt)


def test_kaggle_dataset_external_heldout_delta_stamps_wheel_arm_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-dataset-heldout-arm-") as td:
        root = Path(td)
        dataset_root = root / "dataset"
        csv_path = dataset_root / "raw" / "Emotion_classify_Data.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "Comment,Emotion\n"
            "i am afraid,fear\n"
            "i feel scared,fear\n"
            "i am angry,anger\n"
            "i feel joy,joy\n",
            encoding="utf-8",
            newline="\n",
        )
        dataset_receipt = {
            "ticket": "EMBER-KAGGLE-DATASET-LANE-MATERIALIZATION",
            "ts": "20260618T000000Z",
            "dataset_ref": "abdallahwagih/emotion-dataset",
            "dataset_url": "https://www.kaggle.com/datasets/abdallahwagih/emotion-dataset",
            "license_name": "Apache 2.0",
            "source": "kaggle_datasets_api",
            "root": str(dataset_root),
            "files": [
                {
                    "path": str(csv_path),
                    "relative_path": "raw/Emotion_classify_Data.csv",
                    "bytes": csv_path.stat().st_size,
                    "sha256": harness.sha256_bytes(csv_path.read_bytes()),
                }
            ],
            "file_count": 1,
            "total_bytes": csv_path.stat().st_size,
            "verdict": "MATERIALIZED",
        }
        dataset_receipt_path = root / "dataset-receipt.json"
        dataset_receipt_path.write_text(json.dumps(dataset_receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        candidate_script = root / "candidate.py"
        candidate_script.write_text(
            "import json, sys\n"
            "heldout_path, out_path = sys.argv[1], sys.argv[2]\n"
            "with open(heldout_path, encoding='utf-8') as f, open(out_path, 'w', encoding='utf-8', newline='\\n') as out:\n"
            "    for line in <local-path>"
            "        row = json.loads(line)\n"
            "        text = row['text'].lower()\n"
            "        if 'afraid' in text or 'scared' in text:\n"
            "            pred = 'fear'\n"
            "        elif 'angry' in text:\n"
            "            pred = 'anger'\n"
            "        elif 'joy' in text:\n"
            "            pred = 'joy'\n"
            "        else:\n"
            "            pred = 'fear'\n"
            "        out.write(json.dumps({'case_id': row['case_id'], 'prediction': pred}, sort_keys=True) + '\\n')\n",
            encoding="utf-8",
            newline="\n",
        )

        receipt = harness.run_kaggle_dataset_external_heldout_delta(
            root / "out",
            dataset_receipt_path,
            cycle_id="cycle-test",
            candidate_script_path=candidate_script,
            python_executable=Path(sys.executable),
            wheel_arm="C",
        )

        assert receipt["wheel_arm"] == harness.WHEEL_ARM_CONTRACTS["C"]
        harness.validate_kaggle_dataset_external_heldout_delta_receipt(receipt)


def test_kaggle_dataset_external_heldout_delta_can_train_candidate_from_external_rows() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-kaggle-dataset-trained-heldout-") as td:
        root = Path(td)
        dataset_root = root / "dataset"
        csv_path = dataset_root / "raw" / "Emotion_classify_Data.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "Comment,Emotion\n"
            "fear heldout zero,fear\n"
            "joy heldout zero,joy\n"
            "anger heldout zero,anger\n"
            "fear training one,fear\n"
            "fear training two,fear\n"
            "joy training one,joy\n"
            "joy training two,joy\n"
            "anger training one,anger\n"
            "anger training two,anger\n",
            encoding="utf-8",
            newline="\n",
        )
        dataset_receipt = {
            "ticket": "EMBER-KAGGLE-DATASET-LANE-MATERIALIZATION",
            "ts": "20260618T000000Z",
            "dataset_ref": "abdallahwagih/emotion-dataset",
            "dataset_url": "https://www.kaggle.com/datasets/abdallahwagih/emotion-dataset",
            "license_name": "Apache 2.0",
            "source": "kaggle_datasets_api",
            "root": str(dataset_root),
            "files": [
                {
                    "path": str(csv_path),
                    "relative_path": "raw/Emotion_classify_Data.csv",
                    "bytes": csv_path.stat().st_size,
                    "sha256": harness.sha256_bytes(csv_path.read_bytes()),
                }
            ],
            "file_count": 1,
            "total_bytes": csv_path.stat().st_size,
            "verdict": "MATERIALIZED",
        }
        dataset_receipt_path = root / "dataset-receipt.json"
        dataset_receipt_path.write_text(json.dumps(dataset_receipt, indent=2) + "\n", encoding="utf-8", newline="\n")

        receipt = harness.run_kaggle_dataset_external_heldout_delta(
            root / "out",
            dataset_receipt_path,
            cycle_id="cycle-test",
            heldout_limit=3,
            train_candidate=True,
            wheel_arm="C",
        )

        assert receipt["verdict"] == "EXTERNAL_HELDOUT_DELTA_RECEIPTED"
        assert receipt["candidate_prediction_source"] == "trained_sklearn_text_classifier"
        assert receipt["training_case_count"] == 6
        assert receipt["training_source"] == "external_rows_after_frozen_heldout"
        assert receipt["candidate_training"]["model_family"] == "sklearn.multinomial_nb"
        assert receipt["candidate_training"]["training_case_count"] == 6
        assert receipt["candidate_training"]["model_artifact_sha256"].startswith("sha256:")
        assert receipt["candidate_training"]["model_artifact_path"]
        assert receipt["candidate_script_path"] is None
        assert receipt["candidate_returncode"] == 0
        assert receipt["score"]["candidate_score"] == 1.0
        harness.validate_kaggle_dataset_external_heldout_delta_receipt(receipt)


def _write_raw_prepare_assets(root: Path) -> None:
    for task_id, required in harness.RAW_PREPARE_ASSETS.items():
        for rel_path in required:
            path = root / task_id / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{task_id}:{rel_path}\n", encoding="utf-8", newline="\n")


def test_raw_data_import_copies_exact_prepare_inputs_and_receipts_hashes() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-raw-import-") as td:
        root = Path(td)
        source_root = root / "source"
        data_root = root / "data"
        _write_raw_prepare_assets(source_root)

        receipt = harness.run_raw_data_import(root / "out", source_root, data_root, cycle_id="cycle-test")

        assert receipt["ticket"] == "EMBER-MLE-MICRO-RAW-DATA-IMPORT"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["raw_data_ready"] is True
        assert receipt["copied_count"] == sum(len(v) for v in harness.RAW_PREPARE_ASSETS.values())
        assert receipt["missing_source_assets"] == []
        assert receipt["verdict"] == "IMPORTED"
        for task_id, required in harness.RAW_PREPARE_ASSETS.items():
            for rel_path in required:
                assert (data_root / task_id / rel_path).read_text(encoding="utf-8") == f"{task_id}:{rel_path}\n"
        assert all(row["sha256"].startswith("sha256:") for row in receipt["copied_assets"])
        harness.validate_raw_data_import_receipt(receipt)


def test_raw_data_import_blocks_incomplete_source_without_partial_ready_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-raw-import-") as td:
        root = Path(td)
        source_root = root / "source"
        data_root = root / "data"
        first_task = harness.MLE_LOW_MICRO_TASK_IDS[0]
        first_rel = harness.RAW_PREPARE_ASSETS[first_task][0]
        path = source_root / first_task / first_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("partial\n", encoding="utf-8", newline="\n")

        receipt = harness.run_raw_data_import(root / "out", source_root, data_root)

        assert receipt["raw_data_ready"] is False
        assert receipt["copied_count"] == 0
        assert receipt["copied_assets"] == []
        assert receipt["missing_source_assets"]
        assert receipt["verdict"] == "BLOCKED"
        harness.validate_raw_data_import_receipt(receipt)


def test_official_prepare_execution_runs_commands_and_verifies_prepared_assets() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-prepare-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
        _write_raw_prepare_assets(data_root)

        def command_factory(task_id: str, default_command: list[str]) -> list[str]:
            script = (
                "import pathlib, sys\n"
                "task_id = sys.argv[1]\n"
                "data_root = pathlib.Path(sys.argv[2])\n"
                "private = data_root / task_id / 'prepared' / 'private'\n"
                "public = data_root / task_id / 'prepared' / 'public'\n"
                "private.mkdir(parents=True, exist_ok=True)\n"
                "public.mkdir(parents=True, exist_ok=True)\n"
                "(private / 'test.csv').write_text('id,target\\n1,0\\n', encoding='utf-8')\n"
                "(private / 'gold_submission.csv').write_text('id,target\\n1,0\\n', encoding='utf-8')\n"
                "(public / 'sample_submission.csv').write_text('id,target\\n1,0\\n', encoding='utf-8')\n"
            )
            return ["python", "-c", script, task_id, str(data_root)]

        receipt = harness.run_official_prepare_execution(
            root / "out",
            source_root,
            data_root,
            cycle_id="cycle-test",
            command_factory=command_factory,
        )

        assert receipt["ticket"] == "EMBER-MLE-MICRO-OFFICIAL-PREPARE-RUN"
        assert receipt["cycle_id"] == "cycle-test"
        assert receipt["raw_data_ready"] is True
        assert receipt["prepared_data_ready"] is True
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["verdict"] == "PREPARED"
        assert len(receipt["task_results"]) == len(harness.MLE_LOW_MICRO_TASK_IDS)
        harness.validate_official_prepare_execution_receipt(receipt)


def test_official_prepare_execution_blocks_without_raw_inputs() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-prepare-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)

        receipt = harness.run_official_prepare_execution(root / "out", source_root, data_root)

        assert receipt["raw_data_ready"] is False
        assert receipt["prepared_data_ready"] is False
        assert receipt["blocked_reason"] == "raw_data_audit_failed"
        assert receipt["task_results"] == []
        assert receipt["verdict"] == "BLOCKED"
        harness.validate_official_prepare_execution_receipt(receipt)


def test_official_prepare_execution_can_attempt_without_raw_inputs() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-prepare-attempt-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)

        def command_factory(task_id: str, default_command: list[str]) -> list[str]:
            return [
                "python",
                "-c",
                "import sys; print('prepare attempted for ' + sys.argv[1]); raise SystemExit(7)",
                task_id,
            ]

        receipt = harness.run_official_prepare_execution(
            root / "out",
            source_root,
            data_root,
            command_factory=command_factory,
            attempt_prepare_without_raw=True,
        )

        assert receipt["raw_data_ready"] is False
        assert receipt["prepared_data_ready"] is False
        assert receipt["blocked_reason"] == "official_prepare_command_failed"
        assert receipt["raw_audit_blocking_bypassed"] is True
        assert receipt["failed_task_id"] == harness.MLE_LOW_MICRO_TASK_IDS[0]
        assert len(receipt["task_results"]) == 1
        assert receipt["task_results"][0]["returncode"] == 7
        assert "prepare attempted" in receipt["task_results"][0]["output_excerpt"]
        assert receipt["verdict"] == "BLOCKED"
        harness.validate_official_prepare_execution_receipt(receipt)


def test_official_prepare_execution_uses_configured_python_executable() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-prepare-python-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        configured_python = root / "venv" / "Scripts" / "python.exe"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)

        seen_defaults: list[list[str]] = []

        def command_factory(task_id: str, default_command: list[str]) -> list[str]:
            seen_defaults.append(default_command)
            return ["python", "-c", "raise SystemExit(3)"]

        receipt = harness.run_official_prepare_execution(
            root / "out",
            source_root,
            data_root,
            command_factory=command_factory,
            attempt_prepare_without_raw=True,
            python_executable=configured_python,
        )

        assert seen_defaults
        assert seen_defaults[0][0] == str(configured_python)
        assert receipt["prepare_commands"][0]["command"][0] == str(configured_python)
        assert receipt["blocked_reason"] == "official_prepare_command_failed"
        harness.validate_official_prepare_execution_receipt(receipt)


def test_local_micro_execution_runs_ready_tasks_and_scores_delta() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
        root = Path(td)
        mle_root = root / "mle-low"
        candidate_root = root / "candidates"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_ready_task(mle_root, task_id)
            _write_candidate(candidate_root, task_id)

        receipt = harness.run_local_micro_execution(root / "out", mle_root, candidate_root, cycle_id="cycle-test")

        assert receipt["ticket"] == "EMBER-MLE-MICRO-REAL-RUN"
        assert receipt["fixture_only"] is False
        assert receipt["real_mle_tasks_executed"] is True
        assert receipt["frozen_before_execution"] is True
        assert receipt["verdict"] == "PASS"
        assert len(receipt["task_results"]) == len(harness.MLE_LOW_MICRO_TASK_IDS)
        assert receipt["score"]["baseline_score"] == 0.5
        assert receipt["score"]["candidate_score"] == 0.75
        assert receipt["score"]["mean_normalized_improvement"] == 0.5
        harness.validate_local_execution_receipt(receipt)


def test_local_micro_execution_blocks_missing_hydration() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
        root = Path(td)
        mle_root = root / "mle-low"
        candidate_root = root / "candidates"
        _write_ready_task(mle_root, harness.MLE_LOW_MICRO_TASK_IDS[0])
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_candidate(candidate_root, task_id)

        receipt = harness.run_local_micro_execution(root / "out", mle_root, candidate_root, cycle_id="cycle-test")

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["blocked_reason"] == "hydration_preflight_failed"
        assert receipt["missing_assets"]
        harness.validate_local_execution_receipt(receipt)


def test_local_micro_execution_blocks_missing_candidates() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
        root = Path(td)
        mle_root = root / "mle-low"
        candidate_root = root / "candidates"
        for task_id in harness.MLE_LOW_MICRO_TASK_IDS:
            _write_ready_task(mle_root, task_id)
        _write_candidate(candidate_root, harness.MLE_LOW_MICRO_TASK_IDS[0])

        receipt = harness.run_local_micro_execution(root / "out", mle_root, candidate_root, cycle_id="cycle-test")

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["blocked_reason"] == "candidate_assets_missing"
        assert receipt["missing_candidate_assets"]
        harness.validate_local_execution_receipt(receipt)


def main() -> int:
    test_freeze_manifest_preserves_mle_low_micro_subset()
    test_tiny_fixture_scores_mean_normalized_improvement()
    test_hydration_preflight_reports_ready_local_assets()
    test_hydration_preflight_blocks_missing_local_assets()
    test_official_source_preflight_reports_ready_source_without_execution()
    test_official_grading_preflight_reports_ready_commands_without_execution()
    test_official_grading_preflight_blocks_missing_prepared_data()
    test_official_grading_preflight_does_not_require_blank_gold_submission()
    test_official_grade_execution_runs_ready_grade_commands_and_scores_delta()
    test_official_grade_execution_can_auto_materialize_sample_submissions()
    test_official_grade_execution_blocks_when_preflight_not_ready()
    test_sample_submission_bootstrap_copies_prepared_samples_to_submission_root()
    test_sample_submission_bootstrap_blocks_missing_samples()
    test_raw_data_audit_reports_missing_prepare_inputs()
    test_raw_data_audit_passes_when_prepare_inputs_exist()
    test_kaggle_auth_preflight_records_credential_shape_without_secret()
    test_kaggle_auth_preflight_records_access_token_surface_without_secret()
    test_kaggle_auth_preflight_blocks_malformed_credential_file()
    test_kaggle_auth_preflight_uses_explicit_live_command_and_redacts_error()
    test_acquisition_status_prefers_local_raw_files_over_missing_auth()
    test_acquisition_status_blocks_when_raw_missing_and_live_auth_fails()
    test_kaggle_sdk_raw_download_extracts_required_assets_without_secret()
    test_kaggle_sdk_raw_download_blocks_missing_token_file()
    test_kaggle_sdk_raw_download_records_forbidden_without_crashing()
    test_kaggle_benchmarks_sdk_probe_blocks_python_below_required_version()
    test_kaggle_benchmarks_sdk_probe_reports_ready_shape_when_runtime_and_import_exist()
    test_kaggle_benchmarks_task_probe_records_task_and_run_artifacts_without_score_claim()
    test_kaggle_benchmarks_task_probe_accepts_completed_run_file_despite_cleanup_exit()
    test_kaggle_benchmarks_task_probe_runner_routes_temp_dirs_into_workdir()
    test_kaggle_benchmarks_task_probe_runner_sets_python_tempfile_dir_in_child_script()
    test_kaggle_benchmarks_score_shape_probe_receipts_local_metric_without_delta_claim()
    test_kaggle_benchmarks_livecodebench_public_test_pilot_receipts_smoke_without_delta_claim()
    test_kaggle_benchmarks_livecodebench_public_test_pilot_accepts_completed_run_file_when_cleanup_drops_summary()
    test_kaggle_benchmarks_livecodebench_candidate_vs_baseline_receipts_frozen_public_test_delta_without_external_claim()
    test_kaggle_benchmarks_livecodebench_candidate_vs_baseline_runner_imports_sys_for_arm_arg()
    test_kaggle_benchmarks_frozen_heldout_delta_receipts_numeric_score_without_external_claim()
    test_cli_exposes_kaggle_benchmarks_frozen_heldout_delta()
    test_kaggle_dataset_external_heldout_delta_certifies_source_but_marks_fixture_candidate()
    test_kaggle_dataset_external_heldout_delta_runs_candidate_script_without_gold_echo()
    test_kaggle_dataset_external_heldout_delta_stamps_wheel_arm_contract()
    test_raw_data_import_copies_exact_prepare_inputs_and_receipts_hashes()
    test_raw_data_import_blocks_incomplete_source_without_partial_ready_claim()
    test_official_prepare_execution_runs_commands_and_verifies_prepared_assets()
    test_official_prepare_execution_blocks_without_raw_inputs()
    test_official_prepare_execution_can_attempt_without_raw_inputs()
    test_official_prepare_execution_uses_configured_python_executable()
    test_local_micro_execution_runs_ready_tasks_and_scores_delta()
    test_local_micro_execution_blocks_missing_hydration()
    test_local_micro_execution_blocks_missing_candidates()
    print("EMBER_MLE_MICRO_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
