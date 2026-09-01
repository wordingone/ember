# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""exp711_scorer.py -- #711 ordering-screen CPU apparatus, component 4:
frozen PPM scorer.

Prereg v2 SS3 (binding): ONE PPM scorer, order-4, escape method C,
byte-level counting model, trained on the A7 reservation bytes (component
1's output, concatenated in source/receipt order) and then FROZEN --
no further count updates once training completes, so re-scoring any
window is order-independent and reproducible regardless of which arm
processes it first (a requirement for Spearman(B,C) sanity and for the
scorer's cost being N=1-chargeable rather than order-dependent).

  score(w) = total scorer code length in bits over the detokenized bytes
  of x (the disjoint seq-token segment ONLY; targets/MTP tail excluded)
  / n_bytes(x). Detokenization must round-trip exactly under the frozen
  tokenizer or the window is NONCAUSAL_INVALID (no silent lossy detok).
  Context resets at each window boundary (each score_window call starts
  with empty in-call history; the model's TRAINED counts are read-only
  and never touched during scoring -- "frozen" means frozen, not
  adaptive-during-scoring, which is what makes re-scoring order-
  independent).

Escape method C (Moffat): for a context with n total counts and t
distinct symbols seen, P(escape) = t / (n+t); P(symbol) = count(symbol) /
(n+t) for a symbol already seen in that context. An unseen context
contributes zero cost and falls straight to the next lower order (no
escape event has occurred there -- nothing to charge). Order -1 (below
order 0) is the uniform 256-symbol fallback (8 bits/symbol exactly).

Degeneracy kills (SS3 + SS8, implemented here as selftests against
synthetic fixtures constructed to both PASS and FAIL each kill, proving
the kill actually fires): score dispersion floor (IQR >= 0.05 bits/byte);
max tie-block <= 1% of windows; |Spearman(B_order, canonical id order)|
<= 0.5; sanity Spearman(B,C) ~= -1 (B/C built from the SAME scores, one
ascending one descending -- exact -1 with no ties, provably >= -1 with
ties present, per exp711_permute.py's tie rule).

Run (real corpus, given a component-1 intervals receipt + component-2
manifest receipt; --max-train-bytes / --n-score-sample bound this to a
FAST proof-of-wiring pass -- the UNCAPPED full-reservation training +
full-manifest scoring is hours-class GPU-equivalent work per prereg SS7
and belongs to treatment-launch time, not this apparatus build):
    python scripts/exp711_scorer.py --emit \\
        --intervals-receipt <path> --manifest-receipt <path> \\
        --max-train-bytes 500000 --n-score-sample 500
Selftest (small synthetic streams, degeneracy kills exercised both ways):
    python scripts/exp711_scorer.py --selftest
"""
import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/a1_predicate_scan.py
import importlib.util as _ember_376b57c2d601539f_importlib
import sys as _ember_376b57c2d601539f_sys
from pathlib import Path as _ember_376b57c2d601539f_Path
_ember_376b57c2d601539f_path = _ember_376b57c2d601539f_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'a1_predicate_scan.py')
if not _ember_376b57c2d601539f_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/a1_predicate_scan.py')
_ember_376b57c2d601539f_aliases = ('_ember_issue2015_376b57c2d601539f', 'a1_predicate_scan', 'scripts.a1_predicate_scan')
_ember_376b57c2d601539f_existing = []
for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
    _ember_376b57c2d601539f_candidate = _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias)
    if _ember_376b57c2d601539f_candidate is not None and all(_ember_376b57c2d601539f_candidate is not item for item in _ember_376b57c2d601539f_existing):
        _ember_376b57c2d601539f_existing.append(_ember_376b57c2d601539f_candidate)
if len(_ember_376b57c2d601539f_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/a1_predicate_scan.py')
if _ember_376b57c2d601539f_existing:
    _ember_376b57c2d601539f_module = _ember_376b57c2d601539f_existing[0]
    _ember_376b57c2d601539f_observed = getattr(_ember_376b57c2d601539f_module, '__file__', None)
    if _ember_376b57c2d601539f_observed is None or _ember_376b57c2d601539f_Path(_ember_376b57c2d601539f_observed).resolve() != _ember_376b57c2d601539f_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/a1_predicate_scan.py')
else:
    _ember_376b57c2d601539f_spec = _ember_376b57c2d601539f_importlib.spec_from_file_location('_ember_issue2015_376b57c2d601539f', _ember_376b57c2d601539f_path)
    if _ember_376b57c2d601539f_spec is None or _ember_376b57c2d601539f_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/a1_predicate_scan.py')
    _ember_376b57c2d601539f_module = _ember_376b57c2d601539f_importlib.module_from_spec(_ember_376b57c2d601539f_spec)
    for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
        _ember_376b57c2d601539f_prior = _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias)
        if _ember_376b57c2d601539f_prior is not None and _ember_376b57c2d601539f_prior is not _ember_376b57c2d601539f_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/a1_predicate_scan.py')
        _ember_376b57c2d601539f_sys.modules[_ember_376b57c2d601539f_alias] = _ember_376b57c2d601539f_module
    try:
        _ember_376b57c2d601539f_spec.loader.exec_module(_ember_376b57c2d601539f_module)
    except BaseException:
        for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
            if _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias) is _ember_376b57c2d601539f_module:
                _ember_376b57c2d601539f_sys.modules.pop(_ember_376b57c2d601539f_alias, None)
        raise
for _ember_376b57c2d601539f_alias in _ember_376b57c2d601539f_aliases:
    _ember_376b57c2d601539f_prior = _ember_376b57c2d601539f_sys.modules.get(_ember_376b57c2d601539f_alias)
    if _ember_376b57c2d601539f_prior is not None and _ember_376b57c2d601539f_prior is not _ember_376b57c2d601539f_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/a1_predicate_scan.py')
    _ember_376b57c2d601539f_sys.modules[_ember_376b57c2d601539f_alias] = _ember_376b57c2d601539f_module
load_stripped_tokenizer = getattr(_ember_376b57c2d601539f_module, 'load_stripped_tokenizer')
# issue2015 exact-local-import-end:src/ember/governance/scripts/a1_predicate_scan.py  # noqa: E402
import exp711_manifest as em  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over a canonical (sorted-key) JSON serialization of the trained count tables"

MAX_ORDER = 4
IQR_FLOOR_BITS_PER_BYTE = 0.05
MAX_TIE_BLOCK_FRACTION = 0.01
ID_CORRELATION_CEILING = 0.5
OUT_DIR = os.path.join(REPO, "receipts", "exp711-apparatus")


def _now_ts():
    return datetime.now(timezone.utc).isoformat()


class ScorerError(ValueError):
    pass


# ---------------------------------------------------------------------------
# PPM order-4, escape method C, byte-level counting model
# ---------------------------------------------------------------------------

class PPMScorer:
    """Adaptive-during-TRAINING, frozen-during-SCORING PPM model. counts[k]
    maps a k-byte context (bytes object, k in 0..MAX_ORDER) -> {symbol:
    count}. Order 0's context is the empty bytes object b''."""

    def __init__(self, max_order: int = MAX_ORDER):
        self.max_order = max_order
        self.counts = [dict() for _ in range(max_order + 1)]
        self.n_train_bytes = 0

    def train(self, data: bytes) -> None:
        """One left-to-right pass. At each position i, update ALL orders
        0..min(max_order, i) using the i preceding bytes as context --
        the standard PPM training convention (every symbol occurrence
        informs every context length it could plausibly be predicted
        from)."""
        counts = self.counts
        mo = self.max_order
        n = len(data)
        for i in range(n):
            sym = data[i]
            max_k = mo if i >= mo else i
            for k in range(0, max_k + 1):
                ctx = data[i - k:i] if k > 0 else b""
                d = counts[k].get(ctx)
                if d is None:
                    counts[k][ctx] = {sym: 1}
                else:
                    d[sym] = d.get(sym, 0) + 1
        self.n_train_bytes += n

    def is_frozen_identical(self, other: "PPMScorer") -> bool:
        return self.counts_sha256() == other.counts_sha256()

    def counts_sha256(self) -> str:
        """Deterministic hash of the trained count tables -- the frozen
        scorer's identity (L3 note: "scorer config + counts hashes
        receipted")."""
        h = hashlib.sha256()
        for k in range(self.max_order + 1):
            for ctx in sorted(self.counts[k].keys()):
                d = self.counts[k][ctx]
                h.update(f"K{k}|{ctx.hex()}|".encode("ascii"))
                for sym in sorted(d.keys()):
                    h.update(f"{sym}:{d[sym]},".encode("ascii"))
                h.update(b";")
        return h.hexdigest()

    def code_length_bits(self, data: bytes) -> float:
        """Total code length in bits scoring `data` under the FROZEN
        model (self.counts is read-only here -- no training). Context
        resets at the start of `data` (history is local to this call)."""
        total_bits = 0.0
        counts = self.counts
        mo = self.max_order
        history = bytearray()
        for sym in data:
            hlen = len(history)
            max_k = mo if hlen >= mo else hlen
            coded = False
            for k in range(max_k, -1, -1):
                ctx = bytes(history[hlen - k:]) if k > 0 else b""
                d = counts[k].get(ctx)
                if d is None:
                    continue  # never-seen context: zero cost, drop a level
                n = sum(d.values())
                t = len(d)
                c = d.get(sym)
                if c is not None:
                    p = c / (n + t)
                    total_bits += -math.log2(p)
                    coded = True
                    break
                else:
                    p_esc = t / (n + t)
                    total_bits += -math.log2(p_esc)
            if not coded:
                total_bits += 8.0  # order -1 uniform-256 fallback
            history.append(sym)
        return total_bits


# ---------------------------------------------------------------------------
# score(w) -- detok round-trip gate + code-length / n_bytes
# ---------------------------------------------------------------------------

def detok_round_trip(tokenizer, ids: list):
    """(ok, text_bytes_or_None). Decode ids -> text, re-ENCODE text, and
    require the id sequence to match EXACTLY -- "no silent lossy detok"
    (prereg SS3)."""
    text = tokenizer.decode(ids, skip_special_tokens=False)
    reencoded = tokenizer.encode(text, add_special_tokens=False).ids
    if list(reencoded) != list(ids):
        return False, None
    return True, text.encode("utf-8")


def score_window(scorer: PPMScorer, tokenizer, stream, window_id: int,
                  seq: int) -> dict:
    """score(w) over the disjoint seq-token segment x = w[:seq] ONLY
    (targets/MTP tail excluded). context resets: code_length_bits starts
    a fresh history for this call."""
    start = window_id * seq
    x_ids = [int(t) for t in stream[start:start + seq]]
    ok, detok_bytes = detok_round_trip(tokenizer, x_ids)
    if not ok:
        return {"window_id": int(window_id), "valid": False,
                "reason": "NONCAUSAL_INVALID_DETOK_ROUNDTRIP"}
    n_bytes = len(detok_bytes)
    if n_bytes == 0:
        return {"window_id": int(window_id), "valid": False,
                "reason": "NONCAUSAL_INVALID_EMPTY_DETOK"}
    bits = scorer.code_length_bits(detok_bytes)
    return {"window_id": int(window_id), "valid": True,
            "score": bits / n_bytes, "n_bytes": n_bytes, "bits": bits}


# ---------------------------------------------------------------------------
# Degeneracy kills
# ---------------------------------------------------------------------------

def _rankdata_average(values: list) -> list:
    """Ranks with average-rank tie handling (1-based), no scipy dep."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(a: list, b: list) -> float:
    if len(a) != len(b) or len(a) < 2:
        raise ScorerError("spearman: need equal-length arrays, len>=2")
    ra, rb = _rankdata_average(a), _rankdata_average(b)
    n = len(a)
    mean_ra = sum(ra) / n
    mean_rb = sum(rb) / n
    cov = sum((ra[i] - mean_ra) * (rb[i] - mean_rb) for i in range(n))
    var_a = sum((r - mean_ra) ** 2 for r in ra)
    var_b = sum((r - mean_rb) ** 2 for r in rb)
    if var_a == 0 or var_b == 0:
        return 0.0
    return cov / math.sqrt(var_a * var_b)


def _percentile(sorted_vals: list, p: float) -> float:
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = p / 100.0 * (n - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def iqr(scores: list) -> float:
    s = sorted(scores)
    return _percentile(s, 75) - _percentile(s, 25)


def max_tie_block_fraction(scores: list) -> float:
    c = Counter(scores)
    return max(c.values()) / len(scores)


def degeneracy_report(window_ids: list, scores: list) -> dict:
    """All four SS3/SS8 kills, evaluated together (used by both the
    selftest and --emit)."""
    ranks_by_id = _rankdata_average(scores)  # B-order rank per window (ascending score)
    canonical_rank = _rankdata_average(window_ids)  # canonical id order rank
    id_corr = spearman(scores, window_ids)
    report = {
        "n_windows": len(scores),
        "iqr_bits_per_byte": iqr(scores),
        "iqr_floor": IQR_FLOOR_BITS_PER_BYTE,
        "iqr_pass": iqr(scores) >= IQR_FLOOR_BITS_PER_BYTE,
        "max_tie_block_fraction": max_tie_block_fraction(scores),
        "max_tie_block_ceiling": MAX_TIE_BLOCK_FRACTION,
        "tie_block_pass": max_tie_block_fraction(scores) <= MAX_TIE_BLOCK_FRACTION,
        "spearman_score_vs_canonical_id": id_corr,
        "id_correlation_ceiling": ID_CORRELATION_CEILING,
        "id_correlation_pass": abs(id_corr) <= ID_CORRELATION_CEILING,
    }
    report["all_pass"] = (report["iqr_pass"] and report["tie_block_pass"]
                           and report["id_correlation_pass"])
    return report


def assert_degeneracy_kills(window_ids: list, scores: list) -> dict:
    """Fail-closed wrapper: raises ScorerError naming every failing kill
    if any one fails."""
    r = degeneracy_report(window_ids, scores)
    if not r["all_pass"]:
        failed = [k for k in ("iqr_pass", "tie_block_pass", "id_correlation_pass")
                  if not r[k]]
        raise ScorerError(f"DEGENERACY_KILL: {failed} -- {r}")
    return r


# ---------------------------------------------------------------------------
# Real-corpus wiring (bounded proof-of-wiring; the uncapped run is
# treatment-launch-time hours-class work)
# ---------------------------------------------------------------------------

SHARD_DIR_DEFAULT = os.path.join(os.path.dirname(REPO), "shards-v0")
MMAP_CACHE_DIR_DEFAULT = os.path.join(
    os.path.dirname(REPO), "wt-stab480", "models", "cbase-grow-rung",
    "rung2-stabilize-leg1", "shard-memmap-cache")
COMBINED_MANIFEST_SHA256_EXPECTED = (
    "aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a")


def _load_production_tokenizer_from_intervals(intervals_receipt):
    """Reuses exp711_intervals's tokenizer loading (orphaned-merge
    workaround + ByteLevel decoder wiring -- see that module's
    _wire_bytelevel_decoder docstring) so component 4 decodes identically
    to component 1."""
    # issue2015 exact-local-import:src/ember/governance/scripts/exp711_intervals.py
    import importlib.util as _ember_95bc16ea56a5e3d6_importlib
    import sys as _ember_95bc16ea56a5e3d6_sys
    from pathlib import Path as _ember_95bc16ea56a5e3d6_Path
    _ember_95bc16ea56a5e3d6_path = _ember_95bc16ea56a5e3d6_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'exp711_intervals.py')
    if not _ember_95bc16ea56a5e3d6_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/exp711_intervals.py')
    _ember_95bc16ea56a5e3d6_aliases = ('_ember_issue2015_95bc16ea56a5e3d6', 'exp711_intervals', 'scripts.exp711_intervals')
    _ember_95bc16ea56a5e3d6_existing = []
    for _ember_95bc16ea56a5e3d6_alias in _ember_95bc16ea56a5e3d6_aliases:
        _ember_95bc16ea56a5e3d6_candidate = _ember_95bc16ea56a5e3d6_sys.modules.get(_ember_95bc16ea56a5e3d6_alias)
        if _ember_95bc16ea56a5e3d6_candidate is not None and all(_ember_95bc16ea56a5e3d6_candidate is not item for item in _ember_95bc16ea56a5e3d6_existing):
            _ember_95bc16ea56a5e3d6_existing.append(_ember_95bc16ea56a5e3d6_candidate)
    if len(_ember_95bc16ea56a5e3d6_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/exp711_intervals.py')
    if _ember_95bc16ea56a5e3d6_existing:
        _ember_95bc16ea56a5e3d6_module = _ember_95bc16ea56a5e3d6_existing[0]
        _ember_95bc16ea56a5e3d6_observed = getattr(_ember_95bc16ea56a5e3d6_module, '__file__', None)
        if _ember_95bc16ea56a5e3d6_observed is None or _ember_95bc16ea56a5e3d6_Path(_ember_95bc16ea56a5e3d6_observed).resolve() != _ember_95bc16ea56a5e3d6_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/exp711_intervals.py')
    else:
        _ember_95bc16ea56a5e3d6_spec = _ember_95bc16ea56a5e3d6_importlib.spec_from_file_location('_ember_issue2015_95bc16ea56a5e3d6', _ember_95bc16ea56a5e3d6_path)
        if _ember_95bc16ea56a5e3d6_spec is None or _ember_95bc16ea56a5e3d6_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/exp711_intervals.py')
        _ember_95bc16ea56a5e3d6_module = _ember_95bc16ea56a5e3d6_importlib.module_from_spec(_ember_95bc16ea56a5e3d6_spec)
        for _ember_95bc16ea56a5e3d6_alias in _ember_95bc16ea56a5e3d6_aliases:
            _ember_95bc16ea56a5e3d6_prior = _ember_95bc16ea56a5e3d6_sys.modules.get(_ember_95bc16ea56a5e3d6_alias)
            if _ember_95bc16ea56a5e3d6_prior is not None and _ember_95bc16ea56a5e3d6_prior is not _ember_95bc16ea56a5e3d6_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/exp711_intervals.py')
            _ember_95bc16ea56a5e3d6_sys.modules[_ember_95bc16ea56a5e3d6_alias] = _ember_95bc16ea56a5e3d6_module
        try:
            _ember_95bc16ea56a5e3d6_spec.loader.exec_module(_ember_95bc16ea56a5e3d6_module)
        except BaseException:
            for _ember_95bc16ea56a5e3d6_alias in _ember_95bc16ea56a5e3d6_aliases:
                if _ember_95bc16ea56a5e3d6_sys.modules.get(_ember_95bc16ea56a5e3d6_alias) is _ember_95bc16ea56a5e3d6_module:
                    _ember_95bc16ea56a5e3d6_sys.modules.pop(_ember_95bc16ea56a5e3d6_alias, None)
            raise
    for _ember_95bc16ea56a5e3d6_alias in _ember_95bc16ea56a5e3d6_aliases:
        _ember_95bc16ea56a5e3d6_prior = _ember_95bc16ea56a5e3d6_sys.modules.get(_ember_95bc16ea56a5e3d6_alias)
        if _ember_95bc16ea56a5e3d6_prior is not None and _ember_95bc16ea56a5e3d6_prior is not _ember_95bc16ea56a5e3d6_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/exp711_intervals.py')
        _ember_95bc16ea56a5e3d6_sys.modules[_ember_95bc16ea56a5e3d6_alias] = _ember_95bc16ea56a5e3d6_module
    ei = _ember_95bc16ea56a5e3d6_module
    # issue2015 exact-local-import-end:src/ember/governance/scripts/exp711_intervals.py
    tok = intervals_receipt["tokenizer"]
    tok_path = os.path.join(REPO, tok["tokenizer_json_path"])
    tk, actual_sha, n_dropped, n_total = load_stripped_tokenizer(
        tok_path, expected_sha=tok["tokenizer_json_sha256"])
    ei._wire_bytelevel_decoder(tk, tok_path)
    return tk


def _open_stream(shard_dir, cache_dir, expected_sha):
    from timeshare_pretrain import PackedShardLoader
    loader = PackedShardLoader(shard_dir, seq=1024, n_mtp=2,
                                mmap_cache_dir=cache_dir,
                                expected_manifest_sha256=expected_sha)
    return loader.stream


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--intervals-receipt")
    ap.add_argument("--manifest-receipt")
    ap.add_argument("--max-train-bytes", type=int, default=500_000,
                     help="cap on training bytes for a FAST proof-of-wiring "
                          "pass; the full ~67MB reservation is hours-class "
                          "and belongs to treatment-launch time")
    ap.add_argument("--n-score-sample", type=int, default=500)
    ap.add_argument("--shard-dir", default=SHARD_DIR_DEFAULT)
    ap.add_argument("--cache-dir", default=MMAP_CACHE_DIR_DEFAULT)
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if not args.emit:
        ap.error("pass --emit or --selftest")
    if not (args.intervals_receipt and args.manifest_receipt):
        ap.error("--emit requires --intervals-receipt and --manifest-receipt")

    with open(args.intervals_receipt, encoding="utf-8") as f:
        irec = json.load(f)
    with open(args.manifest_receipt, encoding="utf-8") as f:
        mrec = json.load(f)

    tokenizer = _load_production_tokenizer_from_intervals(irec)
    stream = _open_stream(args.shard_dir, args.cache_dir,
                           COMBINED_MANIFEST_SHA256_EXPECTED)

    # Train on a BOUNDED prefix of each reservation interval (proof-of-
    # wiring cap; disclosed below). Order preserved: receipt/source order.
    scorer = PPMScorer()
    per_source_bytes_used = {}
    remaining = args.max_train_bytes
    for r in irec["reservations"]:
        if remaining <= 0:
            per_source_bytes_used[r["source"]] = 0
            continue
        ids = [int(t) for t in stream[r["reserved_start"]:r["reserved_end"]]]
        text = tokenizer.decode(ids, skip_special_tokens=False)
        b = text.encode("utf-8")[:remaining]
        scorer.train(b)
        per_source_bytes_used[r["source"]] = len(b)
        remaining -= len(b)

    seq = mrec["seq"]
    sample_ids = (mrec["manifest_window_ids_first_1000"][:args.n_score_sample])
    results = [score_window(scorer, tokenizer, stream, wid, seq) for wid in sample_ids]
    valid = [r for r in results if r["valid"]]
    invalid = [r for r in results if not r["valid"]]

    degeneracy = None
    if len(valid) >= 8:
        degeneracy = degeneracy_report([r["window_id"] for r in valid],
                                        [r["score"] for r in valid])

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(OUT_DIR, f"exp711-scorer-{ts}.json")
    receipt_out = {
        "ticket": "EXP711-SCORER",
        "ts": _now_ts(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "refs": [711, 739],
        "intervals_receipt": os.path.basename(args.intervals_receipt),
        "manifest_receipt": os.path.basename(args.manifest_receipt),
        "note": ("BOUNDED PROOF-OF-WIRING run, not the frozen production "
                 "scorer -- max_train_bytes caps training far below the "
                 "full ~67MB reservation (hours-class GPU-equivalent per "
                 "prereg SS7, treatment-launch-time work), and only the "
                 "manifest receipt's disclosed first-N window-id sample is "
                 "scored, not the full ~6.8M-window manifest"),
        "max_train_bytes_arg": args.max_train_bytes,
        "per_source_train_bytes_used": per_source_bytes_used,
        "n_train_bytes_total": scorer.n_train_bytes,
        "counts_sha256": scorer.counts_sha256(),
        "n_scored": len(results),
        "n_valid": len(valid),
        "n_invalid": len(invalid),
        "invalid_reasons": dict(Counter(r["reason"] for r in invalid)),
        "degeneracy": degeneracy,
        "scored_window_ids": [r["window_id"] for r in valid],
        "scores": [r["score"] for r in valid],
    }
    checked_write(out_path, receipt_out)
    print(f"EXP711_SCORER_EMIT_OK: {out_path}")
    print(json.dumps({
        "n_train_bytes_total": scorer.n_train_bytes,
        "n_scored": len(results), "n_valid": len(valid), "n_invalid": len(invalid),
        "degeneracy": degeneracy,
    }, indent=2))


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest():
    import random

    # --- PPM correctness: a highly regular string should compress far
    # below the 8 bits/byte uniform floor once trained on itself.
    text = ("the quick brown fox jumps over the lazy dog. " * 40).encode("utf-8")
    s = PPMScorer()
    s.train(text)
    bits = s.code_length_bits(text)
    bits_per_byte = bits / len(text)
    assert bits_per_byte < 2.0, (
        f"SELFTEST: PPM failed to compress a highly regular self-trained "
        f"string below 2 bits/byte (got {bits_per_byte})")

    # --- Order -1 fallback: an UNTRAINED model scores exactly 8 bits/byte
    # for every symbol (uniform-256, no context ever seen).
    s_blank = PPMScorer()
    blank_bits = s_blank.code_length_bits(b"xyz")
    assert abs(blank_bits - 24.0) < 1e-9, (
        f"SELFTEST: blank model should cost exactly 8 bits/symbol "
        f"(3 bytes -> 24 bits), got {blank_bits}")

    # --- Frozen-during-scoring: scoring the SAME data twice gives the
    # SAME cost (no adaptation leaking across calls), and scoring in a
    # different order doesn't change either result (order-independence).
    b1 = s.code_length_bits(b"the quick")
    b2 = s.code_length_bits(b"lazy dog.")
    b1_again = s.code_length_bits(b"the quick")
    assert b1 == b1_again, "SELFTEST: frozen scorer not reproducible across calls"
    b2_first = PPMScorer()
    b2_first.train(text)
    r2 = b2_first.code_length_bits(b"lazy dog.")
    r1 = b2_first.code_length_bits(b"the quick")
    assert r1 == b1 and r2 == b2, (
        "SELFTEST: scoring order changed results -- frozen model must be "
        "order-independent (no in-scoring adaptation)")

    # --- Context reset: history from one code_length_bits call must NOT
    # leak into the next. Uses two symbols ('Y'=89, 'Z'=90) that never
    # appear ANYWHERE in training (only lowercase a/b/c/d were trained),
    # so order-1+ context b'Y' is provably untrained regardless of
    # position -- the only way scoring "YZ" together could differ from
    # scoring "Y" then "Z" fresh is if 'Y' leaked into 'Z''s context, and
    # an untrained order-1 context contributes exactly zero cost (skip to
    # order 0), so the two must be bit-identical if and only if context
    # truly resets per call.
    s2 = PPMScorer()
    s2.train(b"ab" * 200 + b"cd" * 200)
    cost_yz_together = s2.code_length_bits(b"YZ")
    s2_fresh_y = PPMScorer()
    s2_fresh_y.train(b"ab" * 200 + b"cd" * 200)
    cost_y_alone = s2_fresh_y.code_length_bits(b"Y")
    s2_fresh_z = PPMScorer()
    s2_fresh_z.train(b"ab" * 200 + b"cd" * 200)
    cost_z_alone = s2_fresh_z.code_length_bits(b"Z")
    assert abs(cost_yz_together - (cost_y_alone + cost_z_alone)) < 1e-9, (
        "SELFTEST: context did not reset between windows (scoring 'YZ' as "
        "one call must equal scoring 'Y' then 'Z' as independent "
        "fresh-history calls, since Y/Z never appear in training so "
        "order-1+ context b'Y' is provably untrained)")

    # --- counts_sha256 identity: same training -> same hash; different
    # training -> different hash.
    s3a = PPMScorer(); s3a.train(b"hello world")
    s3b = PPMScorer(); s3b.train(b"hello world")
    s3c = PPMScorer(); s3c.train(b"goodbye world")
    assert s3a.counts_sha256() == s3b.counts_sha256(), (
        "SELFTEST: identical training must produce identical counts hash")
    assert s3a.counts_sha256() != s3c.counts_sha256(), (
        "SELFTEST: different training must produce different counts hash")

    # --- detok round-trip gate: a synthetic tokenizer-like stub that
    # deliberately fails round-trip on one id sequence.
    class _StubTok:
        """encode/decode over a tiny fixed byte-level vocab; id 99 is a
        LOSSY merge (decodes to 'X' but 'X' re-encodes to id 5, never 99)
        -- the deliberate round-trip failure fixture."""
        VOCAB_DECODE = {i: chr(i + 32) for i in range(95)}
        VOCAB_DECODE[99] = "X"  # lossy: decodes but never re-encoded to

        def decode(self, ids, skip_special_tokens=False):
            return "".join(self.VOCAB_DECODE.get(i, "?") for i in ids)

        def encode(self, text, add_special_tokens=False):
            class _E:
                def __init__(self, ids):
                    self.ids = ids
            out = []
            for ch in text:
                found = None
                for i, c in self.VOCAB_DECODE.items():
                    if c == ch and i != 99:  # id 99 unreachable from re-encode
                        found = i
                        break
                out.append(found if found is not None else 0)
            return _E(out)

    stub = _StubTok()
    ok_ids = [ord("a") - 32, ord("b") - 32]
    ok, detok = detok_round_trip(stub, ok_ids)
    assert ok and detok == b"ab", "SELFTEST: valid round-trip incorrectly rejected"
    bad_ids = [99]
    ok2, detok2 = detok_round_trip(stub, bad_ids)
    assert not ok2 and detok2 is None, (
        "SELFTEST: lossy round-trip (id 99) must be rejected, not silently accepted")

    class _FakeStream:
        def __init__(self, ids):
            self._ids = ids
        def __getitem__(self, sl):
            return self._ids[sl]

    scorer_for_windows = PPMScorer()
    scorer_for_windows.train(b"abcdefgh" * 50)
    stream_ids = ok_ids + bad_ids + [ord("a") - 32] * 5
    fake_stream = _FakeStream(stream_ids)
    r_ok = score_window(scorer_for_windows, stub, fake_stream, 0, seq=2)
    assert r_ok["valid"], "SELFTEST: score_window rejected a valid window"
    r_bad = score_window(scorer_for_windows, stub, fake_stream, 2, seq=1)  # index 2 == bad_ids[0] (99)
    assert not r_bad["valid"] and r_bad["reason"] == "NONCAUSAL_INVALID_DETOK_ROUNDTRIP", (
        "SELFTEST: score_window did not correctly flag a round-trip failure")

    # --- Spearman: exact +1 / -1 / ~0 fixtures.
    a = [1, 2, 3, 4, 5]
    assert abs(spearman(a, a) - 1.0) < 1e-9, "SELFTEST: spearman(a,a) != 1"
    assert abs(spearman(a, a[::-1]) - (-1.0)) < 1e-9, "SELFTEST: spearman(a,reverse(a)) != -1"
    rng = random.Random(20260711)
    shuffled = a * 40
    b_rand = [rng.random() for _ in shuffled]
    corr = spearman(shuffled, b_rand)
    assert abs(corr) < 0.3, f"SELFTEST: spearman on independent data unexpectedly large ({corr})"

    # --- Degeneracy kills: a PASSING fixture (varied real-text scores)
    # and a FAILING fixture for EACH of the three kills, proving each
    # kill actually fires rather than being dead code.
    rng2 = random.Random(4241)
    trainer = PPMScorer()
    trainer.train(("lorem ipsum dolor sit amet consectetur adipiscing elit "
                    "sed do eiusmod tempor incididunt ut labore et dolore "
                    "magna aliqua ut enim ad minim veniam quis nostrud "
                    "exercitation ullamco laboris nisi ut aliquip ex ea "
                    "commodo consequat").encode("utf-8") * 5)
    alphabet = "abcdefghijklmnopqrstuvwxyz ,."
    good_ids, good_scores = [], []
    for i in range(200):
        length = 8 + rng2.randrange(40)
        w = "".join(rng2.choice(alphabet) for _ in range(length))
        b = w.encode("utf-8")
        bits = trainer.code_length_bits(b)
        good_ids.append(i)
        good_scores.append(bits / len(b))
    good_report = degeneracy_report(good_ids, good_scores)
    assert good_report["all_pass"], (
        f"SELFTEST: expected varied real-text scores to PASS degeneracy "
        f"kills, got {good_report}")

    # IQR-floor failure: identical scores for every window (dispersion 0).
    flat_scores = [3.14159] * 100
    flat_ids = list(range(100))
    flat_report = degeneracy_report(flat_ids, flat_scores)
    assert not flat_report["iqr_pass"], (
        "SELFTEST: IQR-floor kill failed to fire on a flat score distribution")
    try:
        assert_degeneracy_kills(flat_ids, flat_scores)
        raise AssertionError("SELFTEST: assert_degeneracy_kills did not raise on flat scores")
    except ScorerError:
        pass

    # Tie-block failure: >1% of windows share one exact score value.
    tie_scores = [1.0] * 5 + [round(1.0 + i * 0.01, 6) for i in range(95)]
    tie_ids = list(range(100))
    tie_report = degeneracy_report(tie_ids, tie_scores)
    assert not tie_report["tie_block_pass"], (
        "SELFTEST: tie-block kill failed to fire on a 5%-tie-block fixture")

    # id-correlation-ceiling failure: score IS the canonical id (perfect
    # collapse toward domain-blocked id order).
    collapse_ids = list(range(100))
    collapse_scores = [float(i) for i in collapse_ids]
    collapse_report = degeneracy_report(collapse_ids, collapse_scores)
    assert not collapse_report["id_correlation_pass"], (
        "SELFTEST: id-correlation-ceiling kill failed to fire when score "
        "== canonical id exactly")
    assert abs(collapse_report["spearman_score_vs_canonical_id"] - 1.0) < 1e-9

    # --- B/C sanity: Spearman(B,C) ~= -1 built from the SAME score
    # dict (B ascending, C descending) via exp711_permute.
    import exp711_permute as ep
    scores_by_id = {i: s for i, s in zip(good_ids, good_scores)}
    arm_b = ep.score_ordered_arm(good_ids, scores_by_id, ascending=True)
    arm_c = ep.score_ordered_arm(good_ids, scores_by_id, ascending=False)
    b_scores_ordered = [scores_by_id[int(w)] for w in arm_b]
    c_scores_ordered = [scores_by_id[int(w)] for w in arm_c]
    bc_corr = spearman(b_scores_ordered, list(reversed(c_scores_ordered)))
    # B's score sequence compared to C's score sequence read BACKWARDS
    # should align (both express the same ascending order); direct
    # Spearman(position_in_B, position_in_C) for the SAME window id is
    # the prereg's actual sanity statistic:
    pos_in_b = {int(w): i for i, w in enumerate(arm_b)}
    pos_in_c = {int(w): i for i, w in enumerate(arm_c)}
    common_ids = sorted(set(pos_in_b) & set(pos_in_c))
    corr_bc = spearman([pos_in_b[w] for w in common_ids],
                        [pos_in_c[w] for w in common_ids])
    assert corr_bc < -0.99, (
        f"SELFTEST: Spearman(B,C) position correlation must be ~= -1, got {corr_bc}")

    print("EXP711_SCORER_SELFTEST_PASS")
    print(json.dumps({
        "self_trained_bits_per_byte": bits_per_byte,
        "good_fixture_degeneracy": good_report,
        "spearman_bc_position": corr_bc,
    }, indent=2))


if __name__ == "__main__":
    main()
