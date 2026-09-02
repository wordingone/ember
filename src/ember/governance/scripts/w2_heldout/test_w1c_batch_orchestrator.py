# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_w1c_batch_orchestrator.py -- TDD for the #558 K-batch production
orchestrator: rebuild of the #553 harvest's build_k_certified_batches.py
skeleton, rewired onto the FROZEN two-part predicate (HeldoutCertifier +
BoilerplateBloomIndex, #506+#554) instead of the superseded corpus_bloom_index.

Written BEFORE src/ember/governance/scripts/w2_heldout/w1c_batch_orchestrator.py (TDD).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS_ROOT)

from w2_heldout.w1c_batch_orchestrator import (
    source_for_global_start,
    certification_windows,
    certify_row,
    build_k_batches,
    write_batch_receipts,
)
from w2_heldout.corpus_boilerplate_bloom import BoilerplateBloomIndex
from w2_heldout.certify_heldout_batch import HeldoutCertifier


# ---------------------------------------------------------------------------
# corpus_bloom_index BAN (frozen spec: "superseded corpus_bloom_index BANNED
# as a dependency") -- static import-graph guard, not just "I didn't type it".
# ---------------------------------------------------------------------------

def test_orchestrator_never_imports_banned_corpus_bloom_index():
    import ast
    import w2_heldout.w1c_batch_orchestrator as mod
    with open(mod.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=mod.__file__)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
            imported_modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    banned_hits = [m for m in imported_modules if "corpus_bloom_index" in m]
    assert not banned_hits, (
        f"BANNED dependency imported: {banned_hits} -- the #374 re-scope "
        "ruling retired corpus_bloom_index (original 6.98B-key design); "
        "#558's frozen spec bans it as a dependency.")


# ---------------------------------------------------------------------------
# source_for_global_start
# ---------------------------------------------------------------------------

class TestSourceForGlobalStart:
    BOUNDARIES = [
        {"source": "code_github_clean", "start": 0, "end": 1000},
        {"source": "fineweb_edu", "start": 1000, "end": 2000},
        {"source": "gutenberg_en", "start": 2000, "end": 2100},
    ]

    def test_start_of_range_inclusive(self):
        assert source_for_global_start(0, self.BOUNDARIES) == "code_github_clean"
        assert source_for_global_start(1000, self.BOUNDARIES) == "fineweb_edu"

    def test_end_of_range_exclusive(self):
        assert source_for_global_start(999, self.BOUNDARIES) == "code_github_clean"

    def test_middle_of_range(self):
        assert source_for_global_start(2050, self.BOUNDARIES) == "gutenberg_en"

    def test_out_of_all_ranges_returns_none(self):
        assert source_for_global_start(5000, self.BOUNDARIES) is None

    def test_row_spanning_two_sources_detected(self):
        # A row occupying [990, 1010) starts in code_github_clean but its
        # END crosses into fineweb_edu -- the caller must check BOTH the
        # row's start AND end fall in the same source's [start,end).
        row_start, row_end = 990, 1010
        src_start = source_for_global_start(row_start, self.BOUNDARIES)
        src_end = source_for_global_start(row_end - 1, self.BOUNDARIES)
        assert src_start == "code_github_clean"
        assert src_end == "fineweb_edu"
        assert src_start != src_end  # straddle -- caller must reject this row


# ---------------------------------------------------------------------------
# certification_windows -- sliding W-token windows, stride 1
# ---------------------------------------------------------------------------

class TestCertificationWindows:
    def test_count_matches_formula(self):
        row = list(range(20))
        windows = certification_windows(row, window_tokens=5)
        assert len(windows) == 20 - 5 + 1

    def test_keys_are_u2_little_endian_bytes(self):
        row = [10, 11, 12, 13]
        windows = certification_windows(row, window_tokens=4)
        assert len(windows) == 1
        assert windows[0] == np.asarray([10, 11, 12, 13], dtype="<u2").tobytes()

    def test_stride_one_overlap(self):
        row = [1, 2, 3, 4, 5]
        windows = certification_windows(row, window_tokens=3)
        expected = [
            np.asarray([1, 2, 3], dtype="<u2").tobytes(),
            np.asarray([2, 3, 4], dtype="<u2").tobytes(),
            np.asarray([3, 4, 5], dtype="<u2").tobytes(),
        ]
        assert windows == expected

    def test_row_shorter_than_window_yields_no_windows(self):
        row = [1, 2]
        windows = certification_windows(row, window_tokens=5)
        assert windows == []


# ---------------------------------------------------------------------------
# certify_row -- DROP-ONLY: any uncertified sub-window drops the WHOLE row
# (frozen predicate v2.1 point 4: "the ROW containing it in scored position
# is DROPPED as unusable")
# ---------------------------------------------------------------------------

def _make_certifier(boilerplate_keys: dict[str, list[bytes]] | None = None,
                    cap_saturated_keys: dict[str, list[bytes]] | None = None):
    index = BoilerplateBloomIndex.build_from_keys(
        boilerplate_keys or {"src_a": []},
        cap_saturated_keys or {},
        target_fp_rate=0.01,
    )
    return HeldoutCertifier(index, cap_saturated_per_source=cap_saturated_keys or {})


class TestCertifyRow:
    def test_clean_row_certified(self):
        certifier = _make_certifier()
        row = [1, 2, 3, 4, 5, 6]
        result = certify_row(row, "src_a", {"src_a"}, certifier, window_tokens=4)
        assert result["certified"] is True
        assert result["n_sub_windows"] == 6 - 4 + 1

    def test_boilerplate_sub_window_drops_whole_row(self):
        boilerplate_key = np.asarray([2, 3, 4, 5], dtype="<u2").tobytes()
        certifier = _make_certifier(boilerplate_keys={"src_a": [boilerplate_key]})
        row = [1, 2, 3, 4, 5, 6]  # sub-window [2,3,4,5] is boilerplate
        result = certify_row(row, "src_a", {"src_a"}, certifier, window_tokens=4)
        assert result["certified"] is False
        assert result["reason"] in ("bloom_positive", "bloom_positive_confirmed")

    def test_source_contamination_drops_row(self):
        certifier = _make_certifier()
        row = [1, 2, 3, 4]
        result = certify_row(row, "src_a", {"src_a", "src_b"}, certifier, window_tokens=4)
        assert result["certified"] is False
        assert result["reason"] == "source_contamination"

    def test_first_failing_sub_window_short_circuits(self):
        # Two boilerplate sub-windows present; certify_row must report on
        # the FIRST failure and not need to scan every sub-window.
        bp1 = np.asarray([1, 2, 3, 4], dtype="<u2").tobytes()
        certifier = _make_certifier(boilerplate_keys={"src_a": [bp1]})
        row = [1, 2, 3, 4, 9, 9, 9, 9]
        result = certify_row(row, "src_a", {"src_a"}, certifier, window_tokens=4)
        assert result["certified"] is False
        assert result["failed_at_sub_window"] == 0


# ---------------------------------------------------------------------------
# build_k_batches -- kill criteria: report achieved K honestly, never loosen
# certification to hit K.
# ---------------------------------------------------------------------------

class TestBuildKBatchesKillCriteria:
    def test_pool_exhaustion_reports_achieved_k_not_target_k(self, tmp_path):
        # Tiny synthetic single-shard corpus: only enough clean windows for
        # 1 full batch of batch_size=2, never 3.
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()
        # 40 tokens, all distinct low integers -- no boilerplate possible.
        tokens = np.arange(40, dtype="<u2")
        (shard_dir / "shard-00.bin").write_bytes(tokens.tobytes())

        boundaries = [{"source": "src_a", "start": 0, "end": 40}]
        certifier = _make_certifier()

        result = build_k_batches(
            shard_dir=str(shard_dir), boundaries=boundaries, certifier=certifier,
            seq=4, n_mtp=0, batch_size=2, ceiling_steps=0, train_batch=1,
            k=3, window_tokens=3, source_order=["src_a"],
        )
        clean = [b for b in result["batches"] if b["status"] == "CLEAN"]
        assert result["achieved_k"] == len(clean)
        assert result["achieved_k"] < 3  # never fabricates the target K
        assert result["target_k"] == 3

    def test_disjointness_uses_global_not_source_local_window_indices(self, tmp_path):
        # Regression: a source that starts LATE in the global stream (e.g.
        # gutenberg_en, positioned after ~4.2B tokens of earlier sources)
        # must not have its held-out pool computed as if the source's own
        # LOCAL window count were the global index space -- that bug tripped
        # W1_LIVE_HELDOUT_NOT_DISJOINT on real-corpus data that was in fact
        # trivially disjoint (discovered building #558's AC1 real-corpus run).
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()
        # Simulate a source that starts far past the global training ceiling
        # by making the FIRST 100 windows (400 tokens) belong to an earlier,
        # irrelevant source, and the actual test source start at window 100.
        n_tokens = 200
        tokens = np.arange(n_tokens, dtype="<u2")
        (shard_dir / "shard-00.bin").write_bytes(tokens.tobytes())

        # seq=4 -> 50 windows total; source starts at global window 25
        # (global token offset 100), ends at window 50 (token 200).
        boundaries = [{"source": "src_late", "start": 100, "end": 200}]
        certifier = _make_certifier()

        # ceiling_steps*train_batch = 10*1 = 10 -- far below this source's
        # global window range [25, 50), so it MUST be reachable/disjoint.
        result = build_k_batches(
            shard_dir=str(shard_dir), boundaries=boundaries, certifier=certifier,
            seq=4, n_mtp=0, batch_size=2, ceiling_steps=10, train_batch=1,
            k=1, window_tokens=3, source_order=["src_late"],
        )
        assert result["achieved_k"] >= 1, (
            "a source positioned entirely after the global training ceiling "
            "must certify batches, not spuriously fail disjointness")

    def test_never_loosens_certification_to_reach_k(self, tmp_path):
        # Every window in this tiny corpus IS boilerplate -- 0 batches should
        # ever certify, regardless of target K.
        shard_dir = tmp_path / "shards"
        shard_dir.mkdir()
        tokens = np.array([1, 2, 3, 4] * 10, dtype="<u2")  # repeats
        (shard_dir / "shard-00.bin").write_bytes(tokens.tobytes())
        boundaries = [{"source": "src_a", "start": 0, "end": 40}]

        bp_key = np.asarray([1, 2, 3], dtype="<u2").tobytes()
        certifier = _make_certifier(boilerplate_keys={"src_a": [bp_key]})

        result = build_k_batches(
            shard_dir=str(shard_dir), boundaries=boundaries, certifier=certifier,
            seq=4, n_mtp=0, batch_size=2, ceiling_steps=0, train_batch=1,
            k=2, window_tokens=3, source_order=["src_a"],
        )
        assert result["achieved_k"] == 0


# ---------------------------------------------------------------------------
# Receipt schema
# ---------------------------------------------------------------------------

def test_receipt_schema_and_fields(tmp_path):
    import json
    result = {
        "target_k": 2, "achieved_k": 1,
        "batches": [{
            "batch_no": 1, "status": "CLEAN", "source": "src_a",
            "batch_sha256": "deadbeef", "seq": 4, "n_mtp": 0, "batch_size": 2,
            "selected_window_indices": [0, 1],
            "certification_verdicts": [{"certified": True, "reason": "certified"}] * 2,
        }],
        "source_order": ["src_a"],
        "window_tokens": 50,
    }
    paths = write_batch_receipts(result, receipt_dir=str(tmp_path), shard_dir="some/local/shard/dir")
    assert len(paths) == 1
    with open(paths[0], "r", encoding="utf-8") as f:
        receipt = json.load(f)
    assert receipt["schema"] == "w2-k-certified-batches/v1"
    assert receipt["achieved_k"] == 1
    assert receipt["target_k"] == 2
    assert "certification_verdicts" in receipt
    assert receipt["shard_dir"] == "<ROOT>"  # redaction law: never a real local path
