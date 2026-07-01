#!/usr/bin/env python3
"""Validate cumulative C1 near-duplicate exclusion materialization v12."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v12-2026-07-01.json"
BASE_VALIDATION_RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-validation-2026-07-01.json"
SOURCE_BASE_RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-2026-07-01.json"
SOURCE_REMEDIATION_RECEIPT = "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-window150-remediation-2026-07-01.json"
MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v12-2026-07-01.jsonl"


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
    base_validation = read_json(root / BASE_VALIDATION_RECEIPT) if (root / BASE_VALIDATION_RECEIPT).exists() else {}
    base = read_json(root / SOURCE_BASE_RECEIPT) if (root / SOURCE_BASE_RECEIPT).exists() else {}
    remediation = read_json(root / SOURCE_REMEDIATION_RECEIPT) if (root / SOURCE_REMEDIATION_RECEIPT).exists() else {}
    rows = read_jsonl(root / MANIFEST)
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V12_READY_NOT_COMPLETION":
        failures.append({"code": "bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("manifest", {}).get("repo_path") != MANIFEST:
        failures.append({"code": "manifest_path_mismatch", "actual": receipt.get("manifest", {}).get("repo_path")})
    if receipt.get("source_base_exclusion_receipt") != SOURCE_BASE_RECEIPT:
        failures.append({"code": "source_base_receipt_mismatch", "actual": receipt.get("source_base_exclusion_receipt")})
    if receipt.get("source_lsh_adjudication_remediation_receipt") != SOURCE_REMEDIATION_RECEIPT:
        failures.append({"code": "source_remediation_receipt_mismatch", "actual": receipt.get("source_lsh_adjudication_remediation_receipt")})
    if base_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V11_VALIDATED":
        failures.append({"code": "base_manifest_not_validated", "actual": base_validation.get("verdict")})
    if remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V11_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "remediation_bad_verdict", "actual": remediation.get("verdict")})

    base_count = int(base.get("exclusion_document_count", -1))
    remediation_count = int(remediation.get("remediation_exclusion_document_count", -1))
    declared_count = int(receipt.get("exclusion_document_count", -1))
    if base_count < 1 or remediation_count < 1:
        failures.append({"code": "source_counts_missing", "base": base_count, "remediation": remediation_count})
    if declared_count != base_count + remediation_count or declared_count != len(rows) or declared_count != 1892:
        failures.append({"code": "exclusion_count_mismatch", "declared": declared_count, "rows": len(rows), "base_plus_remediation": base_count + remediation_count, "expected": 1892})

    token_floor = sum(int(row.get("token_len", 0)) for row in rows)
    expected_floor = int(base.get("exclusion_token_floor", -1)) + int(remediation.get("remediation_exclusion_token_floor", -1))
    if receipt.get("exclusion_token_floor") != token_floor or token_floor != expected_floor or token_floor != 3250574:
        failures.append({"code": "token_floor_mismatch", "declared": receipt.get("exclusion_token_floor"), "rows": token_floor, "expected": expected_floor, "required": 3250574})

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
    if source_counts.get("cumulative_v11") != base_count:
        failures.append({"code": "base_source_count_mismatch", "source_counts": source_counts, "expected": base_count})
    if source_counts.get("lsh_band48_v11_window150_adjudication_remediation") != remediation_count:
        failures.append({"code": "remediation_source_count_mismatch", "source_counts": source_counts, "expected": remediation_count})
    if receipt.get("source_overlap_count") != 0:
        failures.append({"code": "source_overlap_nonzero", "actual": receipt.get("source_overlap_count")})
    limit = str(receipt.get("completion_limit", ""))
    for phrase in (
        "not a full band-48 remediation",
        "not an all-pairs near-duplicate PASS",
        "not eval-contamination evidence",
        "not overall baseline completion",
    ):
        if phrase not in limit:
            failures.append({"code": "completion_limit_missing_phrase", "phrase": phrase})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V12_VALIDATED" if not failures else "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V12_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "summary": {
            "exclusion_document_count": declared_count if declared_count >= 0 else None,
            "exclusion_token_floor": receipt.get("exclusion_token_floor"),
            "source_counts": source_counts,
        },
        "completion_limit": "This validates cumulative discovered-cluster exclusions v12 only. It is not full band-48/full-corpus/all-pairs near-duplicate PASS evidence and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
