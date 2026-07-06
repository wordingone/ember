"""test_classify_dict_lookup_equivalence.py -- issue #193 machinery fix.

The match-classification inner loop in both build_decontam_batch.py and
build_decontam_batch_mp.py used to re-scan every candidate row per confirmed
match (_row_contains_window: O(row_len) per (match, candidate) pair, so
O(M x C x L) overall). At the mid-corpus re-draw's scale (M ~= 5.7M matches,
C=32 candidates) that loop ran single-core for hours. The fix precomputes,
once per _classify_once call, a dict of every contiguous window-length tuple
each candidate row contains -> the candidate indices whose row contains it
(_build_candidate_window_index), turning the per-match membership check into
an O(1) average-case dict lookup: O(M + C x L) overall.

This suite proves the rewrite is behavior-preserving by comparing it, on one
fixed synthetic fixture, against a literal copy of the PRE-FIX attribution
loop (the code this replaced, reconstructed from the pre-edit diff -- the
only thing it no longer does is re-scan rows per match). The two untouched
helper primitives the pre-fix loop used (_row_contains_window,
_match_global_start) are reused directly from each module since neither was
touched by the fix; only the changed attribution loop itself is reproduced
here as the "old" reference.

The fixture is built to exercise every edge case the dict-lookup path must
treat identically to the row-rescan path:
  - a self-match at each candidate's own reflection (exact global-start
    match, so both the mp module's overlap-based is_self and the serial
    module's exact-start is_self agree),
  - a genuine external duplicate of the SAME window content shared by TWO
    different candidate rows (row0 and row2 both contain [1,2,3,4]) -- the
    multi-index dict-bucket case,
  - a near-miss window ([999,999,999,999]) absent from every candidate row
    entirely (dict lookup must return nothing, exactly like the row-rescan
    finding no containment anywhere),
  - two candidates (row1, row4) referenced by zero confirmed matches at all.

contamination_recheck/_serial_contamination_recheck is monkeypatched to
return this fixed match list directly (use_mp=False / single-implementation
serial path) so no real shard files or corpus scan are needed -- this
targets the classification/attribution logic in isolation, which is the
only code the deviation changed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_decontam_batch as serial_mod  # noqa: E402
import build_decontam_batch_mp as mp_mod  # noqa: E402

WINDOW = 4


def _build_fixture():
    row0 = [1, 2, 3, 4, 5, 6, 7, 8]           # global_start 0
    row1 = [9, 10, 11, 12, 13, 14, 15, 16]    # global_start 1000 -- never matched
    row2 = [1, 2, 3, 4, 20, 21, 22, 23]       # global_start 8 -- shares [1,2,3,4] w/ row0
    row3 = [30, 31, 32, 33, 34, 35, 36, 37]   # global_start 16 -- self- + external match
    row4 = [40, 41, 42, 43, 44, 45, 46, 47]   # global_start 24 -- genuinely clean

    candidate_rows = [row0, row1, row2, row3, row4]
    candidate_positions = [
        {"shard": "synthetic-00000.bin", "offset": 0, "global_start": 0},
        {"shard": "synthetic-00000.bin", "offset": 1000, "global_start": 1000},
        {"shard": "synthetic-00000.bin", "offset": 8, "global_start": 8},
        {"shard": "synthetic-00000.bin", "offset": 16, "global_start": 16},
        {"shard": "synthetic-00000.bin", "offset": 24, "global_start": 24},
    ]
    files = [{"name": "synthetic-00000.bin", "size_bytes": 2016, "n_tokens": 1008}]
    cum = [0, 1008]

    confirmed_matches = [
        # candidate0's own reflection -- self for idx0
        {"shard": "synthetic-00000.bin", "offset": 0, "window": [1, 2, 3, 4]},
        # candidate2's own reflection -- self for idx2
        {"shard": "synthetic-00000.bin", "offset": 8, "window": [1, 2, 3, 4]},
        # genuine external duplicate of the SAME content, far from both
        # idx0's and idx2's own positions -- both rows contain [1,2,3,4], so
        # this one confirmed match attributes to BOTH (multi-bucket case)
        {"shard": "synthetic-00000.bin", "offset": 500, "window": [1, 2, 3, 4]},
        # candidate3's own reflection -- self for idx3
        {"shard": "synthetic-00000.bin", "offset": 16, "window": [30, 31, 32, 33]},
        # external match against candidate3's window [34,35,36,37]
        {"shard": "synthetic-00000.bin", "offset": 600, "window": [34, 35, 36, 37]},
        # near-miss: content absent from every candidate row entirely
        {"shard": "synthetic-00000.bin", "offset": 700, "window": [999, 999, 999, 999]},
    ]
    block_len = 8
    return candidate_rows, candidate_positions, files, cum, confirmed_matches, block_len


def _old_attribute_matches(mod, candidate_rows, candidate_positions, confirmed_matches,
                            *, window, name_to_index, cum, use_overlap, block_len=None):
    """Literal copy of the pre-#193-fix attribution loop (the code the dict
    lookup replaced), using only the two helper primitives (_row_contains_window,
    _match_global_start) that the fix left untouched. `use_overlap` selects
    which module's is_self shape to reproduce: the mp module's overlap-based
    check (when it was given a block_len) or the exact-start check (the
    serial module always, and the mp module when block_len is None)."""
    non_self_matches_by_candidate = [[] for _ in candidate_rows]
    self_matches_excluded = 0

    for m in confirmed_matches:
        window_tuple = tuple(m["window"])
        if name_to_index is not None and cum is not None:
            match_global_start = mod._match_global_start(m, name_to_index, cum, window)
        else:
            match_global_start = None
        for idx, row in enumerate(candidate_rows):
            if not mod._row_contains_window(row, window_tuple, window):
                continue
            pos = candidate_positions[idx]
            if use_overlap:
                candidate_end = pos["global_start"] + block_len
                is_self = (match_global_start is not None
                           and pos["global_start"] <= match_global_start
                           and match_global_start + window <= candidate_end)
            else:
                is_self = (match_global_start is not None
                           and match_global_start == pos["global_start"])
            if is_self:
                self_matches_excluded += 1
            else:
                non_self_matches_by_candidate[idx].append(m)

    clean_idx = [i for i, ms in enumerate(non_self_matches_by_candidate) if not ms]
    contaminated_idx = [i for i, ms in enumerate(non_self_matches_by_candidate) if ms]
    return {
        "clean_idx": clean_idx,
        "contaminated_idx": contaminated_idx,
        "self_matches_excluded": self_matches_excluded,
        "non_self_matches_by_candidate": non_self_matches_by_candidate,
    }


def _fake_raw(confirmed_matches):
    return {
        "method": "synthetic-fixture (test double, no real corpus scan)",
        "shards_scanned": 1,
        "windows_hashed": 0,
        "confirmed_matches": confirmed_matches,
        "hash_collisions_ruled_out": 0,
        "verdict": "CONTAMINATED" if confirmed_matches else "CLEAN",
    }


def test_serial_dict_lookup_matches_old_row_rescan_with_files_cum(monkeypatch):
    candidate_rows, candidate_positions, files, cum, confirmed_matches, block_len = _build_fixture()
    monkeypatch.setattr(serial_mod, "contamination_recheck",
                         lambda *a, **kw: _fake_raw(confirmed_matches))

    new_result = serial_mod._classify_once(
        candidate_rows, candidate_positions, "unused-shard-dir",
        window=WINDOW, roll_base=257, files=files, cum=cum)

    name_to_index = {f["name"]: i for i, f in enumerate(files)}
    old_result = _old_attribute_matches(
        serial_mod, candidate_rows, candidate_positions, confirmed_matches,
        window=WINDOW, name_to_index=name_to_index, cum=cum, use_overlap=False)

    print(f"[EQUIV-SERIAL] new: clean={new_result['clean_idx']} "
          f"contaminated={new_result['contaminated_idx']} "
          f"self_excluded={new_result['self_matches_excluded']}")
    print(f"[EQUIV-SERIAL] old: clean={old_result['clean_idx']} "
          f"contaminated={old_result['contaminated_idx']} "
          f"self_excluded={old_result['self_matches_excluded']}")

    assert new_result["clean_idx"] == old_result["clean_idx"]
    assert new_result["contaminated_idx"] == old_result["contaminated_idx"]
    assert new_result["self_matches_excluded"] == old_result["self_matches_excluded"]
    assert new_result["non_self_matches_by_candidate"] == old_result["non_self_matches_by_candidate"]
    # Sanity: the fixture actually exercises the multi-bucket + self + near-miss
    # + never-referenced cases it claims to (not vacuously trivial).
    assert new_result["clean_idx"] == [1, 4]
    assert new_result["contaminated_idx"] == [0, 2, 3]
    assert new_result["self_matches_excluded"] == 3


def test_serial_dict_lookup_matches_old_row_rescan_without_files_cum(monkeypatch):
    """Safe-default path (files/cum omitted -> boundary/global resolution
    unavailable -> match_global_start always None -> never self)."""
    candidate_rows, candidate_positions, files, cum, confirmed_matches, block_len = _build_fixture()
    monkeypatch.setattr(serial_mod, "contamination_recheck",
                         lambda *a, **kw: _fake_raw(confirmed_matches))

    new_result = serial_mod._classify_once(
        candidate_rows, candidate_positions, "unused-shard-dir",
        window=WINDOW, roll_base=257, files=None, cum=None)

    old_result = _old_attribute_matches(
        serial_mod, candidate_rows, candidate_positions, confirmed_matches,
        window=WINDOW, name_to_index=None, cum=None, use_overlap=False)

    assert new_result["clean_idx"] == old_result["clean_idx"]
    assert new_result["contaminated_idx"] == old_result["contaminated_idx"]
    assert new_result["self_matches_excluded"] == old_result["self_matches_excluded"]
    assert new_result["non_self_matches_by_candidate"] == old_result["non_self_matches_by_candidate"]


def test_mp_dict_lookup_matches_old_row_rescan_with_files_cum_and_block_len(monkeypatch):
    candidate_rows, candidate_positions, files, cum, confirmed_matches, block_len = _build_fixture()
    monkeypatch.setattr(mp_mod, "contamination_recheck",
                         lambda *a, **kw: _fake_raw(confirmed_matches))

    new_result = mp_mod._classify_once(
        candidate_rows, candidate_positions, "unused-shard-dir",
        window=WINDOW, roll_base=257, files=files, cum=cum,
        use_mp=False, block_len=block_len)

    name_to_index = {f["name"]: i for i, f in enumerate(files)}
    old_result = _old_attribute_matches(
        mp_mod, candidate_rows, candidate_positions, confirmed_matches,
        window=WINDOW, name_to_index=name_to_index, cum=cum, use_overlap=True, block_len=block_len)

    print(f"[EQUIV-MP] new: clean={new_result['clean_idx']} "
          f"contaminated={new_result['contaminated_idx']} "
          f"self_excluded={new_result['self_matches_excluded']}")
    print(f"[EQUIV-MP] old: clean={old_result['clean_idx']} "
          f"contaminated={old_result['contaminated_idx']} "
          f"self_excluded={old_result['self_matches_excluded']}")

    assert new_result["clean_idx"] == old_result["clean_idx"]
    assert new_result["contaminated_idx"] == old_result["contaminated_idx"]
    assert new_result["self_matches_excluded"] == old_result["self_matches_excluded"]
    assert new_result["non_self_matches_by_candidate"] == old_result["non_self_matches_by_candidate"]
    assert new_result["clean_idx"] == [1, 4]
    assert new_result["contaminated_idx"] == [0, 2, 3]
    assert new_result["self_matches_excluded"] == 3


def test_mp_dict_lookup_matches_old_row_rescan_without_block_len(monkeypatch):
    """block_len=None -> mp module falls back to the exact-start is_self
    check (same shape as the serial module's only check)."""
    candidate_rows, candidate_positions, files, cum, confirmed_matches, block_len = _build_fixture()
    monkeypatch.setattr(mp_mod, "contamination_recheck",
                         lambda *a, **kw: _fake_raw(confirmed_matches))

    new_result = mp_mod._classify_once(
        candidate_rows, candidate_positions, "unused-shard-dir",
        window=WINDOW, roll_base=257, files=files, cum=cum,
        use_mp=False, block_len=None)

    name_to_index = {f["name"]: i for i, f in enumerate(files)}
    old_result = _old_attribute_matches(
        mp_mod, candidate_rows, candidate_positions, confirmed_matches,
        window=WINDOW, name_to_index=name_to_index, cum=cum, use_overlap=False)

    assert new_result["clean_idx"] == old_result["clean_idx"]
    assert new_result["contaminated_idx"] == old_result["contaminated_idx"]
    assert new_result["self_matches_excluded"] == old_result["self_matches_excluded"]
    assert new_result["non_self_matches_by_candidate"] == old_result["non_self_matches_by_candidate"]
