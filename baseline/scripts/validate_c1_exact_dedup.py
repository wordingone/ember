#!/usr/bin/env python3
"""Validate the C1 exact-document dedupe scan receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-exact-dedupe-scan-2026-06-30.json"
PASS_VERDICT = "C1_EXACT_DEDUPE_PASS"


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
    if receipt.get("verdict") != PASS_VERDICT:
        failures.append({"code": "exact_dedupe_not_pass", "actual": receipt.get("verdict")})
    if receipt.get("duplicate_documents") != 0 or receipt.get("duplicate_document_tokens") != 0:
        failures.append({"code": "duplicates_present", "duplicate_documents": receipt.get("duplicate_documents"), "duplicate_document_tokens": receipt.get("duplicate_document_tokens")})
    if receipt.get("total_stream_tokens") != 6977868758:
        failures.append({"code": "stream_token_total_mismatch", "actual": receipt.get("total_stream_tokens")})
    if receipt.get("separator_tokens") != 4236458:
        failures.append({"code": "separator_total_mismatch", "actual": receipt.get("separator_tokens")})
    if receipt.get("source_receipt") != "receipts/token-shards-v0-20260611T170047Z.json":
        failures.append({"code": "source_receipt_mismatch", "actual": receipt.get("source_receipt")})
    if len(receipt.get("shards", [])) != 26:
        failures.append({"code": "shard_count_mismatch", "actual": len(receipt.get("shards", []))})
    if "not a near-duplicate/MinHash scan" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_scope_guard"})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_EXACT_DEDUPE_VALIDATED" if not failures else "C1_EXACT_DEDUPE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "completion_limit": "This validates exact token-document dedupe only. It is not near-duplicate, eval-contamination, long-run training, or overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
