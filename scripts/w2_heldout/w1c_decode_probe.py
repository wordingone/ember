# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""w1c_decode_probe.py -- decode contamination-scan match positions back into
readable text, plus a block-structure characterization (contiguous vs
scattered) of where those matches land in a shard.

Why this exists: a bare match COUNT from a rolling-hash contamination scan
(e.g. contamination_recheck_mp's confirmed_matches / --dump-matches output)
tells you THAT something recurs, never WHAT is recurring or WHY. During the
#372 W1c region-scout mission, a fwd_1m needle set matched ~1044 times per
window with 100% of the matches landing in one shard -- this script is the
tool that answered whether that was real content duplication (a corpus-
assembly artifact) or degenerate/low-entropy filler, by actually decoding
the matched spans with the corpus tokenizer and measuring how tightly the
match offsets cluster. (Answer, for the record: real, coherent prose --
recurring TEMPLATE STRUCTURE across many distinct entries of one formulaic
reference document, not verbatim duplication of a single passage and not
filler. See the #372/#440 threads for the full finding; per L4/L10
provenance concerns raised there, decoded verbatim text belongs in a LOCAL
receipt only, never pasted into a PR body or other public artifact -- this
script writes it to --output-dir, which callers must not commit.)

Calls the existing contamination_recheck_mp (build_decontam_batch_mp.py,
hardened by PR #302 -- adaptive per-shard chunking, streaming match dump,
no reimplemented scanning here) rather than re-scanning independently.

WINDOW-INDEX CONVENTION: --pool-start is a non-overlapping window index,
token_start = pool_start_index * (seq_len + 1) -- see w1c_window_sweep.py's
module docstring for why this is explicitly NOT the same convention as this
repo's held_out_window_start()/PackedShardLoader stride, and why mixing the
two produces silently-wrong offsets.

Usage:
    python w1c_decode_probe.py --shard-dir /path/to/shards \\
        --tokenizer-path /path/to/tokenizer.json \\
        --pool-start 5194351 --batch-size 16 --seq-len 1024 --window 13 \\
        --n-decode-samples 4 --block-gap-threshold-multiplier 10 \\
        --output-dir ./w1c-certs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py
import importlib.util as _ember_9c92008c8512cb00_importlib
import sys as _ember_9c92008c8512cb00_sys
from pathlib import Path as _ember_9c92008c8512cb00_Path
_ember_9c92008c8512cb00_path = _ember_9c92008c8512cb00_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'w2_heldout', 'build_decontam_batch_mp.py')
if not _ember_9c92008c8512cb00_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
_ember_9c92008c8512cb00_aliases = ('_ember_issue2015_9c92008c8512cb00', 'build_decontam_batch_mp', 'scripts.w2_heldout.build_decontam_batch_mp')
_ember_9c92008c8512cb00_existing = []
for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
    _ember_9c92008c8512cb00_candidate = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
    if _ember_9c92008c8512cb00_candidate is not None and all(_ember_9c92008c8512cb00_candidate is not item for item in _ember_9c92008c8512cb00_existing):
        _ember_9c92008c8512cb00_existing.append(_ember_9c92008c8512cb00_candidate)
if len(_ember_9c92008c8512cb00_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
if _ember_9c92008c8512cb00_existing:
    _ember_9c92008c8512cb00_module = _ember_9c92008c8512cb00_existing[0]
    _ember_9c92008c8512cb00_observed = getattr(_ember_9c92008c8512cb00_module, '__file__', None)
    if _ember_9c92008c8512cb00_observed is None or _ember_9c92008c8512cb00_Path(_ember_9c92008c8512cb00_observed).resolve() != _ember_9c92008c8512cb00_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
else:
    _ember_9c92008c8512cb00_spec = _ember_9c92008c8512cb00_importlib.spec_from_file_location('_ember_issue2015_9c92008c8512cb00', _ember_9c92008c8512cb00_path)
    if _ember_9c92008c8512cb00_spec is None or _ember_9c92008c8512cb00_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
    _ember_9c92008c8512cb00_module = _ember_9c92008c8512cb00_importlib.module_from_spec(_ember_9c92008c8512cb00_spec)
    for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
        _ember_9c92008c8512cb00_prior = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
        if _ember_9c92008c8512cb00_prior is not None and _ember_9c92008c8512cb00_prior is not _ember_9c92008c8512cb00_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
        _ember_9c92008c8512cb00_sys.modules[_ember_9c92008c8512cb00_alias] = _ember_9c92008c8512cb00_module
    try:
        _ember_9c92008c8512cb00_spec.loader.exec_module(_ember_9c92008c8512cb00_module)
    except BaseException:
        for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
            if _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias) is _ember_9c92008c8512cb00_module:
                _ember_9c92008c8512cb00_sys.modules.pop(_ember_9c92008c8512cb00_alias, None)
        raise
for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
    _ember_9c92008c8512cb00_prior = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
    if _ember_9c92008c8512cb00_prior is not None and _ember_9c92008c8512cb00_prior is not _ember_9c92008c8512cb00_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
    _ember_9c92008c8512cb00_sys.modules[_ember_9c92008c8512cb00_alias] = _ember_9c92008c8512cb00_module
contamination_recheck_mp = getattr(_ember_9c92008c8512cb00_module, 'contamination_recheck_mp')
CONTAMINATION_WINDOW_TOKENS = getattr(_ember_9c92008c8512cb00_module, 'CONTAMINATION_WINDOW_TOKENS')
CONTAMINATION_ROLL_BASE = getattr(_ember_9c92008c8512cb00_module, 'CONTAMINATION_ROLL_BASE')
DEFAULT_MP_WORKERS = getattr(_ember_9c92008c8512cb00_module, 'DEFAULT_MP_WORKERS')
# issue2015 exact-local-import-end:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py


def _shard_lengths(shard_dir: str) -> tuple:
    names = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    if not names:
        raise SystemExit(f"W1C_DECODE_NO_SHARDS: {shard_dir!r}")
    lens = [os.path.getsize(os.path.join(shard_dir, n)) // 2 for n in names]
    return names, lens


def load_eval_rows(shard_dir: str, pool_start: int, batch_size: int, seq_len: int) -> list:
    """Same non-overlapping convention as w1c_window_sweep.py -- see module
    docstring. Windows straddling a shard boundary are not supported (pick
    a different pool_start)."""
    tokens_per_window = seq_len + 1
    names, lens = _shard_lengths(shard_dir)
    cumulative = [0]
    for L in lens:
        cumulative.append(cumulative[-1] + L)

    def _locate(g_start, g_end):
        for idx, name in enumerate(names):
            s, e = cumulative[idx], cumulative[idx + 1]
            if s <= g_start and g_end <= e:
                return name, g_start - s
        raise SystemExit(
            f"W1C_DECODE_CROSS_SHARD_WINDOW: [{g_start},{g_end}) spans a shard "
            f"boundary -- pick a different pool_start")

    eval_rows, row_locations = [], []
    cache: dict[str, np.ndarray] = {}
    for offset in range(batch_size):
        window_idx = pool_start + offset
        g_start = window_idx * tokens_per_window
        g_end = g_start + tokens_per_window
        name, local_start = _locate(g_start, g_end)
        if name not in cache:
            cache[name] = np.fromfile(os.path.join(shard_dir, name), dtype="<u2")
        eval_rows.append(cache[name][local_start:local_start + tokens_per_window].tolist())
        row_locations.append((name, local_start))
    return eval_rows, row_locations, cache


def characterize_blocks(offsets: list, gap_threshold: int) -> dict:
    offsets = sorted(set(offsets))
    if not offsets:
        return {"n_matches": 0}
    gaps = np.diff(offsets) if len(offsets) > 1 else np.array([])
    n_blocks = int((gaps > gap_threshold).sum()) + 1 if len(gaps) else 1
    return {
        "n_matches": len(offsets),
        "offset_min": int(offsets[0]),
        "offset_max": int(offsets[-1]),
        "span_tokens": int(offsets[-1] - offsets[0]),
        "gap_median": float(np.median(gaps)) if len(gaps) else None,
        "gap_p95": float(np.percentile(gaps, 95)) if len(gaps) else None,
        "gap_max": int(gaps.max()) if len(gaps) else None,
        "block_gap_threshold_tokens": gap_threshold,
        "n_contiguous_blocks": n_blocks,
    }


def decode_context(tok, arr: np.ndarray, center_start: int, span_len: int, pad: int = 50):
    lo = max(0, center_start - pad)
    hi = min(arr.shape[0], center_start + span_len + pad)
    return tok.decode(arr[lo:hi].tolist()), lo, hi


def run_probe(*, shard_dir: str, tokenizer_path: str, pool_start: int, batch_size: int,
              seq_len: int, window: int, roll_base: int, n_workers: int,
              n_decode_samples: int, block_gap_multiplier: int, output_dir: str) -> dict:
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(tokenizer_path)

    tokens_per_window = seq_len + 1
    eval_rows, row_locations, shard_cache = load_eval_rows(
        shard_dir, pool_start, batch_size, seq_len)

    result = contamination_recheck_mp(
        eval_rows, shard_dir, window=window, roll_base=roll_base, n_workers=max(2, n_workers))

    matches = result.get("confirmed_matches")
    if matches is None:
        raise SystemExit(
            "W1C_DECODE_NO_MATCH_LIST: contamination_recheck_mp fell back to a path that "
            "didn't return per-match records (e.g. dump_matches was required for n_workers>1 "
            "and wasn't set) -- pass a small enough eval set / n_workers config that "
            "confirmed_matches is populated, or read matches back from a --dump-matches file.")

    by_shard: dict[str, list] = {}
    for m in matches:
        shard = m.get("shard") or m.get("boundary")
        if shard:
            by_shard.setdefault(shard, []).append(m["offset" if "offset" in m else "offset_in_join"])

    block_structure = {shard: characterize_blocks(offs, window * block_gap_multiplier)
                        for shard, offs in by_shard.items()}

    # Decode: a handful of pool-window contexts (spread across the batch)
    # plus a handful of matched-position contexts (spread across whichever
    # shard has the most matches, sampling across its offset range rather
    # than just the first N sequential hits).
    decoded_pool_samples = []
    sample_rows = sorted(set([0, batch_size // 2, batch_size - 1][:n_decode_samples]))
    for row_idx in sample_rows:
        name, local_start = row_locations[row_idx]
        text, lo, hi = decode_context(tok, shard_cache[name], local_start, tokens_per_window)
        decoded_pool_samples.append({
            "row_idx": row_idx, "shard": name, "local_start": local_start,
            "decoded_text_first_200chars": text[:200],
        })

    decoded_match_samples = []
    if by_shard:
        dominant_shard = max(by_shard, key=lambda k: len(by_shard[k]))
        offs = sorted(set(by_shard[dominant_shard]))
        idxs = sorted(set([0, len(offs) // 3, (2 * len(offs)) // 3, len(offs) - 1]))[:n_decode_samples]
        if dominant_shard not in shard_cache:
            # boundary-join matches reference two shard names; only decode
            # true single-shard entries here for simplicity
            base_name = dominant_shard.split("|")[0] if "|" in dominant_shard else dominant_shard
            if base_name in shard_cache:
                dominant_shard = base_name
        if dominant_shard in shard_cache:
            for i in idxs:
                off = offs[i]
                text, lo, hi = decode_context(tok, shard_cache[dominant_shard], off, window)
                decoded_match_samples.append({
                    "shard": dominant_shard, "offset": off, "decoded_text": text,
                })

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(output_dir, exist_ok=True)
    receipt = {
        "schema": "w1c-decode-probe/v1", "ts": ts,
        "pool_start": pool_start, "batch_size": batch_size, "seq_len": seq_len,
        "window": window,
        "window_index_convention": "non-overlapping, stride=seq_len+1 "
            "(NOT this repo's held_out_window_start/PackedShardLoader stride)",
        "match_count": result.get("matches_found", len(matches)),
        "per_shard_match_count": {k: len(v) for k, v in by_shard.items()},
        "block_structure": block_structure,
        "decoded_pool_window_samples": decoded_pool_samples,
        "decoded_match_position_samples": decoded_match_samples,
    }
    out_path = os.path.join(output_dir, f"w1c-decode-probe-{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)
    print(f"per_shard_match_count: {json.dumps(receipt['per_shard_match_count'])}")
    print(f"block_structure: {json.dumps(block_structure, indent=2)}")
    print(f"receipt written (verbatim decoded text lives ONLY here -- do not commit "
          f"or paste into a PR/issue; describe structure only): {out_path}")
    return receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shard-dir", required=True)
    ap.add_argument("--tokenizer-path", required=True)
    ap.add_argument("--pool-start", type=int, required=True)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--window", type=int, default=CONTAMINATION_WINDOW_TOKENS)
    ap.add_argument("--roll-base", type=int, default=CONTAMINATION_ROLL_BASE)
    ap.add_argument("--n-workers", type=int, default=DEFAULT_MP_WORKERS)
    ap.add_argument("--n-decode-samples", type=int, default=4)
    ap.add_argument("--block-gap-threshold-multiplier", type=int, default=10,
                     help="Matches within window*multiplier tokens of each other count as "
                          "the same contiguous block.")
    ap.add_argument("--output-dir", type=str, default="./w1c-certs")
    args = ap.parse_args()

    run_probe(
        shard_dir=args.shard_dir, tokenizer_path=args.tokenizer_path,
        pool_start=args.pool_start, batch_size=args.batch_size, seq_len=args.seq_len,
        window=args.window, roll_base=args.roll_base, n_workers=args.n_workers,
        n_decode_samples=args.n_decode_samples,
        block_gap_multiplier=args.block_gap_threshold_multiplier,
        output_dir=args.output_dir)


if __name__ == "__main__":
    main()
