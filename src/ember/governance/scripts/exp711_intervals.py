# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""exp711_intervals.py -- #711 ordering-screen CPU apparatus, component 1:
per-source global token intervals + scorer reservation intervals.

Construction order is AMENDMENT A7 (binding, #711 comment 4941032455):

  1. Per-source global token intervals derived FIRST from the frozen
     TOKEN-SHARDS-V0 receipt's per_source order (receipt-iteration order ==
     tiling order; verified by a sum-tiling assert) + boundary probes
     (detokenized +/-2KiB text at each claimed source boundary, banked to
     the apparatus receipt).
  2. Reservation intervals selected SECOND, before the packed-window
     manifest exists: per source, the FIRST contiguous token interval of
     that source's global range, sized per item 3's allocation rule.
  3. Allocation rule (replaces an equal 5-way split, which is impossible --
     the smallest source totals well under one nominal share): nominal
     share = 12.8 MiB of DETOKENIZED bytes/source (the unit the PPM scorer
     trains on). Any source whose total detokenized size < 2x its nominal
     share contributes exactly HALF its own bytes (the other half stays in
     training); the shortfall (nominal - actual small-source contribution)
     redistributes equally across the remaining (non-small) sources.

Real-corpus derivation reads ONLY the frozen receipt JSON (cheap) plus
bounded memmap slices of the token stream (boundary probes + reservation
sizing scans, via binary/exponential search -- never a full-source decode,
never the 13GB stream loaded whole).

Run (real corpus, writes the apparatus receipt):
    python src/ember/governance/scripts/exp711_intervals.py --emit
Selftest (small synthetic streams, no real corpus/cache required):
    python src/ember/governance/scripts/exp711_intervals.py --selftest
"""
import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "ember-restart-3b"))

from frozen_tokenizer_decoder import attach_frozen_bytelevel_decoder  # noqa: E402
from receipt_write import checked_write  # noqa: E402
import token_shards_v0 as tsv0  # noqa: E402
from a1_predicate_scan import load_stripped_tokenizer  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = ("sha256 over the exact detokenized UTF-8 byte sequence "
                   "produced by tokenizer.decode() over the reservation's "
                   "token id range, no normalization")

NOMINAL_SHARE_BYTES = int(12.8 * 1024 * 1024)  # 12.8 MiB detokenized/source
BOUNDARY_PROBE_HALF_BYTES = 2048               # +/-2KiB
BOUNDARY_PROBE_WINDOW_TOKENS = 8192            # bounded token window around a boundary
MIN_BYTES_PER_TOKEN = 1  # byte-level BPE floor: every token decodes to >=1
                          # raw byte by construction (base vocab = 256
                          # bytes; merges only concatenate existing byte
                          # sequences, never shrink below 1 byte/token) --
                          # this is a cheap, provable lower bound used to
                          # skip exact decoding of sources that obviously
                          # clear the 2x-nominal "small source" threshold.

TOKEN_SHARDS_RECEIPT_NAME = "token-shards-v0-20260611T170047Z.json"
TOKENIZER_FREEZE_RECEIPT_NAME = "tokenizer-freeze-20260611T154111Z.json"
SHARD_DIR_DEFAULT = os.path.join(os.path.dirname(REPO), "shards-v0")
MMAP_CACHE_DIR_DEFAULT = os.path.join(
    os.path.dirname(REPO), "wt-stab480", "models", "cbase-grow-rung",
    "rung2-stabilize-leg1", "shard-memmap-cache")
COMBINED_MANIFEST_SHA256_EXPECTED = (
    "aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a")

OUT_DIR = os.path.join(REPO, "receipts", "exp711-apparatus")


def _now_ts():
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# Step 1: per-source global token intervals + tiling assert
# ---------------------------------------------------------------------------

def derive_source_intervals(per_source: dict) -> list:
    """[{source, start, end, stream_tokens}], contiguous from 0, one
    interval per source, in per_source's own iteration order (== the
    frozen receipt's JSON key order -- Python 3.7+ dict/json.load preserve
    insertion order, so this IS "receipt order")."""
    intervals = []
    cursor = 0
    for name, rec in per_source.items():
        n = int(rec["stream_tokens"])
        intervals.append({"source": name, "start": cursor, "end": cursor + n,
                           "stream_tokens": n})
        cursor += n
    return intervals


def assert_tiling(intervals: list, n_tokens: int) -> None:
    """Exact tiling of [0, n_tokens): contiguous, no gaps, no overlaps,
    starts at 0, ends at n_tokens. Fail-closed (raises ValueError)."""
    if not intervals:
        raise ValueError("TILING: empty interval list")
    if intervals[0]["start"] != 0:
        raise ValueError("TILING: first interval does not start at 0 "
                          f"(got {intervals[0]['start']})")
    for i in range(1, len(intervals)):
        prev_end = intervals[i - 1]["end"]
        cur_start = intervals[i]["start"]
        if cur_start != prev_end:
            raise ValueError(f"TILING: gap/overlap between interval {i - 1} "
                              f"end={prev_end} and interval {i} "
                              f"start={cur_start}")
    total = sum(iv["end"] - iv["start"] for iv in intervals)
    if total != n_tokens:
        raise ValueError(f"TILING: sum of interval spans {total} != "
                          f"n_tokens {n_tokens}")
    if intervals[-1]["end"] != n_tokens:
        raise ValueError(f"TILING: last interval end {intervals[-1]['end']} "
                          f"!= n_tokens {n_tokens}")


# ---------------------------------------------------------------------------
# Boundary probes (disclosure only -- banked to the apparatus receipt)
# ---------------------------------------------------------------------------

def boundary_probe(decode_range_fn, boundary: int,
                    window_tokens: int = BOUNDARY_PROBE_WINDOW_TOKENS,
                    half_bytes: int = BOUNDARY_PROBE_HALF_BYTES) -> dict:
    """Detokenized +/-2KiB text around a claimed source boundary token
    index. Reads a small bounded token window on each side via
    decode_range_fn(start, end) -> bytes, then clips to the requested
    +/-2KiB. Base64-banked (the byte slice may cut a multi-byte UTF-8
    sequence at either edge; base64 tolerates that without re-encoding
    ambiguity)."""
    before = decode_range_fn(max(0, boundary - window_tokens), boundary)
    after = decode_range_fn(boundary, boundary + window_tokens)
    before_clip = before[-half_bytes:]
    after_clip = after[:half_bytes]
    return {
        "boundary_token": boundary,
        "before_bytes_len": len(before_clip),
        "after_bytes_len": len(after_clip),
        "before_bytes_b64": base64.b64encode(before_clip).decode("ascii"),
        "after_bytes_b64": base64.b64encode(after_clip).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# Step 2+3: reservation sizing (A7 item 3 allocation rule)
# ---------------------------------------------------------------------------

def find_reservation_boundary(decode_len_fn, span_tokens: int,
                               target_bytes: float,
                               start_probe: int = 1_000_000) -> int:
    """Smallest k in [0, span_tokens] such that
    len(decode(first k tokens)) >= target_bytes, found by exponential
    search for an upper bound then binary search -- O(log K) decode calls
    where K is the answer's order of magnitude, never proportional to the
    whole source (decode_len_fn(k) always decodes exactly k tokens from
    the source's start, so calls stay bounded near K).

    Relies on decode-prefix-monotonicity: ByteLevel BPE decode maps each
    token to a fixed byte sequence and concatenates them in order with no
    cross-token lookahead, so decode(ids[:k]) is always a byte-string
    prefix of decode(ids[:k+1]) -- verified directly by the selftest."""
    if span_tokens <= 0 or target_bytes <= 0:
        return 0
    k = min(start_probe, span_tokens)
    prev = 0
    while decode_len_fn(k) < target_bytes and k < span_tokens:
        prev = k
        k = min(k * 2, span_tokens)
    if decode_len_fn(k) < target_bytes:
        return span_tokens  # whole source falls short of target
    lo, hi = prev, k
    while lo < hi:
        mid = (lo + hi) // 2
        if decode_len_fn(mid) >= target_bytes:
            hi = mid
        else:
            lo = mid + 1
    return lo


def classify_and_size_reservations(intervals: list, decode_len_fn_factory,
                                    nominal_bytes: int = NOMINAL_SHARE_BYTES
                                    ) -> list:
    """A7 item 3. decode_len_fn_factory(source_start) -> a function
    k -> decoded-byte-length of the first k tokens of that source (bounded
    decode calls, no full-stream reads).

    Returns per-source reservation records in ORIGINAL interval order:
    {source, reserved_start, reserved_end, reservation_tokens,
     reservation_bytes_target, reservation_bytes_actual, is_small}.
    """
    small, large = [], []
    for iv in intervals:
        span = iv["end"] - iv["start"]
        lower_bound_bytes = span * MIN_BYTES_PER_TOKEN
        if lower_bound_bytes >= 2 * nominal_bytes:
            # Provably NOT small: the cheap 1-byte/token floor alone
            # already clears the 2x-nominal threshold -- skip exact decode.
            large.append(dict(iv, is_small=False, total_detok_bytes=None))
        else:
            decode_len = decode_len_fn_factory(iv["start"])
            total_bytes = decode_len(span)
            is_small = total_bytes < 2 * nominal_bytes
            rec = dict(iv, is_small=is_small, total_detok_bytes=total_bytes)
            (small if is_small else large).append(rec)

    if not large:
        raise ValueError("A7 item 3: every source classified small -- no "
                          "non-small source to redistribute the shortfall "
                          "to (allocation rule undefined for this corpus)")

    shortfall = 0.0
    for s in small:
        s["reservation_bytes_target"] = s["total_detok_bytes"] / 2.0
        shortfall += nominal_bytes - s["reservation_bytes_target"]
    per_large_bonus = shortfall / len(large)
    for lrec in large:
        lrec["reservation_bytes_target"] = nominal_bytes + per_large_bonus

    out = []
    for rec in small + large:
        decode_len = decode_len_fn_factory(rec["start"])
        span = rec["end"] - rec["start"]
        target = rec["reservation_bytes_target"]
        k = find_reservation_boundary(decode_len, span, target)
        actual_bytes = decode_len(k)
        out.append({
            "source": rec["source"],
            "reserved_start": rec["start"],
            "reserved_end": rec["start"] + k,
            "reservation_tokens": k,
            "reservation_bytes_target": target,
            "reservation_bytes_actual": actual_bytes,
            "is_small": rec["is_small"],
            "total_detok_bytes": rec.get("total_detok_bytes"),
        })

    order = {iv["source"]: i for i, iv in enumerate(intervals)}
    out.sort(key=lambda r: order[r["source"]])
    return out


def assert_zero_intersection_reservations(reservations: list) -> None:
    """Reservation intervals are each the FIRST contiguous slice of their
    own source's range -- assert no reservation interval overlaps another
    (they shouldn't by construction since sources themselves tile
    disjointly and each reservation is <= its own source's span)."""
    spans = sorted((r["reserved_start"], r["reserved_end"]) for r in reservations)
    for i in range(1, len(spans)):
        if spans[i][0] < spans[i - 1][1]:
            raise ValueError("RESERVATION_OVERLAP: reservation intervals "
                              f"{spans[i - 1]} and {spans[i]} overlap")


# ---------------------------------------------------------------------------
# Real-corpus wiring
# ---------------------------------------------------------------------------

def _load_token_shards_receipt():
    p = os.path.join(REPO, "receipts", TOKEN_SHARDS_RECEIPT_NAME)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _load_production_tokenizer(token_shards_receipt=None):
    """Load the frozen tokenizer via the CURRENT pin recorded in the
    token-shards-v0 receipt's own premises (premises.tokenizer_json), using
    the pre-existing, already-disclosed orphaned-merge workaround from
    src/ember/governance/scripts/a1_predicate_scan.py (ember #631): the on-disk tokenizer.json
    (post-58ddf8d-scrub, sha 6923a52...) has 21/31755 merge rules that
    produce a target string absent from its own vocab (proper-noun vocab
    entries the public-root consolidation scrub removed broke those merge
    rules) and the standard `tokenizers` library refuses to deserialize it
    as-is. load_stripped_tokenizer drops exactly those orphaned merge rules
    from an IN-MEMORY COPY (on-disk bytes never touched) and discloses the
    drop count. This is NOT a silent operationalization of the prereg's
    detok requirement: AMENDMENT A7 / prereg SS3 already specify a
    fail-closed path for any single window's detok not round-tripping
    exactly (NONCAUSAL_INVALID) -- a dropped merge can only make the
    stripped tokenizer's re-encode diverge from the original shard-
    generation ids MORE conservatively (splits stay one step finer), never
    silently accept a wrong answer; genuinely broken windows correctly
    fail the round-trip check downstream instead."""
    if token_shards_receipt is None:
        token_shards_receipt = _load_token_shards_receipt()
    tok_json = token_shards_receipt["premises"]["tokenizer_json"]
    tok_path = os.path.join(REPO, tok_json["path"])
    tk, actual_sha, n_dropped, n_merges_total = load_stripped_tokenizer(
        tok_path, expected_sha=tok_json["sha256"])
    decoder_wired = _wire_bytelevel_decoder(tk, tok_path)
    return tk, {
        "tokenizer_json_path": tok_json["path"],
        "tokenizer_json_sha256": actual_sha,
        "orphaned_merge_workaround": {
            "source": "src/ember/governance/scripts/a1_predicate_scan.py:load_stripped_tokenizer "
                       "(ember #631, pre-existing disclosed defect)",
            "n_dropped_orphan_merges": n_dropped,
            "n_merges_total": n_merges_total,
        },
        "decoder_wiring": decoder_wired,
    }


def _wire_bytelevel_decoder(tk, tok_path: str) -> dict:
    """The on-disk tokenizer.json has "decoder": null -- production never
    called .decode() (shards are produced by ENCODING text, never
    decoding ids), so a decoder was never wired. Its pre_tokenizer is
    ByteLevel (verified below from the same on-disk JSON, not assumed),
    and ByteLevel's decode is the canonical, parameter-free, LOSSLESS
    inverse of ByteLevel pre-tokenization -- attaching
    tokenizers.decoders.ByteLevel() in-memory is not a guess or a new
    encoding choice, it is completing the one decoder that matches the
    tokenizer's own documented encode-side transform. On-disk bytes
    untouched; this is the exact same class of in-memory-only fix as
    load_stripped_tokenizer's orphaned-merge drop."""
    with open(tok_path, "rb") as tokenizer_file:
        tokenizer_bytes = tokenizer_file.read()
    return attach_frozen_bytelevel_decoder(tk, tokenizer_bytes)


def _open_stream(shard_dir=SHARD_DIR_DEFAULT, cache_dir=MMAP_CACHE_DIR_DEFAULT,
                  expected_sha=COMBINED_MANIFEST_SHA256_EXPECTED):
    """Open the flat token stream read-only via the production
    PackedShardLoader memmap-cache path. Reuses the already-built cache
    (bin+manifest exist, sha matches) -- never writes there."""
    # issue2015 exact-local-import:scripts/timeshare_pretrain.py
    import importlib.util as _ember_d9c5c82c124e1dc8_importlib
    import sys as _ember_d9c5c82c124e1dc8_sys
    from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
    _ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parents[4].joinpath('scripts', 'timeshare_pretrain.py')
    if not _ember_d9c5c82c124e1dc8_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'scripts.timeshare_pretrain', 'timeshare_pretrain')
    _ember_d9c5c82c124e1dc8_existing = []
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
            _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
    if len(_ember_d9c5c82c124e1dc8_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/timeshare_pretrain.py')
    if _ember_d9c5c82c124e1dc8_existing:
        _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
        _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
        if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/timeshare_pretrain.py')
    else:
        _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
        if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
            if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
            _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
        try:
            _ember_d9c5c82c124e1dc8_spec.loader.exec_module(_ember_d9c5c82c124e1dc8_module)
        except BaseException:
            for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
                if _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias) is _ember_d9c5c82c124e1dc8_module:
                    _ember_d9c5c82c124e1dc8_sys.modules.pop(_ember_d9c5c82c124e1dc8_alias, None)
            raise
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
    PackedShardLoader = getattr(_ember_d9c5c82c124e1dc8_module, 'PackedShardLoader')
    # issue2015 exact-local-import-end:scripts/timeshare_pretrain.py
    loader = PackedShardLoader(shard_dir, seq=1024, n_mtp=2,
                                mmap_cache_dir=cache_dir,
                                expected_manifest_sha256=expected_sha)
    return loader.stream, loader


def _decode_range_factory(tokenizer, stream):
    def decode_range(start, end):
        ids = [int(t) for t in stream[start:end]]
        return tokenizer.decode(ids, skip_special_tokens=False).encode("utf-8")
    return decode_range


def build_apparatus(tokenizer, stream, per_source: dict,
                     total_stream_tokens: int,
                     nominal_bytes: int = NOMINAL_SHARE_BYTES) -> dict:
    """Full component-1 pipeline: intervals -> tiling assert -> boundary
    probes -> reservation sizing -> zero-intersection assert -> receipt
    body (caller wraps with ticket/ts/invariant/sha_convention)."""
    intervals = derive_source_intervals(per_source)
    assert_tiling(intervals, total_stream_tokens)

    decode_range = _decode_range_factory(tokenizer, stream)

    boundaries = [iv["start"] for iv in intervals[1:]]  # interior boundaries
    probes = [boundary_probe(decode_range, b) for b in boundaries]

    def decode_len_fn_factory(source_start):
        def decode_len(k):
            return len(decode_range(source_start, source_start + k))
        return decode_len

    reservations = classify_and_size_reservations(
        intervals, decode_len_fn_factory, nominal_bytes=nominal_bytes)
    assert_zero_intersection_reservations(reservations)

    for r in reservations:
        rbytes = decode_range(r["reserved_start"], r["reserved_end"])
        r["reservation_sha256"] = _sha256_bytes(rbytes)
        assert len(rbytes) == r["reservation_bytes_actual"], (
            "reservation byte-length mismatch on re-decode "
            f"({len(rbytes)} != {r['reservation_bytes_actual']})")

    return {
        "n_tokens": total_stream_tokens,
        "nominal_share_bytes": nominal_bytes,
        "source_intervals": intervals,
        "boundary_probes": probes,
        "reservations": reservations,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true",
                     help="run against the real corpus and write the "
                          "apparatus receipt")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shard-dir", default=SHARD_DIR_DEFAULT)
    ap.add_argument("--cache-dir", default=MMAP_CACHE_DIR_DEFAULT)
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if not args.emit:
        ap.error("pass --emit or --selftest")

    receipt = _load_token_shards_receipt()
    per_source = receipt["per_source"]
    total_stream_tokens = int(receipt["total_stream_tokens"])

    tokenizer, tok_meta = _load_production_tokenizer(receipt)
    stream, loader = _open_stream(args.shard_dir, args.cache_dir)
    if int(stream.shape[0]) != total_stream_tokens:
        raise ValueError(f"stream length {stream.shape[0]} != receipt "
                          f"total_stream_tokens {total_stream_tokens}")

    body = build_apparatus(tokenizer, stream, per_source, total_stream_tokens)

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(OUT_DIR, f"exp711-intervals-{ts}.json")
    receipt_out = {
        "ticket": "EXP711-INTERVALS",
        "ts": _now_ts(),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "refs": [711, 739],
        "token_shards_receipt": TOKEN_SHARDS_RECEIPT_NAME,
        "tokenizer": tok_meta,
        **body,
    }
    checked_write(out_path, receipt_out)
    print(f"EXP711_INTERVALS_EMIT_OK: {out_path}")
    print(json.dumps({
        "n_reservations": len(body["reservations"]),
        "reservation_bytes_actual": {
            r["source"]: r["reservation_bytes_actual"]
            for r in body["reservations"]},
    }, indent=2))


# ---------------------------------------------------------------------------
# Selftest -- small synthetic per-source streams via the REAL frozen
# tokenizer (fast: a few thousand tokens total), exercising both the
# small-source and large-source branches of the allocation rule.
# ---------------------------------------------------------------------------

def _selftest():
    tokenizer, tok_meta = _load_production_tokenizer()
    if tok_meta["orphaned_merge_workaround"]["n_dropped_orphan_merges"]:
        print("EXP711_INTERVALS_SELFTEST_NOTE: real tokenizer loaded via "
              "orphaned-merge workaround, "
              f"{tok_meta['orphaned_merge_workaround']['n_dropped_orphan_merges']} "
              "merges dropped in-memory (ember #631, pre-existing)")

    # Five synthetic "sources" of visibly different sizes so the tiny
    # nominal_bytes below classifies some small, some large.
    texts = {
        "src_big_a": ("The quick brown fox jumps over the lazy dog. " * 400),
        "src_big_b": ("import os\nimport sys\ndef f(x):\n    return x + 1\n" * 300),
        "src_big_c": ("Lorem ipsum dolor sit amet, consectetur adipiscing. " * 350),
        "src_small_a": "tiny source content, just a few words here.",
        "src_small_b": "x=1",
    }
    per_source = {}
    token_chunks = []
    cursor = 0
    for name, text in texts.items():
        ids = tokenizer.encode(text, add_special_tokens=False).ids
        per_source[name] = {"stream_tokens": len(ids)}
        token_chunks.append(ids)
        cursor += len(ids)
    total_stream_tokens = cursor

    class _FakeStream:
        """Minimal stand-in exposing the same __getitem__ slicing surface
        PackedShardLoader.stream (a numpy memmap) provides."""
        def __init__(self, chunks):
            flat = []
            for c in chunks:
                flat.extend(c)
            self._flat = flat

        def __getitem__(self, sl):
            return self._flat[sl]

        @property
        def shape(self):
            return (len(self._flat),)

    stream = _FakeStream(token_chunks)

    intervals = derive_source_intervals(per_source)
    assert_tiling(intervals, total_stream_tokens)
    assert [iv["source"] for iv in intervals] == list(texts.keys()), \
        "SELFTEST: interval order must match per_source (receipt) order"

    # Decode-prefix-monotonicity check (the assumption find_reservation_
    # boundary relies on): for each source, decoded-byte-length must be
    # non-decreasing as more tokens are included.
    decode_range = _decode_range_factory(tokenizer, stream)
    for iv in intervals:
        span = iv["end"] - iv["start"]
        prev_len = 0
        for k in range(0, span + 1, max(1, span // 10)):
            cur_len = len(decode_range(iv["start"], iv["start"] + k))
            assert cur_len >= prev_len, (
                f"SELFTEST: decode not prefix-monotonic for {iv['source']} "
                f"at k={k} ({cur_len} < {prev_len})")
            prev_len = cur_len

    # Tiny nominal share so src_small_a / src_small_b land in the
    # "< 2x nominal" branch while the src_big_* sources don't.
    tiny_nominal = 400  # bytes
    body = build_apparatus(tokenizer, stream, per_source, total_stream_tokens,
                            nominal_bytes=tiny_nominal)

    reservations_by_source = {r["source"]: r for r in body["reservations"]}
    n_small = sum(1 for r in body["reservations"] if r["is_small"])
    n_large = sum(1 for r in body["reservations"] if not r["is_small"])
    assert n_small >= 1, "SELFTEST: expected at least one small source"
    assert n_large >= 1, "SELFTEST: expected at least one large source"
    assert reservations_by_source["src_small_b"]["is_small"], (
        "SELFTEST: src_small_b (x=1, 3 tokens) must classify small")

    # Small-source contribution == exactly half its own total bytes.
    for r in body["reservations"]:
        if r["is_small"]:
            expected = r["total_detok_bytes"] / 2.0
            assert abs(r["reservation_bytes_target"] - expected) < 1e-9, (
                f"SELFTEST: small source {r['source']} target != half its "
                f"own bytes ({r['reservation_bytes_target']} vs {expected})")

    # Large sources get an equal share of the redistributed shortfall.
    large_targets = [r["reservation_bytes_target"]
                      for r in body["reservations"] if not r["is_small"]]
    assert max(large_targets) - min(large_targets) < 1e-6, (
        "SELFTEST: large-source reservation targets must be identical "
        "(equal shortfall redistribution)")

    # Reservation intervals are disjoint and each within its own source.
    assert_zero_intersection_reservations(body["reservations"])
    for r in body["reservations"]:
        src_iv = next(iv for iv in intervals if iv["source"] == r["source"])
        assert src_iv["start"] <= r["reserved_start"] < r["reserved_end"] <= src_iv["end"], (
            f"SELFTEST: reservation for {r['source']} escapes its source's "
            "own token range")

    # Reproducibility: re-running produces byte-identical reservation shas.
    body2 = build_apparatus(tokenizer, stream, per_source, total_stream_tokens,
                             nominal_bytes=tiny_nominal)
    sha1 = {r["source"]: r["reservation_sha256"] for r in body["reservations"]}
    sha2 = {r["source"]: r["reservation_sha256"] for r in body2["reservations"]}
    assert sha1 == sha2, "SELFTEST: reservation shas not reproducible across runs"

    # Boundary probes: 4 interior boundaries for 5 sources.
    assert len(body["boundary_probes"]) == 4, (
        f"SELFTEST: expected 4 boundary probes, got "
        f"{len(body['boundary_probes'])}")
    for p in body["boundary_probes"]:
        assert p["before_bytes_len"] <= BOUNDARY_PROBE_HALF_BYTES
        assert p["after_bytes_len"] <= BOUNDARY_PROBE_HALF_BYTES

    # Tiling-violation fixture: a gap must raise.
    bad_intervals = [dict(iv) for iv in intervals]
    bad_intervals[2]["start"] += 1  # introduce a gap
    try:
        assert_tiling(bad_intervals, total_stream_tokens)
        raise AssertionError("SELFTEST: assert_tiling failed to catch a gap")
    except ValueError as e:
        assert "TILING" in str(e)

    print("EXP711_INTERVALS_SELFTEST_PASS")
    print(json.dumps({
        "n_sources": len(intervals),
        "n_small": n_small,
        "n_large": n_large,
        "reservations": {r["source"]: {
            "is_small": r["is_small"],
            "reservation_tokens": r["reservation_tokens"],
            "reservation_bytes_actual": r["reservation_bytes_actual"],
        } for r in body["reservations"]},
    }, indent=2))


if __name__ == "__main__":
    main()
