"""Issue #2119 row 8 (live page): the page regenerates from live receipts and says STALE when an input is missing or old.

The page showed an owner-reported "hour 31 dispatched" as its newest fact. The page now carries no hand-written
fact; `continuity_page_live` writes it from the live selected head, the newest receipts and the snapshot, and a missing or older input
puts a red STALE banner on the first line. Each guard has a deliberate red.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
for entry in (str(HERE), str(TOOLS), str(ROOT / 'src/ember/governance/scripts'), str(ROOT / 'src')):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import continuity_page_live as live  # noqa: E402
import continuity_snapshot as producer  # noqa: E402
import test_issue2119_continuity_page as fixtures  # noqa: E402

H2, H3 = 'b' * 64, 'c' * 64
CAPTURED = '2026-10-08T16:00:00Z'
CAPTURED_EPOCH = live._parse_stamp(CAPTURED)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        snapshot = producer.build_snapshot(fixtures.status_dict(head=H3), candidate_audit=fixtures.NO_CANDIDATE_AUDIT, captured_at=CAPTURED)
        self.snapshot = producer.write_snapshot(self.dir / 'snapshot.json', snapshot)
        self.receipt = self.dir / 'hour-result.json'
        self.receipt.write_text('{}', encoding='utf-8')
        self.set_receipt_age(seconds_before_capture=60)
        self.out = self.dir / 'page.md'

    def set_receipt_age(self, *, seconds_before_capture):
        stamp = CAPTURED_EPOCH - seconds_before_capture
        os.utime(self.receipt, (stamp, stamp))

    def generate(self, *, head=H3, receipts=None, snapshot=None):
        return live.generate_live_page(snapshot_path=snapshot or self.snapshot, receipts_root=None, out_path=self.out,
                                       receipt_paths=[self.receipt] if receipts is None else receipts, current_head=lambda: head, now=CAPTURED_EPOCH + 5)

    def page(self):
        return self.out.read_text(encoding='utf-8')


class FreshPageTests(Base):
    def test_a_current_snapshot_with_older_receipts_renders_current_with_no_banner(self):
        verdict = self.generate()
        self.assertEqual((verdict['state'], verdict['reasons']), ('CURRENT', []))
        text = self.page()
        self.assertNotIn('STALE', text.replace('State: **CURRENT**', ''))
        self.assertIn(f'Live selected head: `{H3}`', text)
        self.assertIn(f'captured `{CAPTURED}`', text)
        self.assertIn('Training continuity', text)                       # the rendered block from the snapshot
        self.assertNotIn('owner-reported', text)

    def test_a_receipt_written_in_the_same_second_as_capture_is_not_stale(self):
        self.set_receipt_age(seconds_before_capture=0)
        os.utime(self.receipt, (CAPTURED_EPOCH + 0.9, CAPTURED_EPOCH + 0.9))   # captured_at is truncated to the second
        self.assertEqual(self.generate()['state'], 'CURRENT')

    def test_the_page_is_deterministic_for_fixed_inputs_and_has_lf_endings(self):
        self.generate()
        first = self.out.read_bytes()
        self.generate()
        self.assertEqual(self.out.read_bytes(), first)
        self.assertNotIn(b'\r', first)
        self.assertFalse((self.dir / 'page.md.tmp').exists())


class StalePageTests(Base):
    def assert_red_banner(self, needle):
        first = self.page().splitlines()[0]
        self.assertTrue(first.startswith(live.BANNER_PREFIX), first)
        self.assertIn(needle, first)
        self.assertIn('State: **STALE**', self.page())

    def test_deliberate_red_a_stale_pointer_shows_the_banner_and_labels_the_old_facts(self):
        verdict = self.generate(head=H2)                                   # the live pointer moved on to another head
        self.assertEqual(verdict['state'], 'STALE')
        self.assert_red_banner(f'live selected head is {H2}')
        self.assertIn('NOT current (reference only)', self.page())
        self.assertNotIn('State: **CURRENT**', self.page())

    def test_deliberate_red_a_receipt_newer_than_the_snapshot_shows_the_banner(self):
        later = CAPTURED_EPOCH + 120
        os.utime(self.receipt, (later, later))
        verdict = self.generate()
        self.assertEqual(verdict['state'], 'STALE')
        self.assert_red_banner('hour-result.json')
        self.assertIn('newer than the snapshot captured_at', verdict['reasons'][0])

    def test_deliberate_red_a_missing_snapshot_shows_only_the_banner_and_no_fact(self):
        verdict = self.generate(snapshot=self.dir / 'absent.json')
        self.assertEqual(verdict['state'], 'STALE')
        self.assert_red_banner('snapshot missing or unreadable')
        self.assertIn('No snapshot facts are shown', self.page())
        self.assertNotIn(H3, self.page().replace('Live selected head: `' + H3 + '`', ''))

    def test_deliberate_red_a_missing_receipt_shows_the_banner(self):
        verdict = self.generate(receipts=[self.dir / 'absent-receipt.json'])
        self.assertEqual(verdict['state'], 'STALE')
        self.assert_red_banner('receipt missing: absent-receipt.json')

    def test_a_live_head_reader_that_raises_is_stale_not_a_crash(self):
        def broken():
            raise OSError('drive offline')
        verdict = live.freshness(self.snapshot, live_head=broken, receipt_paths=[self.receipt])
        self.assertEqual(verdict['state'], 'STALE')
        self.assertIn('live selected head unreadable', verdict['reasons'][0])

    def test_a_corrupt_snapshot_is_stale(self):
        self.snapshot.write_text('{not json', encoding='utf-8')
        self.assertEqual(self.generate()['state'], 'STALE')


class ContractTests(Base):
    """Constants and the command line."""

    def test_the_schema_constant_agrees_with_the_producer(self):
        self.assertEqual(live.SNAPSHOT_SCHEMA, producer.SNAPSHOT_SCHEMA)

    def test_generate_requires_a_head_source(self):
        with self.assertRaises(ValueError):
            live.generate_live_page(snapshot_path=self.snapshot, receipts_root=None, out_path=self.out)

    def test_cli_exit_code_follows_the_state(self):
        calls = {}
        original = live.generate_live_page

        def fake(**kwargs):
            calls.update(kwargs)
            return {'state': 'STALE', 'reasons': ['x']}
        live.generate_live_page = fake
        try:
            code = live.main(['--snapshot', str(self.snapshot), '--receipts-root', str(self.dir), '--out', str(self.out), '--receipt', str(self.receipt)])
        finally:
            live.generate_live_page = original
        self.assertEqual(code, 1)
        self.assertEqual(calls['receipt_paths'], [self.receipt])


if __name__ == '__main__':
    unittest.main()
