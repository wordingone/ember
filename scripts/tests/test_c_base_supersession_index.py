#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression test for the C-BASE harness-timeout cure.

test_c_base.py's `main()` scans the full receipts/ corpus twice, and (prior
to this cure) called `_is_superseded(rp, all_receipts)` once per receipt in
each scan -- and that function re-read and re-parsed EVERY receipt file's
JSON on EVERY call, searching for a VOID receipt naming the target. That is
O(N) work per call times O(N) calls times 2 loops = O(N^2) total JSON
parses. On this repo's real receipts/ corpus (1097 files at cure time),
profiling extrapolated this to ~435s for ONE of the two loops alone --
comfortably explaining the observed 600s harness-timeout ("HARNESS TIMEOUT:
test_c_base.py exceeded 600s -- probe did not complete", board verdict
UNEVALUABLE).

The cure introduces `SupersessionIndex`, which builds the VOID-receipt
supersession index ONCE via a single O(N) pass, then answers each
`is_superseded()` query in O(1) (filename) or O(1)-amortized (hash). This
is an engineering fix to *how* the check is computed, not a narrowing of
*what* it checks: every receipt still has its supersession status resolved
against the exact same universe of VOID receipts and the exact same
filename/sha256 matching rules as before.

This test proves two things:
  1. Correctness parity -- `SupersessionIndex.is_superseded()` (and the
     back-compat `_is_superseded()` wrapper) agree with each other, and
     with hand-computed expectations, on filename-based supersession,
     sha256-based supersession, and non-supersession, across VOID receipts
     that use either the dict-list or the string-list `supersedes` shape.
  2. The performance fix itself -- building one `SupersessionIndex` and
     querying it N times over a synthetic corpus large enough to make the
     old O(N^2) per-call-rescan pattern slow is bounded well under what the
     O(N^2) pattern would cost, scaling sub-quadratically with corpus size.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "scripts" / "ember_totality" / "test_c_base.py"


def _load_target():
    spec = importlib.util.spec_from_file_location("ember_totality_test_c_base_perf", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


target = _load_target()


def _write_receipt(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8", newline="\n")


class SupersessionIndexCorrectnessTest(unittest.TestCase):
    """SupersessionIndex must agree with the original per-call semantics:
    a receipt is superseded iff some VOID receipt's `supersedes` array names
    its filename or sha256 (dict-shaped {"filename":..,"sha256":..} entries,
    or bare string entries matching either field)."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_filename_based_supersession_dict_shape(self) -> None:
        target_receipt = self.root / "cbase-old-001.json"
        _write_receipt(target_receipt, {"verdict": "RED", "note": "superseded target"})

        void_receipt = self.root / "cbase-void-001.json"
        _write_receipt(
            void_receipt,
            {"verdict": "VOID", "supersedes": [{"filename": "cbase-old-001.json"}]},
        )

        other_receipt = self.root / "cbase-other-001.json"
        _write_receipt(other_receipt, {"verdict": "GREEN", "note": "unrelated"})

        all_receipts = sorted(self.root.glob("*.json"))
        idx = target.SupersessionIndex(all_receipts)

        self.assertTrue(idx.is_superseded(target_receipt))
        self.assertFalse(idx.is_superseded(other_receipt))
        self.assertFalse(idx.is_superseded(void_receipt))

        # Back-compat wrapper must agree exactly.
        self.assertEqual(
            target._is_superseded(target_receipt, all_receipts),
            idx.is_superseded(target_receipt),
        )
        self.assertEqual(
            target._is_superseded(other_receipt, all_receipts),
            idx.is_superseded(other_receipt),
        )

    def test_sha256_based_supersession_string_shape(self) -> None:
        target_receipt = self.root / "cbase-old-002.json"
        _write_receipt(target_receipt, {"verdict": "RED", "note": "superseded by hash"})
        receipt_hash = target._sha256_first16(target_receipt)
        self.assertTrue(receipt_hash)

        void_receipt = self.root / "cbase-void-002.json"
        _write_receipt(void_receipt, {"verdict": "VOID", "supersedes": [receipt_hash]})

        all_receipts = sorted(self.root.glob("*.json"))
        idx = target.SupersessionIndex(all_receipts)

        self.assertTrue(idx.is_superseded(target_receipt))
        self.assertEqual(
            target._is_superseded(target_receipt, all_receipts),
            idx.is_superseded(target_receipt),
        )

    def test_non_void_receipt_naming_a_file_does_not_supersede(self) -> None:
        target_receipt = self.root / "cbase-old-003.json"
        _write_receipt(target_receipt, {"verdict": "RED"})

        # A GREEN/RED receipt (not VOID) that happens to mention the filename
        # in a "supersedes"-shaped field must NOT count -- only verdict=="VOID"
        # receipts are consulted.
        decoy_receipt = self.root / "cbase-decoy-003.json"
        _write_receipt(
            decoy_receipt,
            {"verdict": "GREEN", "supersedes": [{"filename": "cbase-old-003.json"}]},
        )

        all_receipts = sorted(self.root.glob("*.json"))
        idx = target.SupersessionIndex(all_receipts)

        self.assertFalse(idx.is_superseded(target_receipt))
        self.assertEqual(
            target._is_superseded(target_receipt, all_receipts),
            idx.is_superseded(target_receipt),
        )

    def test_malformed_json_receipts_are_skipped_not_fatal(self) -> None:
        target_receipt = self.root / "cbase-old-004.json"
        _write_receipt(target_receipt, {"verdict": "RED"})

        garbage = self.root / "cbase-garbage-004.json"
        garbage.write_text("{not valid json", encoding="utf-8")

        all_receipts = sorted(self.root.glob("*.json"))
        idx = target.SupersessionIndex(all_receipts)  # must not raise
        self.assertFalse(idx.is_superseded(target_receipt))


class SupersessionIndexPerformanceTest(unittest.TestCase):
    """Guards against regressing back to the O(N^2) per-call rescan. Builds
    a synthetic corpus large enough that the old pattern (re-reading and
    re-parsing all N receipts on each of N is_superseded calls) is clearly
    quadratic, then asserts the indexed approach stays comfortably linear
    and fast -- bounding what would, under the old code, already be
    seconds-to-tens-of-seconds at this size and grow to the observed 600s+
    timeout at the real corpus's ~1097-file scale."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build_corpus(self, n: int) -> list[Path]:
        paths: list[Path] = []
        for i in range(n):
            p = self.root / f"cbase-receipt-{i:05d}.json"
            _write_receipt(p, {"verdict": "RED", "seq": i})
            paths.append(p)
        return sorted(paths)

    def test_indexed_lookup_is_near_linear_not_quadratic(self) -> None:
        small = self._build_corpus(60)
        # Reuse the same directory's file count by adding more for the large run.
        large_dir = self.root.parent / "large_corpus"
        large_dir.mkdir()
        large: list[Path] = []
        for i in range(240):
            p = large_dir / f"cbase-receipt-{i:05d}.json"
            _write_receipt(p, {"verdict": "RED", "seq": i})
            large.append(p)
        large = sorted(large)

        def timed_full_scan(receipts: list[Path]) -> float:
            t0 = time.perf_counter()
            idx = target.SupersessionIndex(receipts)
            for rp in receipts:
                idx.is_superseded(rp)
            return time.perf_counter() - t0

        t_small = timed_full_scan(small)
        t_large = timed_full_scan(large)

        # Corpus grew 4x (60 -> 240). Under the old O(N^2) per-call rescan
        # this scan-of-all-receipts pattern would cost ~16x as long; the
        # indexed O(N) approach should cost roughly ~4x (linear), with
        # generous headroom for scheduling noise on a shared CI runner.
        ratio = t_large / max(t_small, 1e-6)
        self.assertLess(
            ratio,
            10.0,
            msg=(
                f"SupersessionIndex scan scaled {ratio:.2f}x when corpus grew 4x "
                "(small={t_small:.4f}s, large={t_large:.4f}s) -- this looks "
                "quadratic again; the O(N^2) per-call rescan regression this "
                "test guards against would scale ~16x here."
            ).format(t_small=t_small, t_large=t_large, ratio=ratio),
        )

    def test_single_index_build_beats_600s_budget_by_wide_margin(self) -> None:
        # Synthetic corpus sized well below the real ~1097-file corpus but
        # large enough to be a meaningful bound check in CI.
        receipts = self._build_corpus(300)
        t0 = time.perf_counter()
        idx = target.SupersessionIndex(receipts)
        for rp in receipts:
            idx.is_superseded(rp)
        elapsed = time.perf_counter() - t0
        # Generous bound: the real fix runs the full ~1097-file corpus (two
        # such passes) in ~2s end-to-end. 300 receipts, one pass, should be
        # well under a second on any CI runner; 30s is a wide safety margin.
        self.assertLess(elapsed, 30.0, f"indexed scan of {len(receipts)} receipts took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
