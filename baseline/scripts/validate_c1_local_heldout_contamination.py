#!/usr/bin/env python3
"""Validate local heldout exact 32-token contamination scan receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-local-heldout-contamination-scan-2026-06-30.json"


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
    if receipt.get("verdict") != "C1_LOCAL_HELDOUT_EXACT_32GRAM_CONTAMINATION_PASS":
        failures.append({"code": "local_heldout_contamination_not_pass", "actual": receipt.get("verdict")})
    if receipt.get("exact_32_token_hits") != 0:
        failures.append({"code": "exact_32_token_hits_present", "actual": receipt.get("exact_32_token_hits")})
    if receipt.get("total_stream_tokens") != 6977868758:
        failures.append({"code": "stream_token_total_mismatch", "actual": receipt.get("total_stream_tokens")})
    summary = receipt.get("pattern_summary", {})
    if summary.get("heldout_items", 0) < 1 or summary.get("total_ngram_patterns", 0) < 1:
        failures.append({"code": "heldout_patterns_missing", "actual": summary})
    if "not a full eval-suite contamination scan" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_scope_guard"})
    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_LOCAL_HELDOUT_CONTAMINATION_VALIDATED" if not failures else "C1_LOCAL_HELDOUT_CONTAMINATION_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "completion_limit": "This validates local heldout exact 32-token contamination only. It is not full eval-suite contamination, normalized-span contamination, near-duplicate scanning, or overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
