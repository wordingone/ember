#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Prospective self-growth operator for Ember MVP loops."""
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
TICKET = "EMBER-SELF-GROWTH-OPERATOR-DECISION"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _growth_ready(readiness: dict[str, Any]) -> bool:
    return bool(
        readiness.get("verdict") == "MVP_READY"
        and readiness.get("growth_verdict") == "GROWTH_READY"
        and readiness.get("growth_receipt", {}).get("ready") is True
    )


def _scale_ready(scale: dict[str, Any]) -> bool:
    return bool(
        scale.get("verdict") == "SCALE_UP_READY"
        and scale.get("scale_allowed") is True
        and scale.get("operator_decision", {}).get("ready") is True
        and scale.get("next_cycle_ceiling", {}).get("fits_24h") is True
    )


def validate_operator_decision(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("ticket") != TICKET:
        errors.append("ticket")
    if receipt.get("verdict") != "SELF_GROWTH_OPERATOR_READY":
        errors.append("verdict")
    action = receipt.get("selected_next_action", {})
    if action.get("kind") not in {"bounded_scale_up", "stronger_external_benchmark"}:
        errors.append("selected_next_action.kind")
    if action.get("selected_by") != "receipt_trace_next_cycle_router_v1":
        errors.append("selected_next_action.selected_by")
    if action.get("kind") == "stronger_external_benchmark":
        if action.get("benchmark_family") != "research_journal":
            errors.append("selected_next_action.benchmark_family")
        if action.get("preferred_candidate") != "ScienceAgentBench":
            errors.append("selected_next_action.preferred_candidate")
        if "research-benchmark-admission" not in action.get("required_next_receipts", []):
            errors.append("selected_next_action.required_next_receipts")
    if receipt.get("manual_selection") is not False:
        errors.append("manual_selection")
    if receipt.get("deletion_load_bearing_test", {}).get("degrades_without_operator") is not True:
        errors.append("deletion_load_bearing_test.degrades_without_operator")
    if receipt.get("deletion_load_bearing_test", {}).get("deleted_action", {}).get("kind") != "blocked_manual_selection_forbidden":
        errors.append("deletion_load_bearing_test.deleted_action")
    return errors


def build_operator_decision(
    readiness_path: Path,
    *,
    scale_receipt_path: Path | None = None,
    operator_deleted: bool = False,
) -> dict[str, Any]:
    readiness = load_json(readiness_path)
    errors: list[str] = []
    growth_receipt = readiness.get("growth_receipt", {}).get("receipt", {})
    scale_receipt = load_json(scale_receipt_path) if scale_receipt_path else None
    if operator_deleted:
        errors.append("operator.deleted")
        selected = {
            "kind": "blocked_manual_selection_forbidden",
            "reason": "self-growing operator deleted; Codex/manual next-action choice is not valid product behavior",
        }
        verdict = "SELF_GROWTH_OPERATOR_BLOCKED"
    elif _growth_ready(readiness):
        selected = {
            "kind": "stronger_external_benchmark",
            "benchmark_family": "research_journal",
            "preferred_candidate": "ScienceAgentBench",
            "fallback_candidates": ["SciReplicate-Bench", "ResearchBench", "PaperBench"],
            "selected_by": "receipt_trace_next_cycle_router_v1",
            "selection_basis": {
                "readiness_verdict": readiness.get("verdict"),
                "growth_verdict": readiness.get("growth_verdict"),
                "scale_verdict": scale_receipt.get("verdict") if scale_receipt else None,
                "scale_factor": scale_receipt.get("scale_factor") if scale_receipt else None,
                "benchmark_subset_id": growth_receipt.get("benchmark_subset_id"),
                "frozen_heldout_sha256": growth_receipt.get("frozen_heldout_sha256"),
            },
            "required_next_receipts": [
                "research-benchmark-admission",
                "external-heldout-a-b-c-cycle",
                "operator-deletion-test",
                "readiness",
            ],
        }
        verdict = "SELF_GROWTH_OPERATOR_READY"
    else:
        errors.append("growth.not_ready")
        selected = {
            "kind": "repeat_growth_window",
            "selected_by": "receipt_trace_next_cycle_router_v1",
            "reason": "growth gate is not ready; repeat external-heldout A/B/C cycle",
        }
        verdict = "SELF_GROWTH_OPERATOR_BLOCKED"

    deleted_action = {
        "kind": "blocked_manual_selection_forbidden",
        "reason": "without the operator, the harness refuses to route a scale-up or benchmark replacement",
    }
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "readiness_receipt_path": str(readiness_path),
        "scale_receipt_path": str(scale_receipt_path) if scale_receipt_path else None,
        "operator_id": "receipt_trace_next_cycle_router_v1",
        "manual_selection": False,
        "selected_next_action": selected,
        "deletion_load_bearing_test": {
            "operator_deleted": operator_deleted,
            "deleted_action": deleted_action,
            "degrades_without_operator": selected.get("kind") != deleted_action["kind"],
            "must_degrade": "next-loop routing",
        },
        "errors": errors,
        "verdict": verdict,
    }


def write_operator_decision(
    out_path: Path,
    readiness_path: Path,
    *,
    scale_receipt_path: Path | None = None,
    operator_deleted: bool = False,
) -> dict[str, Any]:
    receipt = build_operator_decision(
        readiness_path,
        scale_receipt_path=scale_receipt_path,
        operator_deleted=operator_deleted,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    return receipt


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--readiness-receipt")
    ap.add_argument("--scale-receipt")
    ap.add_argument("--out")
    ap.add_argument("--operator-deleted", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        import ember_operator_harness_selftest

        return ember_operator_harness_selftest.main()

    if not (args.readiness_receipt and args.out):
        ap.print_help()
        return 1

    receipt = write_operator_decision(
        Path(args.out),
        Path(args.readiness_receipt),
        scale_receipt_path=Path(args.scale_receipt) if args.scale_receipt else None,
        operator_deleted=args.operator_deleted,
    )
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "SELF_GROWTH_OPERATOR_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
