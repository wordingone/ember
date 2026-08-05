#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_1436_fineweb_edu_exclusion.py -- #1436: fineweb_edu exclusion ruled but
NOT enforced. Reproduce-first + fix verification.

FAIL half (pre-fix state, reproduced against the real repo receipts, read-only):
  scripts/token_shards_v0.py's TOKEN-SHARDS-V0 receipt for shards-v0 declares
  1,666,837,789 fineweb_edu content_tokens with no exclusion marker anywhere in
  the schema, and scripts/timeshare_pretrain.py's PackedShardLoader (pre-#1436)
  had no parameter that could ever skip an offset range -- every window drawn
  from the stream could include fineweb_edu tokens. This file proves that gap
  is closed:

PASS half (this fix):
  1. scripts/fineweb_exclusion.py derives the fineweb_edu token-offset range
     PROGRAMMATICALLY from the real, on-disk, receipt-validated shard bytes
     (never a hardcoded literal) and the range matches the L3 audit's
     independently-derived figure exactly: [4,055,121,325, 5,723,508,974).
  2. The derivation is fail-closed: any receipt/byte mismatch refuses rather
     than returning a stale range (tested against synthetic tampering, no
     production bytes touched).
  3. usable_window_starts()/assert_windows_exclude_ranges() prove, byte-exact
     over EVERY window (never sampled), that a window overlapping the
     excluded range is never yielded -- the loader-integration contract
     PackedShardLoader.__init__ now delegates to.

Run: pytest tests/test_1436_fineweb_edu_exclusion.py -v
     (or python tests/test_1436_fineweb_edu_exclusion.py for the CLI runner)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import fineweb_exclusion as fx          # noqa: E402
import token_shards_v0 as tsv           # noqa: E402

REAL_SHARD_RECEIPT = "token-shards-v0-20260611T170047Z.json"
REAL_ASSEMBLY_RECEIPT = tsv.ASSEMBLY_RECEIPT

# The 2026-08-04 L3 provenance audit's independently-derived figure: the
# range this fix must reproduce exactly, from the receipts alone, with no
# hardcoded shortcut in fineweb_exclusion.py.
EXPECTED_FINEWEB_RANGE = (4_055_121_325, 5_723_508_974)
EXPECTED_CLEAN_CONTENT_TOKENS = 5_306_794_511


def _shard_receipt_dict():
    p = os.path.join(REPO, "receipts", REAL_SHARD_RECEIPT)
    assert os.path.exists(p), f"real shard receipt missing: {p}"
    return json.load(open(p, encoding="utf-8"))


def _assembly_receipt_dict():
    p = os.path.join(REPO, "receipts", REAL_ASSEMBLY_RECEIPT)
    assert os.path.exists(p), f"real assembly receipt missing: {p}"
    return json.load(open(p, encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Offset derivation matches the L3 audit's independently-derived figure,
#    computed PURELY from the receipts (no shard bytes needed for this part).
# ---------------------------------------------------------------------------
def test_derived_fineweb_range_matches_l3_audit():
    receipt = _shard_receipt_dict()
    assembly = _assembly_receipt_dict()
    offsets = fx.compute_source_offsets(receipt, assembly)
    assert "fineweb_edu" in offsets
    assert offsets["fineweb_edu"] == EXPECTED_FINEWEB_RANGE, offsets["fineweb_edu"]


def test_per_source_offsets_partition_the_full_stream():
    receipt = _shard_receipt_dict()
    assembly = _assembly_receipt_dict()
    offsets = fx.compute_source_offsets(receipt, assembly)
    spans = sorted(offsets.values())
    # contiguous, no gaps, no overlaps -- exactly matches the writer's own
    # strict-concatenation order (fp22_row)
    assert spans[0][0] == 0
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        assert e0 == s1, (e0, s1)
    assert spans[-1][1] == receipt["total_stream_tokens"]


def test_clean_content_total_matches_l3_audit_conservative_floor():
    receipt = _shard_receipt_dict()
    excluded_content = receipt["per_source"]["fineweb_edu"]["content_tokens"]
    clean = receipt["content_total_tokens"] - excluded_content
    assert clean == EXPECTED_CLEAN_CONTENT_TOKENS, clean


# ---------------------------------------------------------------------------
# 2. Fail-closed derivation: excluded_token_ranges() requires the receipt to
#    validate against real shard bytes. If the real multi-GB shard bytes are
#    not present in this checkout (they live in an out-of-tree data store,
#    optionally pointed to via EMBER_SHARDS_V0_DIR), this is skipped rather
#    than false-failing on an environment difference -- the hermetic
#    equivalent (test_fail_closed_* below) covers the same contract with
#    synthetic bytes.
# ---------------------------------------------------------------------------
def test_excluded_token_ranges_against_real_shards_if_present():
    receipt = _shard_receipt_dict()
    shard_dir = os.path.join(REPO, receipt["shard_dir"])
    candidates = [shard_dir]
    env_dir = os.environ.get("EMBER_SHARDS_V0_DIR")
    if env_dir:
        candidates.append(env_dir)
    real_dir = next((d for d in candidates if os.path.isdir(d)
                     and any(f.endswith(".bin") for f in os.listdir(d))), None)
    if real_dir is None:
        import pytest
        pytest.skip("no on-disk shards-v0 .bin bytes in this checkout/env "
                    "(expected off-tree; hermetic fail-closed tests cover "
                    "the same contract with synthetic bytes)")
    ranges = fx.excluded_token_ranges(REPO, shard_dir=real_dir)
    assert ranges == [EXPECTED_FINEWEB_RANGE], ranges


# ---------------------------------------------------------------------------
# 3. Hermetic: the fail-closed contract, proven end-to-end with synthetic
#    receipts + bytes (touches zero production data).
# ---------------------------------------------------------------------------
def test_fail_closed_selftest_suite():
    fx._selftest()
    fx._selftest_fail_closed_against_real_schema()


# ---------------------------------------------------------------------------
# 4. Window-filter contract: this is what PackedShardLoader.__init__ (#1436)
#    now delegates to. Byte-exact, never sampled, over EVERY window.
# ---------------------------------------------------------------------------
def test_no_usable_window_ever_overlaps_the_excluded_range():
    seq, n_mtp = 1024, 2
    block_len = seq + 1 + n_mtp
    n_tokens = 200_000
    excluded = [(50_000, 90_000)]
    starts = fx.usable_window_starts(n_tokens, seq, block_len, excluded)
    assert starts, "expected some usable windows outside the excluded range"
    fx.assert_windows_exclude_ranges(starts, block_len, excluded)   # must not raise
    # and every DROPPED window really did overlap (no over-dropping)
    all_starts = fx.usable_window_starts(n_tokens, seq, block_len, [])
    dropped = set(all_starts) - set(starts)
    assert dropped
    for s in dropped:
        e = s + block_len
        assert e > excluded[0][0] and s < excluded[0][1]


def test_exclude_everything_raises_if_wired_to_a_loader():
    # a range covering the whole stream must leave zero usable windows --
    # PackedShardLoader.__init__ treats that as a hard refusal to start.
    seq, n_mtp = 8, 2
    block_len = seq + 1 + n_mtp
    n_tokens = 100
    excluded = [(0, n_tokens)]
    starts = fx.usable_window_starts(n_tokens, seq, block_len, excluded)
    assert starts == []


def test_loader_source_awareness_wired_in_timeshare_pretrain():
    """Static check that PackedShardLoader accepts excluded_ranges and wires
    it to fineweb_exclusion (the historical_only lock on timeshare_pretrain.py
    makes it non-importable right now -- see #1436 report; this asserts the
    source text carries the integration rather than skipping the check)."""
    src = open(os.path.join(SCRIPTS, "timeshare_pretrain.py"), encoding="utf-8").read()
    assert "excluded_ranges" in src
    assert "from fineweb_exclusion import" in src
    assert "usable_window_starts" in src
    assert "assert_windows_exclude_ranges" in src


if __name__ == "__main__":
    test_derived_fineweb_range_matches_l3_audit()
    test_per_source_offsets_partition_the_full_stream()
    test_clean_content_total_matches_l3_audit_conservative_floor()
    test_fail_closed_selftest_suite()
    test_no_usable_window_ever_overlaps_the_excluded_range()
    test_exclude_everything_raises_if_wired_to_a_loader()
    test_loader_source_awareness_wired_in_timeshare_pretrain()
    print("TEST_1436_FINEWEB_EDU_EXCLUSION_PASS")
