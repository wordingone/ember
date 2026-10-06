"""Issue #2119 row 15: the durable pending-continuation record survives a restart.

A fresh interpreter (a real owned child process, no shared module state) recovers the next segment, or its blocker, from the
disk alone; a record written for an older head reads blocked, never ready; a corrupt record refuses; a record for a head that
is not current is refused at write time. One deliberate red: a reader that caches its first answer in a module-level variable
returns the OLD ready segment after another process moved the pointer, which the real reader does not.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pending_continuation as pending  # noqa: E402
import selected_continuation_head as head_pointer  # noqa: E402
import training_continuity_status as status  # noqa: E402
from owned_children import pid_alive, python_argv, run_one  # noqa: E402

_PRELUDE = '''
import json, sys
from pathlib import Path
args = json.loads(sys.argv[1])
sys.path.insert(0, args['module_dir'])
import selected_continuation_head as hp
import pending_continuation as pc
import training_continuity_status as st
root = Path(args['receipts_root'])
'''

_CHILD_WRITE = _PRELUDE + '''
c = args['checkpoint']
head = hp.advance_selected_continuation_head(
    repo_root=Path(args['root']), receipts_root=root, published_checkpoint_root=Path(c['published_checkpoint_root']),
    hour_result_path=Path(c['hour_result_path']), hour_result_sha256=c['hour_result_sha256'],
    expected_parent_checkpoint_manifest_sha256=hp.GENESIS_SENTINEL, now=1000.0)['lineage_checkpoint_manifest_sha256']
if args['kind'] == 'ready':
    pc.write_pending_continuation(root, lineage_checkpoint_manifest_sha256=head,
                                  training_job_purpose=args['purpose'], run_id=args['run_id'], now=1001.0)
else:
    pc.write_pending_continuation(root, lineage_checkpoint_manifest_sha256=head, blocker=args['blocker'], now=1001.0)
print(json.dumps({'head': head}))
'''

_CHILD_READ = _PRELUDE + '''
head = hp.current_head_sha256(root)
try:
    recovered = pc.read_pending_continuation(root, current_head_sha256=head)
except pc.PendingContinuationRefusal as exc:
    print(json.dumps({'head': head, 'refused': str(exc)}))
    sys.exit(0)
print(json.dumps({'head': head, 'recovered': recovered, 'next_segment': st.next_segment_status(**recovered)}))
'''


class PendingContinuationRestoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.receipts_root = self.root / 'receipts'

    def _run(self, script, **args):
        payload = dict(module_dir=str(MODULE_DIR), root=str(ROOT), receipts_root=str(self.receipts_root), **args)
        done = run_one(python_argv('-c', script, json.dumps(payload)), timeout_s=120)
        self.assertEqual((done.status, done.returncode), ('completed', 0), done.stderr)
        self.assertFalse(pid_alive(done.pid), f'pid {done.pid} still alive after completion')
        return json.loads(done.stdout.strip().splitlines()[-1])

    def _checkpoint(self, name, record_index):
        hour_dir = self.root / name
        child_dir = hour_dir / 'trained-child'
        child_dir.mkdir(parents=True)
        manifest_bytes = json.dumps({'data_cursor': {'shard': 0, 'record_index': record_index}}).encode('utf-8')
        (child_dir / 'checkpoint-manifest.json').write_bytes(manifest_bytes)
        hour_result_bytes = json.dumps({'name': name}).encode('utf-8')
        (hour_dir / 'hour-result.json').write_bytes(hour_result_bytes)
        return dict(published_checkpoint_root=str(child_dir), hour_result_path=str(hour_dir / 'hour-result.json'),
                    hour_result_sha256=hashlib.sha256(hour_result_bytes).hexdigest(),
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())

    def _advance(self, checkpoint, expected_parent):
        head_pointer.advance_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=Path(checkpoint['published_checkpoint_root']),
            hour_result_path=Path(checkpoint['hour_result_path']), hour_result_sha256=checkpoint['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=expected_parent, now=1500.0)

    def test_a_fresh_process_recovers_the_pending_segment_from_disk_alone(self):
        c1 = self._checkpoint('c1', 1)
        written = self._run(_CHILD_WRITE, checkpoint=c1, kind='ready', purpose='DIAGNOSTIC', run_id='next-r7')
        self.assertEqual(written['head'], c1['manifest_sha256'])
        recovered = self._run(_CHILD_READ)
        self.assertEqual(recovered['head'], c1['manifest_sha256'])
        self.assertEqual(recovered['next_segment'],
                         {'status': 'ready', 'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'next-r7'})

    def test_a_blocked_record_recovers_as_blocked_with_its_reason(self):
        c1 = self._checkpoint('c1', 1)
        self._run(_CHILD_WRITE, checkpoint=c1, kind='blocked', blocker='readiness blocker: image evaluator unbound')
        self.assertEqual(self._run(_CHILD_READ)['next_segment'],
                         {'status': 'blocked', 'blocker': 'readiness blocker: image evaluator unbound'})

    def test_a_stale_pending_record_reads_blocked_never_ready(self):
        c1, c2 = self._checkpoint('c1', 1), self._checkpoint('c2', 2)
        self._run(_CHILD_WRITE, checkpoint=c1, kind='ready', purpose='DIAGNOSTIC', run_id='next-r7')
        self._advance(c2, c1['manifest_sha256'])
        recovered = self._run(_CHILD_READ)
        self.assertEqual(recovered['head'], c2['manifest_sha256'])
        self.assertEqual(recovered['next_segment'], {'status': 'blocked', 'blocker': pending.STALE_BLOCKER})

    def test_a_missing_record_reads_blocked_not_ready(self):
        self._advance(self._checkpoint('c1', 1), head_pointer.GENESIS_SENTINEL)
        self.assertEqual(self._run(_CHILD_READ)['next_segment'], {'status': 'blocked', 'blocker': pending.MISSING_BLOCKER})

    def test_a_corrupt_pending_record_refuses_rather_than_reading_ready(self):
        c1 = self._checkpoint('c1', 1)
        self._run(_CHILD_WRITE, checkpoint=c1, kind='ready', purpose='DIAGNOSTIC', run_id='next-r7')
        path = pending.pending_path(self.receipts_root)
        path.write_bytes(path.read_bytes()[:40])   # truncated JSON
        self.assertIn('not valid JSON', self._run(_CHILD_READ)['refused'])
        path.write_text(json.dumps({'schema': pending.SCHEMA, 'status': 'ready'}), encoding='utf-8')   # open fields
        self.assertIn('fields are not closed', self._run(_CHILD_READ)['refused'])

    def test_a_record_for_a_head_that_is_not_current_is_refused_at_write_time(self):
        c1, c2 = self._checkpoint('c1', 1), self._checkpoint('c2', 2)
        self._advance(c1, head_pointer.GENESIS_SENTINEL)
        self._advance(c2, c1['manifest_sha256'])
        with self.assertRaises(pending.PendingContinuationRefusal):
            pending.write_pending_continuation(self.receipts_root, lineage_checkpoint_manifest_sha256=c1['manifest_sha256'],
                                               training_job_purpose='DIAGNOSTIC', run_id='late-writer')
        self.assertFalse(pending.pending_path(self.receipts_root).exists())

    def test_the_status_producer_reads_the_pending_record_in_place_of_a_caller_supplied_next_segment(self):
        c1 = self._checkpoint('c1', 1)
        self._run(_CHILD_WRITE, checkpoint=c1, kind='ready', purpose='DIAGNOSTIC', run_id='next-r7')
        hour_result = {'child_manifest_sha256': c1['manifest_sha256'], 'parent_manifest_sha256': 'p' * 64, 'applied_positions': 8}
        lineage_record = {'schema': status.LINEAGE_SCHEMA, 'head_manifest_sha256': c1['manifest_sha256'],
                          'genesis_manifest_sha256': 'g' * 64, 'depth': 1, 'cumulative_applied_token_delta': 8,
                          'cumulative_step_delta': 1}
        record = status.training_continuity_status(
            custody_parent=self.root, hour_result=hour_result, lineage_record=lineage_record, current_identity=None,
            measurement=None, pending_receipts_root=self.receipts_root)
        self.assertEqual(record['next_segment'], {'status': 'ready', 'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'next-r7'})
        with self.assertRaises(ValueError):   # the caller may not also supply one
            status.training_continuity_status(
                custody_parent=self.root, hour_result=hour_result, lineage_record=lineage_record, current_identity=None,
                measurement=None, pending_receipts_root=self.receipts_root, next_blocker='x')

    def test_deliberate_red_a_reader_that_caches_its_first_answer_misses_a_pointer_advance_by_another_process(self):
        c1, c2 = self._checkpoint('c1', 1), self._checkpoint('c2', 2)
        self._run(_CHILD_WRITE, checkpoint=c1, kind='ready', purpose='DIAGNOSTIC', run_id='next-r7')
        cache = {}

        def cached_read():   # the defect: the first answer is kept in module-level state and returned forever
            if 'value' not in cache:
                cache['value'] = self._run(_CHILD_READ)['next_segment']
            return cache['value']

        self.assertEqual(cached_read()['status'], 'ready')
        self._advance(c2, c1['manifest_sha256'])
        self.assertEqual(self._run(_CHILD_READ)['next_segment']['status'], 'blocked')   # the real reader sees the advance
        self.assertEqual(cached_read()['status'], 'ready')                              # the cached one still says ready: stale


class ChildInvocationRouteTests(unittest.TestCase):
    """Every non-Ember interpreter child starts through the mandatory headless wrapper on Windows (Kai 61929)."""

    @staticmethod
    def _through_wrapper(argv) -> bool:
        return (argv[0].lower().startswith('powershell') and '-File' in argv
                and any(str(part).replace('\\', '/').endswith('headless-python.ps1') for part in argv)
                and argv[argv.index('--') + 1] == '-B' and argv[0] != sys.executable)

    @unittest.skipUnless(sys.platform == 'win32', 'the wrapper route is the Windows argv')
    def test_python_argv_routes_through_the_headless_wrapper_on_windows(self):
        self.assertTrue(self._through_wrapper(python_argv('-c', 'pass')))

    def test_a_child_started_by_the_helper_runs_the_requested_code_and_returns_its_exit_code(self):
        done = run_one(python_argv('-c', 'import sys; print("child-ok"); sys.exit(3)'), timeout_s=120)
        self.assertEqual((done.returncode, done.stdout.strip()), (3, 'child-ok'))

    def test_deliberate_red_the_bare_interpreter_argv_fails_the_wrapper_predicate(self):
        bare = [sys.executable, '-B', '-c', 'pass']   # what the helper built before this repair
        self.assertFalse(self._through_wrapper(bare))


if __name__ == '__main__':
    unittest.main()
