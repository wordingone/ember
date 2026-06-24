#!/usr/bin/env python3
"""One-command A/B/C wheel runner for Ember MVP v0.

This composes the official-grade micro benchmark harness with the real wheel
gate. If the prepared MLE-bench data or submissions are absent, each arm emits
a blocked grade receipt and the wheel emits a blocked real-wheel receipt. If
they are present, A, B, and C execute under the same cycle id and are bound
into one real wheel receipt.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import ember_mle_micro_harness as mle
import ember_wheel_harness as wheel
from receipt_write import checked_write

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
ARM_IDS = ("A", "B", "C")
CommandFactory = Callable[[str, list[str]], list[str]]


class WheelRunnerValidationError(ValueError):
    pass


def run_official_abc_wheel(
    root: Path,
    source_root: Path,
    data_root: Path,
    submission_root: Path,
    cycle_id: str,
    command_factories: dict[str, CommandFactory] | None = None,
    baseline_score: float = 0.0,
    max_score: float = 1.0,
) -> dict[str, Any]:
    root = Path(root)
    source_root = Path(source_root)
    data_root = Path(data_root)
    submission_root = Path(submission_root)
    command_factories = command_factories or {}

    arm_receipt_paths: dict[str, Path] = {}
    arm_summaries: list[dict[str, Any]] = []
    for arm_id in ARM_IDS:
        grade_receipt = mle.run_official_grade_execution(
            root / "arms" / arm_id,
            source_root,
            data_root,
            submission_root,
            cycle_id=cycle_id,
            command_factory=command_factories.get(arm_id),
            baseline_score=baseline_score,
            max_score=max_score,
            wheel_arm=arm_id,
        )
        arm_path = Path(grade_receipt["receipt_path"])
        arm_receipt_paths[arm_id] = arm_path
        arm_summaries.append(
            {
                "id": arm_id,
                "receipt_path": str(arm_path),
                "verdict": grade_receipt.get("verdict"),
                "blocked_reason": grade_receipt.get("blocked_reason"),
                "real_mle_tasks_executed": grade_receipt.get("real_mle_tasks_executed"),
                "mean_normalized_improvement": (
                    grade_receipt.get("score", {}).get("mean_normalized_improvement")
                ),
            }
        )

    wheel_receipt = wheel.run_real_wheel(
        root / "wheel",
        cycle_id=cycle_id,
        arm_receipts=arm_receipt_paths,
    )
    runner_verdict = wheel_receipt["verdict"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "EMBER-MVP-OFFICIAL-ABC-WHEEL-RUNNER",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "fixture_only": False,
        "source_root": str(source_root),
        "data_root": str(data_root),
        "submission_root": str(submission_root),
        "arms": arm_summaries,
        "wheel_receipt_path": wheel_receipt.get("receipt_path"),
        "wheel_verdict": wheel_receipt.get("verdict"),
        "blocked_reason": wheel_receipt.get("blocked_reason"),
        "real_mle_tasks_executed": wheel_receipt.get("real_mle_tasks_executed"),
        "ordering": wheel_receipt.get("ordering"),
        "verdict": runner_verdict,
    }
    out = root / "receipts" / "wheel-runner" / f"official-abc-wheel-runner-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_wheel_runner_receipt(receipt)
    return receipt


def validate_wheel_runner_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MVP-OFFICIAL-ABC-WHEEL-RUNNER":
        errors.append("bad ticket")
    if receipt.get("fixture_only") is not False:
        errors.append("wheel runner must not be marked fixture_only")
    if not receipt.get("cycle_id"):
        errors.append("missing cycle_id")
    arms = receipt.get("arms", [])
    if [arm.get("id") for arm in arms] != list(ARM_IDS):
        errors.append("runner must execute arms A, B, C in order")
    for arm in arms:
        if not arm.get("receipt_path"):
            errors.append(f"missing arm receipt path for {arm.get('id')}")
    if not receipt.get("wheel_receipt_path"):
        errors.append("missing wheel receipt path")
    verdict = receipt.get("verdict")
    if verdict not in {"PASS", "FAIL", "BLOCKED"}:
        errors.append("verdict must be PASS, FAIL, or BLOCKED")
    if verdict == "PASS":
        if receipt.get("real_mle_tasks_executed") is not True:
            errors.append("PASS requires real MLE task execution")
        if receipt.get("ordering") != "C>B>A":
            errors.append("PASS requires C>B>A ordering")
    if verdict == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked runner must record blocked_reason")
    if errors:
        raise WheelRunnerValidationError("; ".join(errors))


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture-out", required=True, help="write runner receipts under this directory")
    ap.add_argument("--source-root", required=True, help="official MLE-bench source checkout")
    ap.add_argument("--data-root", required=True, help="prepared MLE-bench data directory")
    ap.add_argument("--submission-root", required=True, help="candidate submission root")
    ap.add_argument("--cycle-id", default="cycle-20260617T000000Z-0001")
    args = ap.parse_args()

    receipt = run_official_abc_wheel(
        Path(args.fixture_out),
        Path(args.source_root),
        Path(args.data_root),
        Path(args.submission_root),
        cycle_id=args.cycle_id,
    )
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
