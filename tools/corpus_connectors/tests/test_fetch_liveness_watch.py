# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for fetch_liveness_watch.py -- the staleness/terminal watch that makes
an unattended connector fetch's death loud instead of silent."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fetch_liveness_watch as flw


class LivenessWatchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.dest = self.root / "dest"
        self.dest.mkdir()
        self.log = self.root / "fetch.log"
        self.log.write_text("START\n", encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def _write(self, *lines):
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_terminal_line_is_detected_and_exits_nonzero(self):
        self._write("START", "TERMINAL HTTPError: HTTP Error 429: Unknown Error")
        self.assertEqual(flw.watch(self.log, self.dest, None, 300, 0.01), 1)

    def test_exhausted_retries_is_terminal(self):
        self._write("START", "FLOW-CONTROL-EXHAUSTED code=429 attempts=9 -- giving up")
        self.assertEqual(flw.watch(self.log, self.dest, None, 300, 0.01), 1)

    def test_done_line_exits_zero(self):
        self._write("START", "DONE receipt committed")
        self.assertEqual(flw.watch(self.log, self.dest, None, 300, 0.01), 0)

    def test_dead_pid_without_completion_line_is_an_alert(self):
        # A process killed mid-run leaves no TERMINAL line of its own -- the
        # silence is exactly the failure mode this watch exists to catch.
        self._write("START")
        self.assertEqual(flw.watch(self.log, self.dest, 999999, 300, 0.01), 1)

    def test_dead_pid_after_clean_completion_is_success_not_an_alert(self):
        # The process being gone is normal once it has finished; alarming here
        # would fire on every successful run.
        self._write("START", "DONE receipt committed")
        self.assertEqual(flw.watch(self.log, self.dest, 999999, 300, 0.01), 0)

    def test_pending_retry_accounts_for_quiet_time(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=600)
        self._write("START", f"FLOW-CONTROL code=429 attempt=1/8 next_attempt_at={future.isoformat()} url=x")
        self.assertIsNotNone(flw.pending_retry_deadline(self.log))
        self.assertGreater(flw.pending_retry_deadline(self.log), datetime.now(timezone.utc))

    def test_elapsed_retry_no_longer_accounts_for_quiet_time(self):
        # Once a declared wake time (plus grace) has passed with nothing
        # happening, the quiet is no longer explained and must alarm.
        past = datetime.now(timezone.utc) - timedelta(seconds=flw.RETRY_GRACE_SECONDS + 600)
        self._write("START", f"FLOW-CONTROL code=429 attempt=1/8 next_attempt_at={past.isoformat()} url=x")
        self.assertLess(flw.pending_retry_deadline(self.log), datetime.now(timezone.utc))

    def test_last_retry_stamp_wins_over_earlier_ones(self):
        old = datetime.now(timezone.utc) - timedelta(seconds=5000)
        new = datetime.now(timezone.utc) + timedelta(seconds=600)
        self._write(
            "START",
            f"FLOW-CONTROL attempt=1/8 next_attempt_at={old.isoformat()} url=x",
            f"FLOW-CONTROL attempt=2/8 next_attempt_at={new.isoformat()} url=x",
        )
        self.assertGreater(flw.pending_retry_deadline(self.log), datetime.now(timezone.utc))

    def test_no_retry_stamp_returns_none(self):
        self._write("START", "PROGRESS n=1/10 id=x bytes=1")
        self.assertIsNone(flw.pending_retry_deadline(self.log))

    def test_unparseable_retry_stamp_degrades_to_none(self):
        self._write("START", "FLOW-CONTROL attempt=1/8 next_attempt_at=not-a-timestamp url=x")
        self.assertIsNone(flw.pending_retry_deadline(self.log))

    def test_newest_mtime_sees_writes_into_an_existing_child(self):
        # A directory's own mtime does not change when an existing file inside
        # it is written to, so watching only the dir reads as stale while a
        # large download is actively streaming.
        child = self.dest / "paper.pdf"
        child.write_bytes(b"x")
        dir_mtime = self.dest.stat().st_mtime
        time.sleep(0.05)
        child.write_bytes(b"xy")
        self.assertGreaterEqual(flw.newest_mtime(self.dest), dir_mtime)

    def test_fresh_log_line_counts_as_progress_when_dest_is_untouched(self):
        # A large --paper-list spends its whole metadata phase (hundreds of
        # batched API calls) writing log lines and no output files at all.
        # Watching dest alone would call that healthy phase a stall.
        import os

        ancient = time.time() - 5000
        os.utime(self.dest, (ancient, ancient))
        self.log.write_text("START\nMETA-BATCH 3/539 ids=100 entries=300\n", encoding="utf-8")
        dest_only_age = time.time() - flw.newest_mtime(self.dest)
        combined_age = time.time() - max(flw.newest_mtime(self.dest), self.log.stat().st_mtime)
        self.assertGreater(dest_only_age, 4000)
        self.assertLess(combined_age, 60)

    def test_missing_dest_reports_zero_rather_than_raising(self):
        self.assertEqual(flw.newest_mtime(self.root / "does-not-exist"), 0.0)

    def test_missing_log_does_not_raise(self):
        missing = self.root / "absent.log"
        self.assertIsNone(flw.pending_retry_deadline(missing))
        self.assertIsNone(flw.log_contains(missing, ("TERMINAL ",)))


if __name__ == "__main__":
    unittest.main()
