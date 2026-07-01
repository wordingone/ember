#!/usr/bin/env python3
"""Expand discovered C1 near-duplicate sample clusters across the full shard stream."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np

SEPARATOR_ID = 0
SOURCE_RECEIPT = "receipts/token-shards-v0-20260611T170047Z.json"
REMEDIATION_RECEIPT = "receipts/4090-near-duplicate-sample-remediation-2026-06-30.json"
POLICY_RECEIPT = "baseline/receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def shingle_hashes(tokens: np.ndarray, k: int) -> np.ndarray:
    if tokens.size < k:
        return np.empty(0, dtype=np.uint64)
    base = np.uint64(1469598103934665603)
    prime = np.uint64(1099511628211)
    for i in range(k):
        vals = tokens[i : tokens.size - k + 1 + i].astype(np.uint64, copy=False)
        base = (base ^ (vals + np.uint64((i + 1) * 1315423911))) * prime
    return np.unique(base)


def jaccard_to_ref(shingles: np.ndarray, ref: np.ndarray) -> float:
    if shingles.size == 0 and ref.size == 0:
        return 1.0
    if shingles.size == 0 or ref.size == 0:
        return 0.0
    inter = np.intersect1d(shingles, ref, assume_unique=True).size
    union = shingles.size + ref.size - inter
    return float(inter / union) if union else 0.0


def iter_docs(path: Path, chunk_bytes: int, carry: bytearray) -> Iterator[bytes]:
    with path.open("rb") as fh:
        while True:
            data = fh.read(chunk_bytes)
            if not data:
                break
            if len(data) % 2:
                raise SystemExit(f"odd byte chunk in {path.name}")
            arr = np.frombuffer(data, dtype="<u2")
            seps = np.flatnonzero(arr == SEPARATOR_ID)
            start = 0
            view = memoryview(data)
            for sep in seps.tolist():
                seg = view[start * 2 : sep * 2]
                if carry:
                    doc = bytes(carry) + seg.tobytes()
                else:
                    doc = seg.tobytes()
                yield doc
                carry.clear()
                start = sep + 1
            if start < int(arr.size):
                carry.extend(view[start * 2 :].tobytes())


def doc_row(doc_index: int, shard: str, doc: bytes) -> dict[str, Any]:
    return {
        "doc_index": doc_index,
        "doc_sha256": hashlib.sha256(doc).hexdigest(),
        "shard": shard,
        "token_len": len(doc) // 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-doc-tokens", type=int, default=64)
    parser.add_argument("--max-doc-tokens", type=int, default=4096)
    parser.add_argument("--chunk-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-matches", type=int, default=100000)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    started = time.time()
    repo = args.repo_root.resolve()
    source = read_json(repo / SOURCE_RECEIPT)
    remediation = read_json(repo / "baseline" / REMEDIATION_RECEIPT) if (repo / "baseline").name == "baseline" else read_json(repo / REMEDIATION_RECEIPT)
    policy = read_json(repo / POLICY_RECEIPT)
    threshold = float(policy["thresholds"]["near_duplicate_minhash"]["primary_jaccard_threshold"])
    shingle_size = int(policy["thresholds"]["near_duplicate_minhash"]["shingle_size_tokens"])

    clusters = remediation.get("clusters", [])
    target_rows = [cluster["keep"] for cluster in clusters]
    target_by_index = {int(row["doc_index"]): row for row in target_rows}
    target_docs: dict[int, bytes] = {}
    shard_rows = []

    docs_seen = 0
    carry = bytearray()
    for expected in source["shards"]:
        name = expected["name"]
        path = args.shard_dir.resolve() / name
        observed_sha = sha256_file(path)
        if observed_sha != expected["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}")
        shard_docs = 0
        for doc in iter_docs(path, args.chunk_bytes, carry):
            if docs_seen in target_by_index:
                target_docs[docs_seen] = doc
            docs_seen += 1
            shard_docs += 1
        shard_rows.append({"name": name, "sha256": observed_sha, "documents_seen": shard_docs})
    if carry:
        if docs_seen in target_by_index:
            target_docs[docs_seen] = bytes(carry)
        docs_seen += 1

    missing_targets = sorted(set(target_by_index) - set(target_docs))
    if missing_targets:
        raise SystemExit(f"missing target docs: {missing_targets}")

    target_shingles = {}
    for idx, doc in target_docs.items():
        observed = doc_row(idx, target_by_index[idx]["shard"], doc)
        if observed["doc_sha256"] != target_by_index[idx]["doc_sha256"]:
            raise SystemExit(f"target doc hash mismatch for {idx}")
        target_shingles[idx] = shingle_hashes(np.frombuffer(doc, dtype="<u2").copy(), shingle_size)

    matches_by_target: dict[int, list[dict[str, Any]]] = {idx: [] for idx in target_shingles}
    eligible_docs = skipped_short = skipped_long = 0
    docs_seen_second = 0
    carry = bytearray()
    for expected in source["shards"]:
        name = expected["name"]
        path = args.shard_dir.resolve() / name
        for doc in iter_docs(path, args.chunk_bytes, carry):
            token_len = len(doc) // 2
            if token_len < args.min_doc_tokens:
                skipped_short += 1
                docs_seen_second += 1
                continue
            if token_len > args.max_doc_tokens:
                skipped_long += 1
                docs_seen_second += 1
                continue
            eligible_docs += 1
            tokens = np.frombuffer(doc, dtype="<u2").copy()
            shingles = shingle_hashes(tokens, shingle_size)
            best_target = None
            best_jaccard = 0.0
            for target_idx, ref in target_shingles.items():
                exact = jaccard_to_ref(shingles, ref)
                if exact > best_jaccard:
                    best_jaccard = exact
                    best_target = target_idx
            if best_target is not None and best_jaccard >= threshold:
                row = doc_row(docs_seen_second, name, doc)
                row["exact_jaccard_to_target"] = round(best_jaccard, 6)
                matches_by_target[best_target].append(row)
                total_matches = sum(len(rows) for rows in matches_by_target.values())
                if total_matches > args.max_matches:
                    raise SystemExit(f"match cap exceeded: {total_matches}")
            docs_seen_second += 1
    if carry:
        docs_seen_second += 1

    sample_exclusions = {(int(row["doc_index"]), str(row["doc_sha256"])) for row in remediation.get("exclusions", [])}
    expanded_exclusions = []
    target_summaries = []
    for target_idx, rows in sorted(matches_by_target.items()):
        target_hash = target_by_index[target_idx]["doc_sha256"]
        removals = []
        for row in sorted(rows, key=lambda item: (item["doc_index"], item["doc_sha256"])):
            if row["doc_index"] == target_idx and row["doc_sha256"] == target_hash:
                continue
            removals.append(row)
        expanded_exclusions.extend(removals)
        target_summaries.append(
            {
                "target_doc_index": target_idx,
                "target_doc_sha256": target_hash,
                "match_count_including_target": len(rows),
                "exclusion_count": len(removals),
                "max_exact_jaccard": max((row["exact_jaccard_to_target"] for row in rows), default=0.0),
            }
        )
    expanded_keys = {(int(row["doc_index"]), str(row["doc_sha256"])) for row in expanded_exclusions}
    missing_sample_exclusions = sorted(sample_exclusions - expanded_keys)
    token_floor = sum(int(row["token_len"]) for row in expanded_exclusions)

    result = {
        "kind": "single_4090_c1_near_duplicate_targeted_expansion",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_READY" if not missing_sample_exclusions else "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_INCOMPLETE",
        "source_receipt": SOURCE_RECEIPT,
        "remediation_receipt": REMEDIATION_RECEIPT,
        "policy_receipt": POLICY_RECEIPT,
        "local_path_policy": "shard-dir is an input only; checked-in receipt records shard names and hashes, not machine-local absolute paths",
        "method": "full pinned-shard stream scan for documents with exact 13-token shingle Jaccard >= 0.80 to the deterministic representatives of the discovered sample clusters",
        "threshold": threshold,
        "shingle_size_tokens": shingle_size,
        "target_count": len(target_shingles),
        "documents_seen": docs_seen_second,
        "documents_seen_first_pass": docs_seen,
        "eligible_documents": eligible_docs,
        "skipped_short_documents": skipped_short,
        "skipped_long_documents": skipped_long,
        "sample_exclusion_document_count": len(sample_exclusions),
        "expanded_exclusion_document_count": len(expanded_exclusions),
        "expanded_exclusion_token_floor": token_floor,
        "missing_sample_exclusions": [f"{idx}:{digest}" for idx, digest in missing_sample_exclusions],
        "target_summaries": target_summaries,
        "exclusions": sorted(expanded_exclusions, key=lambda item: (item["doc_index"], item["doc_sha256"])),
        "shards": shard_rows,
        "elapsed_seconds": round(time.time() - started, 3),
        "scope_limit": "This expands only the already-discovered sample cluster representatives across the full corpus. It is not an all-pairs full-corpus near-duplicate PASS and cannot complete C1 data hygiene by itself.",
        "completion_limit": "This targeted expansion supplies a materialized exclusion packet for discovered near-duplicate clusters only. Full all-pairs MinHash/near-duplicate scan, final corpus materialization, and post-remediation PASS validation remain required.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["verdict"] == "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
