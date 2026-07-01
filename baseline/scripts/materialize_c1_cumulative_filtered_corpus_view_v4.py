#!/usr/bin/env python3
"""Materialize a cumulative v4 near-duplicate filtered-corpus view receipt.

This applies the existing targeted exclusion manifest to the pinned C1 document
stream as a replayable view. It does not rewrite binary token shards and does
not claim all-pairs near-duplicate completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXACT_DEDUPE_RECEIPT = "receipts/4090-exact-dedupe-scan-2026-06-30.json"
EXCLUSION_RECEIPT = "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-2026-06-30.json"
EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl"
VERDICT = "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V4_READY_NOT_COMPLETION"


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


def digest_exclusion_keys(rows: list[dict[str, Any]]) -> str:
    lines = [f"{int(row['doc_index'])}\t{row['doc_sha256']}\t{int(row['token_len'])}" for row in rows]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    exact = read_json(root / EXACT_DEDUPE_RECEIPT)
    exclusion_receipt = read_json(root / EXCLUSION_RECEIPT)
    exclusions = read_jsonl(root / EXCLUSION_MANIFEST)

    by_shard: dict[str, dict[str, int]] = defaultdict(lambda: {"excluded_document_count": 0, "excluded_token_floor": 0})
    seen_indices: set[int] = set()
    seen_keys: set[tuple[int, str]] = set()
    failures: list[dict[str, Any]] = []
    for row in exclusions:
        doc_index = int(row["doc_index"])
        doc_sha = str(row["doc_sha256"])
        key = (doc_index, doc_sha)
        if key in seen_keys:
            failures.append({"code": "duplicate_exclusion_key", "doc_index": doc_index, "doc_sha256": doc_sha})
        if doc_index in seen_indices:
            failures.append({"code": "duplicate_exclusion_doc_index", "doc_index": doc_index})
        seen_indices.add(doc_index)
        seen_keys.add(key)
        shard = str(row["shard"])
        by_shard[shard]["excluded_document_count"] += 1
        by_shard[shard]["excluded_token_floor"] += int(row["token_len"])

    excluded_docs = len(exclusions)
    excluded_tokens = sum(int(row["token_len"]) for row in exclusions)
    if excluded_docs != exclusion_receipt.get("exclusion_document_count"):
        failures.append({"code": "exclusion_doc_count_mismatch", "manifest": excluded_docs, "receipt": exclusion_receipt.get("exclusion_document_count")})
    if excluded_tokens != exclusion_receipt.get("exclusion_token_floor"):
        failures.append({"code": "exclusion_token_floor_mismatch", "manifest": excluded_tokens, "receipt": exclusion_receipt.get("exclusion_token_floor")})

    per_shard = []
    for source in exact.get("shards", []):
        shard = str(source["name"])
        ex = by_shard.get(shard, {"excluded_document_count": 0, "excluded_token_floor": 0})
        remaining_docs = int(source["documents_closed"]) - int(ex["excluded_document_count"])
        if remaining_docs < 0:
            failures.append({"code": "negative_remaining_docs", "shard": shard, "remaining": remaining_docs})
        per_shard.append({
            "shard": shard,
            "source_sha256": source.get("sha256"),
            "source_stream_tokens": source.get("n_tokens"),
            "source_documents_closed": source.get("documents_closed"),
            "excluded_document_count": int(ex["excluded_document_count"]),
            "excluded_token_floor": int(ex["excluded_token_floor"]),
            "remaining_documents": remaining_docs,
        })

    source_docs = int(exact.get("documents_seen", 0))
    source_stream_tokens = int(exact.get("total_stream_tokens", 0))
    result = {
        "kind": "single_4090_c1_cumulative_filtered_corpus_view_v4",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": VERDICT if not failures else "C1_TARGETED_FILTERED_CORPUS_VIEW_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "source_exact_dedupe_receipt": EXACT_DEDUPE_RECEIPT,
        "source_exclusion_receipt": EXCLUSION_RECEIPT,
        "source_exclusion_manifest": EXCLUSION_MANIFEST,
        "source_exclusion_manifest_sha256": sha256_file(root / EXCLUSION_MANIFEST),
        "source_corpus": {
            "documents_seen": source_docs,
            "stream_tokens": source_stream_tokens,
            "separator_token_id": exact.get("separator_token_id"),
            "shard_count": len(exact.get("shards", [])),
        },
        "cumulative_filtered_view": {
            "view_materialized": True,
            "binary_shards_rewritten": False,
            "exclusion_application": "exclude listed document indices from the C1 document stream before sampling/training",
            "excluded_document_count": excluded_docs,
            "excluded_token_floor": excluded_tokens,
            "excluded_document_fraction": excluded_docs / source_docs if source_docs else None,
            "excluded_token_floor_fraction_of_stream": excluded_tokens / source_stream_tokens if source_stream_tokens else None,
            "remaining_document_count": source_docs - excluded_docs,
            "remaining_content_token_floor": source_stream_tokens - excluded_tokens,
            "exclusion_key_digest_sha256": digest_exclusion_keys(exclusions),
        },
        "excluded_doc_index_summary": {
            "unique_doc_index_count": len(seen_indices),
            "min_doc_index": min(seen_indices) if seen_indices else None,
            "max_doc_index": max(seen_indices) if seen_indices else None,
        },
        "per_shard_application": per_shard,
        "completion_limit": "This materializes a cumulative v4 filtered-corpus view for cumulative discovered near-duplicate clusters only. It is not an all-pairs near-duplicate PASS, not binary shard rewrite, not a full-corpus MinHash PASS, not eval-contamination evidence, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
