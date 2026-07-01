#!/usr/bin/env python3
"""Validate the C1 near-duplicate targeted expansion receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json"
REMEDIATION = "receipts/4090-near-duplicate-sample-remediation-2026-06-30.json"


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
    remediation = read_json(root / REMEDIATION) if (root / REMEDIATION).exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_READY":
        failures.append({"code": "targeted_expansion_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("documents_seen") != 4236458 or receipt.get("documents_seen_first_pass") != 4236458:
        failures.append({"code": "document_total_mismatch", "first": receipt.get("documents_seen_first_pass"), "second": receipt.get("documents_seen")})
    if receipt.get("target_count") != remediation.get("cluster_count") or receipt.get("target_count", 0) < 1:
        failures.append({"code": "target_count_mismatch", "target_count": receipt.get("target_count"), "cluster_count": remediation.get("cluster_count")})
    if receipt.get("threshold") != 0.8 or receipt.get("shingle_size_tokens") != 13:
        failures.append({"code": "policy_mismatch", "threshold": receipt.get("threshold"), "shingle_size": receipt.get("shingle_size_tokens")})
    if len(receipt.get("missing_sample_exclusions", [])) != 0:
        failures.append({"code": "sample_exclusions_not_covered", "missing": receipt.get("missing_sample_exclusions")})
    if receipt.get("sample_exclusion_document_count") != remediation.get("sample_exclusion_document_count"):
        failures.append({"code": "sample_exclusion_count_mismatch", "receipt": receipt.get("sample_exclusion_document_count"), "remediation": remediation.get("sample_exclusion_document_count")})
    if receipt.get("expanded_exclusion_document_count", 0) < remediation.get("sample_exclusion_document_count", 0):
        failures.append({"code": "expanded_exclusions_below_sample_floor", "expanded": receipt.get("expanded_exclusion_document_count"), "sample": remediation.get("sample_exclusion_document_count")})
    if receipt.get("expanded_exclusion_token_floor", 0) < remediation.get("sample_exclusion_token_floor", 0):
        failures.append({"code": "expanded_token_floor_below_sample_floor", "expanded": receipt.get("expanded_exclusion_token_floor"), "sample": remediation.get("sample_exclusion_token_floor")})
    if len(receipt.get("shards", [])) != 26:
        failures.append({"code": "shard_count_mismatch", "actual": len(receipt.get("shards", []))})
    seen = set()
    for row in receipt.get("exclusions", []):
        key = (row.get("doc_index"), row.get("doc_sha256"))
        if key in seen:
            failures.append({"code": "duplicate_expanded_exclusion", "key": key})
        seen.add(key)
        if row.get("exact_jaccard_to_target", 0) < 0.8 or row.get("token_len", 0) <= 0 or not row.get("shard"):
            failures.append({"code": "bad_expanded_exclusion_row", "row": row})
    if "not an all-pairs full-corpus near-duplicate PASS" not in str(receipt.get("scope_limit", "")):
        failures.append({"code": "scope_limit_missing_noncompletion_guard"})
    if "Full all-pairs MinHash/near-duplicate scan" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_VALIDATED" if not failures else "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "summary": {
            "target_count": receipt.get("target_count"),
            "expanded_exclusion_document_count": receipt.get("expanded_exclusion_document_count"),
            "expanded_exclusion_token_floor": receipt.get("expanded_exclusion_token_floor"),
            "eligible_documents": receipt.get("eligible_documents"),
        },
        "completion_limit": "This validates targeted expansion for discovered near-duplicate clusters only. It is not an all-pairs near-duplicate pass, not C1 completion, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
