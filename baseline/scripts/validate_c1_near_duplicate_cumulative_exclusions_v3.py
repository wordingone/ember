#!/usr/bin/env python3
"""Validate cumulative C1 near-duplicate exclusion materialization v3."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v3-2026-06-30.json"
VALIDATION_RECEIPT = "receipts/4090-cumulative-filtered-challenge-remediation-v3-validation-2026-06-30.json"
SOURCE_TARGETED_RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v2-2026-06-30.json"
SOURCE_CHALLENGE_RECEIPT = "receipts/4090-cumulative-filtered-challenge-remediation-v3-2026-06-30.json"
MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v3-2026-06-30.jsonl"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = read_json(root / RECEIPT) if (root / RECEIPT).exists() else {}
    challenge_validation = read_json(root / VALIDATION_RECEIPT) if (root / VALIDATION_RECEIPT).exists() else {}
    targeted = read_json(root / SOURCE_TARGETED_RECEIPT) if (root / SOURCE_TARGETED_RECEIPT).exists() else {}
    challenge = read_json(root / SOURCE_CHALLENGE_RECEIPT) if (root / SOURCE_CHALLENGE_RECEIPT).exists() else {}
    rows = read_jsonl(root / MANIFEST)
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V3_READY":
        failures.append({"code": "bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("manifest", {}).get("repo_path") != MANIFEST:
        failures.append({"code": "manifest_path_mismatch", "actual": receipt.get("manifest", {}).get("repo_path")})
    if receipt.get("source_targeted_exclusion_receipt") != SOURCE_TARGETED_RECEIPT:
        failures.append({"code": "source_targeted_receipt_mismatch", "actual": receipt.get("source_targeted_exclusion_receipt")})
    if receipt.get("source_challenge_remediation_receipt") != SOURCE_CHALLENGE_RECEIPT:
        failures.append({"code": "source_challenge_receipt_mismatch", "actual": receipt.get("source_challenge_remediation_receipt")})
    if challenge_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CHALLENGE_REMEDIATION_V3_VALIDATED":
        failures.append({"code": "challenge_remediation_not_validated", "actual": challenge_validation.get("verdict")})

    targeted_count = int(targeted.get("exclusion_document_count", -1))
    challenge_count = int(challenge.get("challenge_exclusion_document_count", -1))
    declared_count = int(receipt.get("exclusion_document_count", -1))
    if targeted_count < 1 or challenge_count < 1:
        failures.append({"code": "source_counts_missing", "targeted": targeted_count, "challenge": challenge_count})
    if declared_count != targeted_count + challenge_count or declared_count != len(rows):
        failures.append({"code": "exclusion_count_mismatch", "declared": declared_count, "rows": len(rows), "targeted_plus_challenge": targeted_count + challenge_count})

    token_floor = sum(int(row.get("token_len", 0)) for row in rows)
    expected_floor = int(targeted.get("exclusion_token_floor", -1)) + int(challenge.get("challenge_exclusion_token_floor", -1))
    if receipt.get("exclusion_token_floor") != token_floor or token_floor != expected_floor:
        failures.append({"code": "token_floor_mismatch", "declared": receipt.get("exclusion_token_floor"), "rows": token_floor, "expected": expected_floor})

    seen_doc_indices: dict[int, str] = {}
    seen_keys = set()
    source_counts: dict[str, int] = {}
    for row in rows:
        doc_index = int(row.get("doc_index", -1))
        doc_sha = str(row.get("doc_sha256", ""))
        key = (doc_index, doc_sha)
        if key in seen_keys:
            failures.append({"code": "duplicate_doc_key", "doc_index": doc_index, "doc_sha256": doc_sha})
        seen_keys.add(key)
        if doc_index in seen_doc_indices and seen_doc_indices[doc_index] != doc_sha:
            failures.append({"code": "doc_index_hash_conflict", "doc_index": doc_index, "first": seen_doc_indices[doc_index], "second": doc_sha})
        seen_doc_indices[doc_index] = doc_sha
        if not row.get("shard") or not doc_sha or int(row.get("token_len", 0)) <= 0:
            failures.append({"code": "bad_manifest_row", "row": row})
        source = str(row.get("source", ""))
        source_counts[source] = source_counts.get(source, 0) + 1
    if source_counts.get("cumulative_v2") != targeted_count:
        failures.append({"code": "targeted_source_count_mismatch", "source_counts": source_counts, "expected": targeted_count})
    if source_counts.get("cumulative_filtered_v2_challenge_remediation") != challenge_count:
        failures.append({"code": "challenge_source_count_mismatch", "source_counts": source_counts, "expected": challenge_count})
    if receipt.get("source_overlap_count") != 0:
        failures.append({"code": "source_overlap_nonzero", "actual": receipt.get("source_overlap_count")})
    if "not an all-pairs near-duplicate PASS" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_guard_missing"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V3_VALIDATED" if not failures else "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V3_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "summary": {
            "exclusion_document_count": declared_count if declared_count >= 0 else None,
            "exclusion_token_floor": receipt.get("exclusion_token_floor"),
            "source_counts": source_counts,
        },
        "completion_limit": "This validates cumulative discovered-cluster exclusions v3 only. It is not all-pairs/full-corpus near-duplicate PASS evidence and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
