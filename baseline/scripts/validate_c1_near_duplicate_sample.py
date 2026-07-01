#!/usr/bin/env python3
"""Validate the bounded C1 near-duplicate MinHash sample receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-near-duplicate-minhash-sample-2026-06-30.json"
PASS_VERDICTS = {
    "C1_NEAR_DUPLICATE_SAMPLE_NO_CROSSING_CANDIDATES",
    "C1_NEAR_DUPLICATE_SAMPLE_CANDIDATES_FOUND",
}


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
    if receipt.get("verdict") not in PASS_VERDICTS:
        failures.append({"code": "near_duplicate_sample_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("sampled_documents", 0) < 50000:
        failures.append({"code": "sampled_documents_below_floor", "actual": receipt.get("sampled_documents")})
    if receipt.get("documents_seen") != 4236458:
        failures.append({"code": "document_total_mismatch", "actual": receipt.get("documents_seen")})
    if len(receipt.get("shards", [])) != 26:
        failures.append({"code": "shard_count_mismatch", "actual": len(receipt.get("shards", []))})
    if receipt.get("threshold") != 0.8 or receipt.get("shingle_size_tokens") != 13:
        failures.append({"code": "policy_threshold_mismatch", "threshold": receipt.get("threshold"), "shingle_size": receipt.get("shingle_size_tokens")})
    if "not a full corpus-wide near-duplicate PASS" not in str(receipt.get("scope_limit", "")):
        failures.append({"code": "scope_limit_missing_noncompletion_guard"})
    if "not a full near-duplicate/MinHash pass" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})
    if receipt.get("crossing_pair_count", 0) > 0 and not receipt.get("crossing_samples"):
        failures.append({"code": "crossing_count_without_samples"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_SAMPLE_VALIDATED" if not failures else "C1_NEAR_DUPLICATE_SAMPLE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "summary": {
            "sampled_documents": receipt.get("sampled_documents"),
            "eligible_documents": receipt.get("eligible_documents"),
            "candidate_pair_count": receipt.get("candidate_pair_count"),
            "crossing_pair_count": receipt.get("crossing_pair_count"),
            "max_exact_jaccard_observed": receipt.get("max_exact_jaccard_observed"),
            "verdict": receipt.get("verdict"),
        },
        "completion_limit": "This validates bounded near-duplicate sample evidence only. It is not a full near-duplicate pass, not eval-contamination evidence, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
