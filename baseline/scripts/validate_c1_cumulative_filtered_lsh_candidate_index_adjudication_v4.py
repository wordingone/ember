#!/usr/bin/env python3
"""Validate exact adjudication over a v4-filtered LSH candidate index."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_VERDICTS = {
    "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_NO_CROSSINGS_NOT_COMPLETION",
    "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--candidate-receipt", required=True)
    parser.add_argument("--expected-partial", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt_rel = args.receipt.replace("\\", "/")
    candidate_rel = args.candidate_receipt.replace("\\", "/")
    receipt = read_json(root / receipt_rel) if (root / receipt_rel).exists() else {}
    candidate = read_json(root / candidate_rel) if (root / candidate_rel).exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") not in VALID_VERDICTS:
        failures.append({"code": "bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("candidate_index_receipt") != candidate_rel:
        failures.append({"code": "candidate_receipt_mismatch", "actual": receipt.get("candidate_index_receipt"), "expected": candidate_rel})
    if receipt.get("candidate_index_sha256") != candidate.get("index_sha256"):
        failures.append({"code": "candidate_index_sha_mismatch", "actual": receipt.get("candidate_index_sha256"), "expected": candidate.get("index_sha256")})
    if receipt.get("band_starts_adjudicated") != candidate.get("band_starts_materialized"):
        failures.append({"code": "band_starts_mismatch", "actual": receipt.get("band_starts_adjudicated"), "expected": candidate.get("band_starts_materialized")})
    if bool(receipt.get("partial_index_adjudication")) != bool(args.expected_partial):
        failures.append({"code": "partial_scope_mismatch", "actual": receipt.get("partial_index_adjudication"), "expected": bool(args.expected_partial)})
    if receipt.get("index_rows_adjudicated", 0) < 1:
        failures.append({"code": "no_rows_adjudicated"})
    if not args.expected_partial and receipt.get("index_rows_adjudicated") != candidate.get("index_row_count"):
        failures.append({"code": "full_index_row_count_mismatch", "actual": receipt.get("index_rows_adjudicated"), "expected": candidate.get("index_row_count")})
    if receipt.get("candidate_pair_count", 0) < 1:
        failures.append({"code": "no_candidate_pairs_adjudicated"})
    if receipt.get("candidate_pair_count") != receipt.get("size_pruned_pair_count", 0) + receipt.get("exact_jaccard_pair_count", 0):
        failures.append({"code": "pair_accounting_mismatch", "candidate_pair_count": receipt.get("candidate_pair_count"), "size_pruned": receipt.get("size_pruned_pair_count"), "exact": receipt.get("exact_jaccard_pair_count")})
    if receipt.get("crossing_pair_count", 0) < 0:
        failures.append({"code": "negative_crossing_count"})
    if receipt.get("threshold") != 0.8 or receipt.get("shingle_size_tokens") != 13:
        failures.append({"code": "policy_threshold_mismatch", "threshold": receipt.get("threshold"), "shingle_size": receipt.get("shingle_size_tokens")})
    if "not full 16-band adjudication" not in str(receipt.get("scope_limit", "")):
        failures.append({"code": "scope_limit_missing_noncompletion_guard"})
    if "Full required candidate coverage" not in str(receipt.get("completion_limit", "")):
        failures.append({"code": "completion_limit_missing_noncompletion_guard"})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_VALIDATED" if not failures else "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": receipt_rel,
        "summary": {
            "verdict": receipt.get("verdict"),
            "index_rows_adjudicated": receipt.get("index_rows_adjudicated"),
            "partial_index_adjudication": receipt.get("partial_index_adjudication"),
            "candidate_pair_count": receipt.get("candidate_pair_count"),
            "size_pruned_pair_count": receipt.get("size_pruned_pair_count"),
            "exact_jaccard_pair_count": receipt.get("exact_jaccard_pair_count"),
            "crossing_pair_count": receipt.get("crossing_pair_count"),
            "max_exact_jaccard_observed": receipt.get("max_exact_jaccard_observed"),
        },
        "completion_limit": "This validates exact adjudication evidence only. It is not full C1 hygiene completion and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
