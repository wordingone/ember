#!/usr/bin/env python3
"""Audit mandatory Ember baseline family contracts.

The audit creates receipt evidence that each family has a concrete contract/protocol/report/source
surface. It does not mark any family complete and cannot satisfy the ultimate baseline by itself.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORBIDDEN_STATUS = {
    "OUT_OF_SCOPE_FOR_THIS_BASELINE_RELEASE",
    "OUT_OF_SCOPE",
    "DEFERRED",
    "OPTIONAL",
    "TODO",
    "TBD",
    "STAGING_ONLY",
    "OPERATOR_ACCEPTANCE_ASSUMED",
    "USER_WILL_PROBABLY_ACCEPT",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_sources(path: Path) -> set[str]:
    ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                ids.add(json.loads(line).get("id"))
    return ids


def check_family(root: Path, family: str, row: dict[str, Any], source_ids: set[str]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for field in ("contract_path", "protocol_path", "report_path", "field_relevance"):
        if not row.get(field):
            failures.append({"code": "missing_lock_field", "field": field})
    for field in ("contract_path", "protocol_path", "report_path"):
        rel = row.get(field)
        if rel and not (root / rel).exists():
            failures.append({"code": "referenced_path_missing", "field": field, "path": rel})
    missing_sources = [sid for sid in row.get("source_rows", []) if sid not in source_ids]
    if missing_sources:
        failures.append({"code": "source_rows_missing", "ids": missing_sources})
    status = str(row.get("status", ""))
    if status in FORBIDDEN_STATUS:
        failures.append({"code": "forbidden_family_status", "status": status})
    text_hits = []
    for field in ("contract_path", "protocol_path", "report_path"):
        rel = row.get(field)
        path = root / rel if rel else None
        if path and path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for term in FORBIDDEN_STATUS:
                if term in text:
                    text_hits.append({"path": rel, "term": term})
    if text_hits:
        failures.append({"code": "forbidden_terms_in_family_files", "hits": text_hits})
    return {
        "family": family,
        "status_in_lock": row.get("status"),
        "verdict": "CONTRACT_AUDIT_PASS_NOT_BASELINE_COMPLETE" if not failures else "CONTRACT_AUDIT_FAIL",
        "failures": failures,
        "checked_paths": {field: row.get(field) for field in ("contract_path", "protocol_path", "report_path")},
        "source_rows": row.get("source_rows", []),
        "field_relevance_present": bool(row.get("field_relevance")),
        "completion_limit": "This receipt checks family contract surface readiness only. The family remains incomplete until its baseline module, locked thresholds, governed receipts, and final verifier PASS exist.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    lock = read_json(root / "completion-lock.json")
    source_ids = read_sources(root / "sources.jsonl")
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out_dir = args.out_dir.resolve()
    summary_path = args.summary.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for family, row in lock.get("mandatory_claim_families", {}).items():
        result = check_family(root, family, row, source_ids)
        result["created_at_utc"] = created_at
        result["overall_goal_status"] = lock.get("status")
        receipt_path = out_dir / f"{family}.json"
        receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        results.append({"family": family, "receipt": str(receipt_path.relative_to(root)), "verdict": result["verdict"], "failure_count": len(result["failures"])})
    summary = {
        "created_at_utc": created_at,
        "verdict": "CONTRACT_AUDIT_PASS_NOT_BASELINE_COMPLETE" if all(r["failure_count"] == 0 for r in results) else "CONTRACT_AUDIT_FAIL",
        "family_count": len(results),
        "families": results,
        "completion_limit": "This audit does not complete the baseline. It only records that family contract surfaces are present and source rows resolve.",
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["verdict"] == "CONTRACT_AUDIT_PASS_NOT_BASELINE_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
