"""w1c_batch_orchestrator.py -- K-certified batch production orchestrator
(#558 rebuild of the #553 harvest's build_k_certified_batches.py skeleton).

WHAT THIS IS: keeps the #553 diff's loop/receipt-schema/kill-criteria shape
(K=10 fresh-batch production, per-batch disjointness assertions, "report
achieved K and stop" -- never loosen certification to hit K) but REWIRES
certification onto the FROZEN two-part predicate that landed on master via
#506+#554 (HeldoutCertifier + BoilerplateBloomIndex), instead of the #553
harvest's `corpus_bloom_index` module.

WHY THE REWIRE: `corpus_bloom_index` implements the ORIGINAL 6.98B-key
universal-window design the RE-SCOPE RULING (issue #374 comment 4920277395)
explicitly retired -- "orders of magnitude smaller m than the original
6.98B-key design". #553's own `build_k_certified_batches.py` (adjudicated
in PR #553 comment 4925410455) called that retired module and therefore
enforced the WRONG predicate. This file is deliberately banned from ever
importing `corpus_bloom_index` -- see
test_w1c_batch_orchestrator.py::test_orchestrator_never_imports_banned_corpus_bloom_index.

THE FROZEN PREDICATE (v2.1, issue #440 comment 4916781765), as implemented
here:
  1. Position/document disjointness from the realized training front --
     UNCHANGED, "everything else survives" per the re-scope ruling: reuses
     `reserve_pool`/`read_window_tokens` from build_decontam_batch.py exactly
     as the pre-re-scope design did (a row's position must fall after the
     training ceiling).
  2. Source-homogeneity per batch -- a batch is drawn entirely from ONE
     source (HeldoutCertifier._check_source_disjointness requires
     len(sources_in_batch)==1); this orchestrator iterates sources in a
     disclosed fixed order, filling whole batches within a source before
     moving to the next.
  3. Boilerplate DROP-ONLY at window granularity W=50 (DEFAULT_WINDOW_TOKENS
     in heldout_v21_fcalib.py, the value governing FUTURE held-out
     construction per the v2.1 predicate doc): every row is sliced into
     stride-1 50-token sub-windows; a row is CERTIFIED only if ALL its
     sub-windows certify. Any single failing sub-window drops the WHOLE row
     (predicate point 4: "the ROW containing it in scored position is
     DROPPED as unusable -- never admit-and-forgive").

Kill criteria (preserved from #553's skeleton): if a source's held-out pool
is exhausted before a batch reaches batch_size certified rows, that partial
batch is INSUFFICIENT and is not counted; the orchestrator moves to the next
source. If, after exhausting every source in source_order, achieved_k < the
target k, it STOPS and reports the achieved count honestly -- it never
lowers the certification bar to manufacture more clean batches.

Schema: w2-k-certified-batches/v1.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

from w2_heldout.build_decontam_batch import (
    cheap_shard_sizes,
    _cumulative_token_offsets,
    read_window_tokens,
    reserve_pool,
    batch_sha256,
)
from w2_heldout.certify_heldout_batch import HeldoutCertifier

DEFAULT_SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
DEFAULT_SEQ = 1024
DEFAULT_N_MTP = 2
DEFAULT_BATCH_SIZE = 16
DEFAULT_CEILING_STEPS = 1533
DEFAULT_TRAIN_BATCH = 16
DEFAULT_K = 10
DEFAULT_WINDOW_TOKENS = 50  # v2.1 predicate's W, NOT the older strict-13 W1 value

RECEIPT_DIR = os.path.join(REPO_ROOT, "receipts", "ember-c-scale")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sanitize_shard_dir(shard_dir: str) -> str:
    """Never let an absolute local filesystem path land in a committed
    receipt (repo-guard [paths]). Redaction law: <ROOT> placeholder."""
    return "<ROOT>" if shard_dir else ""


# ---------------------------------------------------------------------------
# Source attribution
# ---------------------------------------------------------------------------

def source_for_global_start(global_start: int, boundaries: list[dict]) -> str | None:
    """Which source's [start,end) contains this GLOBAL token position.

    Returns None if global_start falls in no known source range (caller
    must treat that as out-of-corpus, not silently attribute a source).
    """
    for b in boundaries:
        if b["start"] <= global_start < b["end"]:
            return b["source"]
    return None


# ---------------------------------------------------------------------------
# Certification-window slicing (v2.1 content layer: W tokens, stride 1)
# ---------------------------------------------------------------------------

def certification_windows(row_tokens: list[int], window_tokens: int) -> list[bytes]:
    """Slide a window_tokens-wide window across row_tokens with stride 1,
    returning each sub-window's key (little-endian uint16 bytes -- the same
    encoding heldout_v21_fcalib.py and BoilerplateBloomIndex use)."""
    n = len(row_tokens)
    if n < window_tokens:
        return []
    arr = np.asarray(row_tokens, dtype="<u2")
    return [arr[i:i + window_tokens].tobytes() for i in range(n - window_tokens + 1)]


# ---------------------------------------------------------------------------
# Row certification -- DROP-ONLY (predicate point 4)
# ---------------------------------------------------------------------------

def certify_row(row_tokens: list[int], source: str, sources_in_batch: set[str],
                 certifier: HeldoutCertifier, window_tokens: int = DEFAULT_WINDOW_TOKENS) -> dict:
    """Certify one candidate row against the frozen two-part predicate.

    A row certifies only if EVERY stride-1 W-token sub-window certifies.
    The first failing sub-window short-circuits and drops the whole row
    (never admit-and-forgive; the row is unusable, not partially usable).

    Returns:
      {"certified": bool, "reason": str|None, "n_sub_windows": int,
       "failed_at_sub_window": int|None}
    """
    windows = certification_windows(row_tokens, window_tokens)
    for i, window_key in enumerate(windows):
        result = certifier.certify_window(window_key, source, sources_in_batch)
        if not result.certified:
            return {
                "certified": False,
                "reason": result.reason,
                "n_sub_windows": len(windows),
                "failed_at_sub_window": i,
            }
    return {
        "certified": True,
        "reason": "certified",
        "n_sub_windows": len(windows),
        "failed_at_sub_window": None,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_k_batches(*, shard_dir: str, boundaries: list[dict], certifier: HeldoutCertifier,
                     seq: int = DEFAULT_SEQ, n_mtp: int = DEFAULT_N_MTP,
                     batch_size: int = DEFAULT_BATCH_SIZE,
                     ceiling_steps: int = DEFAULT_CEILING_STEPS,
                     train_batch: int = DEFAULT_TRAIN_BATCH,
                     k: int = DEFAULT_K,
                     window_tokens: int = DEFAULT_WINDOW_TOKENS,
                     source_order: list[str] | None = None,
                     max_rounds_per_batch: int = 6) -> dict:
    """Produce up to k fresh certified batches of batch_size rows each,
    iterating sources in source_order and filling whole batches within a
    source before moving to the next. Kill criteria: stop and report
    achieved_k honestly once every source's pool is exhausted -- never
    loosen certification to reach the target k.
    """
    t_start = time.perf_counter()
    block_len = seq + n_mtp

    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)
    n_windows_total = cum[-1] // seq

    sources = source_order if source_order is not None else sorted({b["source"] for b in boundaries})
    boundary_by_source = {b["source"]: b for b in boundaries}

    batches: list[dict] = []
    batch_no = 0

    for source in sources:
        b = boundary_by_source.get(source)
        if b is None:
            continue
        # Restrict window indices to this source's own token range so a row
        # never straddles a source boundary (straddling rows are simply
        # skipped -- a rare edge case, not a certification concern).
        src_first_idx = -(-b["start"] // seq)  # ceil
        src_last_idx_excl = min(n_windows_total, b["end"] // seq)
        n_windows_in_source = max(0, src_last_idx_excl - src_first_idx)
        if n_windows_in_source <= 0:
            continue

        # held_out_window_start/assert_disjoint_from_training operate on
        # GLOBAL window indices (training consumes a GLOBAL prefix of the
        # whole concatenated stream, window 0 upward) -- so the pool must be
        # reserved from src_last_idx_excl (this source's GLOBAL end index),
        # never from n_windows_in_source (a source-LOCAL count). Passing the
        # local count here is the bug this comment replaces: for any source
        # positioned after the training-front prefix (i.e. every source but
        # possibly the very first), it silently produced a held_out_start
        # near 0 instead of near src_last_idx_excl, tripping the disjointness
        # assertion on data that was in fact trivially disjoint.
        #
        # Pool spans the source's ENTIRE disjoint range (not just a narrow
        # tail slice): a real-corpus AC1 run found the immediate tail can be
        # a locally boilerplate-dense stretch (consistent with issue #440's
        # documented "tail zero-clean" near-duplication defect) while other
        # parts of the same source certify at a healthy rate -- reserving
        # only the last few dozen windows would silently miss all of that,
        # producing a false "achieved_k=0" that isn't about certification
        # correctness, only about where the search looked.
        # -1 margin: held_out_window_start rejects a pool spanning the exact
        # full range (start would land at 0, which it treats as empty), so
        # reserve one window less than the source's entire disjoint span.
        pool_span = max(1, n_windows_in_source - 1)
        pool_start_global, disjoint_check = reserve_pool(
            src_last_idx_excl, pool_span, ceiling_steps, train_batch)
        next_pool_idx = pool_start_global

        while batch_no < k:
            selected_rows: list[list[int]] = []
            selected_indices: list[int] = []
            certification_results: list[dict] = []
            rounds = []

            for round_no in range(1, max_rounds_per_batch + 1):
                need = batch_size - len(selected_rows)
                if need <= 0:
                    break
                pool_indices = [
                    idx for idx in range(next_pool_idx, min(next_pool_idx + need * 2, src_last_idx_excl))
                ]
                if not pool_indices:
                    break

                clean_found = 0
                dropped_found = 0
                for pool_idx in pool_indices:
                    if len(selected_rows) >= batch_size:
                        break
                    start = pool_idx * seq
                    end = start + block_len
                    if end > b["end"]:
                        continue  # row would straddle out of this source
                    row_tokens = read_window_tokens(shard_dir, files, cum, seq, block_len, pool_idx)
                    verdict = certify_row(row_tokens, source, {source}, certifier, window_tokens)
                    if verdict["certified"]:
                        selected_rows.append(row_tokens)
                        selected_indices.append(pool_idx)
                        certification_results.append(verdict)
                        clean_found += 1
                    else:
                        dropped_found += 1

                rounds.append({
                    "round": round_no, "pool_start": next_pool_idx,
                    "pool_size": len(pool_indices),
                    "clean_found": clean_found, "dropped_found": dropped_found,
                })
                next_pool_idx = pool_indices[-1] + 1 if pool_indices else next_pool_idx

            if len(selected_rows) < batch_size:
                # Kill criteria: this source's pool is exhausted before a
                # full batch certified. Do NOT count a partial batch; move
                # to the next source (outer for-loop). Never widen the
                # predicate to force a fill.
                break

            batch_no += 1
            sha = batch_sha256(selected_rows, seq)
            batches.append({
                "batch_no": batch_no, "status": "CLEAN", "source": source,
                "batch_sha256": sha, "seq": seq, "n_mtp": n_mtp,
                "batch_size": batch_size,
                "selected_window_indices": selected_indices,
                "certification_verdicts": certification_results,
                "rounds": rounds,
                "disjoint_check": disjoint_check,
            })

        if batch_no >= k:
            break

    achieved_k = sum(1 for b_ in batches if b_["status"] == "CLEAN")
    wall_total = round(time.perf_counter() - t_start, 3)

    return {
        "target_k": k,
        "achieved_k": achieved_k,
        "batches": batches,
        "source_order": sources,
        "seq": seq,
        "n_mtp": n_mtp,
        "batch_size": batch_size,
        "window_tokens": window_tokens,
        "total_wall_s": wall_total,
    }


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

def write_batch_receipts(result: dict, *, receipt_dir: str = RECEIPT_DIR,
                          shard_dir: str = "") -> list[str]:
    """Write one receipt per CLEAN batch, schema w2-k-certified-batches/v1."""
    os.makedirs(receipt_dir, exist_ok=True)
    receipt_paths = []

    for batch_data in result["batches"]:
        if batch_data["status"] != "CLEAN":
            continue
        ts = _utc_ts()
        receipt = {
            "schema": "w2-k-certified-batches/v1",
            "ts": ts,
            "spec_ref": "issue #558 (rebuild of #553 skeleton on the frozen "
                        "two-part predicate, HeldoutCertifier + BoilerplateBloomIndex)",
            "shard_dir": _sanitize_shard_dir(shard_dir),
            "batch_no": batch_data["batch_no"],
            "target_k": result["target_k"],
            "achieved_k": result["achieved_k"],
            "source": batch_data["source"],
            "batch_sha256": batch_data["batch_sha256"],
            "seq": batch_data["seq"],
            "n_mtp": batch_data["n_mtp"],
            "batch_size": batch_data["batch_size"],
            "window_tokens": result["window_tokens"],
            "selected_window_indices": batch_data["selected_window_indices"],
            "certification_verdicts": batch_data["certification_verdicts"],
            "disjoint_check": batch_data.get("disjoint_check"),
            "rounds": batch_data.get("rounds"),
            "pass": True,
        }
        path = os.path.join(receipt_dir, f"w2-k-certified-batch-{batch_data['batch_no']}-{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)
        receipt_paths.append(path)

    return receipt_paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    from heldout_v21_fcalib import load_source_boundaries, DEFAULT_SHARD_RECEIPT, SOURCE_ORDER
    from w2_heldout.corpus_boilerplate_bloom import BoilerplateBloomIndex

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard-dir", default=DEFAULT_SHARD_DIR)
    ap.add_argument("--shard-receipt", default=DEFAULT_SHARD_RECEIPT)
    ap.add_argument("--boilerplate-keys", required=True,
                     help="Path to heldout_v21_fcalib.py --emit-boilerplate-keys JSON output")
    ap.add_argument("--f-key", default="1e-03")
    ap.add_argument("--seq", type=int, default=DEFAULT_SEQ)
    ap.add_argument("--n-mtp", type=int, default=DEFAULT_N_MTP)
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--ceiling-steps", type=int, default=DEFAULT_CEILING_STEPS)
    ap.add_argument("--train-batch", type=int, default=DEFAULT_TRAIN_BATCH)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--window-tokens", type=int, default=DEFAULT_WINDOW_TOKENS)
    ap.add_argument("--sources", default="", help="comma list; default = every source in the shard receipt")
    ap.add_argument("--receipt-dir", default=RECEIPT_DIR)
    args = ap.parse_args(argv)

    if not args.shard_dir:
        raise SystemExit(
            "W1C_ORCH_SHARD_DIR_REQUIRED: shard directory must be specified via "
            "--shard-dir or EMBER_SHARD_DIR environment variable")

    source_order = [s.strip() for s in args.sources.split(",") if s.strip()] or None
    full_source_order = source_order or SOURCE_ORDER
    boundaries, _total, _raw = load_source_boundaries(args.shard_receipt, SOURCE_ORDER)
    if source_order:
        boundaries = [b for b in boundaries if b["source"] in source_order]

    bloom_index, cap_saturated = BoilerplateBloomIndex.build_from_fcalib_boilerplate_keys(
        args.boilerplate_keys, f_key=args.f_key)
    certifier = HeldoutCertifier(bloom_index, cap_saturated_per_source=cap_saturated)

    result = build_k_batches(
        shard_dir=args.shard_dir, boundaries=boundaries, certifier=certifier,
        seq=args.seq, n_mtp=args.n_mtp, batch_size=args.batch_size,
        ceiling_steps=args.ceiling_steps, train_batch=args.train_batch,
        k=args.k, window_tokens=args.window_tokens,
        source_order=[b["source"] for b in boundaries],
    )

    print(f"K-batch certification complete: {result['achieved_k']}/{result['target_k']} clean batches")
    if result["achieved_k"] > 0:
        paths = write_batch_receipts(result, receipt_dir=args.receipt_dir, shard_dir=args.shard_dir)
        print(f"Receipts written: {len(paths)} files")
        for p in paths:
            print(f"  {p}")
    return result


if __name__ == "__main__":
    main()
