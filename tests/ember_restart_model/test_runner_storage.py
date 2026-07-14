# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production runner storage preflight tests."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import run_vertical_slice


class RunnerStorageTests(unittest.TestCase):
    def test_retention_prunes_only_after_successful_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            oldest = parent / "checkpoint-oldest"; oldest.mkdir()
            middle = parent / "checkpoint-middle"; middle.mkdir()
            now = time.time_ns(); os.utime(oldest, ns=(now - 2_000_000_000, now - 2_000_000_000)); os.utime(middle, ns=(now - 1_000_000_000, now - 1_000_000_000))
            with self.assertRaisesRegex(RuntimeError, "writer failed"):
                run_vertical_slice._retain_after_success(parent, max_count=2, operation=lambda: (_ for _ in ()).throw(RuntimeError("writer failed")))
            self.assertTrue(oldest.exists())
            self.assertTrue(middle.exists())
            newest = parent / "checkpoint-newest"
            result = run_vertical_slice._retain_after_success(parent, max_count=2, operation=lambda: (newest.mkdir(), "published")[1])
            self.assertEqual(result, "published")
            self.assertFalse(oldest.exists())
            self.assertTrue(middle.exists())
            self.assertTrue(newest.exists())
    def test_production_artifact_root_requires_an_explicit_b_drive_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "B:"):
            run_vertical_slice.production_artifact_root(Path("C:/tmp/ember-checkpoint"))
        accepted = run_vertical_slice.production_artifact_root(Path("B:/ember-checkpoint"))
        self.assertEqual(accepted.drive.upper(), "B:")


if __name__ == "__main__":
    unittest.main()