#!/usr/bin/env python3
"""Selftest for the one-command Ember MVP A/B/C wheel runner."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import ember_mle_micro_harness as mle
import ember_mvp_wheel_runner as runner


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


def _ready_tree(root: Path) -> tuple[Path, Path, Path]:
    source_root = root / "mle-bench-src"
    data_root = root / "data"
    submission_root = root / "submissions"
    for task_id in mle.MLE_LOW_MICRO_TASK_IDS:
        _write_official_config(source_root, task_id)
        _write_prepared_data(data_root, task_id)
        _write_submission(submission_root, task_id)
    return source_root, data_root, submission_root


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


def test_runner_executes_all_arms_and_passes_real_wheel_when_scores_order() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-runner-") as td:
        root = Path(td)
        source_root, data_root, submission_root = _ready_tree(root)

        receipt = runner.run_official_abc_wheel(
            root / "out",
            source_root,
            data_root,
            submission_root,
            cycle_id="cycle-test",
            command_factories={
                "A": _score_factory(0.1),
                "B": _score_factory(0.2),
                "C": _score_factory(0.3),
            },
        )

        assert receipt["ticket"] == "EMBER-MVP-OFFICIAL-ABC-WHEEL-RUNNER"
        assert receipt["verdict"] == "PASS"
        assert receipt["wheel_verdict"] == "PASS"
        assert receipt["ordering"] == "C>B>A"
        assert receipt["real_mle_tasks_executed"] is True
        assert [arm["id"] for arm in receipt["arms"]] == ["A", "B", "C"]
        assert [arm["verdict"] for arm in receipt["arms"]] == ["PASS", "PASS", "PASS"]
        assert [arm["mean_normalized_improvement"] for arm in receipt["arms"]] == [0.1, 0.2, 0.3]
        assert Path(receipt["wheel_receipt_path"]).exists()
        assert Path(receipt["receipt_path"]).exists()
        runner.validate_wheel_runner_receipt(receipt)


def test_runner_blocks_without_prepared_data_but_still_writes_wheel_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-runner-") as td:
        root = Path(td)
        source_root = root / "mle-bench-src"
        data_root = root / "data"
        submission_root = root / "submissions"
        for task_id in mle.MLE_LOW_MICRO_TASK_IDS:
            _write_official_config(source_root, task_id)
            _write_submission(submission_root, task_id)

        receipt = runner.run_official_abc_wheel(
            root / "out",
            source_root,
            data_root,
            submission_root,
            cycle_id="cycle-test",
        )

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["wheel_verdict"] == "BLOCKED"
        assert receipt["blocked_reason"] == "benchmark_receipts_not_real"
        assert receipt["real_mle_tasks_executed"] is False
        assert all(arm["verdict"] == "BLOCKED" for arm in receipt["arms"])
        assert all(arm["blocked_reason"] == "official_grading_preflight_failed" for arm in receipt["arms"])
        wheel_receipt = json.loads(Path(receipt["wheel_receipt_path"]).read_text(encoding="utf-8"))
        assert wheel_receipt["blocked_arms"] == ["A", "B", "C"]
        runner.validate_wheel_runner_receipt(receipt)


def main() -> int:
    test_runner_executes_all_arms_and_passes_real_wheel_when_scores_order()
    test_runner_blocks_without_prepared_data_but_still_writes_wheel_receipt()
    print("EMBER_MVP_WHEEL_RUNNER_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
