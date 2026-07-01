#!/usr/bin/env python3
"""Scan pinned C1 token shards for exact local heldout multi-ngram contamination."""

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
            if str(key).startswith("_"):
                continue
            yield from iter_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{idx}]")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if line.strip():
                row = json.loads(line)
                row["_line"] = line_no
                rows.append(row)
    return rows


def hash_tokens(tokens: np.ndarray, powers: np.ndarray) -> int:
    return int(np.sum(tokens.astype(np.uint64, copy=False) * powers, dtype=np.uint64))


def build_patterns(rows: list[dict[str, Any]], tokenizer: Tokenizer, ngrams: list[int]) -> tuple[dict[int, dict[int, list[dict[str, Any]]]], dict[str, Any]]:
    powers_by_n = {n: (BASE ** np.arange(n, dtype=np.uint64)).astype(np.uint64) for n in ngrams}
    by_n: dict[int, dict[int, list[dict[str, Any]]]] = {n: defaultdict(list) for n in ngrams}
    summary = {str(n): {"total_patterns": 0, "unique_hashes": 0, "strings_with_patterns": 0, "strings_too_short": 0} for n in ngrams}
    string_count = 0
    for row in rows:
        item_id = str(row.get("id", f"line-{row.get('_line')}"))
        for field_path, text in iter_strings(row):
            string_count += 1
            if not text.strip():
                continue
            ids = tokenizer.encode(text, add_special_tokens=False).ids
            arr = np.asarray(ids, dtype=np.uint16)
            for n in ngrams:
                if len(ids) < n:
                    summary[str(n)]["strings_too_short"] += 1
                    continue
                summary[str(n)]["strings_with_patterns"] += 1
                powers = powers_by_n[n]
                for start in range(0, len(ids) - n + 1):
                    window = arr[start:start+n]
                    if int(np.count_nonzero(window == 0)):
                        continue
                    digest = hash_tokens(window, powers)
                    by_n[n][digest].append({
                        "item_id": item_id,
                        "field_path": field_path,
                        "start_token": start,
                        "tokens": tuple(int(x) for x in window.tolist()),
                        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    })
                    summary[str(n)]["total_patterns"] += 1
    for n in ngrams:
        summary[str(n)]["unique_hashes"] = len(by_n[n])
    return by_n, {"heldout_items": len(rows), "strings_seen": string_count, "by_ngram": summary}


def rolling_hashes(tokens: np.ndarray, powers: np.ndarray, n: int) -> np.ndarray:
    count = int(tokens.size) - n + 1
    out = np.zeros(count, dtype=np.uint64)
    vals = tokens.astype(np.uint64, copy=False)
    for offset in range(n):
        out += vals[offset:offset+count] * powers[offset]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ngrams", default="16,32,64")
    parser.add_argument("--chunk-tokens", type=int, default=4_194_304)
    parser.add_argument("--max-hits", type=int, default=50)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    started = time.time()
    root = args.baseline_root.resolve()
    ngrams = sorted({int(x.strip()) for x in args.ngrams.split(",") if x.strip()})
    max_ngram = max(ngrams)
    tokenizer = Tokenizer.from_file(str(args.tokenizer.resolve()))
    rows = load_jsonl(args.heldout.resolve())
    patterns, pattern_summary = build_patterns(rows, tokenizer, ngrams)
    pattern_hashes = {n: np.asarray(list(patterns[n].keys()), dtype=np.uint64) for n in ngrams}
    powers = {n: (BASE ** np.arange(n, dtype=np.uint64)).astype(np.uint64) for n in ngrams}
    shard_receipt = read_json(root.parent / SHARD_RECEIPT)

    hits = {str(n): [] for n in ngrams}
    hit_counts = {str(n): 0 for n in ngrams}
    windows_scanned = {str(n): 0 for n in ngrams}
    invalid_separator_windows = {str(n): 0 for n in ngrams}
    total_tokens = 0
    carry = np.asarray([], dtype=np.uint16)
    shard_rows = []

    for shard in shard_receipt["shards"]:
        name = shard["name"]
        path = args.shard_dir.resolve() / name
        if not path.exists():
            raise SystemExit(f"missing shard {name}")
        if sha256_file(path) != shard["sha256"]:
            raise SystemExit(f"sha256 mismatch for {name}")
        mmap = np.memmap(path, dtype="<u2", mode="r")
        shard_hits = {str(n): 0 for n in ngrams}
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
            for n in ngrams:
                hashes_available = pattern_hashes[n]
                if scan.size < n or not hashes_available.size:
                    continue
                hashes = rolling_hashes(scan, powers[n], n)
                zero = (scan == 0).astype(np.int16)
                zero_prefix = np.concatenate([np.asarray([0], dtype=np.int64), np.cumsum(zero, dtype=np.int64)])
                zero_counts = zero_prefix[n:] - zero_prefix[:-n]
                valid_mask = zero_counts == 0
                invalid_separator_windows[str(n)] += int(valid_mask.size - np.count_nonzero(valid_mask))
                valid_indices = np.flatnonzero(valid_mask)
                if valid_indices.size:
                    valid_hashes = hashes[valid_indices]
                    maybe = np.isin(valid_hashes, hashes_available)
                    for idx in valid_indices[np.flatnonzero(maybe)].tolist():
                        h = int(hashes[idx])
                        window = tuple(int(x) for x in scan[idx:idx+n].tolist())
                        for pattern in patterns[n].get(h, []):
                            if pattern["tokens"] == window:
                                hit_counts[str(n)] += 1
                                shard_hits[str(n)] += 1
                                if len(hits[str(n)]) < args.max_hits:
                                    hits[str(n)].append({
                                        "item_id": pattern["item_id"],
                                        "field_path": pattern["field_path"],
                                        "heldout_start_token": pattern["start_token"],
                                        "heldout_text_sha256": pattern["text_sha256"],
                                        "shard": name,
                                        "stream_token_start": absolute_start_base + idx,
                                        "ngram_tokens_sha256": hashlib.sha256(np.asarray(window, dtype="<u2").tobytes()).hexdigest(),
                                    })
                windows_scanned[str(n)] += int(hashes.size)
            carry_len = min(max_ngram - 1, int(scan.size))
            carry = np.asarray(scan[-carry_len:], dtype=np.uint16).copy() if carry_len else np.asarray([], dtype=np.uint16)
            pos = end
        shard_rows.append({"name": name, "n_tokens": shard["n_tokens"], "exact_hits_by_ngram": shard_hits, "sha256": shard["sha256"]})

    failures = []
    if total_tokens != shard_receipt.get("total_stream_tokens"):
        failures.append({"code": "stream_token_total_mismatch", "expected": shard_receipt.get("total_stream_tokens"), "actual": total_tokens})
    total_hits = sum(hit_counts.values())
    verdict = "C1_LOCAL_HELDOUT_MULTI_NGRAM_CONTAMINATION_PASS" if not failures and total_hits == 0 else "C1_LOCAL_HELDOUT_MULTI_NGRAM_CONTAMINATION_HITS" if not failures else "C1_LOCAL_HELDOUT_MULTI_NGRAM_CONTAMINATION_INVALID"
    result = {
        "kind": "single_4090_c1_local_heldout_multi_ngram_contamination_scan",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": verdict,
        "failure_count": len(failures),
        "failures": failures,
        "method": "tokenize every string in local heldout.jsonl with frozen tokenizer.json; build exact 16/32/64-token patterns; stream pinned uint16 token shards; vectorized rolling hash with exact token verification; windows containing separator token 0 are excluded",
        "heldout_input": {"repo_path": "data/ember_avir_tasks/heldout.jsonl", "sha256": sha256_file(args.heldout.resolve())},
        "tokenizer": {"repo_path": "tokenizer/tokenizer.json", "sha256": sha256_file(args.tokenizer.resolve())},
        "source_receipt": SHARD_RECEIPT,
        "ngrams": ngrams,
        "pattern_summary": pattern_summary,
        "total_stream_tokens": total_tokens,
        "windows_scanned_by_ngram": windows_scanned,
        "invalid_separator_windows_by_ngram": invalid_separator_windows,
        "exact_hits_by_ngram": hit_counts,
        "hit_samples_by_ngram": hits,
        "shards": shard_rows,
        "elapsed_seconds": round(time.time() - started, 3),
        "completion_limit": "This is a stronger local heldout exact token-overlap scan only. It is not a full external eval-suite contamination scan, not a normalized character-span scan, not a near-duplicate scan, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if verdict.endswith("PASS") else (1 if verdict.endswith("HITS") else 2)


if __name__ == "__main__":
    raise SystemExit(main())
