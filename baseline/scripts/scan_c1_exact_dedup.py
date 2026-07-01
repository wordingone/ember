#!/usr/bin/env python3
"""Scan the C1 token shards for exact duplicate documents.

The scan is public-safe: local shard paths are inputs, but the receipt records only
repo-relative source receipts, shard names, hashes, token counts, and aggregate
results. Documents are exact token-byte spans delimited by separator token 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SEPARATOR_ID = 0
EXPECTED_RECEIPT = "receipts/token-shards-v0-20260611T170047Z.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finalize_doc(
    doc_bytes: bytes | memoryview,
    doc_len_tokens: int,
    shard_name: str,
    docs_seen: int,
    counts: dict[tuple[int, bytes], int],
    first_seen: dict[tuple[int, bytes], tuple[int, str]],
    duplicate_samples: list[dict[str, Any]],
    max_samples: int,
) -> tuple[int, int]:
    if doc_len_tokens == 0:
        return 0, 0
    digest = hashlib.sha256(doc_bytes).digest()
    key = (doc_len_tokens, digest)
    prior = counts.get(key, 0)
    counts[key] = prior + 1
    if prior == 0:
        first_seen[key] = (docs_seen, shard_name)
        return 0, 0
    duplicate_tokens = doc_len_tokens
    if len(duplicate_samples) < max_samples:
        first_doc_index, first_shard = first_seen[key]
        duplicate_samples.append(
            {
                "sha256": digest.hex(),
                "doc_len_tokens": doc_len_tokens,
                "first_doc_index": first_doc_index,
                "first_shard": first_shard,
                "duplicate_doc_index": docs_seen,
                "duplicate_shard": shard_name,
                "occurrence_number": prior + 1,
            }
        )
    return 1, duplicate_tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--chunk-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-samples", type=int, default=25)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if args.chunk_bytes % 2:
        raise SystemExit("--chunk-bytes must be even for uint16 token shards")

    started = time.time()
    root = args.baseline_root.resolve()
    shard_dir = args.shard_dir.resolve()
    source_receipt = read_json(root.parent / EXPECTED_RECEIPT)
    expected_shards = source_receipt["shards"]

    counts: dict[tuple[int, bytes], int] = {}
    first_seen: dict[tuple[int, bytes], tuple[int, str]] = {}
    duplicate_samples: list[dict[str, Any]] = []
    docs_seen = 0
    duplicate_docs = 0
    duplicate_tokens = 0
    empty_docs = 0
    separators_seen = 0
    total_tokens = 0
    max_doc_tokens = 0
    shard_rows: list[dict[str, Any]] = []
    carry = bytearray()
    carry_tokens = 0

    for expected in expected_shards:
        name = expected["name"]
        path = shard_dir / name
        if not path.exists():
            raise SystemExit(f"missing shard: {name}")
        size = path.stat().st_size
        if size != expected["n_tokens"] * 2:
            raise SystemExit(f"size mismatch for {name}: {size} != {expected['n_tokens'] * 2}")
        observed_sha = sha256_file(path)
        if observed_sha != expected["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}: {observed_sha} != {expected['sha256']}")

        shard_separators = 0
        shard_docs = 0
        shard_duplicate_docs = 0
        with path.open("rb") as fh:
            while True:
                data = fh.read(args.chunk_bytes)
                if not data:
                    break
                if len(data) % 2:
                    raise SystemExit(f"odd byte chunk in {name}")
                arr = np.frombuffer(data, dtype="<u2")
                total_tokens += int(arr.size)
                sep_positions = np.flatnonzero(arr == SEPARATOR_ID)
                start_token = 0
                view = memoryview(data)
                for sep_token in sep_positions.tolist():
                    seg = view[start_token * 2 : sep_token * 2]
                    doc_len = carry_tokens + (sep_token - start_token)
                    max_doc_tokens = max(max_doc_tokens, doc_len)
                    if doc_len == 0:
                        empty_docs += 1
                    else:
                        if carry:
                            doc = bytes(carry) + seg.tobytes()
                        else:
                            doc = seg
                        dup_doc, dup_tok = finalize_doc(
                            doc,
                            doc_len,
                            name,
                            docs_seen,
                            counts,
                            first_seen,
                            duplicate_samples,
                            args.max_samples,
                        )
                        duplicate_docs += dup_doc
                        duplicate_tokens += dup_tok
                        shard_duplicate_docs += dup_doc
                    docs_seen += 1
                    shard_docs += 1
                    separators_seen += 1
                    shard_separators += 1
                    carry.clear()
                    carry_tokens = 0
                    start_token = sep_token + 1
                if start_token < int(arr.size):
                    carry.extend(view[start_token * 2 :].tobytes())
                    carry_tokens += int(arr.size) - start_token
        shard_rows.append(
            {
                "name": name,
                "sha256": observed_sha,
                "n_tokens": expected["n_tokens"],
                "separator_tokens": shard_separators,
                "documents_closed": shard_docs,
                "duplicate_documents": shard_duplicate_docs,
            }
        )

    trailing_doc_tokens = carry_tokens
    if carry_tokens:
        max_doc_tokens = max(max_doc_tokens, carry_tokens)
        dup_doc, dup_tok = finalize_doc(
            bytes(carry),
            carry_tokens,
            expected_shards[-1]["name"],
            docs_seen,
            counts,
            first_seen,
            duplicate_samples,
            args.max_samples,
        )
        duplicate_docs += dup_doc
        duplicate_tokens += dup_tok
        docs_seen += 1

    expected_stream = source_receipt.get("total_stream_tokens")
    expected_separators = source_receipt.get("freeze_reproduction", {}).get("separator_tokens")
    failures = []
    if total_tokens != expected_stream:
        failures.append({"code": "stream_token_total_mismatch", "expected": expected_stream, "actual": total_tokens})
    if separators_seen != expected_separators:
        failures.append({"code": "separator_total_mismatch", "expected": expected_separators, "actual": separators_seen})

    verdict = "C1_EXACT_DEDUPE_PASS" if not failures and duplicate_docs == 0 else "C1_EXACT_DEDUPE_DUPLICATES_FOUND" if not failures else "C1_EXACT_DEDUPE_INVALID"
    result = {
        "kind": "single_4090_c1_exact_document_dedupe_scan",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": verdict,
        "failure_count": len(failures),
        "failures": failures,
        "method": "stream uint16 token shards in pinned shard order; split documents on separator token id 0; sha256 exact token-byte document spans; count repeated (length, sha256) keys",
        "source_receipt": EXPECTED_RECEIPT,
        "local_path_policy": "shard-dir is an input only; checked-in receipt records shard names and hashes, not machine-local absolute paths",
        "separator_token_id": SEPARATOR_ID,
        "total_stream_tokens": total_tokens,
        "separator_tokens": separators_seen,
        "documents_seen": docs_seen,
        "empty_documents": empty_docs,
        "unique_nonempty_documents": len(counts),
        "duplicate_documents": duplicate_docs,
        "duplicate_document_tokens": duplicate_tokens,
        "duplicate_document_fraction": duplicate_docs / docs_seen if docs_seen else 0.0,
        "duplicate_token_fraction_of_stream": duplicate_tokens / total_tokens if total_tokens else 0.0,
        "max_doc_tokens": max_doc_tokens,
        "trailing_doc_tokens_after_last_separator": trailing_doc_tokens,
        "shards": shard_rows,
        "duplicate_samples": duplicate_samples,
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This is an exact token-document duplicate scan only. It is not a near-duplicate/MinHash scan, not an eval contamination scan, not a data-quality guarantee, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if verdict == "C1_EXACT_DEDUPE_PASS" else (1 if verdict == "C1_EXACT_DEDUPE_DUPLICATES_FOUND" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
