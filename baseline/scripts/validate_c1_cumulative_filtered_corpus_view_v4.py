#!/usr/bin/env python3
"""Validate the cumulative v4 near-duplicate filtered-corpus view receipt.

This validates that the targeted exclusion manifest has been applied to the
pinned token-document corpus as a replayable view. It is not an all-pairs
near-duplicate PASS and does not rebuild binary token shards.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json"
EXACT_DEDUPE_RECEIPT = "receipts/4090-exact-dedupe-scan-2026-06-30.json"
EXCLUSION_RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-2026-06-30.json"
EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl"
EXPECTED_VERDICT = "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V4_READY_NOT_COMPLETION"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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
    receipt_path = root / RECEIPT
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    exact = read_json(root / EXACT_DEDUPE_RECEIPT) if (root / EXACT_DEDUPE_RECEIPT).exists() else {}
    exclusion_receipt = read_json(root / EXCLUSION_RECEIPT) if (root / EXCLUSION_RECEIPT).exists() else {}
    exclusions = read_jsonl(root / EXCLUSION_MANIFEST) if (root / EXCLUSION_MANIFEST).exists() else []
    failures: list[dict[str, Any]] = []

    if not receipt_path.exists():
        failures.append({"code": "cumulative_filtered_corpus_view_receipt_missing", "path": RECEIPT})
    if receipt.get("verdict") != EXPECTED_VERDICT:
        failures.append({"code": "cumulative_filtered_corpus_view_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("source_exact_dedupe_receipt") != EXACT_DEDUPE_RECEIPT:
        failures.append({"code": "source_exact_dedupe_receipt_mismatch", "actual": receipt.get("source_exact_dedupe_receipt")})
    if receipt.get("source_exclusion_receipt") != EXCLUSION_RECEIPT:
        failures.append({"code": "source_exclusion_receipt_mismatch", "actual": receipt.get("source_exclusion_receipt")})
    if receipt.get("source_exclusion_manifest") != EXCLUSION_MANIFEST:
        failures.append({"code": "source_exclusion_manifest_mismatch", "actual": receipt.get("source_exclusion_manifest")})

    source = receipt.get("source_corpus", {})
    filtered = receipt.get("cumulative_filtered_view", {})
    expected_docs = exact.get("documents_seen")
    expected_stream_tokens = exact.get("total_stream_tokens")
    expected_exclusion_docs = exclusion_receipt.get("exclusion_document_count")
    expected_exclusion_tokens = exclusion_receipt.get("exclusion_token_floor")
    if source.get("documents_seen") != expected_docs or source.get("stream_tokens") != expected_stream_tokens:
        failures.append({"code": "source_corpus_totals_mismatch", "source": source, "exact": {"documents_seen": expected_docs, "stream_tokens": expected_stream_tokens}})
    if filtered.get("excluded_document_count") != expected_exclusion_docs or filtered.get("excluded_token_floor") != expected_exclusion_tokens:
        failures.append({"code": "exclusion_totals_mismatch", "filtered": filtered, "exclusion_receipt": {"docs": expected_exclusion_docs, "tokens": expected_exclusion_tokens}})
    expected_remaining_docs = expected_docs - expected_exclusion_docs if isinstance(expected_docs, int) and isinstance(expected_exclusion_docs, int) else None
    expected_remaining_tokens = expected_stream_tokens - expected_exclusion_tokens if isinstance(expected_stream_tokens, int) and isinstance(expected_exclusion_tokens, int) else None
    if filtered.get("remaining_document_count") != expected_remaining_docs:
        failures.append({"code": "remaining_document_count_mismatch", "expected": expected_remaining_docs, "actual": filtered.get("remaining_document_count")})
    if filtered.get("remaining_content_token_floor") != expected_remaining_tokens:
        failures.append({"code": "remaining_token_floor_mismatch", "expected": expected_remaining_tokens, "actual": filtered.get("remaining_content_token_floor")})
    if filtered.get("exclusion_application") != "exclude listed document indices from the C1 document stream before sampling/training":
        failures.append({"code": "exclusion_application_contract_missing", "actual": filtered.get("exclusion_application")})
    if filtered.get("binary_shards_rewritten") is not False or filtered.get("view_materialized") is not True:
        failures.append({"code": "view_materialization_flags_invalid", "filtered": filtered})

    per_shard = receipt.get("per_shard_application", [])
    if not isinstance(per_shard, list) or not per_shard:
        failures.append({"code": "per_shard_application_missing"})
    else:
        total_ex_docs = sum(int(row.get("excluded_document_count", 0)) for row in per_shard)
        total_ex_tokens = sum(int(row.get("excluded_token_floor", 0)) for row in per_shard)
        if total_ex_docs != expected_exclusion_docs or total_ex_tokens != expected_exclusion_tokens:
            failures.append({"code": "per_shard_exclusion_totals_mismatch", "docs": total_ex_docs, "tokens": total_ex_tokens})
        exact_shards = {row.get("name"): row for row in exact.get("shards", [])}
        for row in per_shard:
            name = row.get("shard")
            source_row = exact_shards.get(name)
            if not source_row:
                failures.append({"code": "per_shard_unknown_shard", "row": row})
                continue
            if row.get("source_documents_closed") != source_row.get("documents_closed"):
                failures.append({"code": "per_shard_source_doc_count_mismatch", "row": row, "source": source_row})
            if row.get("remaining_documents") != row.get("source_documents_closed") - row.get("excluded_document_count"):
                failures.append({"code": "per_shard_remaining_doc_count_mismatch", "row": row})

    indices = [int(row["doc_index"]) for row in exclusions if "doc_index" in row]
    index_summary = receipt.get("excluded_doc_index_summary", {})
    if indices:
        if index_summary.get("min_doc_index") != min(indices) or index_summary.get("max_doc_index") != max(indices) or index_summary.get("unique_doc_index_count") != len(set(indices)):
            failures.append({"code": "excluded_doc_index_summary_mismatch", "summary": index_summary})
    if len(set(indices)) != len(indices):
        failures.append({"code": "exclusion_manifest_duplicate_doc_indices"})

    limit = str(receipt.get("completion_limit", ""))
    for phrase in (
        "not an all-pairs near-duplicate PASS",
        "not binary shard rewrite",
        "not overall baseline completion",
    ):
        if phrase not in limit:
            failures.append({"code": "completion_limit_missing_phrase", "phrase": phrase})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V4_VALIDATED" if not failures else "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V4_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "excluded_document_count": filtered.get("excluded_document_count"),
        "excluded_token_floor": filtered.get("excluded_token_floor"),
        "remaining_document_count": filtered.get("remaining_document_count"),
        "remaining_content_token_floor": filtered.get("remaining_content_token_floor"),
        "completion_limit": "This validates a cumulative v4 filtered-corpus view only. It is not an all-pairs near-duplicate PASS, not binary shard rewrite, and not overall baseline completion.",
    }
    text = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
