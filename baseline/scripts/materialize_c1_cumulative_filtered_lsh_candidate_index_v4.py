#!/usr/bin/env python3
"""Materialize v4-filtered LSH collision-bucket candidate postings.

This is the bridge between the bucket census and exact near-duplicate
adjudication. It deliberately does not claim a PASS: it writes the concrete
collision buckets/members that an exact Jaccard adjudicator must consume.
"""

from __future__ import annotations

import argparse
import hashlib
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
from scan_c1_cumulative_filtered_lsh_bucket_census_v4 import (  # noqa: E402
    EXCLUSION_MANIFEST,
    FILTERED_VIEW,
    band_key,
    digest_rows,
    parse_band_starts,
    read_jsonl,
)

VERDICT = "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_MATERIALIZED_NOT_COMPLETION"


def bucket_digest(band_start: int, bucket: tuple[int, ...]) -> str:
    return hashlib.sha256(repr((band_start, bucket)).encode("utf-8")).hexdigest()


def iter_eligible_docs(args: argparse.Namespace, source: dict[str, Any], excluded: dict[int, str]):
    docs_seen = eligible_docs = excluded_docs_seen = skipped_short = skipped_long = 0
    shard_rows: list[dict[str, Any]] = []
    carry = bytearray()
    for expected in source["shards"]:
        name = expected["name"]
        path = args.shard_dir.resolve() / name
        if not path.exists():
            raise SystemExit(f"missing shard: {name}")
        observed_sha = sha256_file(path)
        if observed_sha != expected["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}")
        shard_docs = shard_eligible = shard_excluded = shard_skipped_short = shard_skipped_long = 0
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
                shard_skipped_short += 1
                continue
            if token_len > args.max_doc_tokens:
                skipped_long += 1
                shard_skipped_long += 1
                continue
            eligible_docs += 1
            shard_eligible += 1
            yield {
                "doc_index": doc_index,
                "doc_sha256": doc_sha,
                "shard": name,
                "token_len": token_len,
                "doc": doc,
            }
        shard_rows.append({
            "name": name,
            "sha256": observed_sha,
            "documents_seen": shard_docs,
            "eligible_documents_after_filter": shard_eligible,
            "excluded_documents": shard_excluded,
            "skipped_short_documents_after_filter": shard_skipped_short,
            "skipped_long_documents_after_filter": shard_skipped_long,
        })
    if carry:
        raise SystemExit("unexpected unterminated trailing document carry")
    args._scan_stats = {
        "documents_seen": docs_seen,
        "eligible_documents_after_filter_seen": eligible_docs,
        "excluded_documents_seen": excluded_docs_seen,
        "skipped_short_documents_after_filter": skipped_short,
        "skipped_long_documents_after_filter": skipped_long,
        "shards": shard_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--index-out", type=Path, required=True)
    parser.add_argument("--band-starts", required=True, help="Comma-separated band starts to materialize.")
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
    band_starts = parse_band_starts(args.band_starts, args.signature_size, args.band_size)
    seed_values = [int.from_bytes(hashlib.blake2b(f"c1-near-{i}".encode(), digest_size=8).digest(), "big") for i in range(args.signature_size)]
    band_seeds = {start: seed_values[start: start + args.band_size] for start in band_starts}
    threshold = policy["thresholds"]["near_duplicate_minhash"]["primary_jaccard_threshold"]
    shingle_size = policy["thresholds"]["near_duplicate_minhash"]["shingle_size_tokens"]

    bucket_counts: dict[tuple[int, tuple[int, ...]], int] = defaultdict(int)
    docs_censused = 0
    for row in iter_eligible_docs(args, source, excluded):
        shingles = shingle_hashes(np.frombuffer(row["doc"], dtype="<u2").copy(), shingle_size)
        for start, seeds in band_seeds.items():
            bucket_counts[(start, band_key(shingles, seeds))] += 1
        docs_censused += 1

    collision_keys = {key for key, count in bucket_counts.items() if count > 1}
    postings: dict[tuple[int, tuple[int, ...]], list[dict[str, Any]]] = {key: [] for key in collision_keys}
    for row in iter_eligible_docs(args, source, excluded):
        shingles = shingle_hashes(np.frombuffer(row["doc"], dtype="<u2").copy(), shingle_size)
        for start, seeds in band_seeds.items():
            key = (start, band_key(shingles, seeds))
            if key in postings:
                postings[key].append({
                    "doc_index": row["doc_index"],
                    "doc_sha256": row["doc_sha256"],
                    "shard": row["shard"],
                    "token_len": row["token_len"],
                })

    args.index_out.parent.mkdir(parents=True, exist_ok=True)
    index_rows = []
    pair_upper_bound = 0
    collision_document_memberships = 0
    max_bucket_size = 0
    with args.index_out.open("w", encoding="utf-8", newline="\n") as fh:
        for key in sorted(postings, key=lambda item: (item[0], bucket_digest(item[0], item[1]))):
            members = sorted(postings[key], key=lambda item: item["doc_index"])
            size = len(members)
            band_start, bucket = key
            pair_upper_bound += size * (size - 1) // 2
            collision_document_memberships += size
            max_bucket_size = max(max_bucket_size, size)
            row = {
                "band_start": band_start,
                "bucket_hash_sha256": bucket_digest(band_start, bucket),
                "bucket_size": size,
                "members": members,
            }
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            index_rows.append({
                "band_start": band_start,
                "bucket_hash_sha256": row["bucket_hash_sha256"],
                "bucket_size": size,
                "first_doc_index": members[0]["doc_index"],
            })

    index_sha = sha256_file(args.index_out)
    index_row_digest = digest_rows(index_rows)
    view = filtered_view.get("cumulative_filtered_view", {})
    stats = args._scan_stats
    failures = []
    if stats["excluded_documents_seen"] != len(exclusions):
        failures.append({"code": "not_all_exclusions_seen", "seen": stats["excluded_documents_seen"], "expected": len(exclusions)})
    if stats["documents_seen"] != filtered_view.get("source_corpus", {}).get("documents_seen"):
        failures.append({"code": "documents_seen_mismatch", "actual": stats["documents_seen"], "expected": filtered_view.get("source_corpus", {}).get("documents_seen")})
    if docs_censused != stats["eligible_documents_after_filter_seen"]:
        failures.append({"code": "censused_eligible_mismatch", "documents_censused": docs_censused, "eligible": stats["eligible_documents_after_filter_seen"]})
    if any(len(members) < 2 for members in postings.values()):
        failures.append({"code": "singleton_bucket_written"})

    result = {
        "kind": "single_4090_c1_cumulative_filtered_lsh_candidate_index_v4",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": VERDICT if not failures else "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "source_receipt": SOURCE_RECEIPT,
        "policy_receipt": POLICY_RECEIPT,
        "source_filtered_view_receipt": FILTERED_VIEW,
        "source_exclusion_manifest": EXCLUSION_MANIFEST,
        "source_exclusion_manifest_sha256": sha256_file(baseline / EXCLUSION_MANIFEST),
        "exclusion_manifest_row_digest_sha256": digest_rows(exclusions),
        "method": "two-pass v4-filtered LSH candidate-index materialization; first pass counts selected-band buckets, second pass writes only collision bucket members for exact Jaccard adjudication",
        "scope_limit": "Candidate-index materialization only. It is not exact Jaccard adjudication, not an all-pairs near-duplicate PASS, not eval-contamination evidence, and not overall baseline completion.",
        "threshold": threshold,
        "shingle_size_tokens": shingle_size,
        "signature_size": args.signature_size,
        "band_size": args.band_size,
        "band_starts_materialized": band_starts,
        "band_count_materialized": len(band_starts),
        "full_band_coverage": band_starts == list(range(0, args.signature_size, args.band_size)),
        "full_document_coverage": True,
        "documents_seen": stats["documents_seen"],
        "eligible_documents_after_filter_seen": stats["eligible_documents_after_filter_seen"],
        "documents_censused": docs_censused,
        "excluded_document_count": len(exclusions),
        "excluded_documents_seen": stats["excluded_documents_seen"],
        "remaining_document_count": view.get("remaining_document_count"),
        "remaining_content_token_floor": view.get("remaining_content_token_floor"),
        "skipped_short_documents_after_filter": stats["skipped_short_documents_after_filter"],
        "skipped_long_documents_after_filter": stats["skipped_long_documents_after_filter"],
        "collision_bucket_count": len(postings),
        "collision_document_memberships": collision_document_memberships,
        "candidate_pair_upper_bound_before_deduplication": pair_upper_bound,
        "max_bucket_size": max_bucket_size,
        "index_path": args.index_out.relative_to(baseline).as_posix() if baseline in args.index_out.resolve().parents else args.index_out.as_posix(),
        "index_sha256": index_sha,
        "index_row_count": len(postings),
        "index_row_digest_sha256": index_row_digest,
        "shards": stats["shards"],
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This materializes LSH collision candidates only. Exact candidate-pair Jaccard adjudication, remediation as needed, and a replacement C1 near-duplicate PASS receipt remain required before C1 or overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
