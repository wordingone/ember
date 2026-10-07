"""Issue #2119 row 8 (hook half): the continuity snapshot is written at the publication boundary, and a failure there is loud.

`continuity_snapshot` had a producer and nothing that called it. These tests pin the call: the hook walks the real ancestry from the
published head and writes a snapshot whose head equals that head; a head or genesis that does not match writes nothing and leaves the
older snapshot in place (the deliberate red: the page then reads stale through `check_live`, it never describes the wrong head); and
`promote_with_pending_v1` writes the snapshot only after a clean move, refuses a malformed snapshot spec before the move, and returns
code 8 (head moved, snapshot not written) instead of hiding the failure.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import continuity_snapshot as snap  # noqa: E402
import continuity_snapshot_hook as hook  # noqa: E402
import promote_with_pending_v1 as promote_module  # noqa: E402
import training_continuity_ledger as ledger  # noqa: E402
import training_lineage_ancestry as ancestry  # noqa: E402


def write_manifest(root: Path, name: str, *, tokens: int, step: int, parent: Path | None = None, parent_sha: str | None = None,
                   token_delta: int | None = None, step_delta: int | None = None) -> tuple[Path, str]:
    directory = root / name
    directory.mkdir()
    lineage = {} if parent is None else {'parent_checkpoint': str(parent).replace('/', '\\'), 'parent_manifest_sha256': parent_sha,
                                         'token_delta': token_delta, 'step_delta': step_delta}
    raw = json.dumps({'schema_version': 'ember-cia-checkpoint-v1', 'lineage': lineage,
                      'data_cursor': {'tokens_seen': tokens, 'global_step': step}}, sort_keys=True).encode()
    (directory / ancestry.MANIFEST_NAME).write_bytes(raw)
    return directory, hashlib.sha256(raw).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.g, self.g_sha = write_manifest(self.root, 'g', tokens=0, step=0)
        self.b, self.b_sha = write_manifest(self.root, 'b', tokens=100, step=10, parent=self.g, parent_sha=self.g_sha, token_delta=100, step_delta=10)
        self.c, self.c_sha = write_manifest(self.root, 'c', tokens=150, step=15, parent=self.b, parent_sha=self.b_sha, token_delta=50, step_delta=5)
        self.hour_result = self.root / 'hour-result.json'
        self.hour_result.write_text(json.dumps({'child_manifest_sha256': self.c_sha, 'parent_manifest_sha256': self.b_sha, 'applied_positions': 50}))
        self.custody = self.root / 'custody'
        self.custody.mkdir()
        self.out = self.root / 'manifests' / 'status.json'
        self.env = patch.dict(os.environ, {ledger.LEDGER_ROOT_ENV: str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def publish(self, **overrides):
        args = dict(head_directory=self.c, hour_result_path=self.hour_result, expected_genesis_manifest_sha256=self.g_sha,
                    custody_parent=self.custody, snapshot_path=self.out, next_blocker='no admitted mixture bound yet')
        args.update(overrides)
        return hook.publish_snapshot(**args)


class HookTests(Fixture):
    def test_writes_a_snapshot_whose_head_is_the_published_head_and_check_live_agrees(self):
        outcome = self.publish()
        self.assertEqual(outcome['status'], 'WRITTEN')
        written = json.loads(self.out.read_text(encoding='utf-8'))
        self.assertEqual((written['head_manifest_sha256'], outcome['head']), (self.c_sha, self.c_sha))
        self.assertEqual(written['status']['lineage']['retained_applied_positions'], 150)
        self.assertFalse(snap.check_live(self.out, current_head=lambda: self.c_sha)['stale'])

    def test_deliberate_red_a_failed_hook_leaves_the_old_snapshot_and_the_page_reads_stale(self):
        self.assertEqual(self.publish()['status'], 'WRITTEN')
        before = self.out.read_bytes()
        # the next hour's head moves on, but the hook is handed a genesis that is not this lineage's: nothing is written
        outcome = self.publish(expected_genesis_manifest_sha256='f' * 64)
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertIn('AncestryRefusal', outcome['why'])
        self.assertEqual(self.out.read_bytes(), before)
        self.assertTrue(snap.check_live(self.out, current_head=lambda: 'e' * 64)['stale'])

    def test_a_hour_result_for_another_head_writes_nothing(self):
        other = json.loads(self.hour_result.read_text())
        other['child_manifest_sha256'] = self.b_sha
        self.hour_result.write_text(json.dumps(other))
        outcome = self.publish()
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertFalse(self.out.exists())

    def test_publish_from_spec_never_raises_on_a_none_or_wrong_typed_path_value(self):
        base = {'published_checkpoint_root': str(self.c), 'hour_result_path': str(self.hour_result), 'expected_genesis': self.g_sha,
                'custody_parent': str(self.custody), 'blocker': 'x', 'snapshot_path': str(self.out)}
        for field in ('custody_parent', 'published_checkpoint_root', 'hour_result_path', 'snapshot_path', 'expected_genesis'):
            for bad in (None, 5, ['a']):
                result = hook.publish_from_spec({**base, field: bad})
                self.assertEqual(result['status'], 'FAILED', (field, bad))
        self.assertFalse(self.out.exists())

    def test_the_hook_never_raises_on_a_missing_head_directory(self):
        outcome = self.publish(head_directory=self.root / 'absent')
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertFalse(self.out.exists())

    def test_spec_must_be_closed_and_name_a_next_segment_source(self):
        base = {'published_checkpoint_root': str(self.c), 'hour_result_path': str(self.hour_result), 'expected_genesis': self.g_sha,
                'custody_parent': str(self.custody), 'snapshot_path': str(self.out)}
        self.assertEqual(hook.publish_from_spec({**base, 'surprise': 1, 'blocker': 'x'})['status'], 'FAILED')
        self.assertEqual(hook.publish_from_spec(base)['status'], 'FAILED')            # no receipts_root, next or blocker
        self.assertFalse(self.out.exists())
        self.assertEqual(hook.publish_from_spec({**base, 'blocker': 'no admitted mixture bound yet'})['status'], 'WRITTEN')


class FakePending:
    def __init__(self, *, fail_advance=False):
        self.calls = []
        self.fail_advance = fail_advance
        self.record = None

    def advance_and_record_pending(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_advance:
            raise RuntimeError('advance refused')
        self.record = {'blocker': kwargs['blocker']}

    def read_pending_continuation(self, receipts_root, *, current_head_sha256):
        return self.record or {}


class FakeHeads:
    def __init__(self, root: Path, head: str):
        self.path = root / 'selected-head.json'
        self.path.write_text('{}')
        self.head = head

    def pointer_path(self, receipts_root):
        return self.path

    def current_head_sha256(self, receipts_root):
        return self.head


class PromoteIntegrationTests(Fixture):
    def spec(self, **snapshot_overrides):
        shot = {'expected_genesis': self.g_sha, 'custody_parent': str(self.custody), 'snapshot_path': str(self.out), **snapshot_overrides}
        return {'repo_root': str(self.root), 'receipts_root': str(self.root), 'published_checkpoint_root': str(self.c),
                'hour_result_path': str(self.hour_result), 'expected_parent': self.b_sha, 'expected_child': self.c_sha,
                'ledger': str(self.root / 'promote-ledger.jsonl'), 'blocker': 'no admitted mixture bound yet', 'snapshot': shot}

    def run_promote(self, spec, *, pending=None, writer=hook.publish_from_spec):
        rows = []
        pending = pending or FakePending()
        out = promote_module.promote(spec, pending=pending, sch=FakeHeads(self.root, self.c_sha), row=lambda **fields: rows.append(fields),
                                     ruling='66882', snapshot=writer)
        return out, pending, rows

    def test_a_clean_move_writes_the_snapshot_and_records_it(self):
        out, pending, rows = self.run_promote(self.spec())
        self.assertEqual((out['code'], out['snapshot']['status']), (0, 'WRITTEN'))
        self.assertEqual(json.loads(self.out.read_text(encoding='utf-8'))['head_manifest_sha256'], self.c_sha)
        self.assertEqual([row['kind'] for row in rows][-2:], ['promote_outcome', 'snapshot_outcome'])
        self.assertEqual(len(pending.calls), 1)

    def test_a_move_without_a_snapshot_key_behaves_exactly_as_before(self):
        spec = self.spec()
        del spec['snapshot']
        out, _, rows = self.run_promote(spec)
        self.assertEqual(out['code'], 0)
        self.assertNotIn('snapshot', out)
        self.assertFalse(self.out.exists())
        self.assertEqual([row['kind'] for row in rows][-1], 'promote_outcome')

    def test_a_snapshot_failure_after_the_move_is_code_8_and_does_not_undo_the_move(self):
        out, pending, rows = self.run_promote(self.spec(expected_genesis='f' * 64))
        self.assertEqual((out['code'], out['status']), (8, 'PROMOTED_SNAPSHOT_FAILED'))
        self.assertEqual(out['snapshot']['status'], 'FAILED')
        self.assertEqual(out['head'], self.c_sha)
        self.assertEqual(len(pending.calls), 1)
        self.assertEqual(rows[-1]['kind'], 'snapshot_outcome')

    def test_a_malformed_snapshot_spec_refuses_before_any_move(self):
        for bad in ({'expected_genesis': self.g_sha}, {'expected_genesis': self.g_sha, 'custody_parent': 'x', 'surprise': 1}):
            spec = self.spec()
            spec['snapshot'] = bad
            out, pending, _ = self.run_promote(spec)
            self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'))
            self.assertEqual(pending.calls, [])

    def test_a_snapshot_spec_with_a_non_string_or_malformed_value_refuses_before_any_move(self):
        # static review finding: custody_parent=None passed the key-only check and reached Path(None) after the move
        for field, bad in (('custody_parent', None), ('custody_parent', ''), ('custody_parent', 5), ('expected_genesis', None),
                           ('expected_genesis', 'not-hex'), ('expected_genesis', 'F' * 64), ('snapshot_path', 7), ('snapshot_path', '')):
            out, pending, rows = self.run_promote(self.spec(**{field: bad}))
            self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'), (field, bad))
            self.assertEqual((pending.calls, rows), ([], []), (field, bad))

    def test_a_writer_that_raises_after_the_move_still_records_the_outcome_and_is_code_8(self):
        def raising_writer(spec):
            raise TypeError('expected str, bytes or os.PathLike object, not NoneType')
        out, pending, rows = self.run_promote(self.spec(), writer=raising_writer)
        self.assertEqual((out['code'], out['status']), (8, 'PROMOTED_SNAPSHOT_FAILED'))
        self.assertEqual(out['snapshot']['status'], 'FAILED')
        self.assertIn('TypeError', out['snapshot']['why'])
        self.assertEqual(out['head'], self.c_sha)
        self.assertEqual(len(pending.calls), 1)
        self.assertEqual([row['kind'] for row in rows][-2:], ['promote_outcome', 'snapshot_outcome'])

    def test_the_chain_promote_to_hook_to_file_to_the_page_renderer(self):
        # the smallest real-consumer chain: promote's boundary calls the real hook, the hook writes the file, the page renderer reads that file
        renderer_path = ROOT / 'src/ember/governance/scripts/gen_readme_status.py'
        sys.path.insert(0, str(renderer_path.parent))
        try:
            spec = importlib.util.spec_from_file_location('chain_gen_readme_status', renderer_path)
            renderer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(renderer)
        finally:
            sys.path.remove(str(renderer_path.parent))
        if not hasattr(renderer, 'apply_continuity_status'):
            self.skipTest('the page renderer (#2339) is not in this tree yet; the chain runs once it merges')
        out, _, rows = self.run_promote(self.spec())
        self.assertEqual((out['code'], out['snapshot']['status']), (0, 'WRITTEN'))
        page_text = 'before\n' + renderer.CONTINUITY_BEGIN_MARKER + '\nold\n' + renderer.CONTINUITY_END_MARKER + '\nafter\n'
        rendered = renderer.apply_continuity_status(page_text, str(self.out))
        self.assertIn(self.c_sha, rendered)
        self.assertIn('`150` positions', rendered)
        self.assertNotIn('\nold\n', rendered)
        self.assertEqual(renderer.apply_continuity_status(rendered, str(self.out)), rendered)     # idempotent: the page is current
        self.assertEqual(rows[-1]['kind'], 'snapshot_outcome')

    def test_a_snapshot_key_without_a_writer_refuses_before_any_move(self):
        out, pending, _ = self.run_promote(self.spec(), writer=None)
        self.assertEqual((out['code'], pending.calls), (4, []))

    def test_a_refused_move_writes_no_snapshot(self):
        out, _, _ = self.run_promote(self.spec(), pending=FakePending(fail_advance=True))
        self.assertNotEqual(out['code'], 0)
        self.assertNotIn('snapshot', out)
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
