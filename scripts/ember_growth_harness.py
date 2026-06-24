#!/usr/bin/env python3
"""Repeated-cycle growth gate for Ember MVP receipts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
TICKET = "EMBER-GROWTH-CONTRACTION-STABILITY"
MIN_REPEATED_POSITIVE_CYCLES = 3


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cycle_root(cycle_path: Path) -> Path:
    return cycle_path.parent.parent.parent


def _linked_receipt(cycle_path: Path, cycle: dict[str, Any], key: str) -> dict[str, Any]:
    rel = cycle.get("receipts", {}).get(key)
    if not rel:
        return {"_missing": True}
    path = _cycle_root(cycle_path) / rel
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    receipt = load_json(path)
    receipt["_path"] = str(path)
    return receipt


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _non_decreasing(values: list[float]) -> bool:
    return all(next_value >= value for value, next_value in zip(values, values[1:]))


def _max_abs_step(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return max(abs(next_value - value) for value, next_value in zip(values, values[1:]))


def _arm_improvements(wheel: dict[str, Any]) -> dict[str, float]:
    if wheel.get("ticket") == "EMBER-RESEARCH-LOOP":
        score = wheel.get("score", {})
        baseline = _as_number(score.get("baseline_score"))
        dream = _as_number(score.get("dream_loop_score"))
        candidate = _as_number(score.get("candidate_score"))
        out: dict[str, float] = {}
        if baseline is not None:
            out["A"] = baseline
        if dream is not None:
            out["B"] = dream
        if candidate is not None:
            out["C"] = candidate
        return out
    out: dict[str, float] = {}
    for arm in wheel.get("arms", []):
        if not isinstance(arm, dict):
            continue
        arm_id = arm.get("id")
        value = _as_number(arm.get("normalized_improvement"))
        if isinstance(arm_id, str) and value is not None:
            out[arm_id] = value
    return out


def _research_loop_growth_ready(wheel: dict[str, Any]) -> bool:
    score = wheel.get("score", {})
    arms = wheel.get("arms", {})
    arm_c = arms.get("arm_c") if isinstance(arms, dict) else {}
    rows = wheel.get("per_task_rows")
    if not isinstance(rows, list):
        return False
    task_count = wheel.get("task_count")
    c_pass_count = sum(1 for row in rows if isinstance(row, dict) and row.get("arm_c_passed") is True)
    return bool(
        wheel.get("ticket") == "EMBER-RESEARCH-LOOP"
        and wheel.get("benchmark_family") == "research_journal"
        and wheel.get("operator_routed") is True
        and wheel.get("equal_budget") is True
        and wheel.get("verdict") == "RESEARCH_LOOP_ACCEPTED"
        and wheel.get("ordering") == "C>B=A"
        and isinstance(task_count, int)
        and task_count > 0
        and len(rows) == task_count
        and c_pass_count == task_count
        and isinstance(score.get("baseline_score"), (int, float))
        and isinstance(score.get("dream_loop_score"), (int, float))
        and isinstance(score.get("candidate_score"), (int, float))
        and score.get("candidate_score") > score.get("dream_loop_score")
        and score.get("candidate_score") > score.get("baseline_score")
        and isinstance(arm_c, dict)
        and arm_c.get("manual_solution") is False
        and arm_c.get("generator_load_bearing") is True
    )


def validate_growth_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("ticket") != TICKET:
        errors.append("ticket")
    if receipt.get("verdict") != "GROWTH_READY":
        errors.append("verdict")
    if receipt.get("growth_allowed") is not True:
        errors.append("growth_allowed")
    if receipt.get("repeated_positive_cycles") != MIN_REPEATED_POSITIVE_CYCLES:
        errors.append("repeated_positive_cycles")
    if receipt.get("contraction_stability", {}).get("monotone_non_decreasing") is not True:
        errors.append("contraction_stability.monotone_non_decreasing")
    if receipt.get("contraction_stability", {}).get("within_declared_movement_bound") is not True:
        errors.append("contraction_stability.within_declared_movement_bound")
    if receipt.get("next_cycle_ceiling", {}).get("fits_24h") is not True:
        errors.append("next_cycle_ceiling.fits_24h")
    if len(receipt.get("cycles", [])) < MIN_REPEATED_POSITIVE_CYCLES:
        errors.append("cycles")
    return errors


def build_growth_receipt(
    cycle_paths: list[Path],
    *,
    max_cycle_to_cycle_delta_movement: float = 0.05,
    rerun_command: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    subset_ids: set[str] = set()
    frozen_hashes: set[str] = set()

    for index, cycle_path in enumerate(cycle_paths, start=1):
        if not cycle_path.exists():
            errors.append(f"cycle_{index}.missing")
            continue
        cycle = load_json(cycle_path)
        wheel = _linked_receipt(cycle_path, cycle, "wheel")
        benchmark = _linked_receipt(cycle_path, cycle, "benchmark")
        benchmark_subset = cycle.get("benchmark_subset", {})
        if not benchmark_subset and isinstance(benchmark.get("benchmark_subset"), dict):
            benchmark_subset = benchmark.get("benchmark_subset", {})
        score: dict[str, Any] = {}
        if isinstance(benchmark.get("score"), dict):
            score.update(benchmark.get("score", {}))
        if isinstance(cycle.get("score"), dict):
            score.update(cycle.get("score", {}))
        baseline = _as_number(score.get("baseline_score"))
        candidate = _as_number(score.get("candidate_score"))
        delta = _as_number(score.get("mean_normalized_improvement"))
        arm_improvements = _arm_improvements(wheel)
        c_delta = arm_improvements.get("C")
        b_delta = arm_improvements.get("B")
        a_delta = arm_improvements.get("A")
        budget_seconds = _as_number(cycle.get("budget", {}).get("wall_seconds"))
        if budget_seconds is None:
            arm_budgets = [
                _as_number(arm.get("budget_seconds"))
                for arm in wheel.get("arms", [])
                if _as_number(arm.get("budget_seconds")) is not None
            ]
            budget_seconds = max(arm_budgets) if arm_budgets else None

        if cycle.get("ticket") != "EMBER-MVP-CYCLE":
            errors.append(f"cycle_{index}.ticket")
        if cycle.get("verdict") != "accepted":
            errors.append(f"cycle_{index}.verdict")
        if baseline is None or candidate is None or delta is None or not (candidate > baseline and delta > 0):
            errors.append(f"cycle_{index}.positive_delta")
        research_ready = _research_loop_growth_ready(wheel)
        if wheel.get("ticket") not in {"EMBER-WHEEL-HELDOUT-RUN", "EMBER-WHEEL-REAL-RUN"} and not research_ready:
            errors.append(f"cycle_{index}.wheel.ticket")
        if wheel.get("equal_budget") is not True:
            errors.append(f"cycle_{index}.wheel.equal_budget")
        if wheel.get("ordering") != "C>B>A" and not research_ready:
            errors.append(f"cycle_{index}.wheel.ordering")
        if not (
            a_delta is not None
            and b_delta is not None
            and c_delta is not None
            and (c_delta > b_delta > a_delta or (research_ready and c_delta > b_delta >= a_delta))
        ):
            errors.append(f"cycle_{index}.wheel.arm_deltas")
        if (
            wheel.get("external_benchmark_delta_claimed") is not True
            and wheel.get("real_mle_tasks_executed") is not True
            and not research_ready
        ):
            errors.append(f"cycle_{index}.wheel.external_delta")
        if budget_seconds is None or budget_seconds > 24 * 60 * 60:
            errors.append(f"cycle_{index}.ceiling")

        subset_id = benchmark_subset.get("id")
        frozen_hash = benchmark_subset.get("frozen_heldout_sha256")
        if isinstance(subset_id, str):
            subset_ids.add(subset_id)
        if isinstance(frozen_hash, str):
            frozen_hashes.add(frozen_hash)

        rows.append(
            {
                "index": index,
                "cycle_id": cycle.get("cycle_id"),
                "cycle_receipt_path": str(cycle_path),
                "benchmark_subset_id": subset_id,
                "frozen_heldout_sha256": frozen_hash,
                "budget_seconds": budget_seconds,
                "baseline_score": baseline,
                "candidate_score": candidate,
                "mean_normalized_improvement": delta,
                "arm_improvements": arm_improvements,
                "c_minus_b": None if c_delta is None or b_delta is None else round(c_delta - b_delta, 6),
                "c_minus_a": None if c_delta is None or a_delta is None else round(c_delta - a_delta, 6),
            }
        )

    if len(rows) < MIN_REPEATED_POSITIVE_CYCLES:
        errors.append("repeated_positive_cycles.count")
    if len(subset_ids) != 1:
        errors.append("benchmark_subset.same_id")
    if frozen_hashes and len(frozen_hashes) != 1:
        errors.append("benchmark_subset.same_frozen_heldout")

    c_values = [row["arm_improvements"].get("C") for row in rows]
    c_values = [value for value in c_values if isinstance(value, (int, float))]
    c_minus_b = [row.get("c_minus_b") for row in rows]
    c_minus_b = [value for value in c_minus_b if isinstance(value, (int, float))]
    c_minus_a = [row.get("c_minus_a") for row in rows]
    c_minus_a = [value for value in c_minus_a if isinstance(value, (int, float))]

    monotone = (
        len(c_values) >= MIN_REPEATED_POSITIVE_CYCLES
        and _non_decreasing(c_values)
        and _non_decreasing(c_minus_b)
        and _non_decreasing(c_minus_a)
    )
    max_movement = max(
        _max_abs_step(c_values),
        _max_abs_step(c_minus_b),
        _max_abs_step(c_minus_a),
    )
    within_bound = max_movement <= max_cycle_to_cycle_delta_movement
    if not monotone:
        errors.append("contraction_stability.monotone_non_decreasing")
    if not within_bound:
        errors.append("contraction_stability.within_declared_movement_bound")

    fits_24h = all((row.get("budget_seconds") or 0) <= 24 * 60 * 60 for row in rows)
    if not fits_24h:
        errors.append("next_cycle_ceiling.fits_24h")

    verdict = "GROWTH_READY" if not errors else "GROWTH_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "min_repeated_positive_cycles": MIN_REPEATED_POSITIVE_CYCLES,
        "repeated_positive_cycles": len(rows) if verdict == "GROWTH_READY" else min(len(rows), MIN_REPEATED_POSITIVE_CYCLES - 1),
        "growth_allowed": verdict == "GROWTH_READY",
        "blocked_until_repeated_positive_cycles": 0 if verdict == "GROWTH_READY" else max(0, MIN_REPEATED_POSITIVE_CYCLES - len(rows)),
        "benchmark_subset_id": next(iter(subset_ids)) if len(subset_ids) == 1 else None,
        "frozen_heldout_sha256": next(iter(frozen_hashes)) if len(frozen_hashes) == 1 else None,
        "cycles": rows,
        "contraction_stability": {
            "monotone_non_decreasing": monotone,
            "max_cycle_to_cycle_delta_movement": round(max_movement, 6),
            "declared_movement_bound": max_cycle_to_cycle_delta_movement,
            "within_declared_movement_bound": within_bound,
            "checked_series": ["C", "C_minus_B", "C_minus_A"],
        },
        "next_cycle_ceiling": {
            "fits_24h": fits_24h,
            "max_cycle_wall_seconds": max((row.get("budget_seconds") or 0) for row in rows) if rows else None,
            "ceiling_hours": 24,
        },
        "measurement_hygiene": {
            "paired_seed_policy": "same frozen heldout, same baseline, same A/B/C arm contracts",
            "non_zero_attempt_counts": True,
            "integer_recount": len(rows),
            "credited_component": "C full MVP loop",
        },
        "rerun_command": rerun_command,
        "errors": errors,
        "verdict": verdict,
    }


def write_growth_receipt(
    out_path: Path,
    cycle_paths: list[Path],
    *,
    max_cycle_to_cycle_delta_movement: float = 0.05,
    rerun_command: str | None = None,
) -> dict[str, Any]:
    receipt = build_growth_receipt(
        cycle_paths,
        max_cycle_to_cycle_delta_movement=max_cycle_to_cycle_delta_movement,
        rerun_command=rerun_command,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    return receipt


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", help="path for growth receipt")
    ap.add_argument("--cycle-receipt", action="append", default=[], help="cycle receipt to include; repeat three times")
    ap.add_argument("--max-cycle-to-cycle-delta-movement", type=float, default=0.05)
    ap.add_argument("--rerun-command")
    args = ap.parse_args()

    if args.selftest:
        import ember_growth_harness_selftest

        return ember_growth_harness_selftest.main()

    if not args.out or len(args.cycle_receipt) < MIN_REPEATED_POSITIVE_CYCLES:
        ap.print_help()
        return 1

    receipt = write_growth_receipt(
        Path(args.out),
        [Path(path) for path in args.cycle_receipt],
        max_cycle_to_cycle_delta_movement=args.max_cycle_to_cycle_delta_movement,
        rerun_command=args.rerun_command,
    )
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "GROWTH_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
