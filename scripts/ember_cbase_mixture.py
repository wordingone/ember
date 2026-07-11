#!/usr/bin/env python3
"""ember_cbase_mixture.py — C-BASE pretrain mixture assembler.

Produces a mixture-dir of packed uint16 .bin shards (PackedShardLoader-
compatible, from timeshare_pretrain.py) that the ember_cbase_launch.py
driver consumes via --mixture-dir.

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- the source-path citations below and the
_SHARDS_V0_CANDIDATES defaults carried absolute drive-letter-rooted / WSL-mount
literals pointing at an operator-local tree outside this repo (no repo-relative
default applies for the shards-v0 corpus). Candidates now come from
EMBER_SHARDS_V0_DIR / EMBER_SHARDS_V0_DIR_WSL env vars (empty when unset,
same clean-refusal behavior in _find_shards_v0); v2/aug sources are already
repo-relative (_V2_SRC/_AUG_SRC below, under data/cbase_pretrain/) and
unaffected. See receipts/ember-c-scale/land210g-*.

Sources (verified SHA256 first 8 hex chars):
  v2    data/cbase_pretrain/cbase_avir_tasks_v2-00000.bin under the repo root
        (see _V2_SRC below); 6874 tok, SHA256[:8] = e9c2f629  -> 40% target
  aug   data/cbase_pretrain/cbase_avir_augment-00000.bin under the repo root
        (see _AUG_SRC below); 55106 tok, SHA256[:8] = 46dffee4 -> 10% target
  s0    the shards-v0 corpus (operator-local, outside this repo; located via
        EMBER_SHARDS_V0_DIR / EMBER_SHARDS_V0_DIR_WSL — see _find_shards_v0
        below), 6.978B tok -> 50% target
        ALL 26 shards are train shards (no held-out eval shards in shards-v0).
        The "h0xx [REDACTED]-task" heldout firewall is an [REDACTED]-task concern, not a
        shards-v0 shard concern — shards-v0 contains general corpus (GitHub
        code, FineWeb-Edu, Wikipedia, Gutenberg, Ledger-MIT) with no [REDACTED]-task
        ids. We subsample the TRAIN portion (all 26 shards) deterministically.

HARD RULES:
  - TRAIN-ONLY FIREWALL: no h0xx [REDACTED]-task ids in any output shard.
    Enforced by: (a) v2 source has firewall upstream; (b) aug source has
    firewall upstream; (c) shards-v0 contains no [REDACTED]-task ids at all.
  - All token ids < 32000 (vocab = 32000; id 0 = doc separator). Assert at
    write time.
  - BYTE-REPRODUCIBLE: deterministic assembly. hashlib (not python hash())
    for all seeding. A fresh-subprocess rebuild yields identical shard SHA256s.
  - No GPU, no daemon — CPU only.
  - Do NOT edit timeshare_pretrain.py (read-only dep).

Usage:
    python scripts/ember_cbase_mixture.py [--out <dir>] [--base-tokens N]
        [--ratio V2:AUG:S0] [--shards-v0-dir <dir>]

    --out            : output mixture directory (default: ./mixture-cbase-YYYYMMDDTHHMMSSZ)
    --base-tokens    : approximate total tokens in the mixture (default: 600000).
                       Actual total may differ slightly due to source-unit alignment.
    --ratio          : target ratio as V2:AUG:S0 floats, colon-separated
                       (default: 40:10:50).
    --shards-v0-dir  : path to shards-v0 directory
                       (default: EMBER_SHARDS_V0_DIR / EMBER_SHARDS_V0_DIR_WSL env vars;
                       see _find_shards_v0)

The assembler writes:
    <out>/mixture-00000.bin  — packed uint16 shard containing the mixture
    <out>/mixture-manifest.json — per-shard SHA256 + token counts + config

Receipt fields reported:
    v2_replication    : number of times the 6874-tok v2 unit is replicated
    realized_ratio    : actual v2:aug:s0 token percentages
    total_tokens
    max_token_id
    heldout_excluded  : True (no h0xx ids; shards-v0 eval shards excluded)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))

# ---------------------------------------------------------------------------
# Source paths
# ---------------------------------------------------------------------------

_V2_SRC = _REPO / "data" / "cbase_pretrain" / "cbase_avir_tasks_v2-00000.bin"
_AUG_SRC = _REPO / "data" / "cbase_pretrain" / "cbase_avir_augment-00000.bin"

_SHARDS_V0_CANDIDATES = [
    Path(v) for v in (
        os.environ.get("EMBER_SHARDS_V0_DIR", ""),
        os.environ.get("EMBER_SHARDS_V0_DIR_WSL", ""),
    ) if v
]


def _find_shards_v0(override: str | None = None) -> Path:
    if override:
        p = Path(override)
        if not p.is_dir():
            raise FileNotFoundError(f"shards-v0 override dir not found: {p}")
        return p
    for candidate in _SHARDS_V0_CANDIDATES:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "shards-v0 directory not found at any candidate path: "
        + ", ".join(str(c) for c in _SHARDS_V0_CANDIDATES)
    )


# ---------------------------------------------------------------------------
# SHA256 utilities (hashlib only — no python hash())
# ---------------------------------------------------------------------------

def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# Source verification
# ---------------------------------------------------------------------------

_V2_SHA_PREFIX = "e9c2f629"
_AUG_SHA_PREFIX = "46dffee4"
_V2_TOKENS = 6874
_AUG_TOKENS = 55106
_VOCAB = 32000


def _load_source(path: Path, expected_sha_prefix: str, expected_tokens: int,
                 name: str) -> np.ndarray:
    """Load a packed uint16 source shard, verify SHA and token count."""
    if not path.exists():
        raise FileNotFoundError(f"{name} source not found: {path}")
    sha = _sha256_file(path)
    if not sha.startswith(expected_sha_prefix):
        raise ValueError(
            f"{name} SHA256 mismatch: expected prefix {expected_sha_prefix!r}, "
            f"got {sha[:8]!r} (full: {sha})"
        )
    arr = np.fromfile(str(path), dtype="<u2")
    if len(arr) != expected_tokens:
        raise ValueError(
            f"{name} token count mismatch: expected {expected_tokens}, got {len(arr)}"
        )
    return arr


def _assert_vocab(arr: np.ndarray, label: str) -> None:
    """Assert all token ids < VOCAB (32000)."""
    max_id = int(arr.max())
    if max_id >= _VOCAB:
        raise ValueError(
            f"VOCAB FIREWALL VIOLATION: {label} contains token id {max_id} >= {_VOCAB}"
        )


# ---------------------------------------------------------------------------
# Held-out [REDACTED]-task firewall (belt-and-suspenders)
# ---------------------------------------------------------------------------

_HELDOUT_PATTERN = re.compile(r"^h\d{3}$")


def _assert_no_heldout_task_tokens(arr: np.ndarray, label: str) -> None:
    """Assert no h0xx [REDACTED]-task token patterns.

    shards-v0 contains no [REDACTED]-task ids (it is general corpus). The v2 and
    aug sources are pre-filtered upstream. This check is a belt-and-suspenders
    guard: token ids 0-7 are reserved band (never in text), ids 8+ are BPE
    pieces. The heldout [REDACTED]-task ids are task *string identifiers* (h001 etc),
    not raw token values — there is no direct mapping to block here. The
    firewall is: we never include held-out *task content* (the v2 and aug
    sources are built from train tasks only). This function is a structural
    no-op guard that documents the invariant.
    """
    # No token-value check is possible for the [REDACTED]-task heldout firewall
    # (task ids are string labels, not token values). The upstream source
    # builders enforce this; the assembler trusts the verified source SHAs.
    # What we DO check: vocab firewall (all ids < 32000).
    _assert_vocab(arr, label)


# ---------------------------------------------------------------------------
# Ratio computation
# ---------------------------------------------------------------------------

def compute_mixture_sizes(
    base_tokens: int,
    r_v2: float,
    r_aug: float,
    r_s0: float,
) -> tuple[int, int, int, int]:
    """Compute (v2_reps, aug_reps, s0_tokens, v2_replication) for target ratio.

    Strategy:
      1. Compute v2_reps = ceil(base_tokens * r_v2 / V2_TOKENS). Anchors v2.
      2. Compute aug_reps = max(1, ceil(base_tokens * r_aug / AUG_TOKENS)).
         Anchored independently from base_tokens, not derived from v2_reps.
      3. Derive s0_tokens from actual v2+aug counts so s0 hits ~50%:
         s0 = round((v2_toks + aug_toks) * r_s0 / (r_v2 + r_aug)).

    Both v2 and aug are anchored to base_tokens independently. This avoids
    the degenerate case where aug_unit >> v2_unit causes a near-zero quotient
    when deriving aug from v2 alone.

    Returns (v2_reps, aug_reps, s0_tokens, v2_replication=v2_reps).
    """
    total_ratio = r_v2 + r_aug + r_s0
    if abs(total_ratio - 1.0) > 1e-6:
        raise ValueError(f"Ratios must sum to 1.0; got {total_ratio}")
    v2_reps = max(1, math.ceil(base_tokens * r_v2 / _V2_TOKENS))
    aug_reps = max(1, math.ceil(base_tokens * r_aug / _AUG_TOKENS))
    v2_toks = v2_reps * _V2_TOKENS
    aug_toks = aug_reps * _AUG_TOKENS
    s0_tokens = round((v2_toks + aug_toks) * r_s0 / (r_v2 + r_aug))
    return v2_reps, aug_reps, s0_tokens, v2_reps


def realized_ratio_str(v2_toks: int, aug_toks: int, s0_toks: int) -> str:
    total = v2_toks + aug_toks + s0_toks
    return (
        f"v2={100*v2_toks/total:.2f}% "
        f"aug={100*aug_toks/total:.2f}% "
        f"s0={100*s0_toks/total:.2f}%"
    )


# ---------------------------------------------------------------------------
# Shards-v0 stream loader (deterministic subsample from head)
# ---------------------------------------------------------------------------

def _load_s0_prefix(shards_v0_dir: Path, n_tokens: int) -> np.ndarray:
    """Load exactly n_tokens from the sorted shards-v0 stream (from the head).

    Uses the same sorted-shard concatenation as PackedShardLoader so the
    subsample is deterministic and reproducible. Reads shards sequentially
    stopping when n_tokens is reached — no shard is loaded beyond need.

    TRAIN-ONLY: all shards are train shards; see module docstring.
    """
    shards = sorted(
        p for p in shards_v0_dir.iterdir()
        if p.name.endswith(".bin")
    )
    if not shards:
        raise ValueError(f"No .bin shards found in {shards_v0_dir}")
    collected: list[np.ndarray] = []
    total = 0
    for shard_path in shards:
        remaining = n_tokens - total
        if remaining <= 0:
            break
        arr = np.fromfile(str(shard_path), dtype="<u2")
        if len(arr) <= remaining:
            collected.append(arr)
            total += len(arr)
        else:
            collected.append(arr[:remaining])
            total += remaining
        if total >= n_tokens:
            break
    result = np.concatenate(collected) if len(collected) > 1 else collected[0]
    assert len(result) == n_tokens, (
        f"s0 token count mismatch: wanted {n_tokens}, got {len(result)}"
    )
    return result


# ---------------------------------------------------------------------------
# Mixture assembly
# ---------------------------------------------------------------------------

def assemble_mixture(
    out_dir: str | Path,
    *,
    base_tokens: int = 600_000,
    r_v2: float = 0.40,
    r_aug: float = 0.10,
    r_s0: float = 0.50,
    shards_v0_dir: str | Path | None = None,
    v2_src: str | Path | None = None,
    aug_src: str | Path | None = None,
) -> dict[str, Any]:
    """Assemble the C-BASE pretrain mixture into out_dir.

    Returns a receipt dict with all fields needed by the driver and tests.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    v2_path = Path(v2_src) if v2_src else _V2_SRC
    aug_path = Path(aug_src) if aug_src else _AUG_SRC
    s0_dir = Path(shards_v0_dir) if shards_v0_dir else _find_shards_v0()

    # --- Load + verify sources ---
    v2_raw = _load_source(v2_path, _V2_SHA_PREFIX, _V2_TOKENS, "v2")
    aug_raw = _load_source(aug_path, _AUG_SHA_PREFIX, _AUG_TOKENS, "aug")

    _assert_no_heldout_task_tokens(v2_raw, "v2")
    _assert_no_heldout_task_tokens(aug_raw, "aug")

    # --- Compute sizes ---
    v2_reps, aug_reps, s0_tokens, v2_replication = compute_mixture_sizes(
        base_tokens, r_v2, r_aug, r_s0
    )

    v2_toks_n = v2_reps * _V2_TOKENS
    aug_toks_n = aug_reps * _AUG_TOKENS

    # --- Replicate v2 + aug ---
    v2_block = np.tile(v2_raw, v2_reps)       # deterministic, no RNG
    aug_block = np.tile(aug_raw, aug_reps)     # deterministic, no RNG

    # --- Load s0 prefix (deterministic head of sorted stream) ---
    s0_block = _load_s0_prefix(s0_dir, s0_tokens)

    # --- Vocab firewall: all ids < 32000 ---
    for arr, label in [(v2_block, "v2_block"), (aug_block, "aug_block"),
                       (s0_block, "s0_block")]:
        _assert_vocab(arr, label)

    # --- Concatenate in spec order: v2 | aug | s0 ---
    # Order is deterministic. The three blocks form a single flat stream.
    mixture = np.concatenate([v2_block, aug_block, s0_block])

    total_tokens = len(mixture)
    max_id = int(mixture.max())
    assert max_id < _VOCAB, f"Post-concat vocab firewall: max_id={max_id}"

    # --- Write shard ---
    shard_name = "mixture-00000.bin"
    shard_path = out_dir / shard_name
    mixture.astype("<u2").tofile(str(shard_path))

    shard_sha256 = _sha256_file(shard_path)

    # --- Write manifest ---
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    realized = realized_ratio_str(v2_toks_n, aug_toks_n, s0_tokens)
    manifest: dict[str, Any] = {
        "ticket": "CBASE-MIXTURE",
        "ts": ts,
        "assembler": "ember_cbase_mixture.py",
        "config": {
            "base_tokens": base_tokens,
            "r_v2": r_v2,
            "r_aug": r_aug,
            "r_s0": r_s0,
        },
        "sources": {
            "v2": {
                "path": str(v2_path),
                "sha256_prefix": _V2_SHA_PREFIX,
                "unit_tokens": _V2_TOKENS,
            },
            "aug": {
                "path": str(aug_path),
                "sha256_prefix": _AUG_SHA_PREFIX,
                "unit_tokens": _AUG_TOKENS,
            },
            "s0": {
                "dir": str(s0_dir),
                "tokens_used": s0_tokens,
                "selection": "head of sorted shard stream (deterministic)",
            },
        },
        "mixture": {
            "v2_replication": v2_replication,
            "v2_tokens": v2_toks_n,
            "aug_reps": aug_reps,
            "aug_tokens": aug_toks_n,
            "s0_tokens": s0_tokens,
            "total_tokens": total_tokens,
            "realized_ratio": realized,
            "max_token_id": max_id,
            "vocab_firewall": f"all token ids < {_VOCAB}",
            "heldout_excluded": True,
            "heldout_detail": (
                "v2/aug: h0xx [REDACTED]-task firewall enforced upstream (sources "
                "contain only train tasks). shards-v0: all 26 shards are general "
                "corpus (no [REDACTED]-task ids); the shards-v0 heldout firewall for "
                "the 50% general half refers to [REDACTED]-task held-out content absent "
                "from shards-v0 entirely."
            ),
        },
        "shards": [
            {
                "name": shard_name,
                "sha256": shard_sha256,
                "n_tokens": total_tokens,
            }
        ],
        "sha_convention": (
            "sha256 over on-disk raw bytes, binary read, no normalization"
        ),
        "pass": True,
        "verdict": "CBASE_MIXTURE_ASSEMBLED",
    }
    manifest_path = out_dir / "mixture-manifest.json"
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=False)

    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble C-BASE pretrain mixture shards."
    )
    parser.add_argument(
        "--out", default=None,
        help="Output mixture directory. Default: auto-named under cwd."
    )
    parser.add_argument(
        "--base-tokens", type=int, default=600_000,
        help="Approximate total tokens in the mixture (default: 600000)."
    )
    parser.add_argument(
        "--ratio", default="40:10:50",
        help="Target ratio as V2:AUG:S0 (default: 40:10:50)."
    )
    parser.add_argument(
        "--shards-v0-dir", default=None,
        help="Path to shards-v0 directory."
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="Run the built-in sanity check and exit."
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    # Parse ratio
    try:
        parts = [float(x) for x in args.ratio.split(":")]
        if len(parts) != 3:
            raise ValueError
        r_v2, r_aug, r_s0 = [p / sum(parts) for p in parts]
    except Exception:
        print(f"ERROR: --ratio must be V2:AUG:S0 floats (e.g. 40:10:50), got {args.ratio!r}")
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or str(Path.cwd() / f"mixture-cbase-{ts}")

    print(f"CBASE_MIXTURE_ASSEMBLER: out={out}")
    print(f"  base_tokens={args.base_tokens} ratio={args.ratio}")

    receipt = assemble_mixture(
        out,
        base_tokens=args.base_tokens,
        r_v2=r_v2,
        r_aug=r_aug,
        r_s0=r_s0,
        shards_v0_dir=args.shards_v0_dir,
    )

    mx = receipt["mixture"]
    print(f"CBASE_MIXTURE_ASSEMBLED:")
    print(f"  v2_replication={mx['v2_replication']}")
    print(f"  v2_tokens={mx['v2_tokens']}")
    print(f"  aug_tokens={mx['aug_tokens']}")
    print(f"  s0_tokens={mx['s0_tokens']}")
    print(f"  total_tokens={mx['total_tokens']}")
    print(f"  realized_ratio={mx['realized_ratio']}")
    print(f"  max_token_id={mx['max_token_id']}")
    print(f"  heldout_excluded={mx['heldout_excluded']}")
    print(f"  shard_sha256={receipt['shards'][0]['sha256'][:16]}...")
    print(f"  manifest={out}/mixture-manifest.json")
    return 0


# ---------------------------------------------------------------------------
# Built-in selftest (CPU-only, no real sources needed — uses tiny synthetic)
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Quick sanity check with synthetic data. Prints CBASE_MIXTURE_SELFTEST_PASS."""
    import tempfile

    print("CBASE_MIXTURE_SELFTEST: running...")

    # Test 1: compute_mixture_sizes
    v2r, ar, s0t, v2rep = compute_mixture_sizes(600_000, 0.40, 0.10, 0.50)
    assert v2r >= 1 and ar >= 1 and s0t > 0 and v2rep == v2r, \
        f"compute_mixture_sizes returned unexpected values: {(v2r,ar,s0t,v2rep)}"
    v2_toks = v2r * _V2_TOKENS
    aug_toks = ar * _AUG_TOKENS
    total = v2_toks + aug_toks + s0t
    v2_pct = 100 * v2_toks / total
    aug_pct = 100 * aug_toks / total
    s0_pct = 100 * s0t / total
    assert abs(v2_pct - 40.0) < 5.0, f"v2% out of range: {v2_pct:.2f}"
    assert abs(aug_pct - 10.0) < 5.0, f"aug% out of range: {aug_pct:.2f}"
    assert abs(s0_pct - 50.0) < 5.0, f"s0% out of range: {s0_pct:.2f}"
    print(f"  T1 compute_mixture_sizes: v2_reps={v2r}, aug_reps={ar}, "
          f"realized v2={v2_pct:.2f}% aug={aug_pct:.2f}% s0={s0_pct:.2f}%  OK")

    # Test 2: realized_ratio_str
    rs = realized_ratio_str(400, 100, 500)
    assert "40.00%" in rs and "10.00%" in rs and "50.00%" in rs, \
        f"realized_ratio_str wrong: {rs!r}"
    print(f"  T2 realized_ratio_str: {rs}  OK")

    # Test 3: assemble with synthetic sources
    rng = np.random.default_rng(seed=int.from_bytes(hashlib.sha256(b"selftest").digest()[:8], "big"))
    synthetic_v2 = rng.integers(8, _VOCAB, size=_V2_TOKENS, dtype=np.uint16)
    synthetic_aug = rng.integers(8, _VOCAB, size=_AUG_TOKENS, dtype=np.uint16)
    # Simulate s0: small synthetic dir
    with tempfile.TemporaryDirectory(prefix="cbase_mixture_selftest_") as td:
        td_path = Path(td)
        # Write synthetic source files
        v2_file = td_path / "cbase_avir_tasks_v2-00000.bin"
        aug_file = td_path / "cbase_avir_augment-00000.bin"
        synthetic_v2.tofile(str(v2_file))
        synthetic_aug.tofile(str(aug_file))
        # Write synthetic shards-v0
        s0_dir = td_path / "shards_v0"
        s0_dir.mkdir()
        # Two small shards
        s0_shard_0 = rng.integers(8, _VOCAB, size=200_000, dtype=np.uint16)
        s0_shard_1 = rng.integers(8, _VOCAB, size=200_000, dtype=np.uint16)
        s0_shard_0.tofile(str(s0_dir / "v0-00000.bin"))
        s0_shard_1.tofile(str(s0_dir / "v0-00001.bin"))
        # Compute expected SHA prefix for synthetic v2 + aug
        v2_sha = hashlib.sha256(synthetic_v2.tobytes()).hexdigest()[:8]
        aug_sha = hashlib.sha256(synthetic_aug.tobytes()).hexdigest()[:8]
        # Monkey-patch source verification to use synthetic values
        _orig_load_source = globals()["_load_source"]
        call_count = [0]

        def _mock_load_source(path, expected_sha_prefix, expected_tokens, name):
            call_count[0] += 1
            arr = np.fromfile(str(path), dtype="<u2")
            return arr

        globals()["_load_source"] = _mock_load_source
        out_dir = td_path / "mixture_out"
        try:
            receipt = assemble_mixture(
                out_dir,
                base_tokens=200_000,
                r_v2=0.40,
                r_aug=0.10,
                r_s0=0.50,
                shards_v0_dir=s0_dir,
                v2_src=v2_file,
                aug_src=aug_file,
            )
        finally:
            globals()["_load_source"] = _orig_load_source

        shard_path = out_dir / "mixture-00000.bin"
        assert shard_path.exists(), "mixture shard not written"
        result_arr = np.fromfile(str(shard_path), dtype="<u2")
        assert receipt["mixture"]["total_tokens"] == len(result_arr), \
            f"token count mismatch: manifest={receipt['mixture']['total_tokens']}, file={len(result_arr)}"
        assert receipt["mixture"]["max_token_id"] < _VOCAB, \
            f"max_token_id {receipt['mixture']['max_token_id']} >= vocab {_VOCAB}"
        assert receipt["mixture"]["heldout_excluded"] is True
        print(f"  T3 assemble with synthetic sources: {len(result_arr)} tokens, "
              f"max_id={receipt['mixture']['max_token_id']}  OK")

        # Test 4: reproducibility — rebuild in same process (fresh arrays, same seed)
        # Determinism test: re-run assembly with same params, compare SHA
        sha_first = receipt["shards"][0]["sha256"]
        receipt2 = assemble_mixture(
            td_path / "mixture_out2",
            base_tokens=200_000,
            r_v2=0.40,
            r_aug=0.10,
            r_s0=0.50,
            shards_v0_dir=s0_dir,
            v2_src=v2_file,
            aug_src=aug_file,
        )
        sha_second = receipt2["shards"][0]["sha256"]
        assert sha_first == sha_second, \
            f"Non-reproducible: first={sha_first[:16]!r} second={sha_second[:16]!r}"
        print(f"  T4 reproducibility: SHA256={sha_first[:16]}...  OK")

        # Test 5: PackedShardLoader can read the mixture
        from timeshare_pretrain import PackedShardLoader
        loader = PackedShardLoader(str(out_dir), seq=16, n_mtp=0)
        assert loader.n_tokens == len(result_arr), \
            f"loader n_tokens {loader.n_tokens} != shard {len(result_arr)}"
        x, y0, y_mtp = loader.window_np(0)
        assert len(x) == 16 and len(y0) == 16 and y_mtp == []
        print(f"  T5 PackedShardLoader: n_windows={loader.n_windows}, "
              f"window_np(0) x.shape={x.shape}  OK")

    print("CBASE_MIXTURE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
