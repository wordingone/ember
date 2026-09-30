# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The selected continuation head pointer is a real conditional update.

Two writers that both expect the same head must not both succeed: exactly one advances it and the other
refuses as stale, and the final pointer is the winner's. Each writer is a separate process started behind a
file barrier; the sibling authorities are stubbed with data-only fixtures (no checkpoint, no model, no GPU),
and the atomic replace is delayed so a check-then-replace race is certain when the compare is not held under
a lock. POINTER_MODULE overrides the module under test (the deliberate red runs the pre-lock module).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(os.environ.get('POINTER_MODULE') or ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/selected_continuation_head.py')
P0, WIN_A, WIN_B = '0' * 64, 'a' * 64, 'b' * 64

WORKER = r'''
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
barrier = Path(barrier)
(barrier / f'ready-{name}').write_text('1')
while not (barrier / 'go').exists():
    time.sleep(0.005)
common = dict(repo_root=Path(module_path).parent, receipts_root=Path(receipts), published_checkpoint_root=Path('unused'),
              hour_result_path=Path('hour-result.json'), hour_result_sha256='f' * 64)
try:
    if mode == 'seed':
        pointer.seed_selected_continuation_head(reason='fixture', **common)
    else:
        pointer.advance_selected_continuation_head(expected_parent_checkpoint_manifest_sha256=expected, **common)
    print(json.dumps({'ok': True}))
except pointer.StaleParentError as error:
    print(json.dumps({'ok': False, 'stale': True, 'error': str(error)}))
'''


def run_workers(receipts, jobs):
    """Start every job behind a barrier; return the parsed result of each. jobs: (name, mode, digest, expected)."""
    with tempfile.TemporaryDirectory() as barrier:
        script = Path(barrier) / 'worker.py'
        script.write_text(WORKER, encoding='utf-8')
        procs = [subprocess.Popen([sys.executable, '-B', str(script), str(MODULE), str(receipts), mode, digest, expected, barrier, name],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for name, mode, digest, expected in jobs]
        deadline = time.monotonic() + 60
        while len(list(Path(barrier).glob('ready-*'))) < len(jobs):
            if time.monotonic() > deadline or any(p.poll() not in (None, 0) for p in procs):
                break
            time.sleep(0.01)
        (Path(barrier) / 'go').write_text('1')
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=120)
            if proc.returncode != 0:
                raise AssertionError(f'worker failed: {err}')
            results.append(json.loads(out.strip().splitlines()[-1]))
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


if __name__ == '__main__':
    unittest.main()
