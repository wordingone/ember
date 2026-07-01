#!/usr/bin/env python3
"""Validate the v4 cumulative-filtered LSH bucket-census receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-2026-06-30.json"
FILTERED_VIEW = "receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json"
EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl"
VALID_VERDICTS = {
    "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION",
    "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_FULL_CENSUS_NOT_COMPLETION",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", default=RECEIPT, help="Receipt path relative to --root.")
    parser.add_argument("--expected-band-starts", help="Comma-separated expected band starts for this receipt.")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_rel = args.receipt.replace("\\", "/")
    receipt_path = root / receipt_rel
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    filtered = read_json(root / FILTERED_VIEW) if (root / FILTERED_VIEW).exists() else {}
    exclusions = read_jsonl(root / EXCLUSION_MANIFEST) if (root / EXCLUSION_MANIFEST).exists() else []
    view = filtered.get("cumulative_filtered_view", {}) if isinstance(filtered.get("cumulative_filtered_view"), dict) else {}
    failures: list[dict[str, Any]] = []

    if not receipt_path.exists():
        failures.append({"code": "receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") not in VALID_VERDICTS:
        failures.append({"code": "bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("source_filtered_view_receipt") != FILTERED_VIEW:
        failures.append({"code": "filtered_view_receipt_mismatch", "actual": receipt.get("source_filtered_view_receipt")})
    if receipt.get("source_exclusion_manifest") != EXCLUSION_MANIFEST:
        failures.append({"code": "exclusion_manifest_mismatch", "actual": receipt.get("source_exclusion_manifest")})
    if receipt.get("excluded_document_count") != len(exclusions):
        failures.append({"code": "excluded_document_count_mismatch", "actual": receipt.get("excluded_document_count"), "expected": len(exclusions)})
    if receipt.get("remaining_document_count") != view.get("remaining_document_count"):
        failures.append({"code": "remaining_document_count_mismatch", "actual": receipt.get("remaining_document_count"), "expected": view.get("remaining_document_count")})
    if receipt.get("threshold") != 0.8 or receipt.get("shingle_size_tokens") != 13:
        failures.append({"code": "policy_threshold_mismatch", "threshold": receipt.get("threshold"), "shingle_size": receipt.get("shingle_size_tokens")})
    if receipt.get("band_size") != 4 or receipt.get("signature_size") != 64:
        failures.append({"code": "signature_policy_mismatch", "band_size": receipt.get("band_size"), "signature_size": receipt.get("signature_size")})
    if receipt.get("band_count_scanned", 0) < 1 or not receipt.get("band_starts_scanned"):
        failures.append({"code": "no_bands_scanned", "actual": receipt.get("band_starts_scanned")})
    if args.expected_band_starts:
        expected_band_starts = [int(part.strip()) for part in args.expected_band_starts.split(",") if part.strip()]
        if receipt.get("band_starts_scanned") != expected_band_starts:
            failures.append({"code": "band_starts_mismatch", "actual": receipt.get("band_starts_scanned"), "expected": expected_band_starts})
        if receipt.get("band_count_scanned") != len(expected_band_starts):
            failures.append({"code": "band_count_mismatch", "actual": receipt.get("band_count_scanned"), "expected": len(expected_band_starts)})
    if receipt.get("documents_censused", 0) < 1:
        failures.append({"code": "no_documents_censused", "actual": receipt.get("documents_censused")})
    if receipt.get("bucket_count", 0) < 1:
        failures.append({"code": "no_buckets_recorded", "actual": receipt.get("bucket_count")})
    if receipt.get("full_document_coverage") is True and receipt.get("documents_seen") != 4236458:
        failures.append({"code": "full_coverage_document_total_mismatch", "actual": receipt.get("documents_seen")})
    if receipt.get("full_band_coverage") is True and receipt.get("band_count_scanned") != 16:
        failures.append({"code": "full_band_coverage_count_mismatch", "actual": receipt.get("band_count_scanned")})
    if "not an all-pairs near-duplicate PASS" not in str(receipt.get("scope_limit", "")):
        failures.append({"code": "scope_limit_missing_all_pairs_guard"})
    if "Exact all-pairs candidate adjudication" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED" if not failures else "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": receipt_rel,
        "summary": {
            "verdict": receipt.get("verdict"),
            "full_document_coverage": receipt.get("full_document_coverage"),
            "full_band_coverage": receipt.get("full_band_coverage"),
            "band_count_scanned": receipt.get("band_count_scanned"),
            "documents_censused": receipt.get("documents_censused"),
            "bucket_count": receipt.get("bucket_count"),
            "collision_bucket_count": receipt.get("collision_bucket_count"),
            "max_bucket_size": receipt.get("max_bucket_size"),
        },
        "completion_limit": "This validates LSH bucket-census evidence only. It is not exact all-pairs near-duplicate adjudication, not a C1 hygiene pass, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
