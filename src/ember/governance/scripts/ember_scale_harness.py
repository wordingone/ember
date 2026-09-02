#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded scale-up verifier for Ember MVP cycles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
TICKET = "EMBER-BOUNDED-SCALE-UP"
BASE_BUDGET_SECONDS = 3600
MAX_CLOSED_CYCLE_SECONDS = 24 * 60 * 60


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


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _arm_improvements(wheel: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for arm in wheel.get("arms", []):
        value = _number(arm.get("normalized_improvement"))
        if isinstance(arm.get("id"), str) and value is not None:
            out[arm["id"]] = value
    return out


def _equal_budget(arms: list[dict[str, Any]]) -> float | None:
    budgets = {_number(arm.get("budget_seconds")) for arm in arms}
    budgets.discard(None)
    if len(budgets) == 1:
        return next(iter(budgets))
    return None


def validate_scale_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("ticket") != TICKET:
        errors.append("ticket")
    if receipt.get("verdict") != "SCALE_UP_READY":
        errors.append("verdict")
    if receipt.get("scale_allowed") is not True:
        errors.append("scale_allowed")
    if receipt.get("growth_prerequisite", {}).get("ready") is not True:
        errors.append("growth_prerequisite.ready")
    if receipt.get("operator_decision", {}).get("ready") is not True:
        errors.append("operator_decision.ready")
    if receipt.get("next_cycle_ceiling", {}).get("fits_24h") is not True:
        errors.append("next_cycle_ceiling.fits_24h")
    if receipt.get("benchmark_continuity", {}).get("same_subset_as_growth") is not True:
        errors.append("benchmark_continuity.same_subset_as_growth")
    if receipt.get("wheel", {}).get("equal_budget") is not True:
        errors.append("wheel.equal_budget")
    if receipt.get("wheel", {}).get("ordering") != "C>B>A":
        errors.append("wheel.ordering")
    if receipt.get("score", {}).get("mean_normalized_improvement", 0) <= 0:
        errors.append("score.mean_normalized_improvement")
    return errors


def build_scale_receipt(
    cycle_path: Path,
    growth_receipt_path: Path,
    operator_decision_path: Path | None,
    *,
    target_budget_seconds: int,
    base_budget_seconds: int = BASE_BUDGET_SECONDS,
) -> dict[str, Any]:
    errors: list[str] = []
    cycle = load_json(cycle_path)
    wheel = _linked_receipt(cycle_path, cycle, "wheel")
    growth = load_json(growth_receipt_path)
    operator = load_json(operator_decision_path) if operator_decision_path else {}

    budget = cycle.get("budget", {})
    wall_seconds = _number(budget.get("wall_seconds"))
    train_seconds = _number(budget.get("train_seconds"))
    eval_seconds = _number(budget.get("eval_seconds"))
    wheel_budget = _equal_budget(wheel.get("arms", []))
    score = cycle.get("score", {})
    delta = _number(score.get("mean_normalized_improvement"))
    baseline = _number(score.get("baseline_score"))
    candidate = _number(score.get("candidate_score"))
    improvements = _arm_improvements(wheel)

    if growth.get("verdict") != "GROWTH_READY" or growth.get("growth_allowed") is not True:
        errors.append("scale.growth_prerequisite")
    operator_action = operator.get("selected_next_action", {})
    operator_ready = (
        operator.get("ticket") == "EMBER-SELF-GROWTH-OPERATOR-DECISION"
        and operator.get("verdict") == "SELF_GROWTH_OPERATOR_READY"
        and operator.get("manual_selection") is False
        and operator_action.get("kind") == "bounded_scale_up"
        and operator_action.get("target_budget_seconds") == target_budget_seconds
        and operator.get("deletion_load_bearing_test", {}).get("degrades_without_operator") is True
    )
    if not operator_ready:
        errors.append("scale.operator_decision")
    if cycle.get("ticket") != "EMBER-MVP-CYCLE" or cycle.get("verdict") != "accepted":
        errors.append("scale.cycle")
    if wall_seconds != float(target_budget_seconds):
        errors.append("scale.target_budget")
    if train_seconds != wall_seconds or eval_seconds != wall_seconds:
        errors.append("scale.budget_components")
    if wheel_budget != wall_seconds:
        errors.append("scale.wheel_budget")
    if wall_seconds is None or wall_seconds > MAX_CLOSED_CYCLE_SECONDS:
        errors.append("scale.next_cycle_ceiling")
    if wall_seconds is None or wall_seconds <= base_budget_seconds:
        errors.append("scale.factor")
    if not (baseline is not None and candidate is not None and delta is not None and candidate > baseline and delta > 0):
        errors.append("scale.positive_delta")
    if not (
        improvements.get("A") is not None
        and improvements.get("B") is not None
        and improvements.get("C") is not None
        and improvements["C"] > improvements["B"] > improvements["A"]
    ):
        errors.append("scale.wheel_ordering")
    if wheel.get("equal_budget") is not True:
        errors.append("scale.equal_budget")

    subset = cycle.get("benchmark_subset", {})
    same_subset = (
        subset.get("id") == growth.get("benchmark_subset_id")
        and subset.get("frozen_heldout_sha256") == growth.get("frozen_heldout_sha256")
    )
    if not same_subset:
        errors.append("scale.benchmark_continuity")

    verdict = "SCALE_UP_READY" if not errors else "SCALE_UP_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "cycle_receipt_path": str(cycle_path),
        "growth_receipt_path": str(growth_receipt_path),
        "operator_decision_path": str(operator_decision_path) if operator_decision_path else None,
        "scale_allowed": verdict == "SCALE_UP_READY",
        "scale_factor": None if wall_seconds is None else round(wall_seconds / base_budget_seconds, 6),
        "target_budget_seconds": target_budget_seconds,
        "base_budget_seconds": base_budget_seconds,
        "growth_prerequisite": {
            "ready": growth.get("verdict") == "GROWTH_READY" and growth.get("growth_allowed") is True,
            "repeated_positive_cycles": growth.get("repeated_positive_cycles"),
            "contraction_stability": growth.get("contraction_stability"),
        },
        "operator_decision": {
            "ready": operator_ready,
            "operator_id": operator.get("operator_id"),
            "selected_next_action": operator_action,
            "deletion_load_bearing_test": operator.get("deletion_load_bearing_test"),
        },
        "next_cycle_ceiling": {
            "fits_24h": wall_seconds is not None and wall_seconds <= MAX_CLOSED_CYCLE_SECONDS,
            "wall_seconds": wall_seconds,
            "ceiling_hours": 24,
        },
        "benchmark_continuity": {
            "same_subset_as_growth": same_subset,
            "benchmark_subset_id": subset.get("id"),
            "frozen_heldout_sha256": subset.get("frozen_heldout_sha256"),
        },
        "wheel": {
            "equal_budget": wheel.get("equal_budget"),
            "arm_budget_seconds": wheel_budget,
            "ordering": wheel.get("ordering"),
            "arm_improvements": improvements,
        },
        "score": score,
        "errors": errors,
        "verdict": verdict,
    }


def write_scale_receipt(
    out_path: Path,
    cycle_path: Path,
    growth_receipt_path: Path,
    operator_decision_path: Path | None,
    *,
    target_budget_seconds: int,
    base_budget_seconds: int = BASE_BUDGET_SECONDS,
) -> dict[str, Any]:
    receipt = build_scale_receipt(
        cycle_path,
        growth_receipt_path,
        operator_decision_path,
        target_budget_seconds=target_budget_seconds,
        base_budget_seconds=base_budget_seconds,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    return receipt


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cycle-receipt")
    ap.add_argument("--growth-receipt")
    ap.add_argument("--operator-decision")
    ap.add_argument("--target-budget-seconds", type=int, default=10800)
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.selftest:
        import ember_scale_harness_selftest

        return ember_scale_harness_selftest.main()

    if not (args.cycle_receipt and args.growth_receipt and args.operator_decision and args.out):
        ap.print_help()
        return 1

    receipt = write_scale_receipt(
        Path(args.out),
        Path(args.cycle_receipt),
        Path(args.growth_receipt),
        Path(args.operator_decision),
        target_budget_seconds=args.target_budget_seconds,
    )
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "SCALE_UP_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
