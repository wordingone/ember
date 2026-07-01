#!/usr/bin/env python3
"""Exact-Jaccard adjudicate a v13-filtered LSH candidate index.

This consumes a materialized collision-bucket member index and computes exact
13-token-shingle Jaccard for candidate pairs. It is intentionally scoped to an
adjudication receipt: any crossing pairs keep C1 open, and even a clean partial
band remains non-completion until the required full C1 pass receipts exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_c1_near_duplicate_sample import (  # noqa: E402
    POLICY_RECEIPT,
    SOURCE_RECEIPT,
    iter_docs,
    jaccard,
    read_json,
    sha256_file,
    shingle_hashes,
)
from scan_c1_cumulative_filtered_lsh_bucket_census_v4 import (  # noqa: E402
    digest_rows,
    read_jsonl,
)

EXCLUSION_MANIFEST = "fragments/c1-near-duplicate-cumulative-exclusions-v13-2026-07-01.jsonl"
FILTERED_VIEW = "receipts/4090-cumulative-filtered-corpus-view-v13-2026-07-01.json"


VERDICT_CLEAN = "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_EXACT_ADJUDICATION_NO_CROSSINGS_NOT_COMPLETION"
VERDICT_CROSSINGS = "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION"
VERDICT_INVALID = "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_EXACT_ADJUDICATION_INVALID"


def read_index_rows(path: Path, skip_buckets: int = 0, max_buckets: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_rows = 0
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if not line.strip():
                continue
            if seen_rows < skip_buckets:
                seen_rows += 1
                continue
            seen_rows += 1
            rows.append(json.loads(line))
            if max_buckets is not None and len(rows) >= max_buckets:
                break
    return rows


def pair_upper_bound(rows: list[dict[str, Any]]) -> int:
    return sum(int(row["bucket_size"]) * (int(row["bucket_size"]) - 1) // 2 for row in rows)


def collect_required_docs(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    docs: dict[int, dict[str, Any]] = {}
    for row in rows:
        for member in row.get("members", []):
            idx = int(member["doc_index"])
            existing = docs.get(idx)
            if existing is not None and existing.get("doc_sha256") != member.get("doc_sha256"):
                raise SystemExit(f"candidate index doc sha conflict for doc_index {idx}")
            docs[idx] = {
                "doc_index": idx,
                "doc_sha256": str(member["doc_sha256"]),
                "shard": str(member["shard"]),
                "token_len": int(member["token_len"]),
            }
    return docs


def load_required_shingles(
    args: argparse.Namespace,
    source: dict[str, Any],
    required: dict[int, dict[str, Any]],
    excluded: dict[int, str],
    shingle_size: int,
) -> tuple[dict[int, np.ndarray], dict[str, Any]]:
    remaining = set(required)
    shingles_by_doc: dict[int, np.ndarray] = {}
    docs_seen = excluded_docs_seen = 0
    carry = bytearray()
    shard_rows: list[dict[str, Any]] = []
    for expected in source["shards"]:
        name = expected["name"]
        path = args.shard_dir.resolve() / name
        if not path.exists():
            raise SystemExit(f"missing shard: {name}")
        observed_sha = sha256_file(path)
        if observed_sha != expected["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}")
        shard_docs = shard_required = shard_excluded = 0
        for doc in iter_docs(path, args.chunk_bytes, carry):
            doc_index = docs_seen
            docs_seen += 1
            shard_docs += 1
            doc_sha = hashlib.sha256(doc).hexdigest()
            if doc_index in excluded:
                excluded_docs_seen += 1
                shard_excluded += 1
                if excluded[doc_index] != doc_sha:
                    raise SystemExit(f"exclusion sha mismatch at doc_index {doc_index}")
            if doc_index not in remaining:
                continue
            expected_row = required[doc_index]
            if expected_row["doc_sha256"] != doc_sha:
                raise SystemExit(f"candidate index sha mismatch for doc_index {doc_index}")
            token_len = len(doc) // 2
            if expected_row["token_len"] != token_len or expected_row["shard"] != name:
                raise SystemExit(f"candidate index metadata mismatch for doc_index {doc_index}")
            tokens = np.frombuffer(doc, dtype="<u2").copy()
            shingles_by_doc[doc_index] = shingle_hashes(tokens, shingle_size)
            remaining.remove(doc_index)
            shard_required += 1
        shard_rows.append({
            "name": name,
            "sha256": observed_sha,
            "documents_seen": shard_docs,
            "candidate_documents_loaded": shard_required,
            "excluded_documents": shard_excluded,
        })
    if carry:
        raise SystemExit("unexpected unterminated trailing document carry")
    return shingles_by_doc, {
        "documents_seen": docs_seen,
        "excluded_documents_seen": excluded_docs_seen,
        "candidate_documents_loaded": len(shingles_by_doc),
        "missing_candidate_documents": sorted(remaining)[:25],
        "missing_candidate_document_count": len(remaining),
        "shards": shard_rows,
    }


def exact_adjudicate(rows: list[dict[str, Any]], required: dict[int, dict[str, Any]], shingles_by_doc: dict[int, np.ndarray], threshold: float, sample_limit: int) -> dict[str, Any]:
    total_pairs = 0
    size_pruned_pairs = 0
    exact_pairs = 0
    crossing_pair_count = 0
    max_exact = 0.0
    crossing_samples: list[dict[str, Any]] = []
    bucket_summaries: list[dict[str, Any]] = []
    for row in rows:
        members = sorted(row.get("members", []), key=lambda item: int(item["doc_index"]))
        bucket_pairs = len(members) * (len(members) - 1) // 2
        bucket_exact = 0
        bucket_pruned = 0
        bucket_crossings = 0
        bucket_max = 0.0
        for i, left in enumerate(members):
            left_idx = int(left["doc_index"])
            left_shingles = shingles_by_doc[left_idx]
            left_size = int(left_shingles.size)
            for right in members[i + 1:]:
                right_idx = int(right["doc_index"])
                right_shingles = shingles_by_doc[right_idx]
                right_size = int(right_shingles.size)
                total_pairs += 1
                if left_size == 0 and right_size == 0:
                    exact = 1.0
                else:
                    small = min(left_size, right_size)
                    large = max(left_size, right_size)
                    if large and (small / large) < threshold:
                        size_pruned_pairs += 1
                        bucket_pruned += 1
                        continue
                    exact = jaccard(left_shingles, right_shingles)
                    exact_pairs += 1
                    bucket_exact += 1
                if exact > max_exact:
                    max_exact = exact
                if exact > bucket_max:
                    bucket_max = exact
                if exact >= threshold:
                    crossing_pair_count += 1
                    bucket_crossings += 1
                    if len(crossing_samples) < sample_limit:
                        crossing_samples.append({
                            "bucket_hash_sha256": row.get("bucket_hash_sha256"),
                            "band_start": row.get("band_start"),
                            "left": required[left_idx],
                            "right": required[right_idx],
                            "exact_jaccard": round(float(exact), 6),
                        })
        bucket_summaries.append({
            "band_start": row.get("band_start"),
            "bucket_hash_sha256": row.get("bucket_hash_sha256"),
            "bucket_size": len(members),
            "candidate_pair_count": bucket_pairs,
            "size_pruned_pair_count": bucket_pruned,
            "exact_jaccard_pair_count": bucket_exact,
            "crossing_pair_count": bucket_crossings,
            "max_exact_jaccard": round(bucket_max, 6),
        })
    return {
        "candidate_pair_count": total_pairs,
        "size_pruned_pair_count": size_pruned_pairs,
        "exact_jaccard_pair_count": exact_pairs,
        "crossing_pair_count": crossing_pair_count,
        "max_exact_jaccard_observed": round(max_exact, 6),
        "crossing_samples": crossing_samples,
        "bucket_summary_digest_sha256": digest_rows(bucket_summaries),
        "bucket_summaries_sample": sorted(bucket_summaries, key=lambda item: (item["crossing_pair_count"], item["max_exact_jaccard"], item["candidate_pair_count"]), reverse=True)[:25],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--candidate-receipt", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skip-buckets", type=int, default=0, help="Skip the first N materialized index rows before adjudicating a window.")
    parser.add_argument("--max-buckets", type=int, help="Adjudicate only N index rows after --skip-buckets for smoke/progress receipts.")
    parser.add_argument("--crossing-sample-limit", type=int, default=25)
    parser.add_argument("--min-doc-tokens", type=int, default=64)
    parser.add_argument("--max-doc-tokens", type=int, default=4096)
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
    excluded = {int(row["doc_index"]): str(row["doc_sha256"]) for row in exclusions}
    candidate_receipt_rel = args.candidate_receipt.replace("\\", "/")
    candidate_receipt = read_json(baseline / candidate_receipt_rel)
    index_path = baseline / candidate_receipt["index_path"]
    rows = read_index_rows(index_path, args.skip_buckets, args.max_buckets)
    required = collect_required_docs(rows)
    threshold = float(policy["thresholds"]["near_duplicate_minhash"]["primary_jaccard_threshold"])
    shingle_size = int(policy["thresholds"]["near_duplicate_minhash"]["shingle_size_tokens"])
    shingles_by_doc, load_stats = load_required_shingles(args, source, required, excluded, shingle_size)
    adjudication = exact_adjudicate(rows, required, shingles_by_doc, threshold, args.crossing_sample_limit)

    failures: list[dict[str, Any]] = []
    if candidate_receipt.get("index_sha256") != sha256_file(index_path):
        failures.append({"code": "candidate_index_sha256_mismatch"})
    if load_stats["missing_candidate_document_count"]:
        failures.append({"code": "missing_candidate_documents", "count": load_stats["missing_candidate_document_count"], "sample": load_stats["missing_candidate_documents"]})
    if load_stats["excluded_documents_seen"] != len(exclusions):
        failures.append({"code": "not_all_exclusions_seen", "seen": load_stats["excluded_documents_seen"], "expected": len(exclusions)})
    if load_stats["documents_seen"] != filtered_view.get("source_corpus", {}).get("documents_seen"):
        failures.append({"code": "documents_seen_mismatch", "actual": load_stats["documents_seen"], "expected": filtered_view.get("source_corpus", {}).get("documents_seen")})
    expected_pairs = pair_upper_bound(rows)
    if adjudication["candidate_pair_count"] != expected_pairs:
        failures.append({"code": "candidate_pair_count_mismatch", "actual": adjudication["candidate_pair_count"], "expected": expected_pairs})

    partial = args.skip_buckets > 0 or (args.max_buckets is not None and (args.skip_buckets + args.max_buckets) < int(candidate_receipt.get("index_row_count", 0)))
    if failures:
        verdict = VERDICT_INVALID
    elif adjudication["crossing_pair_count"]:
        verdict = VERDICT_CROSSINGS
    else:
        verdict = VERDICT_CLEAN

    result = {
        "kind": "single_4090_c1_cumulative_filtered_lsh_candidate_index_V13_exact_adjudication",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": verdict,
        "failure_count": len(failures),
        "failures": failures,
        "source_receipt": SOURCE_RECEIPT,
        "policy_receipt": POLICY_RECEIPT,
        "source_filtered_view_receipt": FILTERED_VIEW,
        "source_exclusion_manifest": EXCLUSION_MANIFEST,
        "source_exclusion_manifest_sha256": sha256_file(baseline / EXCLUSION_MANIFEST),
        "exclusion_manifest_row_digest_sha256": digest_rows(exclusions),
        "candidate_index_receipt": candidate_receipt_rel,
        "candidate_index_path": candidate_receipt.get("index_path"),
        "candidate_index_sha256": candidate_receipt.get("index_sha256"),
        "method": "exact 13-token-shingle Jaccard adjudication over materialized LSH collision buckets; size-ratio upper-bound pruning is allowed only when it proves Jaccard cannot reach threshold",
        "scope_limit": "Exact adjudication for the named candidate-index rows only. It is not full 16-band adjudication, not eval-contamination evidence, not a replacement C1 near-duplicate PASS by itself, and not overall baseline completion.",
        "threshold": threshold,
        "shingle_size_tokens": shingle_size,
        "band_starts_adjudicated": candidate_receipt.get("band_starts_materialized"),
        "index_rows_available": candidate_receipt.get("index_row_count"),
        "index_rows_skipped": args.skip_buckets,
        "index_row_start_offset": args.skip_buckets,
        "index_row_end_exclusive": args.skip_buckets + len(rows),
        "index_rows_adjudicated": len(rows),
        "partial_index_adjudication": partial,
        "candidate_documents_required": len(required),
        "candidate_documents_loaded": load_stats["candidate_documents_loaded"],
        **adjudication,
        "documents_seen": load_stats["documents_seen"],
        "excluded_document_count": len(exclusions),
        "excluded_documents_seen": load_stats["excluded_documents_seen"],
        "remaining_document_count": filtered_view.get("cumulative_filtered_view", {}).get("remaining_document_count"),
        "remaining_content_token_floor": filtered_view.get("cumulative_filtered_view", {}).get("remaining_content_token_floor"),
        "shards": load_stats["shards"],
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This exact-adjudication receipt is not C1 completion. Full required candidate coverage, remediation if crossings are found, replacement C1 near-duplicate PASS receipts, full eval-contamination receipts, and overall baseline verifier PASS remain required.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
