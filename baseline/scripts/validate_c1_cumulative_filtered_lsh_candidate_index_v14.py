#!/usr/bin/env python3
"""Validate a v14-filtered LSH candidate-index materialization receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILTERED_VIEW = "receipts/4090-cumulative-filtered-corpus-view-v14-2026-07-01.json"
EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v14-2026-07-01.jsonl"
VALID_VERDICT = "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V14_MATERIALIZED_NOT_COMPLETION"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--expected-band-starts", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_rel = args.receipt.replace("\\", "/")
    receipt_path = root / receipt_rel
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    filtered = read_json(root / FILTERED_VIEW) if (root / FILTERED_VIEW).exists() else {}
    exclusions = read_jsonl(root / EXCLUSION_MANIFEST) if (root / EXCLUSION_MANIFEST).exists() else []
    expected_bands = [int(part.strip()) for part in args.expected_band_starts.split(",") if part.strip()]
    failures: list[dict[str, Any]] = []

    if not receipt_path.exists():
        failures.append({"code": "receipt_missing", "path": receipt_rel})
    if receipt.get("verdict") != VALID_VERDICT:
        failures.append({"code": "bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("band_starts_materialized") != expected_bands:
        failures.append({"code": "band_starts_mismatch", "actual": receipt.get("band_starts_materialized"), "expected": expected_bands})
    if receipt.get("band_count_materialized") != len(expected_bands):
        failures.append({"code": "band_count_mismatch", "actual": receipt.get("band_count_materialized"), "expected": len(expected_bands)})
    if receipt.get("source_filtered_view_receipt") != FILTERED_VIEW:
        failures.append({"code": "filtered_view_receipt_mismatch", "actual": receipt.get("source_filtered_view_receipt")})
    if receipt.get("source_exclusion_manifest") != EXCLUSION_MANIFEST:
        failures.append({"code": "exclusion_manifest_mismatch", "actual": receipt.get("source_exclusion_manifest")})
    if receipt.get("excluded_document_count") != len(exclusions):
        failures.append({"code": "excluded_document_count_mismatch", "actual": receipt.get("excluded_document_count"), "expected": len(exclusions)})
    if receipt.get("full_document_coverage") is not True:
        failures.append({"code": "not_full_document_coverage"})
    if receipt.get("documents_seen") != filtered.get("source_corpus", {}).get("documents_seen"):
        failures.append({"code": "documents_seen_mismatch", "actual": receipt.get("documents_seen"), "expected": filtered.get("source_corpus", {}).get("documents_seen")})
    if receipt.get("threshold") != 0.8 or receipt.get("shingle_size_tokens") != 13:
        failures.append({"code": "policy_threshold_mismatch", "threshold": receipt.get("threshold"), "shingle_size": receipt.get("shingle_size_tokens")})
    if receipt.get("signature_size") != 64 or receipt.get("band_size") != 4:
        failures.append({"code": "signature_policy_mismatch", "signature_size": receipt.get("signature_size"), "band_size": receipt.get("band_size")})
    if receipt.get("collision_bucket_count", 0) < 1 or receipt.get("index_row_count") != receipt.get("collision_bucket_count"):
        failures.append({"code": "collision_index_count_invalid", "collision_bucket_count": receipt.get("collision_bucket_count"), "index_row_count": receipt.get("index_row_count")})
    if receipt.get("collision_document_memberships", 0) < receipt.get("collision_bucket_count", 0) * 2:
        failures.append({"code": "collision_memberships_invalid", "memberships": receipt.get("collision_document_memberships"), "buckets": receipt.get("collision_bucket_count")})
    if receipt.get("candidate_pair_upper_bound_before_deduplication", 0) < receipt.get("collision_bucket_count", 0):
        failures.append({"code": "candidate_pair_upper_bound_invalid", "actual": receipt.get("candidate_pair_upper_bound_before_deduplication")})
    index_path = root / str(receipt.get("index_path", ""))
    if not index_path.exists():
        failures.append({"code": "index_missing", "path": receipt.get("index_path")})
    elif sha256_file(index_path) != receipt.get("index_sha256"):
        failures.append({"code": "index_sha256_mismatch", "path": receipt.get("index_path")})
    if "not exact Jaccard adjudication" not in str(receipt.get("scope_limit", "")):
        failures.append({"code": "scope_limit_missing_adjudication_guard"})
    if "Exact candidate-pair Jaccard adjudication" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_adjudication_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V14_VALIDATED" if not failures else "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V14_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": receipt_rel,
        "summary": {
            "band_starts_materialized": receipt.get("band_starts_materialized"),
            "collision_bucket_count": receipt.get("collision_bucket_count"),
            "collision_document_memberships": receipt.get("collision_document_memberships"),
            "candidate_pair_upper_bound_before_deduplication": receipt.get("candidate_pair_upper_bound_before_deduplication"),
            "max_bucket_size": receipt.get("max_bucket_size"),
            "index_path": receipt.get("index_path"),
        },
        "completion_limit": "This validates LSH candidate-index materialization only. It is not exact near-duplicate adjudication, not a C1 hygiene pass, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
