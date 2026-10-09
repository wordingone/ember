"""Issue #2119 row 15: the lawful command-line writer of the pending-continuation record.

`write` records the next segment, or its blocker, for the CURRENT head through write_pending_continuation and never moves the pointer; `read` prints
what a fresh interpreter sees. Deliberate reds: a write for a head the pointer has left, and a stale read, must not look like a ready segment.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import pending_continuation as pending  # noqa: E402

HEAD, OTHER = 'a' * 64, 'b' * 64


class PendingCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        pointer = {'schema': 'ember-selected-continuation-head-v1', 'lineage_checkpoint_manifest_sha256': HEAD, 'hour_result_path': 'hour-result.json',
                   'hour_result_sha256': 'f' * 64, 'published_at': 1.0, 'seeded_reason': 'fixture'}
        self.pointer_file = self.root / 'selected-continuation-head.json'
        self.pointer_file.write_text(json.dumps(pointer, sort_keys=True), encoding='utf-8')
        self.pointer_before = hashlib.sha256(self.pointer_file.read_bytes()).hexdigest()

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pending.main(list(argv))
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def test_write_ready_then_read_returns_the_same_segment_and_the_pointer_is_untouched(self):
        code, out = self.cli('write', '--receipts-root', str(self.root), '--head', HEAD, '--purpose', 'CONTINUE_TRAINING', '--run-id', 'r1')
        self.assertEqual((code, out['status']), (0, 'WRITTEN'))
        code, out = self.cli('read', '--receipts-root', str(self.root))
        self.assertEqual(out['read'], {'next_identity': {'training_job_purpose': 'CONTINUE_TRAINING', 'run_id': 'r1'}})
        self.assertEqual(hashlib.sha256(self.pointer_file.read_bytes()).hexdigest(), self.pointer_before)   # a schedule record, not a head advance

    def test_write_blocked_reads_back_with_its_reason(self):
        self.cli('write', '--receipts-root', str(self.root), '--head', HEAD, '--blocker', 'training hold')
        _, out = self.cli('read', '--receipts-root', str(self.root))
        self.assertEqual(out['read'], {'blocker': 'training hold'})

    def test_a_write_for_a_head_the_pointer_has_left_is_refused_DELIBERATE_RED(self):
        code, out = self.cli('write', '--receipts-root', str(self.root), '--head', OTHER, '--purpose', 'CONTINUE_TRAINING', '--run-id', 'r1')
        self.assertEqual((code, out['status']), (3, 'REFUSED'))
        self.assertFalse((self.root / pending.FILENAME).exists())          # nothing was written

    def test_a_read_for_another_head_is_stale_never_ready_DELIBERATE_RED(self):
        self.cli('write', '--receipts-root', str(self.root), '--head', HEAD, '--purpose', 'CONTINUE_TRAINING', '--run-id', 'r1')
        _, out = self.cli('read', '--receipts-root', str(self.root), '--head', OTHER)
        self.assertEqual(out['read'], {'blocker': pending.STALE_BLOCKER})

    def test_write_needs_exactly_one_of_a_segment_or_a_blocker(self):
        code, out = self.cli('write', '--receipts-root', str(self.root), '--head', HEAD)
        self.assertEqual((code, out['status']), (3, 'REFUSED'))
        code, _ = self.cli('write', '--receipts-root', str(self.root), '--head', HEAD, '--purpose', 'P', '--run-id', 'r', '--blocker', 'b')
        self.assertEqual(code, 3)


if __name__ == '__main__':
    unittest.main()
