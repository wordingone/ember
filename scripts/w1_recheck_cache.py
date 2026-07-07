"""w1_recheck_cache.py -- Content-addressed contamination recheck cache (issue #351).

Implements a content-addressed cache for contamination recheck results, keyed by:
  - sha256(batch npy bytes) — the token sequence content
  - sha256(decontam receipt) — the corpus/decontam configuration
  - sha256(w1_collapse_control_run.py) — the classifier code version

Cache hit on all three shas + PASS verdict allows skipping the expensive recheck.
The cached receipt carries the original receipt's fields + disclosure flag.

Usage:
  from w1_recheck_cache import check_recheck_cache, write_recheck_cache

  # On launch, before calling contamination_recheck():
  cached = check_recheck_cache(eval_rows, shard_dir, args.decontam_receipt, out_dir)
  if cached:
    contamination = cached  # use cached result + disclose cache_hit in launch receipt
  else:
    contamination = contamination_recheck(eval_rows, shard_dir)
    write_recheck_cache(contamination, eval_rows, args.decontam_receipt, out_dir)
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def sha256_bytes(data: bytes) -> str:
    """Compute sha256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """Compute sha256 hex digest of file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_batch_sha(eval_rows: "list[list[int]]") -> str:
    """Compute sha256 of batch token sequences (flattened, as int16 bytes).

    The batch is represented as a flat byte array matching numpy's <u2 dtype.
    This ensures the cache key is content-addressed: identical batch content
    yields identical sha, regardless of how it was reconstructed.
    """
    import numpy as np
    # Flatten all rows and convert to uint16 bytes (matching shard .bin format)
    all_tokens = np.array([], dtype=np.uint16)
    for row in eval_rows:
        all_tokens = np.append(all_tokens, np.array(row, dtype=np.uint16))
    return sha256_bytes(all_tokens.tobytes())


def compute_cache_key(
    eval_rows: "list[list[int]]",
    decontam_receipt_path: Optional[str],
    classifier_code_path: str,
) -> tuple[str, str, str]:
    """Compute the three-part cache key: (batch_sha, receipt_sha, code_sha).

    Returns:
      Tuple of (batch_sha, receipt_sha, code_sha) as hex strings.
      If decontam_receipt_path is None, receipt_sha is empty string.
    """
    batch_sha = compute_batch_sha(eval_rows)
    receipt_sha = (
        sha256_file(decontam_receipt_path)
        if decontam_receipt_path and os.path.exists(decontam_receipt_path)
        else ""
    )
    code_sha = sha256_file(classifier_code_path)
    return batch_sha, receipt_sha, code_sha


def cache_dir(cache_root: str) -> str:
    """Return the cache directory (created if missing).

    Args:
      cache_root: the stable cache root directory (e.g., scratch/w1-control/recheck-cache/)
    """
    os.makedirs(cache_root, exist_ok=True)
    return cache_root


def cache_entry_path(batch_sha: str, receipt_sha: str, code_sha: str, cache_root: str) -> str:
    """Return the cache entry path for the given triple key.

    Args:
      batch_sha, receipt_sha, code_sha: components of the cache key
      cache_root: the stable cache root directory (not a per-launch out_dir)
    """
    # Use triple as filename: batch-receipt-code.json
    # Empty receipt_sha becomes "none"
    r_part = receipt_sha if receipt_sha else "none"
    filename = f"{batch_sha}-{r_part}-{code_sha}.json"
    return os.path.join(cache_dir(cache_root), filename)


def check_recheck_cache(
    eval_rows: "list[list[int]]",
    shard_dir: str,
    decontam_receipt_path: Optional[str],
    cache_root: str,
    classifier_code_path: str = None,
) -> Optional[dict]:
    """Check if a cached recheck result exists and is valid.

    Args:
      eval_rows: the evaluation batch rows
      shard_dir: shard directory path (unused for cache check, but required for API consistency)
      decontam_receipt_path: path to decontam receipt (may be None)
      cache_root: stable cache root directory (e.g., scratch/w1-control/recheck-cache/)
      classifier_code_path: path to the classifier code file (defaults to w1_collapse_control_run.py)

    Returns:
      The cached contamination result dict if hit, or None if miss.
      Only returns cached results with verdict="CLEAN" (passing rechecks only).
    """
    if classifier_code_path is None:
        # Default to this script's location (caller should pass in for clarity)
        classifier_code_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "w1_collapse_control_run.py"
        )

    batch_sha, receipt_sha, code_sha = compute_cache_key(
        eval_rows, decontam_receipt_path, classifier_code_path
    )

    entry_path = cache_entry_path(batch_sha, receipt_sha, code_sha, cache_root)

    if not os.path.exists(entry_path):
        return None

    try:
        with open(entry_path, "r", encoding="utf-8") as f:
            cached = json.load(f)

        # Validate: only cache CLEAN verdicts
        if cached.get("verdict") != "CLEAN":
            return None

        # Validate: ensure the cache entry is properly formed and chains to original
        if not all(k in cached for k in ["verdict", "cache_write_ts", "cached_receipt_path", "original_receipt_sha"]):
            return None

        return cached
    except (json.JSONDecodeError, IOError):
        return None


def write_recheck_cache(
    contamination: dict,
    eval_rows: "list[list[int]]",
    decontam_receipt_path: Optional[str],
    cache_root: str,
    classifier_code_path: str = None,
) -> str:
    """Write a contamination recheck result to the cache (if it's a CLEAN pass).

    Args:
      contamination: the result dict from contamination_recheck()
      eval_rows: the evaluation batch rows
      decontam_receipt_path: path to decontam receipt (may be None)
      cache_root: stable cache root directory (e.g., scratch/w1-control/recheck-cache/)
      classifier_code_path: path to the classifier code file

    Returns:
      Path to the cache entry, or empty string if not cached (non-PASS verdict).
    """
    # Only cache CLEAN verdicts
    if contamination.get("verdict") != "CLEAN":
        return ""

    if classifier_code_path is None:
        classifier_code_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "w1_collapse_control_run.py"
        )

    batch_sha, receipt_sha, code_sha = compute_cache_key(
        eval_rows, decontam_receipt_path, classifier_code_path
    )

    entry_path = cache_entry_path(batch_sha, receipt_sha, code_sha, cache_root)

    # Create cache entry: copy original verdict but add disclosure fields
    cache_entry = {
        **contamination,
        "cache_write_ts": datetime.now(timezone.utc).isoformat(),
        "cached_receipt_path": entry_path,
        "cache_key_batch_sha256": batch_sha,
        "cache_key_receipt_sha256": receipt_sha,
        "cache_key_code_sha256": code_sha,
        "original_receipt_sha": sha256_bytes(json.dumps(contamination, sort_keys=True).encode()),
    }

    os.makedirs(os.path.dirname(entry_path), exist_ok=True)
    with open(entry_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cache_entry, f, indent=2)

    return entry_path


def disclose_cache_hit(contamination: dict, launch_receipt: dict) -> dict:
    """Add cache-hit disclosure fields to a launch receipt.

    Args:
      contamination: the (cached or fresh) contamination result dict
      launch_receipt: the launch receipt dict being built

    Returns:
      Updated launch receipt with cache_hit disclosure.
    """
    if contamination.get("cache_write_ts"):
        # This was a cached result
        launch_receipt["cache_hit"] = True
        launch_receipt["cache_hit_path"] = contamination.get("cached_receipt_path")
        launch_receipt["cache_hit_ts"] = contamination.get("cache_write_ts")
        launch_receipt["cache_key_batch_sha256"] = contamination.get("cache_key_batch_sha256")
        launch_receipt["cache_key_receipt_sha256"] = contamination.get("cache_key_receipt_sha256")
        launch_receipt["cache_key_code_sha256"] = contamination.get("cache_key_code_sha256")
    else:
        # Fresh recheck result
        launch_receipt["cache_hit"] = False

    return launch_receipt
