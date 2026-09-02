# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""exp711_manifest.py -- #711 ordering-screen CPU apparatus, component 2:
canonical packed-window manifest.

Prereg v2 SS2 + AMENDMENT A7 item 4 (binding):

  Windows are built via the PRODUCTION PackedShardLoader geometry
  (src/ember/governance/scripts/timeshare_pretrain.py PackedShardLoader): window i spans tokens
  [i*seq, i*seq + block_len), block_len = seq + 1 + n_mtp, stride = seq,
  the final short window is DROPPED (n_windows = (n_tokens - block_len)
  // seq + 1) -- never the mod-n_windows wrap the loader's own batch()
  helper uses for infinite dry-runs.

  Every window whose token span intersects ANY scorer-reservation interval
  (component 1's output) is EXCLUDED -- full-example exclusion; a window
  that merely straddles a reservation boundary drops entirely, it is never
  clipped. THEN the manifest is trimmed to an exact multiple of batch size
  in canonical (ascending) window-id order. THEN it is frozen: ordered
  window ids + SHA256 per full example tuple (the block_len-token span
  that (x, y_primary, y_mtp) are all deterministic slices of -- hashing
  the contiguous raw token bytes of that span is hashing the full example
  tuple).

  "Exactly one epoch" refers to THIS frozen trimmed-reserved manifest;
  training multiset = stream - reservations - trim (A7 item 4).

Zero-intersection is asserted TWO independent ways (range-level interval
arithmetic AND example-id-level set membership, both fail-closed) --
never re-trusting the same computation that built the exclusion mask.

The launch assert helper enforces steps * batch == n_windows_trimmed
EXACTLY and REFUSES any modulo-wrap access into the frozen manifest (the
production loader's batch() wraps i % n_windows for infinite dry-runs;
that wrap must never reach the frozen exp711 manifest, since it would
silently consume a treatment-correlated different multiset on the tail).

Run (real corpus, given a component-1 intervals receipt, writes the
manifest apparatus receipt):
    python src/ember/governance/scripts/exp711_manifest.py --emit \\
        --intervals-receipt receipts/exp711-apparatus/exp711-intervals-<ts>.json \\
        --batch-size 32
Selftest (small synthetic stream + synthetic reservations):
    python src/ember/governance/scripts/exp711_manifest.py --selftest
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
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

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = ("sha256 over the raw little-endian uint16 token bytes of "
                   "a window's full block_len span (the bytes (x, "
                   "y_primary, y_mtp) are all deterministic slices of)")

SEQ_DEFAULT = 1024
N_MTP_DEFAULT = 2
OUT_DIR = os.path.join(REPO, "receipts", "exp711-apparatus")


def _now_ts():
    return datetime.now(timezone.utc).isoformat()


class ManifestError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Candidate windows (PackedShardLoader geometry, verbatim)
# ---------------------------------------------------------------------------

def block_len_of(seq: int, n_mtp: int) -> int:
    return seq + 1 + n_mtp


def n_windows_of(n_tokens: int, seq: int, n_mtp: int) -> int:
    bl = block_len_of(seq, n_mtp)
    if n_tokens < bl:
        raise ManifestError(f"n_tokens {n_tokens} < block_len {bl}")
    return (n_tokens - bl) // seq + 1


def candidate_window_spans(n_tokens: int, seq: int, n_mtp: int):
    """(starts, ends, n_windows) as numpy int64 arrays. window i spans
    [starts[i], ends[i]) = [i*seq, i*seq+block_len). Stride seq, final
    short window dropped by construction of n_windows_of()."""
    import numpy as np
    bl = block_len_of(seq, n_mtp)
    n = n_windows_of(n_tokens, seq, n_mtp)
    starts = np.arange(n, dtype=np.int64) * seq
    ends = starts + bl
    return starts, ends, n


# ---------------------------------------------------------------------------
# Reservation exclusion (full-example -- a straddling window drops entirely)
# ---------------------------------------------------------------------------

def exclusion_mask(starts, ends, reserved_intervals: list):
    """Boolean array, True where window [starts[i], ends[i]) intersects
    ANY reserved interval. Half-open interval intersection:
    a1 < b2 and b1 < a2."""
    import numpy as np
    mask = np.zeros(len(starts), dtype=bool)
    for r in reserved_intervals:
        b1, b2 = int(r["reserved_start"]), int(r["reserved_end"])
        if b2 <= b1:
            continue
        mask |= (starts < b2) & (b1 < ends)
    return mask


def build_and_trim_manifest(n_tokens: int, seq: int, n_mtp: int,
                             reserved_intervals: list, batch_size: int):
    """Full component-2 pipeline. Returns dict with window_ids (post-
    exclusion, post-trim, ascending canonical order), n_windows_candidate,
    n_excluded, n_surviving, n_windows_trimmed, block_len."""
    import numpy as np
    starts, ends, n_candidate = candidate_window_spans(n_tokens, seq, n_mtp)
    mask = exclusion_mask(starts, ends, reserved_intervals)
    excluded_ids = np.nonzero(mask)[0]
    surviving_ids = np.nonzero(~mask)[0]  # already ascending (np.nonzero order)

    n_surviving = len(surviving_ids)
    n_trimmed = (n_surviving // batch_size) * batch_size
    if n_trimmed == 0:
        raise ManifestError(
            f"trim to batch multiple ({batch_size}) leaves zero windows "
            f"(n_surviving={n_surviving})")
    trimmed_ids = surviving_ids[:n_trimmed]  # canonical (ascending) id order

    return {
        "seq": seq, "n_mtp": n_mtp, "block_len": block_len_of(seq, n_mtp),
        "n_tokens": n_tokens,
        "n_windows_candidate": int(n_candidate),
        "n_excluded": int(len(excluded_ids)),
        "n_surviving": int(n_surviving),
        "batch_size": batch_size,
        "n_windows_trimmed": int(n_trimmed),
        "window_ids": trimmed_ids,
        "excluded_ids": excluded_ids,
        "_starts": starts, "_ends": ends,  # internal, not receipted verbatim
    }


# ---------------------------------------------------------------------------
# Zero-intersection asserts -- TWO independent methods, both fail-closed
# ---------------------------------------------------------------------------

def assert_range_level_zero_intersection(window_ids, starts, ends,
                                          reserved_intervals: list) -> None:
    """Interval-arithmetic re-check over the FINAL kept window ids only
    (independent re-derivation of spans from ids, not a reuse of the
    exclusion_mask array)."""
    import numpy as np
    kept_starts = starts[window_ids]
    kept_ends = ends[window_ids]
    for r in reserved_intervals:
        b1, b2 = int(r["reserved_start"]), int(r["reserved_end"])
        if b2 <= b1:
            continue
        bad = np.nonzero((kept_starts < b2) & (b1 < kept_ends))[0]
        if len(bad):
            raise ManifestError(
                f"RANGE_LEVEL_INTERSECTION: {len(bad)} kept window(s) "
                f"intersect reserved interval [{b1},{b2}) -- "
                f"e.g. window id {int(window_ids[bad[0]])}")


def assert_example_id_level_zero_intersection(window_ids, excluded_ids) -> None:
    """Set-membership re-check: the final kept-id set must be disjoint
    from the excluded-id set (a different bug class than interval
    arithmetic -- catches indexing/off-by-one errors in how ids map back
    to the trimmed list)."""
    kept = set(int(w) for w in window_ids)
    excl = set(int(w) for w in excluded_ids)
    overlap = kept & excl
    if overlap:
        raise ManifestError(
            f"EXAMPLE_ID_LEVEL_INTERSECTION: {len(overlap)} window id(s) "
            f"appear in BOTH the kept manifest and the excluded set "
            f"(e.g. {sorted(overlap)[:5]})")


# ---------------------------------------------------------------------------
# Freeze: SHA256 per full example tuple
# ---------------------------------------------------------------------------

def freeze_example_hashes(stream, window_ids, block_len: int, seq: int) -> list:
    """SHA256 of the raw token bytes for each kept window's full
    block_len-token span, in canonical (ascending) id order."""
    import numpy as np
    hashes = []
    for wid in window_ids:
        start = int(wid) * seq
        w = np.asarray(stream[start:start + block_len], dtype="<u2")
        hashes.append(hashlib.sha256(w.tobytes()).hexdigest())
    return hashes


# ---------------------------------------------------------------------------
# Launch assert helper -- exact steps*batch, refuses modulo-wrap
# ---------------------------------------------------------------------------

def assert_launch(steps: int, batch_size: int, n_windows_trimmed: int) -> None:
    """steps * batch_size must equal n_windows_trimmed EXACTLY -- one
    epoch over the frozen manifest, no more, no less."""
    total = steps * batch_size
    if total != n_windows_trimmed:
        raise ManifestError(
            f"LAUNCH_ASSERT: steps({steps}) * batch({batch_size}) = "
            f"{total} != n_windows_trimmed {n_windows_trimmed}")


def window_id_at_position(manifest_window_ids, position: int) -> int:
    """The frozen manifest's window id at a given 0-based POSITION in
    canonical order. REFUSES to wrap (raises IndexError) -- unlike
    PackedShardLoader.batch()'s `i % n_windows`, which exists only for
    infinite dry-runs and must never reach a frozen exp711 manifest (a
    wrap would silently repeat a treatment-correlated different multiset
    once position exceeds len(manifest_window_ids))."""
    n = len(manifest_window_ids)
    if position < 0 or position >= n:
        raise IndexError(
            f"WRAP_REFUSED: position {position} out of range [0,{n}) -- "
            "the frozen manifest never wraps; a caller reaching this is a "
            "launch-assert bug (steps*batch must equal n_windows_trimmed)")
    return int(manifest_window_ids[position])


# ---------------------------------------------------------------------------
# Real-corpus wiring
# ---------------------------------------------------------------------------

def _load_intervals_receipt(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _open_stream(shard_dir, cache_dir, expected_sha):
    from timeshare_pretrain import PackedShardLoader
    loader = PackedShardLoader(shard_dir, seq=SEQ_DEFAULT, n_mtp=N_MTP_DEFAULT,
                                mmap_cache_dir=cache_dir,
                                expected_manifest_sha256=expected_sha)
    return loader.stream


SHARD_DIR_DEFAULT = os.path.join(os.path.dirname(REPO), "shards-v0")
MMAP_CACHE_DIR_DEFAULT = os.path.join(
    os.path.dirname(REPO), "wt-stab480", "models", "cbase-grow-rung",
    "rung2-stabilize-leg1", "shard-memmap-cache")
COMBINED_MANIFEST_SHA256_EXPECTED = (
    "aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--intervals-receipt")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--shard-dir", default=SHARD_DIR_DEFAULT)
    ap.add_argument("--cache-dir", default=MMAP_CACHE_DIR_DEFAULT)
    ap.add_argument("--hash-sample-cap", type=int, default=200_000,
                     help="cap on how many per-window hashes to compute "
                          "for --emit (full-manifest hashing of ~6.8M "
                          "windows is the deliverable's job at treatment- "
                          "launch time, not this apparatus receipt; a "
                          "deterministic stride sample is banked here plus "
                          "the exact manifest window-id list + counts)")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if not args.emit:
        ap.error("pass --emit or --selftest")
    if not args.intervals_receipt:
        ap.error("--emit requires --intervals-receipt")

    intervals_receipt = _load_intervals_receipt(args.intervals_receipt)
    reserved_intervals = intervals_receipt["reservations"]
    n_tokens = intervals_receipt["n_tokens"]

    stream = _open_stream(args.shard_dir, args.cache_dir,
                           COMBINED_MANIFEST_SHA256_EXPECTED)
    if int(stream.shape[0]) != n_tokens:
        raise ManifestError(f"stream length {stream.shape[0]} != intervals "
                             f"receipt n_tokens {n_tokens}")

    m = build_and_trim_manifest(n_tokens, SEQ_DEFAULT, N_MTP_DEFAULT,
                                 reserved_intervals, args.batch_size)
    assert_range_level_zero_intersection(m["window_ids"], m["_starts"],
                                          m["_ends"], reserved_intervals)
    assert_example_id_level_zero_intersection(m["window_ids"], m["excluded_ids"])

    n_ids = len(m["window_ids"])
    if n_ids <= args.hash_sample_cap:
        sample_ids = m["window_ids"]
    else:
        stride = n_ids // args.hash_sample_cap
        sample_ids = m["window_ids"][::stride][:args.hash_sample_cap]
    sample_hashes = freeze_example_hashes(stream, sample_ids, m["block_len"], SEQ_DEFAULT)
    manifest_ids_sha256 = hashlib.sha256(
        m["window_ids"].astype("<i8").tobytes()).hexdigest()

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(OUT_DIR, f"exp711-manifest-{ts}.json")
    receipt_out = {
        "ticket": "EXP711-MANIFEST",
        "ts": _now_ts(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "refs": [711, 739],
        "intervals_receipt": os.path.basename(args.intervals_receipt),
        "seq": m["seq"], "n_mtp": m["n_mtp"], "block_len": m["block_len"],
        "n_tokens": m["n_tokens"],
        "n_windows_candidate": m["n_windows_candidate"],
        "n_excluded": m["n_excluded"],
        "n_surviving": m["n_surviving"],
        "batch_size": m["batch_size"],
        "n_windows_trimmed": m["n_windows_trimmed"],
        "manifest_window_ids_sha256": manifest_ids_sha256,
        "manifest_window_ids_first_1000": [int(w) for w in m["window_ids"][:1000]],
        "manifest_window_ids_last_1000": [int(w) for w in m["window_ids"][-1000:]],
        "example_hash_sample": {
            "n_sampled": len(sample_ids),
            "window_ids": [int(w) for w in sample_ids[:len(sample_hashes)]],
            "sha256_per_window": sample_hashes,
        },
        "zero_intersection_asserts": {"range_level": "PASS", "example_id_level": "PASS"},
    }
    checked_write(out_path, receipt_out)
    print(f"EXP711_MANIFEST_EMIT_OK: {out_path}")
    print(json.dumps({
        "n_windows_candidate": m["n_windows_candidate"],
        "n_excluded": m["n_excluded"],
        "n_windows_trimmed": m["n_windows_trimmed"],
        "manifest_window_ids_sha256": manifest_ids_sha256,
    }, indent=2))


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest():
    import numpy as np

    rng = np.random.default_rng(20260711)
    n_tokens = 5000
    stream = rng.integers(8, 32000, size=n_tokens, dtype=np.uint16)
    seq, n_mtp = 16, 2
    bl = block_len_of(seq, n_mtp)
    assert bl == 19

    n_candidate = n_windows_of(n_tokens, seq, n_mtp)
    assert n_candidate == (n_tokens - bl) // seq + 1

    # Two synthetic reservation intervals: one that will exclude a clean
    # run of windows, one that straddles only a single window's edge.
    reserved = [
        {"reserved_start": 500, "reserved_end": 560},
        {"reserved_start": 4000, "reserved_end": 4001},
    ]
    batch_size = 8
    m = build_and_trim_manifest(n_tokens, seq, n_mtp, reserved, batch_size)

    assert_range_level_zero_intersection(m["window_ids"], m["_starts"],
                                          m["_ends"], reserved)
    assert_example_id_level_zero_intersection(m["window_ids"], m["excluded_ids"])

    # Exclusion correctness: brute-force re-derivation via plain Python,
    # a THIRD independent method, must match exactly.
    brute_excluded = set()
    for i in range(n_candidate):
        s, e = i * seq, i * seq + bl
        for r in reserved:
            if s < r["reserved_end"] and r["reserved_start"] < e:
                brute_excluded.add(i)
                break
    brute_kept = sorted(set(range(n_candidate)) - brute_excluded)
    n_trim = (len(brute_kept) // batch_size) * batch_size
    brute_trimmed = brute_kept[:n_trim]
    assert list(m["window_ids"]) == brute_trimmed, (
        "SELFTEST: manifest window ids diverge from brute-force exclusion "
        f"({len(m['window_ids'])} vs {len(brute_trimmed)} ids)")

    # Trim is an exact batch multiple.
    assert m["n_windows_trimmed"] % batch_size == 0
    assert m["n_windows_trimmed"] <= m["n_surviving"]

    # Canonical (ascending) order preserved.
    ids = list(m["window_ids"])
    assert ids == sorted(ids), "SELFTEST: window ids not in ascending order"

    # Launch assert: correct steps*batch passes, wrong value raises.
    steps = m["n_windows_trimmed"] // batch_size
    assert_launch(steps, batch_size, m["n_windows_trimmed"])
    try:
        assert_launch(steps + 1, batch_size, m["n_windows_trimmed"])
        raise AssertionError("SELFTEST: assert_launch failed to catch a mismatch")
    except ManifestError:
        pass

    # Wrap-refusal: in-range position ok, out-of-range raises (never wraps).
    last_pos = m["n_windows_trimmed"] - 1
    _ = window_id_at_position(m["window_ids"], last_pos)
    try:
        window_id_at_position(m["window_ids"], m["n_windows_trimmed"])
        raise AssertionError("SELFTEST: window_id_at_position failed to "
                              "refuse an out-of-range (wrap) position")
    except IndexError:
        pass

    # Full-example hashing: deterministic + reproducible; a straddling
    # window's neighbors on either side are correctly EXCLUDED (their
    # hashes never appear) while a window fully clear of any reservation
    # both sides is correctly KEPT.
    hashes1 = freeze_example_hashes(stream, m["window_ids"], bl, seq)
    hashes2 = freeze_example_hashes(stream, m["window_ids"], bl, seq)
    assert hashes1 == hashes2, "SELFTEST: example hashes not reproducible"
    assert len(set(hashes1)) == len(hashes1), (
        "SELFTEST: duplicate example hashes among kept windows (collision "
        "or logic bug -- windows should be content-distinct on random data)")

    # A window whose span exactly touches a reservation boundary must be
    # excluded (half-open interval boundary correctness): reservation
    # [500,560) -- the window covering token 500 exactly at its start
    # must be excluded; a window ending exactly at 500 must NOT be.
    touching_start = 500 // seq  # window whose span very likely covers 500
    span_s, span_e = touching_start * seq, touching_start * seq + bl
    if span_s < 560 and 500 < span_e:
        assert touching_start not in set(int(w) for w in m["window_ids"]), (
            "SELFTEST: boundary-touching window not excluded")

    # Zero-intersection assert actually catches a deliberately broken
    # manifest (mutate a kept id into an excluded one).
    if len(m["excluded_ids"]):
        broken_ids = np.array(m["window_ids"], copy=True)
        broken_ids[0] = m["excluded_ids"][0]
        try:
            assert_example_id_level_zero_intersection(broken_ids, m["excluded_ids"])
            raise AssertionError("SELFTEST: id-level assert failed to "
                                  "catch an injected excluded id")
        except ManifestError:
            pass
        try:
            assert_range_level_zero_intersection(broken_ids, m["_starts"],
                                                  m["_ends"], reserved)
            raise AssertionError("SELFTEST: range-level assert failed to "
                                  "catch an injected excluded id")
        except ManifestError:
            pass

    print("EXP711_MANIFEST_SELFTEST_PASS")
    print(json.dumps({
        "n_windows_candidate": m["n_windows_candidate"],
        "n_excluded": m["n_excluded"],
        "n_surviving": m["n_surviving"],
        "n_windows_trimmed": m["n_windows_trimmed"],
        "n_distinct_hashes": len(set(hashes1)),
    }, indent=2))


if __name__ == "__main__":
    main()
