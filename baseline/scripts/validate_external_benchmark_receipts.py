#!/usr/bin/env python3
"""Validate imported prior external benchmark/access receipts.

This validator proves that prior benchmark receipts were imported, hashed, and
classified without laundering blocked/auth/setup receipts into field wins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_EXECUTED = {
    "livecodebench_public_candidate_vs_baseline",
    "livecodebench_frozen_heldout_delta",
    "kaggle_external_heldout_wheel",
}

REQUIRED_GAPS = {
    "official_abc_wheel_runner_blocked",
    "official_mle_prepare_blocked",
    "kaggle_auth_preflight_blocked",
}

ALLOWED_EXECUTED_VERDICTS = {
    "PUBLIC_TEST_DELTA_RECEIPTED",
    "HELDOUT_DELTA_RECEIPTED",
    "HELDOUT_WHEEL_RECEIPTED",
}


def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--gap-out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    index_path = root / "receipts/external-benchmark-receipt-index-2026-06-30.json"
    protocol_path = root / "protocols/external-benchmark-receipt-import-v0.md"
    index = load_json(index_path) if index_path.exists() else {}
    imports = index.get("imports", []) if isinstance(index, dict) else []
    by_id = {row.get("id"): row for row in imports if isinstance(row, dict)}
    missing_executed = sorted(REQUIRED_EXECUTED - set(by_id))
    missing_gaps = sorted(REQUIRED_GAPS - set(by_id))
    if missing_executed:
        failures.append({"code": "missing_executed_imports", "ids": missing_executed})
    if missing_gaps:
        failures.append({"code": "missing_gap_imports", "ids": missing_gaps})
    if not protocol_path.exists() or "Status: SUPPORTING EVIDENCE, NOT COMPLETION" not in protocol_path.read_text(encoding="utf-8-sig", errors="replace"):
        failures.append({"code": "protocol_missing_noncompletion_guard", "path": str(protocol_path)})

    executed_count = 0
    gap_count = 0
    for row in imports:
        for field in ("id", "classification", "scope", "source_branch", "source_commit", "source_path", "import_path", "sha256", "verdict"):
            if not row.get(field):
                failures.append({"code": "import_row_missing_field", "id": row.get("id"), "field": field})
        imported = root / str(row.get("import_path", ""))
        if not imported.exists():
            failures.append({"code": "imported_receipt_missing", "id": row.get("id"), "path": row.get("import_path")})
            continue
        actual_hash = sha256_text(imported)
        if actual_hash != row.get("sha256"):
            failures.append({"code": "imported_receipt_hash_mismatch", "id": row.get("id"), "expected": row.get("sha256"), "actual": actual_hash})
        body = load_json(imported)
        if body.get("verdict") != row.get("verdict"):
            failures.append({"code": "imported_verdict_mismatch", "id": row.get("id"), "expected": row.get("verdict"), "actual": body.get("verdict")})
        classification = str(row.get("classification"))
        if classification.startswith("executed_"):
            executed_count += 1
            if row.get("verdict") not in ALLOWED_EXECUTED_VERDICTS:
                failures.append({"code": "executed_import_bad_verdict", "id": row.get("id"), "verdict": row.get("verdict")})
            if "not field-level" not in str(row.get("scope", "")) and "public-test only" not in str(row.get("scope", "")):
                failures.append({"code": "executed_import_missing_scope_limit", "id": row.get("id"), "scope": row.get("scope")})
        elif classification.startswith("blocked_"):
            gap_count += 1
            if row.get("verdict") != "BLOCKED":
                failures.append({"code": "blocked_import_not_blocked", "id": row.get("id"), "verdict": row.get("verdict")})
        else:
            failures.append({"code": "unknown_import_classification", "id": row.get("id"), "classification": classification})

    if index.get("executed_receipt_count") != executed_count:
        failures.append({"code": "executed_count_mismatch", "expected": executed_count, "actual": index.get("executed_receipt_count")})
    if index.get("blocked_or_access_gap_count") != gap_count:
        failures.append({"code": "gap_count_mismatch", "expected": gap_count, "actual": index.get("blocked_or_access_gap_count")})
    if "not overall baseline completion" not in str(index.get("completion_limit", "")):
        failures.append({"code": "index_missing_noncompletion_guard"})

    gap_result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "EXTERNAL_BENCHMARK_GAP_LEDGER_VALIDATED" if not failures else "EXTERNAL_BENCHMARK_GAP_LEDGER_INVALID",
        "gap_receipt_count": gap_count,
        "gap_receipt_ids": sorted(REQUIRED_GAPS),
        "index_path": "receipts/external-benchmark-receipt-index-2026-06-30.json",
        "completion_limit": "This validates blocked/access-gap receipt preservation only. It is not used as completed-family evidence and not overall baseline completion.",
    }
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "EXTERNAL_BENCHMARK_EXECUTED_IMPORTS_READY" if not failures else "EXTERNAL_BENCHMARK_IMPORTS_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "executed_receipt_count": executed_count,
        "executed_receipt_ids": sorted(REQUIRED_EXECUTED),
        "gap_ledger_path": "receipts/external-benchmark-gap-ledger-validation-2026-06-30.json",
        "index_path": "receipts/external-benchmark-receipt-index-2026-06-30.json",
        "completion_limit": "This validates imported executed benchmark receipts only. Blocked/access-gap receipts are preserved in the separate gap ledger and are not completed-family evidence.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    if args.gap_out:
        args.gap_out.parent.mkdir(parents=True, exist_ok=True)
        args.gap_out.write_text(json.dumps(gap_result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
