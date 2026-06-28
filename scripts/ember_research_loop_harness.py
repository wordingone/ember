#!/usr/bin/env python3
"""Run an admitted docs/research/journal benchmark as an equal-budget A/B/C loop."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-RESEARCH-LOOP"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _run_adapter(adapter: Path, task_id: str, solution: Path, timeout_seconds: int) -> dict[str, Any]:
    cmd = [
        "python",
        str(adapter),
        "--task-id",
        task_id,
        "--solution",
        str(solution),
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_seconds)
        passed = proc.returncode == 0
        if "Result: False" in proc.stdout:
            passed = False
        elif "Result: True" in proc.stdout:
            passed = True
        elif "Pass: False" in proc.stdout or "FAILED:" in proc.stdout:
            passed = False
        elif "Pass: True" in proc.stdout:
            passed = True
        return {
            "command": cmd,
            "returncode": proc.returncode,
            "passed": passed,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": cmd,
            "returncode": None,
            "passed": False,
            "timeout": True,
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }


def _mean(values: list[bool]) -> float:
    return sum(1 for value in values if value) / len(values) if values else 0.0


def _ordering(a_score: float, b_score: float, c_score: float) -> str:
    if c_score > b_score > a_score:
        return "C>B>A"
    if c_score > b_score == a_score:
        return "C>B=A"
    if c_score > a_score >= b_score:
        return "C>A>=B"
    return "not_c_gt_controls"


def build_research_loop_receipt(
    admission_path: Path,
    arm_a_solution: Path,
    arm_b_solution: Path,
    arm_c_solution: Path,
    *,
    budget_seconds: int,
    task_limit: int | None = None,
    arm_c_candidate_receipt_path: Path | None = None,
) -> dict[str, Any]:
    admission = _load_json(admission_path)
    errors: list[str] = []
    if admission.get("verdict") != "RESEARCH_BENCHMARK_ADMITTED":
        errors.append("admission.not_admitted")
    if admission.get("operator_routed") is not True:
        errors.append("admission.not_operator_routed")

    tasks_path = Path(str(admission.get("tasks_path", "")))
    evaluator_path = Path(str(admission.get("evaluator_path", "")))
    if not tasks_path.exists():
        errors.append("tasks_path.missing")
        tasks: list[dict[str, Any]] = []
    else:
        tasks = _load_json(tasks_path).get("tasks", [])
    if not evaluator_path.exists():
        errors.append("evaluator_path.missing")
    selected_tasks = tasks[:task_limit] if task_limit else tasks

    arms = {
        "arm_a": arm_a_solution,
        "arm_b": arm_b_solution,
        "arm_c": arm_c_solution,
    }
    for arm, path in arms.items():
        if not path.exists():
            errors.append(f"{arm}.solution_missing")
    arm_c_candidate_receipt: dict[str, Any] | None = None
    if arm_c_candidate_receipt_path:
        if not arm_c_candidate_receipt_path.exists():
            errors.append("arm_c.candidate_receipt_missing")
        else:
            arm_c_candidate_receipt = _load_json(arm_c_candidate_receipt_path)
            if arm_c_candidate_receipt.get("verdict") != "CANDIDATE_GENERATED":
                errors.append("arm_c.candidate_not_generated")
            if arm_c_candidate_receipt.get("manual_solution") is not False:
                errors.append("arm_c.manual_solution")
            if arm_c_candidate_receipt.get("deletion_load_bearing_test", {}).get("degrades_without_generator") is not True:
                errors.append("arm_c.generator_not_load_bearing")
            if arm_c_candidate_receipt.get("candidate_path") and str(arm_c_solution) != str(Path(arm_c_candidate_receipt["candidate_path"])):
                errors.append("arm_c.solution_candidate_mismatch")

    per_task_rows: list[dict[str, Any]] = []
    arm_passes = {"arm_a": [], "arm_b": [], "arm_c": []}
    if not errors:
        for task in selected_tasks:
            task_id = str(task["id"])
            row: dict[str, Any] = {"task_id": task_id}
            for arm, solution in arms.items():
                result = _run_adapter(evaluator_path, task_id, solution, budget_seconds)
                row[f"{arm}_passed"] = result["passed"]
                row[f"{arm}_returncode"] = result["returncode"]
                row[f"{arm}_stdout_tail"] = result.get("stdout_tail", "")
                row[f"{arm}_stderr_tail"] = result.get("stderr_tail", "")
                arm_passes[arm].append(bool(result["passed"]))
            per_task_rows.append(row)

    a_score = _mean(arm_passes["arm_a"])
    b_score = _mean(arm_passes["arm_b"])
    c_score = _mean(arm_passes["arm_c"])
    positive_delta = c_score > max(a_score, b_score)
    if not positive_delta:
        errors.append("positive_delta.missing")
    if not selected_tasks:
        errors.append("task_rows.missing")

    ordering = _ordering(a_score, b_score, c_score)
    rerun_command = (
        "python scripts\\ember_research_loop_harness.py "
        f"--admission-receipt {admission_path} "
        f"--arm-a-solution {arm_a_solution} "
        f"--arm-b-solution {arm_b_solution} "
        f"--arm-c-solution {arm_c_solution} "
        + (f"--arm-c-candidate-receipt {arm_c_candidate_receipt_path} " if arm_c_candidate_receipt_path else "")
        + f"--budget-seconds {budget_seconds} "
        + (f"--task-limit {task_limit} " if task_limit else "")
        + "--out <receipt-out>"
    )
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "admission_receipt_path": str(admission_path),
        "benchmark_id": admission.get("benchmark_id"),
        "benchmark_family": admission.get("benchmark_family"),
        "operator_routed": admission.get("operator_routed") is True,
        "budget_seconds_per_arm_per_task": budget_seconds,
        "equal_budget": True,
        "arms": {
            arm: {
                "solution_path": str(path),
                "solution_sha256": _sha256(path) if path.exists() else None,
                "budget_seconds": budget_seconds,
                **(
                    {
                        "candidate_generation_receipt_path": str(arm_c_candidate_receipt_path),
                        "manual_solution": arm_c_candidate_receipt.get("manual_solution") is not False,
                        "generator_load_bearing": arm_c_candidate_receipt.get("deletion_load_bearing_test", {}).get("degrades_without_generator") is True,
                    }
                    if arm == "arm_c" and arm_c_candidate_receipt is not None
                    else {}
                ),
            }
            for arm, path in arms.items()
        },
        "task_count": len(selected_tasks),
        "per_task_rows": per_task_rows,
        "score": {
            "baseline_score": a_score,
            "dream_loop_score": b_score,
            "candidate_score": c_score,
            "mean_normalized_improvement": c_score - max(a_score, b_score),
        },
        "reproducibility": {
            "rerun_command": rerun_command,
            "tasks_path": str(tasks_path),
            "tasks_sha256": admission.get("tasks_sha256") or (_sha256(tasks_path) if tasks_path.exists() else None),
            "evaluator_path": str(evaluator_path),
            "evaluator_sha256": admission.get("evaluator_sha256") or (_sha256(evaluator_path) if evaluator_path.exists() else None),
            "task_limit": task_limit,
            "budget_seconds": budget_seconds,
            "arm_solution_sha256": {
                arm: _sha256(path) if path.exists() else None
                for arm, path in arms.items()
            },
        },
        "ordering": ordering,
        "errors": errors,
        "verdict": "RESEARCH_LOOP_ACCEPTED" if not errors else "RESEARCH_LOOP_BLOCKED",
    }


def validate_research_loop_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("ticket") != TICKET:
        errors.append("ticket")
    if receipt.get("verdict") not in {"RESEARCH_LOOP_ACCEPTED", "RESEARCH_LOOP_BLOCKED"}:
        errors.append("verdict")
    if receipt.get("equal_budget") is not True:
        errors.append("equal_budget")
    if not receipt.get("per_task_rows"):
        errors.append("per_task_rows")
    if receipt.get("verdict") == "RESEARCH_LOOP_ACCEPTED":
        score = receipt.get("score", {})
        if score.get("candidate_score", 0) <= max(score.get("baseline_score", 0), score.get("dream_loop_score", 0)):
            errors.append("positive_delta")
        arm_c = receipt.get("arms", {}).get("arm_c", {})
        if arm_c.get("manual_solution") is not False:
            errors.append("arm_c.manual_solution")
        if arm_c.get("generator_load_bearing") is not True:
            errors.append("arm_c.generator_load_bearing")
        if receipt.get("errors"):
            errors.append("errors")
    return errors


def write_research_loop_receipt(
    out_path: Path,
    admission_path: Path,
    arm_a_solution: Path,
    arm_b_solution: Path,
    arm_c_solution: Path,
    *,
    budget_seconds: int,
    task_limit: int | None = None,
    arm_c_candidate_receipt_path: Path | None = None,
) -> dict[str, Any]:
    receipt = build_research_loop_receipt(
        admission_path,
        arm_a_solution,
        arm_b_solution,
        arm_c_solution,
        budget_seconds=budget_seconds,
        task_limit=task_limit,
        arm_c_candidate_receipt_path=arm_c_candidate_receipt_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    return receipt


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--admission-receipt")
    ap.add_argument("--arm-a-solution")
    ap.add_argument("--arm-b-solution")
    ap.add_argument("--arm-c-solution")
    ap.add_argument("--arm-c-candidate-receipt")
    ap.add_argument("--budget-seconds", type=int, default=300)
    ap.add_argument("--task-limit", type=int)
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.selftest:
        import ember_research_loop_harness_selftest

        return ember_research_loop_harness_selftest.main()

    required = [args.admission_receipt, args.arm_a_solution, args.arm_b_solution, args.arm_c_solution, args.out]
    if not all(required):
        ap.print_help()
        return 1

    receipt = write_research_loop_receipt(
        Path(args.out),
        Path(args.admission_receipt),
        Path(args.arm_a_solution),
        Path(args.arm_b_solution),
        Path(args.arm_c_solution),
        budget_seconds=args.budget_seconds,
        task_limit=args.task_limit,
        arm_c_candidate_receipt_path=Path(args.arm_c_candidate_receipt) if args.arm_c_candidate_receipt else None,
    )
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "RESEARCH_LOOP_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
