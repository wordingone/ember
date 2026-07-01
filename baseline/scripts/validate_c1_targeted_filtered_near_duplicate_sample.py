#!/usr/bin/env python3
"""Validate the C1 targeted-filtered near-duplicate challenge sample receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-targeted-filtered-near-duplicate-sample-2026-06-30.json"
FILTERED_VIEW = "receipts/4090-targeted-filtered-corpus-view-2026-06-30.json"
EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl"
VALID_VERDICTS = {
    "C1_TARGETED_FILTERED_NEAR_DUPLICATE_SAMPLE_NO_CROSSING_CANDIDATES",
    "C1_TARGETED_FILTERED_NEAR_DUPLICATE_SAMPLE_CANDIDATES_FOUND",
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
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_path = root / RECEIPT
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    filtered = read_json(root / FILTERED_VIEW) if (root / FILTERED_VIEW).exists() else {}
    exclusions = read_jsonl(root / EXCLUSION_MANIFEST) if (root / EXCLUSION_MANIFEST).exists() else []
    failures: list[dict[str, Any]] = []

    if not receipt_path.exists():
        failures.append({"code": "receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") not in VALID_VERDICTS:
        failures.append({"code": "bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("source_filtered_view_receipt") != FILTERED_VIEW:
        failures.append({"code": "filtered_view_receipt_mismatch", "actual": receipt.get("source_filtered_view_receipt")})
    if receipt.get("source_exclusion_manifest") != EXCLUSION_MANIFEST:
        failures.append({"code": "exclusion_manifest_mismatch", "actual": receipt.get("source_exclusion_manifest")})
    if receipt.get("documents_seen") != 4236458:
        failures.append({"code": "document_total_mismatch", "actual": receipt.get("documents_seen")})
    expected_excluded = len(exclusions)
    if receipt.get("excluded_document_count") != expected_excluded or expected_excluded < 1:
        failures.append({"code": "excluded_document_count_mismatch", "actual": receipt.get("excluded_document_count"), "expected": expected_excluded})
    view = filtered.get("targeted_filtered_view", {}) if isinstance(filtered.get("targeted_filtered_view"), dict) else {}
    if receipt.get("remaining_document_count") != view.get("remaining_document_count"):
        failures.append({"code": "remaining_document_count_mismatch", "actual": receipt.get("remaining_document_count"), "expected": view.get("remaining_document_count")})
    if receipt.get("sampled_documents", 0) < 50000:
        failures.append({"code": "sampled_documents_below_floor", "actual": receipt.get("sampled_documents")})
    if receipt.get("sampled_excluded_document_count") != 0:
        failures.append({"code": "excluded_documents_entered_sample", "actual": receipt.get("sampled_excluded_document_count")})
    if receipt.get("threshold") != 0.8 or receipt.get("shingle_size_tokens") != 13:
        failures.append({"code": "policy_threshold_mismatch", "threshold": receipt.get("threshold"), "shingle_size": receipt.get("shingle_size_tokens")})
    if receipt.get("filtered_view_materialized") is not True or receipt.get("binary_shards_rewritten") is not False:
        failures.append({"code": "filtered_view_policy_mismatch", "filtered_view_materialized": receipt.get("filtered_view_materialized"), "binary_shards_rewritten": receipt.get("binary_shards_rewritten")})
    if receipt.get("crossing_pair_count", 0) > 0 and not receipt.get("crossing_samples"):
        failures.append({"code": "crossing_count_without_samples"})
    if "not an all-pairs near-duplicate PASS" not in str(receipt.get("scope_limit", "")):
        failures.append({"code": "scope_limit_missing_all_pairs_guard"})
    if "not overall baseline completion" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_TARGETED_FILTERED_NEAR_DUPLICATE_SAMPLE_VALIDATED" if not failures else "C1_TARGETED_FILTERED_NEAR_DUPLICATE_SAMPLE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "summary": {
            "sampled_documents": receipt.get("sampled_documents"),
            "remaining_document_count": receipt.get("remaining_document_count"),
            "excluded_document_count": receipt.get("excluded_document_count"),
            "candidate_pair_count": receipt.get("candidate_pair_count"),
            "crossing_pair_count": receipt.get("crossing_pair_count"),
            "max_exact_jaccard_observed": receipt.get("max_exact_jaccard_observed"),
            "verdict": receipt.get("verdict"),
        },
        "completion_limit": "This validates a targeted-filtered near-duplicate challenge sample only. It is not an all-pairs near-duplicate PASS, not eval-contamination evidence, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
