#!/usr/bin/env python3
"""Scan pinned C1 token shards for exact heldout eval 32-token contamination.

This is a real exact token n-gram scan for the local Ember heldout task file.
It does not claim to cover every future eval suite or normalized character-span
contamination; those remain separate C1 blockers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from tokenizers import Tokenizer

NGRAM = 32
BASE = np.uint64(11400714819323198485)
SHARD_RECEIPT = "receipts/token-shards-v0-20260611T170047Z.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_strings(value: Any, path: str = "$"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{idx}]")


def load_heldout(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if line.strip():
                row = json.loads(line)
                row["_line"] = line_no
                rows.append(row)
    return rows


def hash_tokens(tokens: np.ndarray, powers: np.ndarray) -> int:
    vals = tokens.astype(np.uint64, copy=False)
    return int(np.sum(vals * powers, dtype=np.uint64))


def build_patterns(heldout: list[dict[str, Any]], tokenizer: Tokenizer) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    powers = (BASE ** np.arange(NGRAM, dtype=np.uint64)).astype(np.uint64)
    by_hash: dict[int, list[dict[str, Any]]] = defaultdict(list)
    item_count = len(heldout)
    string_count = 0
    tokenized_strings = 0
    ngram_count = 0
    skipped_short = 0
    for row in heldout:
        item_id = str(row.get("id", f"line-{row.get('_line')}"))
        for field_path, text in iter_strings({k: v for k, v in row.items() if not k.startswith("_")}):
            string_count += 1
            if not text.strip():
                continue
            ids = tokenizer.encode(text, add_special_tokens=False).ids
            if len(ids) < NGRAM:
                skipped_short += 1
                continue
            tokenized_strings += 1
            arr = np.asarray(ids, dtype=np.uint16)
            for start in range(0, len(ids) - NGRAM + 1):
                window = arr[start:start + NGRAM]
                if int(np.count_nonzero(window == 0)):
                    continue
                digest = hash_tokens(window, powers)
                by_hash[digest].append({
                    "item_id": item_id,
                    "field_path": field_path,
                    "start_token": start,
                    "tokens": tuple(int(x) for x in window.tolist()),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                })
                ngram_count += 1
    summary = {
        "heldout_items": item_count,
        "strings_seen": string_count,
        "tokenized_strings_with_ngrams": tokenized_strings,
        "strings_shorter_than_ngram": skipped_short,
        "unique_ngram_hashes": len(by_hash),
        "total_ngram_patterns": ngram_count,
    }
    return by_hash, summary


def rolling_hashes(tokens: np.ndarray, powers: np.ndarray) -> np.ndarray:
    n = int(tokens.size) - NGRAM + 1
    out = np.zeros(n, dtype=np.uint64)
    vals = tokens.astype(np.uint64, copy=False)
    for offset in range(NGRAM):
        out += vals[offset:offset + n] * powers[offset]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--chunk-tokens", type=int, default=4_194_304)
    parser.add_argument("--max-hits", type=int, default=50)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    started = time.time()
    root = args.baseline_root.resolve()
    heldout_path = args.heldout.resolve()
    tokenizer_path = args.tokenizer.resolve()
    shard_dir = args.shard_dir.resolve()
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    heldout = load_heldout(heldout_path)
    patterns, pattern_summary = build_patterns(heldout, tokenizer)
    pattern_hashes = np.asarray(list(patterns.keys()), dtype=np.uint64)
    powers = (BASE ** np.arange(NGRAM, dtype=np.uint64)).astype(np.uint64)
    shard_receipt = read_json(root.parent / SHARD_RECEIPT)

    hits: list[dict[str, Any]] = []
    windows_scanned = 0
    invalid_separator_windows = 0
    candidate_hash_hits = 0
    total_tokens = 0
    carry = np.asarray([], dtype=np.uint16)
    shard_rows: list[dict[str, Any]] = []

    for shard in shard_receipt["shards"]:
        name = shard["name"]
        path = shard_dir / name
        if not path.exists():
            raise SystemExit(f"missing shard {name}")
        if sha256_file(path) != shard["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}")
        mmap = np.memmap(path, dtype="<u2", mode="r")
        shard_hits = 0
        shard_windows = 0
        pos = 0
        while pos < int(mmap.size):
            end = min(pos + args.chunk_tokens, int(mmap.size))
            chunk = np.asarray(mmap[pos:end], dtype=np.uint16)
            if carry.size:
                scan = np.concatenate([carry, chunk])
                absolute_start_base = total_tokens - int(carry.size)
            else:
                scan = chunk
                absolute_start_base = total_tokens
            total_tokens += int(chunk.size)
            if scan.size >= NGRAM and pattern_hashes.size:
                hashes = rolling_hashes(scan, powers)
                zero = (scan == 0).astype(np.int16)
                zero_prefix = np.concatenate([np.asarray([0], dtype=np.int64), np.cumsum(zero, dtype=np.int64)])
                zero_counts = zero_prefix[NGRAM:] - zero_prefix[:-NGRAM]
                valid_mask = zero_counts == 0
                invalid_separator_windows += int(valid_mask.size - np.count_nonzero(valid_mask))
                valid_indices = np.flatnonzero(valid_mask)
                if valid_indices.size:
                    valid_hashes = hashes[valid_indices]
                    maybe = np.isin(valid_hashes, pattern_hashes)
                    for idx in valid_indices[np.flatnonzero(maybe)].tolist():
                        h = int(hashes[idx])
                        window = tuple(int(x) for x in scan[idx:idx + NGRAM].tolist())
                        for pattern in patterns.get(h, []):
                            if pattern["tokens"] == window:
                                candidate_hash_hits += 1
                                shard_hits += 1
                                if len(hits) < args.max_hits:
                                    hits.append({
                                        "item_id": pattern["item_id"],
                                        "field_path": pattern["field_path"],
                                        "heldout_start_token": pattern["start_token"],
                                        "heldout_text_sha256": pattern["text_sha256"],
                                        "shard": name,
                                        "stream_token_start": absolute_start_base + idx,
                                        "ngram_tokens_sha256": hashlib.sha256(np.asarray(window, dtype='<u2').tobytes()).hexdigest(),
                                    })
                windows_scanned += int(hashes.size)
                shard_windows += int(hashes.size)
            carry_len = min(NGRAM - 1, int(scan.size))
            carry = np.asarray(scan[-carry_len:], dtype=np.uint16).copy() if carry_len else np.asarray([], dtype=np.uint16)
            pos = end
        shard_rows.append({"name": name, "n_tokens": shard["n_tokens"], "windows_scanned": shard_windows, "exact_32_token_hits": shard_hits, "sha256": shard["sha256"]})

    failures = []
    if total_tokens != shard_receipt.get("total_stream_tokens"):
        failures.append({"code": "stream_token_total_mismatch", "expected": shard_receipt.get("total_stream_tokens"), "actual": total_tokens})
    verdict = "C1_LOCAL_HELDOUT_EXACT_32GRAM_CONTAMINATION_PASS" if not failures and candidate_hash_hits == 0 else "C1_LOCAL_HELDOUT_EXACT_32GRAM_CONTAMINATION_HITS" if not failures else "C1_LOCAL_HELDOUT_EXACT_32GRAM_CONTAMINATION_INVALID"
    result = {
        "kind": "single_4090_c1_local_heldout_exact_32gram_contamination_scan",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": verdict,
        "failure_count": len(failures),
        "failures": failures,
        "method": "tokenize every string in data/ember_avir_tasks/heldout.jsonl with frozen tokenizer.json; build exact 32-token patterns; stream pinned uint16 token shards; vectorized rolling hash with exact token verification for candidate hits; windows containing separator token 0 are excluded",
        "heldout_input": {"repo_path": "data/ember_avir_tasks/heldout.jsonl", "sha256": sha256_file(heldout_path)},
        "tokenizer": {"repo_path": "tokenizer/tokenizer.json", "sha256": sha256_file(tokenizer_path)},
        "source_receipt": SHARD_RECEIPT,
        "pattern_summary": pattern_summary,
        "total_stream_tokens": total_tokens,
        "windows_scanned": windows_scanned,
        "invalid_separator_windows": invalid_separator_windows,
        "exact_32_token_hits": candidate_hash_hits,
        "hit_samples": hits,
        "shards": shard_rows,
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This is a local heldout exact 32-token overlap scan only. It is not a full eval-suite contamination scan, not a normalized character-span scan, not a near-duplicate scan, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if verdict.endswith("PASS") else (1 if verdict.endswith("HITS") else 2)


if __name__ == "__main__":
    raise SystemExit(main())
