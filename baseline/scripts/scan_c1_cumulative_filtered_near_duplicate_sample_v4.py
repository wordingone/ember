#!/usr/bin/env python3
"""Run a C1 near-duplicate challenge sample after cumulative v4 exclusions."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_c1_near_duplicate_sample import (  # noqa: E402
    POLICY_RECEIPT,
    SEPARATOR_ID,
    SOURCE_RECEIPT,
    doc_score,
    iter_docs,
    jaccard,
    minhash_signature,
    read_json,
    sha256_file,
    shingle_hashes,
)

FILTERED_VIEW = "receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json"
EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def maybe_add_sample(
    heap: list[tuple[int, int, dict[str, Any], bytes]],
    score: int,
    sample_limit: int,
    doc_index: int,
    shard_name: str,
    tokens: np.ndarray,
    doc_bytes: bytes,
) -> None:
    row = {
        "doc_index": doc_index,
        "shard": shard_name,
        "token_len": int(tokens.size),
        "sample_score": score,
        "doc_sha256": hashlib.sha256(doc_bytes).hexdigest(),
    }
    item = (-score, doc_index, row, doc_bytes)
    if len(heap) < sample_limit:
        heapq.heappush(heap, item)
    elif item > heap[0]:
        heapq.heapreplace(heap, item)


def digest_rows(rows: list[dict[str, Any]]) -> str:
    payload = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-docs", type=int, default=50000)
    parser.add_argument("--min-doc-tokens", type=int, default=64)
    parser.add_argument("--max-doc-tokens", type=int, default=4096)
    parser.add_argument("--signature-size", type=int, default=64)
    parser.add_argument("--band-size", type=int, default=4)
    parser.add_argument("--chunk-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    started = time.time()
    repo = args.repo_root.resolve()
    baseline = args.baseline_root.resolve()
    source = read_json(repo / SOURCE_RECEIPT)
    policy = read_json(repo / POLICY_RECEIPT)
    filtered_view = read_json(baseline / FILTERED_VIEW)
    exclusions = read_jsonl(baseline / EXCLUSION_MANIFEST)
    excluded: dict[int, str] = {int(row["doc_index"]): str(row["doc_sha256"]) for row in exclusions}
    threshold = policy["thresholds"]["near_duplicate_minhash"]["primary_jaccard_threshold"]
    shingle_size = policy["thresholds"]["near_duplicate_minhash"]["shingle_size_tokens"]
    seeds = [int.from_bytes(hashlib.blake2b(f"c1-near-{i}".encode(), digest_size=8).digest(), "big") for i in range(args.signature_size)]

    heap: list[tuple[int, int, dict[str, Any], bytes]] = []
    docs_seen = eligible_docs = excluded_docs_seen = sampled_excluded = skipped_short = skipped_long = 0
    shard_rows = []
    carry = bytearray()
    for expected in source["shards"]:
        name = expected["name"]
        path = args.shard_dir.resolve() / name
        if not path.exists():
            raise SystemExit(f"missing shard: {name}")
        observed_sha = sha256_file(path)
        if observed_sha != expected["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}")
        shard_docs = shard_eligible = shard_excluded = 0
        for doc in iter_docs(path, args.chunk_bytes, carry):
            doc_index = docs_seen
            docs_seen += 1
            shard_docs += 1
            token_len = len(doc) // 2
            doc_sha = hashlib.sha256(doc).hexdigest()
            if doc_index in excluded:
                excluded_docs_seen += 1
                shard_excluded += 1
                if excluded[doc_index] != doc_sha:
                    raise SystemExit(f"exclusion sha mismatch at doc_index {doc_index}")
                continue
            if token_len < args.min_doc_tokens:
                skipped_short += 1
                continue
            if token_len > args.max_doc_tokens:
                skipped_long += 1
                continue
            eligible_docs += 1
            shard_eligible += 1
            tokens = np.frombuffer(doc, dtype="<u2").copy()
            maybe_add_sample(heap, doc_score(doc), args.sample_docs, doc_index, name, tokens, doc)
        shard_rows.append({"name": name, "sha256": observed_sha, "documents_seen": shard_docs, "eligible_documents_after_filter": shard_eligible, "excluded_documents": shard_excluded})
    if carry:
        doc_index = docs_seen
        docs_seen += 1
        doc = bytes(carry)
        doc_sha = hashlib.sha256(doc).hexdigest()
        if doc_index in excluded:
            excluded_docs_seen += 1
            if excluded[doc_index] != doc_sha:
                raise SystemExit(f"exclusion sha mismatch at doc_index {doc_index}")
        else:
            token_len = len(doc) // 2
            if token_len < args.min_doc_tokens:
                skipped_short += 1
            elif token_len > args.max_doc_tokens:
                skipped_long += 1
            else:
                eligible_docs += 1
                tokens = np.frombuffer(doc, dtype="<u2").copy()
                maybe_add_sample(heap, doc_score(doc), args.sample_docs, doc_index, source["shards"][-1]["name"], tokens, doc)

    samples = sorted([item[2] | {"doc_bytes": item[3]} for item in heap], key=lambda row: row["doc_index"])
    sampled_excluded = sum(1 for row in samples if int(row["doc_index"]) in excluded)
    bands: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    shingle_sets: list[np.ndarray] = []
    for idx, row in enumerate(samples):
        tokens = np.frombuffer(row.pop("doc_bytes"), dtype="<u2").copy()
        shingles = shingle_hashes(tokens, shingle_size)
        sig = minhash_signature(shingles, seeds)
        shingle_sets.append(shingles)
        for band_start in range(0, len(sig), args.band_size):
            band = tuple(sig[band_start: band_start + args.band_size])
            if len(band) == args.band_size:
                bands[(band_start, band)].append(idx)

    candidate_pairs = set()
    for ids in bands.values():
        if len(ids) < 2:
            continue
        for i, left in enumerate(ids):
            for right in ids[i + 1:]:
                candidate_pairs.add((min(left, right), max(left, right)))

    crossing = []
    max_exact = 0.0
    for left, right in sorted(candidate_pairs):
        exact = jaccard(shingle_sets[left], shingle_sets[right])
        max_exact = max(max_exact, exact)
        if exact >= threshold:
            crossing.append({
                "left": {k: samples[left][k] for k in ("doc_index", "shard", "token_len", "doc_sha256")},
                "right": {k: samples[right][k] for k in ("doc_index", "shard", "token_len", "doc_sha256")},
                "exact_jaccard": round(exact, 6),
            })
            if len(crossing) >= 25:
                break

    view = filtered_view.get("cumulative_filtered_view", {})
    failures = []
    if excluded_docs_seen != len(exclusions):
        failures.append({"code": "not_all_exclusions_seen", "seen": excluded_docs_seen, "expected": len(exclusions)})
    if sampled_excluded:
        failures.append({"code": "excluded_documents_sampled", "count": sampled_excluded})
    if docs_seen != filtered_view.get("source_corpus", {}).get("documents_seen"):
        failures.append({"code": "documents_seen_mismatch", "actual": docs_seen, "expected": filtered_view.get("source_corpus", {}).get("documents_seen")})

    result = {
        "kind": "single_4090_c1_cumulative_filtered_near_duplicate_sample_v4",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V4_NO_CROSSING_CANDIDATES" if not crossing and not failures else ("C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V4_CANDIDATES_FOUND" if not failures else "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V4_INVALID"),
        "failure_count": len(failures),
        "failures": failures,
        "source_receipt": SOURCE_RECEIPT,
        "policy_receipt": POLICY_RECEIPT,
        "source_filtered_view_receipt": FILTERED_VIEW,
        "source_exclusion_manifest": EXCLUSION_MANIFEST,
        "source_exclusion_manifest_sha256": sha256_file(baseline / EXCLUSION_MANIFEST),
        "exclusion_manifest_row_digest_sha256": digest_rows(exclusions),
        "method": "deterministic lowest-score sample after applying targeted near-duplicate exclusions to separator-delimited C1 document stream; 13-token shingle MinHash signatures; LSH candidate generation; exact Jaccard audit for candidate pairs",
        "scope_limit": "Cumulative-filtered v4 deterministic challenge sample only. It is not an all-pairs near-duplicate PASS, not full-corpus MinHash proof, and cannot complete C1 data hygiene by itself.",
        "threshold": threshold,
        "shingle_size_tokens": shingle_size,
        "signature_size": args.signature_size,
        "band_size": args.band_size,
        "sample_limit": args.sample_docs,
        "sampled_documents": len(samples),
        "documents_seen": docs_seen,
        "eligible_documents_after_filter": eligible_docs,
        "excluded_document_count": len(exclusions),
        "excluded_documents_seen": excluded_docs_seen,
        "sampled_excluded_document_count": sampled_excluded,
        "remaining_document_count": view.get("remaining_document_count"),
        "remaining_content_token_floor": view.get("remaining_content_token_floor"),
        "filtered_view_materialized": view.get("view_materialized"),
        "binary_shards_rewritten": view.get("binary_shards_rewritten"),
        "skipped_short_documents_after_filter": skipped_short,
        "skipped_long_documents_after_filter": skipped_long,
        "candidate_pair_count": len(candidate_pairs),
        "crossing_pair_count": len(crossing),
        "max_exact_jaccard_observed": round(max_exact, 6),
        "crossing_samples": crossing,
        "sample_policy": "Select documents by stable blake2b document score after cumulative v4 exclusions and eligibility filtering.",
        "shards": shard_rows,
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This records cumulative-filtered v4 near-duplicate sample evidence only. It is not eval contamination evidence, not an all-pairs near-duplicate/MinHash PASS, not a long-run training receipt, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["verdict"] != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V4_INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
