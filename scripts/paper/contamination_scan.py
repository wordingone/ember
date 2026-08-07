#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#552 Component A: eval-contamination scan (Q6b, feeds A1).

Model-free contamination detection via n-gram exact collisions + MinHash-Jaccard.
CPU-only, deterministic, zero GPU, zero model inference anywhere.

Input: (1) eval-suite manifest (JSON list of eval files), (2) corpus shard paths/globs
Output: receipts/paper/contamination-scan-<UTCts>.json

Method:
  - 13-gram exact collision rate per eval item against every shard (normalized case/space)
  - MinHash-Jaccard near-dup score (128 perms, shingle=13)
  - Pre-registered thresholds: collision>0 on 3+ consecutive grams OR jaccard>=0.5
    => item flagged CONTAMINATED-CANDIDATE

Receipt structure:
  - per_item: {item_id, max_13gram_collision, max_minhash_jaccard, worst_shard}
  - suite_summary: {n_items, n_contaminated, contamination_rate}
  - thresholds: {collision_window_len, gram_size, minhash_perms, minhash_shingle,
                  collision_threshold, jaccard_threshold}
  - contaminated_items: [...flagged items...]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _normalize_text(text: str) -> str:
    """Normalize whitespace and case for collision detection."""
    # Lowercase, collapse whitespace
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _ngrams(text: str, n: int) -> list[str]:
    """Generate n-grams from text."""
    words = text.split()
    return [' '.join(words[i:i+n]) for i in range(len(words) - n + 1)]


def _count_ngram_collisions(eval_text: str, shard_text: str, gram_size: int = 13,
                            window_len: int = 3) -> int:
    """Count 13-gram collision windows.

    Returns count of CONSECUTIVE gram matches of length >= window_len.
    A collision window is a contiguous sequence of matching n-grams.
    """
    eval_norm = _normalize_text(eval_text)
    shard_norm = _normalize_text(shard_text)

    eval_grams = _ngrams(eval_norm, gram_size)
    shard_grams = _ngrams(shard_norm, gram_size)

    if not eval_grams or not shard_grams:
        return 0

    # A collision window must be contiguous and ordered in BOTH streams.  A
    # membership set alone falsely joins grams that occur far apart or in a
    # different order in the shard.
    positions: dict[str, list[int]] = {}
    for index, gram in enumerate(shard_grams):
        positions.setdefault(gram, []).append(index)
    for start in range(len(eval_grams) - window_len + 1):
        first = positions.get(eval_grams[start], [])
        for shard_start in first:
            if all(
                shard_start + offset in positions.get(eval_grams[start + offset], [])
                for offset in range(window_len)
            ):
                return 1
    return 0


def _minhash_jaccard(text1: str, text2: str, shingle_size: int = 13,
                     n_perms: int = 128) -> float:
    """Compute MinHash-Jaccard similarity between two texts."""
    def _get_shingles(text: str, k: int) -> set[str]:
        norm = _normalize_text(text)
        words = norm.split()
        shingles = set()
        for i in range(max(0, len(words) - k + 1)):
            shingle = ' '.join(words[i:i+k])
            shingles.add(shingle)
        return shingles

    s1 = _get_shingles(text1, shingle_size)
    s2 = _get_shingles(text2, shingle_size)

    if not s1 and not s2:
        return 0.0  # Empty sets are dissimilar
    if not s1 or not s2:
        return 0.0

    # MinHash: for each permutation, find min hash value in each set
    min_hashes_1 = []
    min_hashes_2 = []

    for perm_idx in range(n_perms):
        min_hash_1 = float('inf')
        min_hash_2 = float('inf')

        for shingle in s1:
            h = int(hashlib.md5(f"{perm_idx}:{shingle}".encode()).hexdigest(), 16)
            min_hash_1 = min(min_hash_1, h)

        for shingle in s2:
            h = int(hashlib.md5(f"{perm_idx}:{shingle}".encode()).hexdigest(), 16)
            min_hash_2 = min(min_hash_2, h)

        min_hashes_1.append(min_hash_1)
        min_hashes_2.append(min_hash_2)

    # Jaccard estimate: fraction of matching min-hashes
    matches = sum(1 for m1, m2 in zip(min_hashes_1, min_hashes_2) if m1 == m2)
    return matches / n_perms


def _load_eval_manifest(manifest_path: str) -> list[dict]:
    """Load eval suite manifest (JSON list of eval items with 'item_id' + text content)."""
    with open(manifest_path, 'r') as f:
        return json.load(f)


def _load_shard(shard_path: str) -> str:
    """Load a corpus shard (text file or JSON with 'text'/'content' field)."""
    shard_path_obj = Path(shard_path)

    if not shard_path_obj.exists():
        return ""

    # Try JSON first
    try:
        with open(shard_path, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict):
                text = data.get('text') or data.get('content') or data.get('body') or ""
            elif isinstance(data, list):
                # List of items
                text = ' '.join(str(item) for item in data)
            else:
                text = str(data)
            return text
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Fall back to plain text
    try:
        with open(shard_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""


def scan_contamination(eval_manifest: list[dict], shard_paths: list[str],
                       collision_window_len: int = 3,
                       gram_size: int = 13,
                       minhash_perms: int = 128,
                       minhash_shingle: int = 13,
                       collision_threshold: int = 0,
                       jaccard_threshold: float = 0.5) -> dict:
    """Scan eval items for contamination against corpus shards."""

    contaminated_items = []
    per_item_results = []

    for eval_item in eval_manifest:
        item_id = eval_item.get('item_id') or eval_item.get('id') or str(eval_item)
        # Try to extract text from eval item
        eval_text = eval_item.get('text') or eval_item.get('content') or eval_item.get('body') or ""
        if not eval_text:
            eval_text = json.dumps(eval_item)

        max_collision = 0
        max_jaccard = 0.0
        worst_shard = None

        # Check against all shards
        for shard_path in shard_paths:
            shard_text = _load_shard(shard_path)
            if not shard_text:
                continue

            # Exact collision check
            collision_score = _count_ngram_collisions(
                eval_text, shard_text, gram_size, collision_window_len
            )
            if collision_score > max_collision:
                max_collision = collision_score
                worst_shard = shard_path

            # MinHash-Jaccard check
            jaccard_score = _minhash_jaccard(
                eval_text, shard_text, minhash_shingle, minhash_perms
            )
            if jaccard_score > max_jaccard:
                max_jaccard = jaccard_score
                worst_shard = shard_path

        item_result = {
            "item_id": item_id,
            "max_13gram_collision": max_collision,
            "max_minhash_jaccard": round(max_jaccard, 4),
            "worst_shard": worst_shard,
        }
        per_item_results.append(item_result)

        # Contamination check
        is_contaminated = (max_collision > collision_threshold or
                          max_jaccard >= jaccard_threshold)
        if is_contaminated:
            contaminated_items.append(item_result)

    return {
        "per_item": per_item_results,
        "suite_summary": {
            "n_items": len(eval_manifest),
            "n_contaminated": len(contaminated_items),
            "contamination_rate": round(len(contaminated_items) / max(1, len(eval_manifest)), 4),
        },
        "thresholds": {
            "collision_window_len": collision_window_len,
            "gram_size": gram_size,
            "minhash_perms": minhash_perms,
            "minhash_shingle": minhash_shingle,
            "collision_threshold": collision_threshold,
            "jaccard_threshold": jaccard_threshold,
        },
        "contaminated_items": contaminated_items,
    }


def _selftest() -> None:
    """Unit test: planted duplicate + clean negative control."""

    # Positive control: planted duplicate
    eval_pos = "the quick brown fox jumps over the lazy dog and then it runs away very fast"
    shard_pos = "the quick brown fox jumps over the lazy dog and then it runs away very fast completely"

    # Negative control: completely different topic
    eval_neg = "metric tons of coal production in eastern pennsylvania during industrial revolution"
    shard_neg = "mathematical theorems in abstract algebra related to group ring theory concepts"

    manifest = [
        {"item_id": "pos_control", "text": eval_pos},
        {"item_id": "neg_control", "text": eval_neg},
    ]

    shards = []
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f_pos:
        f_pos.write(shard_pos)
        shards.append(f_pos.name)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f_neg:
        f_neg.write(shard_neg)
        shards.append(f_neg.name)

    result = scan_contamination(manifest, shards)

    # Verify
    assert len(result["contaminated_items"]) > 0, "Positive control should be detected"
    assert result["contaminated_items"][0]["item_id"] == "pos_control", \
        "Positive control should be flagged"

    neg_items = [item for item in result["per_item"] if item["item_id"] == "neg_control"]
    assert len(neg_items) > 0 and neg_items[0]["max_minhash_jaccard"] < 0.5, \
        "Negative control should not trigger jaccard threshold"

    print("[PASS] SELFTEST: planted duplicate detected, clean item passed")

    # Cleanup
    for shard in shards:
        Path(shard).unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eval contamination scan")
    parser.add_argument("--selftest", action="store_true",
                        help="Run unit test (planted duplicate + clean control)")
    parser.add_argument("--manifest", type=str,
                        help="Path to eval manifest JSON (list of eval items)")
    parser.add_argument("--shards", type=str, nargs='+',
                        help="Corpus shard paths/globs")
    parser.add_argument("--write", action="store_true",
                        help="Write receipt to receipts/paper/")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
    elif args.manifest and args.shards:
        # Expand globs
        shard_paths = []
        for glob_pat in args.shards:
            shard_paths.extend(glob.glob(glob_pat))

        manifest = _load_eval_manifest(args.manifest)
        result = scan_contamination(manifest, shard_paths)

        if args.write:
            receipts_dir = Path(__file__).resolve().parent.parent.parent / "receipts" / "paper"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            receipt_path = receipts_dir / f"contamination-scan-{ts}.json"
            with open(receipt_path, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Receipt written to {receipt_path}")
        else:
            print(json.dumps(result, indent=2))
    else:
        parser.print_help()
