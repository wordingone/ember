#!/usr/bin/env python3
"""Run a bounded C1 near-duplicate MinHash sample scan over pinned token shards."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SEPARATOR_ID = 0
SOURCE_RECEIPT = "receipts/token-shards-v0-20260611T170047Z.json"
POLICY_RECEIPT = "baseline/receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json"
MASK64 = (1 << 64) - 1


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_score(doc_bytes: bytes | memoryview) -> int:
    return int.from_bytes(hashlib.blake2b(doc_bytes, digest_size=8, person=b"c1near01").digest(), "big")


def shingle_hashes(tokens: np.ndarray, k: int) -> np.ndarray:
    if tokens.size < k:
        return np.empty(0, dtype=np.uint64)
    out = np.empty(tokens.size - k + 1, dtype=np.uint64)
    # Deterministic 64-bit rolling-ish hash over uint16 shingles. This is not
    # cryptographic; MinHash only needs stable shingle identities.
    base = np.uint64(1469598103934665603)
    prime = np.uint64(1099511628211)
    for i in range(k):
        vals = tokens[i : tokens.size - k + 1 + i].astype(np.uint64, copy=False)
        base = (base ^ (vals + np.uint64((i + 1) * 1315423911))) * prime
    out[:] = base
    return np.unique(out)


def minhash_signature(shingles: np.ndarray, seeds: list[int]) -> list[int]:
    sig: list[int] = []
    vals = shingles.astype(np.uint64, copy=False)
    for seed in seeds:
        mixed = (vals ^ np.uint64(seed)) * np.uint64(0x9E3779B185EBCA87)
        mixed ^= mixed >> np.uint64(33)
        sig.append(int(mixed.min()) if mixed.size else 0)
    return sig


def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 and b.size == 0:
        return 1.0
    i = j = inter = 0
    while i < a.size and j < b.size:
        av = int(a[i])
        bv = int(b[j])
        if av == bv:
            inter += 1
            i += 1
            j += 1
        elif av < bv:
            i += 1
        else:
            j += 1
    union = a.size + b.size - inter
    return inter / union if union else 0.0


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


def iter_docs(path: Path, chunk_bytes: int, carry: bytearray):
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
    return carry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
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
    source = read_json(repo / SOURCE_RECEIPT)
    policy = read_json(repo / POLICY_RECEIPT)
    threshold = policy["thresholds"]["near_duplicate_minhash"]["primary_jaccard_threshold"]
    shingle_size = policy["thresholds"]["near_duplicate_minhash"]["shingle_size_tokens"]
    seeds = [int.from_bytes(hashlib.blake2b(f"c1-near-{i}".encode(), digest_size=8).digest(), "big") for i in range(args.signature_size)]

    heap: list[tuple[int, int, dict[str, Any], bytes]] = []
    docs_seen = eligible_docs = skipped_short = skipped_long = 0
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
        shard_docs = shard_eligible = 0
        for doc in iter_docs(path, args.chunk_bytes, carry):
            token_len = len(doc) // 2
            docs_seen += 1
            shard_docs += 1
            if token_len < args.min_doc_tokens:
                skipped_short += 1
                continue
            if token_len > args.max_doc_tokens:
                skipped_long += 1
                continue
            eligible_docs += 1
            shard_eligible += 1
            score = doc_score(doc)
            tokens = np.frombuffer(doc, dtype="<u2").copy()
            maybe_add_sample(heap, score, args.sample_docs, docs_seen - 1, name, tokens, doc)
        shard_rows.append({"name": name, "sha256": observed_sha, "documents_seen": shard_docs, "eligible_documents": shard_eligible})
    if carry:
        docs_seen += 1
        token_len = len(carry) // 2
        if token_len < args.min_doc_tokens:
            skipped_short += 1
        elif token_len > args.max_doc_tokens:
            skipped_long += 1
        else:
            eligible_docs += 1
            doc = bytes(carry)
            tokens = np.frombuffer(doc, dtype="<u2").copy()
            maybe_add_sample(heap, doc_score(doc), args.sample_docs, docs_seen - 1, source["shards"][-1]["name"], tokens, doc)

    samples = sorted([item[2] | {"doc_bytes": item[3]} for item in heap], key=lambda row: row["doc_index"])
    bands: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    shingle_sets: list[np.ndarray] = []
    signatures: list[list[int]] = []
    for idx, row in enumerate(samples):
        tokens = np.frombuffer(row.pop("doc_bytes"), dtype="<u2").copy()
        shingles = shingle_hashes(tokens, shingle_size)
        sig = minhash_signature(shingles, seeds)
        shingle_sets.append(shingles)
        signatures.append(sig)
        for band_start in range(0, len(sig), args.band_size):
            band = tuple(sig[band_start : band_start + args.band_size])
            if len(band) == args.band_size:
                bands[(band_start, band)].append(idx)

    candidate_pairs = set()
    for ids in bands.values():
        if len(ids) < 2:
            continue
        for i, left in enumerate(ids):
            for right in ids[i + 1 :]:
                candidate_pairs.add((min(left, right), max(left, right)))

    crossing = []
    max_exact = 0.0
    for left, right in sorted(candidate_pairs):
        exact = jaccard(shingle_sets[left], shingle_sets[right])
        max_exact = max(max_exact, exact)
        if exact >= threshold:
            crossing.append(
                {
                    "left": {k: samples[left][k] for k in ("doc_index", "shard", "token_len", "doc_sha256")},
                    "right": {k: samples[right][k] for k in ("doc_index", "shard", "token_len", "doc_sha256")},
                    "exact_jaccard": round(exact, 6),
                }
            )
            if len(crossing) >= 25:
                break

    result = {
        "kind": "single_4090_c1_near_duplicate_minhash_sample",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NEAR_DUPLICATE_SAMPLE_NO_CROSSING_CANDIDATES" if not crossing else "C1_NEAR_DUPLICATE_SAMPLE_CANDIDATES_FOUND",
        "source_receipt": SOURCE_RECEIPT,
        "policy_receipt": POLICY_RECEIPT,
        "local_path_policy": "shard-dir is an input only; checked-in receipt records shard names and hashes, not machine-local absolute paths",
        "method": "deterministic lowest-score sample of eligible separator-delimited documents; 13-token shingle MinHash signatures; LSH candidate generation; exact Jaccard audit for candidate pairs",
        "scope_limit": "Bounded sample scan only. This is not a full corpus-wide near-duplicate PASS and cannot complete C1 data hygiene by itself.",
        "threshold": threshold,
        "shingle_size_tokens": shingle_size,
        "signature_size": args.signature_size,
        "band_size": args.band_size,
        "sample_limit": args.sample_docs,
        "sampled_documents": len(samples),
        "documents_seen": docs_seen,
        "eligible_documents": eligible_docs,
        "skipped_short_documents": skipped_short,
        "skipped_long_documents": skipped_long,
        "candidate_pair_count": len(candidate_pairs),
        "crossing_pair_count": len(crossing),
        "max_exact_jaccard_observed": round(max_exact, 6),
        "crossing_samples": crossing,
        "sample_policy": "Select documents by stable blake2b document score, independent of shard order after eligibility filtering.",
        "shards": shard_rows,
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This records bounded near-duplicate evidence only. It is not eval contamination evidence, not a full near-duplicate/MinHash pass, not a long-run training receipt, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
