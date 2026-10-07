# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The selected continuation head pointer is a real conditional update.

Two writers that both expect the same head must not both succeed: exactly one advances it and the other
refuses as stale, and the final pointer is the winner's. Each writer is a separate process started behind a
file barrier that is released only after BOTH have acknowledged readiness; the sibling authorities are stubbed
with data-only fixtures (no checkpoint, no model, no GPU), and the atomic replace is delayed so a
check-then-replace race is certain when the compare is not held under a lock. POINTER_MODULE overrides the
module under test (the deliberate red runs the pre-lock module).

Every child interpreter is an owned, hidden process (owned_children -> owned_process.OwnedProcessRunner): no
console window, shell=False, captured streams, the whole tree killed on a timeout and on every failure path
before the temporary roots are torn down.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import owned_children  # noqa: E402
from owned_children import BARRIER_CHILD_PRELUDE, BarrierFailure, pid_alive, python_argv, run_group, run_one  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(os.environ.get('POINTER_MODULE') or ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/selected_continuation_head.py')
P0, WIN_A, WIN_B = '0' * 64, 'a' * 64, 'b' * 64

WORKER = BARRIER_CHILD_PRELUDE + r'''
import importlib.util, json, os, sys, time, types
from pathlib import Path
module_path, receipts, mode, digest, expected, barrier, name = sys.argv[1:8]
artifacts = types.ModuleType('checkpoint_artifacts')
artifacts.published_checkpoint_receipt = lambda root: {'checkpoint_manifest_sha256': digest}
durable = types.ModuleType('durable_io')
def atomic_replace_durable(staged, target):
    time.sleep(0.4)
    for _ in range(200):
        try:
            os.replace(staged, target)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(staged, target)
durable.atomic_replace_durable = atomic_replace_durable
sys.modules['checkpoint_artifacts'], sys.modules['durable_io'] = artifacts, durable
spec = importlib.util.spec_from_file_location('pointer_under_test', module_path)
pointer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pointer)
barrier_ready_and_wait(barrier, name)
common = dict(repo_root=Path(module_path).parent, receipts_root=Path(receipts), published_checkpoint_root=Path('unused'),
              hour_result_path=Path('hour-result.json'), hour_result_sha256='f' * 64)
if mode == 'stall':
    time.sleep(600)
if mode == 'fail':
    sys.exit(5)
try:
    if mode == 'seed':
        pointer.seed_selected_continuation_head(reason='fixture', **common)
    else:
        pointer.advance_selected_continuation_head(expected_parent_checkpoint_manifest_sha256=expected, **common)
    print(json.dumps({'ok': True}))
except pointer.StaleParentError as error:
    print(json.dumps({'ok': False, 'stale': True, 'error': str(error)}))
'''


def launch(receipts, jobs, *, timeout_s=120.0):
    """Start every job as an owned child behind a barrier released only when all have acknowledged readiness.
    jobs: (name, mode, digest, expected). Returns the owned_children.GroupOutcome; every child is gone on return."""
    with tempfile.TemporaryDirectory() as barrier:
        script = Path(barrier) / 'worker.py'
        script.write_text(WORKER, encoding='utf-8')
        argvs = [(name, python_argv(script, MODULE, receipts, mode, digest, expected, barrier, name))
                 for name, mode, digest, expected in jobs]
        return run_group(argvs, barrier_dir=barrier, timeout_s=timeout_s)


def run_workers(receipts, jobs):
    """Return the parsed result of each job, in order; a worker that did not complete with exit 0 raises."""
    outcome = launch(receipts, jobs)
    results = []
    for name, *_ in jobs:
        result = outcome.results[name]
        if result.status != 'completed' or result.returncode != 0:
            raise AssertionError(f'worker {name} {result.status} rc={result.returncode}: {result.stderr}')
        results.append(json.loads(result.stdout.strip().splitlines()[-1]))
    return results


def head(receipts):
    return json.loads((Path(receipts) / 'selected-continuation-head.json').read_text(encoding='utf-8'))['lineage_checkpoint_manifest_sha256']


class PointerConditionalUpdate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.receipts = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def seed_p0(self):
        self.assertEqual(run_workers(self.receipts, [('s', 'seed', P0, '')]), [{'ok': True}])
        self.assertEqual(head(self.receipts), P0)

    def test_two_advances_expecting_the_same_head_exactly_one_wins(self):
        self.seed_p0()
        results = run_workers(self.receipts, [('a', 'advance', WIN_A, P0), ('b', 'advance', WIN_B, P0)])
        wins = [i for i, r in enumerate(results) if r['ok']]
        self.assertEqual(len(wins), 1, results)
        loser = results[1 - wins[0]]
        self.assertTrue(loser.get('stale'), results)
        self.assertEqual(head(self.receipts), (WIN_A, WIN_B)[wins[0]])

    def test_two_seeds_on_an_absent_pointer_exactly_one_wins(self):
        results = run_workers(self.receipts, [('a', 'seed', WIN_A, ''), ('b', 'seed', WIN_B, '')])
        wins = [i for i, r in enumerate(results) if r['ok']]
        self.assertEqual(len(wins), 1, results)
        self.assertTrue(results[1 - wins[0]].get('stale'), results)
        self.assertEqual(head(self.receipts), (WIN_A, WIN_B)[wins[0]])

    def test_a_leftover_lock_file_with_no_holder_does_not_block(self):
        self.seed_p0()
        (self.receipts / 'selected-continuation-head.json.lock').write_bytes(b'x')
        self.assertEqual(run_workers(self.receipts, [('a', 'advance', WIN_A, P0)]), [{'ok': True}])
        self.assertEqual(head(self.receipts), WIN_A)

    def test_a_stale_expectation_is_refused_and_leaves_the_pointer_unchanged(self):
        self.seed_p0()
        results = run_workers(self.receipts, [('a', 'advance', WIN_A, WIN_B)])
        self.assertTrue(results[0].get('stale'), results)
        self.assertEqual(head(self.receipts), P0)


class OwnedChildLifecycle(unittest.TestCase):
    """The worker launch and cleanup paths themselves: hidden spawn flags, a stalled worker, a failing worker, a
    worker that never acknowledges readiness. Each ends with the owned children verifiably gone."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.receipts = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.assertEqual(run_workers(self.receipts, [('s', 'seed', P0, '')]), [{'ok': True}])

    @unittest.skipUnless(os.name == 'nt', 'Windows spawn-boundary flags')
    def test_windows_children_are_spawned_with_no_window_and_a_hidden_startupinfo(self):
        real_popen = subprocess.Popen
        with mock.patch.object(owned_children.owned_process.subprocess, 'Popen', wraps=real_popen) as spy:
            result = run_one(python_argv('-c', 'pass'), timeout_s=60)
        kwargs = spy.call_args.kwargs
        self.assertTrue(kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW, kwargs['creationflags'])
        self.assertTrue(kwargs['startupinfo'].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(kwargs['startupinfo'].wShowWindow, subprocess.SW_HIDE)
        self.assertIs(kwargs['shell'], False)
        self.assertEqual((result.status, result.returncode, result.backend, result.cleanup_verified),
                         ('completed', 0, 'windows-job-object', True))

    @unittest.skipIf(os.name == 'nt', 'POSIX containment backend')
    def test_posix_children_run_in_an_owned_process_group(self):
        result = run_one(python_argv('-c', 'pass'), timeout_s=60)
        self.assertEqual((result.status, result.returncode, result.backend, result.cleanup_verified),
                         ('completed', 0, 'posix-process-group', True))

    def test_a_stalled_worker_is_terminated_and_its_process_is_gone(self):
        outcome = launch(self.receipts, [('a', 'stall', WIN_A, P0)], timeout_s=10)
        result = outcome.results['a']
        self.assertEqual(result.status, 'terminated')
        self.assertFalse(pid_alive(result.pid), f'pid {result.pid} survived the timeout')
        self.assertEqual(head(self.receipts), P0)

    def test_a_failing_worker_reports_its_exit_and_the_sibling_is_still_reaped(self):
        outcome = launch(self.receipts, [('a', 'fail', WIN_A, P0), ('b', 'advance', WIN_B, P0)])
        self.assertEqual((outcome.results['a'].status, outcome.results['a'].returncode), ('completed', 5))
        self.assertEqual(outcome.ready_before_go, ['a', 'b'])
        for result in outcome.results.values():
            self.assertFalse(pid_alive(result.pid), f'pid {result.pid} still alive after the group returned')
        with self.assertRaisesRegex(AssertionError, 'worker a completed rc=5'):
            run_workers(self.receipts, [('a', 'fail', WIN_A, P0)])

    def test_a_worker_that_never_acknowledges_readiness_fails_closed_and_leaves_no_thread(self):
        with tempfile.TemporaryDirectory() as barrier:
            sleeper = python_argv('-c', 'import time; time.sleep(600)')
            with self.assertRaises(BarrierFailure):
                run_group([('a', sleeper)], barrier_dir=barrier, timeout_s=3, ready_timeout_s=1.0)
            self.assertTrue((Path(barrier) / 'abort').exists())
            self.assertFalse((Path(barrier) / 'go').exists())
        import threading
        self.assertEqual([t.name for t in threading.enumerate() if t.name.startswith('owned-child-')], [])


if __name__ == '__main__':
    unittest.main()
