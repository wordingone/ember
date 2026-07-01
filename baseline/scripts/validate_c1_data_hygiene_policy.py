#!/usr/bin/env python3
"""Validate locked C1 data-hygiene policy thresholds."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = read_json(root / RECEIPT) if (root / RECEIPT).exists() else {}
    failures: list[dict[str, Any]] = []
    if receipt.get("verdict") != "C1_DATA_HYGIENE_POLICY_THRESHOLDS_LOCKED":
        failures.append({"code": "bad_verdict", "actual": receipt.get("verdict")})
    doc = receipt.get("document_unit", {})
    if doc.get("document_count") != 4236458 or doc.get("stream_tokens") != 6977868758:
        failures.append({"code": "document_unit_mismatch", "actual": doc})
    thresholds = receipt.get("thresholds", {})
    exact = thresholds.get("exact_duplicate", {})
    if exact.get("pass_rule") != "duplicate_documents == 0 and duplicate_document_tokens == 0":
        failures.append({"code": "exact_duplicate_rule_not_locked", "actual": exact})
    near = thresholds.get("near_duplicate_minhash", {})
    if near.get("shingle_size_tokens") != 13:
        failures.append({"code": "near_duplicate_shingle_size_mismatch", "actual": near.get("shingle_size_tokens")})
    if float(near.get("primary_jaccard_threshold", -1)) != 0.80 or float(near.get("high_confidence_jaccard_threshold", -1)) != 0.90:
        failures.append({"code": "near_duplicate_threshold_mismatch", "actual": near})
    if near.get("status") != "LOCKED_NOT_YET_SCANNED":
        failures.append({"code": "near_duplicate_status_not_locked_gap", "actual": near.get("status")})
    contam = thresholds.get("eval_contamination", {})
    if contam.get("min_exact_ngram_tokens") != 32 or contam.get("min_normalized_char_span") != 200:
        failures.append({"code": "contamination_threshold_mismatch", "actual": contam})
    if contam.get("status") != "LOCKED_NOT_YET_SCANNED":
        failures.append({"code": "contamination_status_not_locked_gap", "actual": contam.get("status")})
    if "not a near-duplicate scan" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_scope_guard"})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_DATA_HYGIENE_POLICY_THRESHOLDS_VALIDATED" if not failures else "C1_DATA_HYGIENE_POLICY_THRESHOLDS_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "completion_limit": "This validates threshold policy only. It is not a near-duplicate scan, not an eval-contamination scan, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
