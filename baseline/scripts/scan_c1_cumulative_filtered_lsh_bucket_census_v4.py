#!/usr/bin/env python3
"""Run a full-corpus LSH bucket census after cumulative v4 exclusions.

This is an evidence step toward the C1 all-pairs near-duplicate gate. A selected
band census is not a pass: it only proves that the named LSH band(s) were scanned
over the v4-filtered corpus and records collision pressure for follow-up exact
Jaccard auditing.
"""

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
    SOURCE_RECEIPT,
    iter_docs,
    read_json,
    sha256_file,
    shingle_hashes,
)

FILTERED_VIEW = "receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json"
EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl"
VERDICT_PARTIAL = "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION"
VERDICT_FULL = "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_FULL_CENSUS_NOT_COMPLETION"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def digest_rows(rows: list[dict[str, Any]]) -> str:
    payload = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def band_key(shingles: np.ndarray, seeds: list[int]) -> tuple[int, ...]:
    values = []
    for seed in seeds:
        mixed = np.bitwise_xor(shingles, np.uint64(seed))
        values.append(int(mixed.min()))
    return tuple(values)


def parse_band_starts(raw: str | None, signature_size: int, band_size: int) -> list[int]:
    valid = list(range(0, signature_size, band_size))
    if not raw:
        return valid
    wanted = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value not in valid:
            raise SystemExit(f"invalid band start {value}; valid starts: {valid}")
        wanted.append(value)
    return sorted(set(wanted))


def top_collision_rows(
    bucket_counts: dict[tuple[int, tuple[int, ...]], int],
    bucket_examples: dict[tuple[int, tuple[int, ...]], dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    heap: list[tuple[int, str, tuple[int, tuple[int, ...]]]] = []
    for key, count in bucket_counts.items():
        if count < 2:
            continue
        stable = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
        item = (count, stable, key)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    rows = []
    for count, stable, key in sorted(heap, reverse=True):
        band_start, bucket = key
        rows.append({
            "band_start": band_start,
            "bucket_hash_sha256": stable,
            "bucket_size": count,
            "example": bucket_examples[key],
            "bucket_prefix": [int(x) for x in bucket[: min(2, len(bucket))]],
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--band-starts", help="Comma-separated band starts. Omit for all bands.")
    parser.add_argument("--min-doc-tokens", type=int, default=64)
    parser.add_argument("--max-doc-tokens", type=int, default=4096)
    parser.add_argument("--signature-size", type=int, default=64)
    parser.add_argument("--band-size", type=int, default=4)
    parser.add_argument("--chunk-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-eligible-docs", type=int)
    parser.add_argument("--top-buckets", type=int, default=25)
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
    band_starts = parse_band_starts(args.band_starts, args.signature_size, args.band_size)
    all_band_starts = list(range(0, args.signature_size, args.band_size))
    seed_values = [int.from_bytes(hashlib.blake2b(f"c1-near-{i}".encode(), digest_size=8).digest(), "big") for i in range(args.signature_size)]
    band_seeds = {start: seed_values[start: start + args.band_size] for start in band_starts}
    threshold = policy["thresholds"]["near_duplicate_minhash"]["primary_jaccard_threshold"]
    shingle_size = policy["thresholds"]["near_duplicate_minhash"]["shingle_size_tokens"]

    bucket_counts: dict[tuple[int, tuple[int, ...]], int] = defaultdict(int)
    bucket_examples: dict[tuple[int, tuple[int, ...]], dict[str, Any]] = {}
    docs_seen = eligible_docs = excluded_docs_seen = skipped_short = skipped_long = docs_censused = 0
    shard_rows = []
    carry = bytearray()
    stopped_by_limit = False
    for expected in source["shards"]:
        name = expected["name"]
        path = args.shard_dir.resolve() / name
        if not path.exists():
            raise SystemExit(f"missing shard: {name}")
        observed_sha = sha256_file(path)
        if observed_sha != expected["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}")
        shard_docs = shard_eligible = shard_excluded = shard_censused = 0
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
            shingles = shingle_hashes(tokens, shingle_size)
            for start, seeds in band_seeds.items():
                key = (start, band_key(shingles, seeds))
                bucket_counts[key] += 1
                if key not in bucket_examples:
                    bucket_examples[key] = {
                        "doc_index": doc_index,
                        "doc_sha256": doc_sha,
                        "shard": name,
                        "token_len": token_len,
                    }
            docs_censused += 1
            shard_censused += 1
            if args.max_eligible_docs is not None and docs_censused >= args.max_eligible_docs:
                stopped_by_limit = True
                break
        shard_rows.append({
            "name": name,
            "sha256": observed_sha,
            "documents_seen": shard_docs,
            "eligible_documents_after_filter": shard_eligible,
            "excluded_documents": shard_excluded,
            "documents_censused": shard_censused,
        })
        if stopped_by_limit:
            break

    collision_bucket_count = sum(1 for count in bucket_counts.values() if count > 1)
    collision_document_memberships = sum(count for count in bucket_counts.values() if count > 1)
    max_bucket_size = max(bucket_counts.values(), default=0)
    full_band_coverage = band_starts == all_band_starts
    full_doc_coverage = not stopped_by_limit
    view = filtered_view.get("cumulative_filtered_view", {})
    failures = []
    if full_doc_coverage and excluded_docs_seen != len(exclusions):
        failures.append({"code": "not_all_exclusions_seen", "seen": excluded_docs_seen, "expected": len(exclusions)})
    if full_doc_coverage and docs_seen != filtered_view.get("source_corpus", {}).get("documents_seen"):
        failures.append({"code": "documents_seen_mismatch", "actual": docs_seen, "expected": filtered_view.get("source_corpus", {}).get("documents_seen")})
    if not full_doc_coverage and args.max_eligible_docs is None:
        failures.append({"code": "unexpected_partial_doc_coverage"})

    result = {
        "kind": "single_4090_c1_cumulative_filtered_lsh_bucket_census_v4",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": VERDICT_FULL if full_band_coverage and full_doc_coverage and not failures else VERDICT_PARTIAL,
        "failure_count": len(failures),
        "failures": failures,
        "source_receipt": SOURCE_RECEIPT,
        "policy_receipt": POLICY_RECEIPT,
        "source_filtered_view_receipt": FILTERED_VIEW,
        "source_exclusion_manifest": EXCLUSION_MANIFEST,
        "source_exclusion_manifest_sha256": sha256_file(baseline / EXCLUSION_MANIFEST),
        "exclusion_manifest_row_digest_sha256": digest_rows(exclusions),
        "method": "v4-filtered corpus LSH bucket census; selected MinHash bands over eligible separator-delimited documents after exclusions; records bucket collision pressure but does not perform exact all-pairs Jaccard adjudication",
        "scope_limit": "LSH bucket census only. It is not an all-pairs near-duplicate PASS, not an exact Jaccard full-corpus adjudication, not eval-contamination evidence, and not overall baseline completion.",
        "threshold": threshold,
        "shingle_size_tokens": shingle_size,
        "signature_size": args.signature_size,
        "band_size": args.band_size,
        "band_starts_scanned": band_starts,
        "band_count_scanned": len(band_starts),
        "full_band_coverage": full_band_coverage,
        "max_eligible_docs": args.max_eligible_docs,
        "full_document_coverage": full_doc_coverage,
        "documents_seen": docs_seen,
        "eligible_documents_after_filter_seen": eligible_docs,
        "documents_censused": docs_censused,
        "excluded_document_count": len(exclusions),
        "excluded_documents_seen": excluded_docs_seen,
        "remaining_document_count": view.get("remaining_document_count"),
        "remaining_content_token_floor": view.get("remaining_content_token_floor"),
        "skipped_short_documents_after_filter": skipped_short,
        "skipped_long_documents_after_filter": skipped_long,
        "bucket_count": len(bucket_counts),
        "collision_bucket_count": collision_bucket_count,
        "collision_document_memberships": collision_document_memberships,
        "max_bucket_size": max_bucket_size,
        "top_collision_buckets": top_collision_rows(bucket_counts, bucket_examples, args.top_buckets),
        "shards": shard_rows,
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This records LSH bucket-census evidence only. Exact all-pairs candidate adjudication and a replacement C1 near-duplicate PASS receipt remain required before C1 or overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
