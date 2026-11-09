# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The hour runner's census refuses only on harm, and waits for a fence tenant instead of refusing it (lead rulings 81909, 81914, 82032 E1).

Reds: (1) the worker copy of the census judges the same rows as the launcher copy, unreadable rows included, with no commit arm;
(2) a live tenant of the GPU fence is exempt from the PRE-fence census only, with its descendants, and a different foreign GPU
holder still refuses; (3) an eval-shaped holder takes the fence, the press's fence section WAITS, proceeds when the holder
ends, and records the wait in custody; (4) the order inside launch() keeps the exemption out of the census taken inside the fence.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
SUBJECT_PATH = TOOLS / 'cia_step_runner.py'
SPEC = importlib.util.spec_from_file_location('bound_checkout_cia_step_runner_fence', SUBJECT_PATH)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
assert Path(runner.__file__).resolve(strict=True) == SUBJECT_PATH.resolve(strict=True)
from ember.governance.scripts import cia_conformance_launch as launch
from ember.governance.scripts import gpu_lock_guard

NOSLEEP = lambda seconds: None
WIN = sys.platform == 'win32'


def base():
    return [{'ProcessId': 1, 'ParentProcessId': 0, 'Name': 'codex.exe'},
            {'ProcessId': 2, 'ParentProcessId': 1, 'Name': 'python.exe'}]


def py(pid, parent=0, commit=2048, command='python.exe x.py', **extra):
    return dict({'ProcessId': pid, 'ParentProcessId': parent, 'Name': 'python.exe', 'PageFileUsage': commit,
                 'CommandLine': command}, **extra)


def unreadable(pid=3, **extra):
    return py(pid, commit=None, command=None, **extra)


def worker_verdict(rows, gpu, reread=None, **kw):
    try:
        runner.reject_unowned_model_processes(rows, set(gpu), 2, reread=reread, sleep=NOSLEEP, **kw)
        return 'pass'
    except ValueError:
        return 'refuse'


def launcher_verdict(rows, gpu, reread=None):
    try:
        launch.reject_resource_conflicts(rows, 2, set(gpu), reread=reread, sleep=NOSLEEP)
        return 'pass'
    except ValueError:
        return 'refuse'


@unittest.skipUnless(WIN, 'Windows process command-line semantics')
class WorkerHarmOnlyCensus(unittest.TestCase):
    def test_unreadable_row_not_on_the_gpu_is_ignored(self):
        rows = base() + [unreadable()]
        self.assertEqual(worker_verdict(rows, set(), lambda: rows), 'pass')

    def test_gpu_listed_unreadable_row_that_exits_or_vanishes_is_ignored(self):
        rows = base() + [unreadable()]
        self.assertEqual(worker_verdict(rows, {3}, lambda: base()), 'pass')
        self.assertEqual(worker_verdict(rows, {3}, lambda: base() + [unreadable(HasExited=True)]), 'pass')

    def test_gpu_listed_row_that_stays_live_and_unreadable_refuses_after_three_rereads(self):
        rows = base() + [unreadable()]
        calls = []
        self.assertEqual(worker_verdict(rows, {3}, lambda: calls.append(1) or rows), 'refuse')
        self.assertEqual(len(calls), runner.UNREADABLE_REREADS)

    def test_gpu_listed_row_that_becomes_readable_is_classified_as_a_gpu_holder(self):
        rows = base() + [unreadable()]
        self.assertEqual(worker_verdict(rows, {3}, lambda: base() + [py(3, command='python.exe holder.py')]), 'refuse')

    def test_exited_unreadable_row_is_ignored_without_reread(self):
        rows = base() + [unreadable(HasExited=True)]
        self.assertEqual(worker_verdict(rows, {3}, lambda: self.fail('no reread for an exited row')), 'pass')

    def test_own_commit_alone_is_not_a_refusal_but_a_training_entry_is(self):
        big = base() + [py(3, commit=15 * 1024 ** 2, command='python.exe serve.py')]
        self.assertEqual(worker_verdict(big, set(), lambda: big), 'pass')
        train = base() + [py(3, command='python.exe train.py')]
        self.assertEqual(worker_verdict(train, set(), lambda: train), 'refuse')

    def test_both_census_copies_agree_on_every_shape_including_unreadable_rows(self):
        shapes = []
        for exited in (True, False, None, ...):
            for gpu in (set(), {3}):
                for commit, command in ((15 * 1024 ** 2, 'python.exe serve.py'), (2048, 'python.exe unknown.py'),
                                        (2048, 'python.exe train.py'), (None, None)):
                    shapes.append((exited, gpu, commit, command))
        for exited, gpu, commit, command in shapes:
            with self.subTest(exited=exited, gpu=gpu, commit=commit, command=command):
                extra = {} if exited is ... else {'HasExited': exited}
                rows = base() + [py(3, commit=commit, command=command, **extra)]
                self.assertEqual(worker_verdict(rows, gpu, lambda: rows), launcher_verdict(rows, gpu, lambda: rows))


@unittest.skipUnless(WIN, 'Windows process command-line semantics')
class FenceTenantExemption(unittest.TestCase):
    def test_tenant_tree_is_the_holder_and_every_descendant(self):
        rows = base() + [py(10), py(11, parent=10), py(12, parent=11), py(13, parent=1)]
        self.assertEqual(runner.fence_tenant_pids(rows, 10), frozenset({10, 11, 12}))
        self.assertEqual(runner.fence_tenant_pids(rows, None), frozenset())

    def test_tenant_tree_survives_a_parent_cycle(self):
        rows = [py(10, parent=11), py(11, parent=10)]
        self.assertEqual(runner.fence_tenant_pids(rows, 10), frozenset({10, 11}))

    def test_a_gpu_holding_fence_tenant_is_exempt_only_when_named_and_a_foreign_holder_still_refuses(self):
        eval_holder = py(10, command='python.exe eval_holder.py')
        child = py(11, parent=10, command='python.exe eval_worker.py')
        foreign = py(20, command='python.exe somebody_else.py')
        rows = base() + [eval_holder, child]
        self.assertEqual(worker_verdict(rows, {10, 11}), 'refuse')
        self.assertEqual(worker_verdict(rows, {10, 11}, exempt_pids=runner.fence_tenant_pids(rows, 10)), 'pass')
        rows = rows + [foreign]
        self.assertEqual(worker_verdict(rows, {10, 11, 20}, exempt_pids=runner.fence_tenant_pids(rows, 10)), 'refuse')

    def test_resource_census_exempts_the_named_holder_on_the_real_path(self):
        rows = base() + [py(10, command='python.exe eval_holder.py')]

        def fake_run(command, **_):
            return mock.Mock(stdout='10\n')
        with mock.patch.object(runner, 'run_readonly', fake_run), mock.patch.object(runner, 'process_census', lambda: rows), \
                mock.patch.object(runner.os, 'getpid', lambda: 2):
            with self.assertRaisesRegex(ValueError, 'requires coordination: 10'):
                runner.resource_census()
            self.assertEqual(runner.resource_census(fence_holder=10), rows)
            with self.assertRaisesRegex(ValueError, 'requires coordination: 10'):
                runner.resource_census(fence_holder=11)


HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
import gpu_lock_guard as g
with g.acquire(script='eval_holder.py', wait_seconds=0):
    time.sleep(float(sys.argv[2]))
"""


@unittest.skipUnless(WIN, 'Windows process command-line semantics')
class PressWaitsForAnEvalShapedHolder(unittest.TestCase):
    def test_press_fence_section_waits_then_proceeds_and_records_the_wait(self):
        scripts = ROOT / 'src/ember/governance/scripts'
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            lock, holder_script, custody = directory / 'gpu.lock', directory / 'eval_holder.py', directory / 'custody'
            custody.mkdir()
            holder_script.write_text(HOLDER, encoding='utf-8')
            saved = gpu_lock_guard.LOCK_PATH
            gpu_lock_guard.LOCK_PATH = str(lock)
            holder = subprocess.Popen([sys.executable, '-B', str(holder_script), str(scripts), '3'],
                                      env=dict(os.environ, EMBER_GPU_LOCK_PATH=str(lock)), creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and gpu_lock_guard.holder_pid() is None:
                    time.sleep(0.1)
                # a venv python.exe is a launcher that runs the real interpreter as its child: the fence names the real pid
                fence_holder = gpu_lock_guard.holder_pid()
                self.assertIsNotNone(fence_holder)
                # the pre-fence census as launch() makes it: the holder lists on the card and would refuse without the exemption
                rows = base() + [py(fence_holder, command='python.exe eval_holder.py')]
                with mock.patch.object(runner, 'run_readonly', lambda command, **_: mock.Mock(stdout=f'{fence_holder}\n')), \
                        mock.patch.object(runner, 'process_census', lambda: rows), mock.patch.object(runner.os, 'getpid', lambda: 2):
                    with self.assertRaisesRegex(ValueError, 'requires coordination'):
                        runner.resource_census()
                    runner.resource_census(fence_holder=fence_holder)
                started = time.monotonic()
                with gpu_lock_guard.acquire(script='cia_step_runner.py', wait_seconds=60, log=lambda event: None):
                    runner.record_fence_wait(custody, gpu_lock_guard, fence_holder)
                    waited = time.monotonic() - started
                self.assertGreater(waited, 0.5)                    # it queued behind the holder, it did not refuse
                self.assertEqual(holder.wait(timeout=30), 0)
                record = json.loads((custody / 'gpu-fence-wait.json').read_text(encoding='utf-8'))
                self.assertEqual(record['schema'], 'ember-gpu-fence-wait-v1')
                self.assertEqual(record['holder_at_preflight'], fence_holder)
                self.assertGreaterEqual(record['wait']['attempts'], 1)
                self.assertGreater(record['wait']['waited_seconds'], 0.5)
                self.assertEqual(record['wait']['holders'][0]['pid'], fence_holder)
                self.assertEqual(record['wait']['holders'][0]['script'], 'eval_holder.py')
                self.assertFalse(lock.exists())
            finally:
                gpu_lock_guard.LOCK_PATH = saved
                if holder.poll() is None:
                    holder.kill()
                    holder.wait()

    def test_a_failed_wait_record_is_named_and_never_fails_the_launch(self):
        import contextlib
        import io
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(err):
            runner.record_fence_wait(Path(directory) / 'missing' / 'custody', gpu_lock_guard, None)
        self.assertIn('GPU_FENCE_WAIT_RECORD_DEGRADED', err.getvalue())


class LaunchOrder(unittest.TestCase):
    def test_exemption_covers_the_pre_fence_census_only(self):
        source = SUBJECT_PATH.read_text(encoding='utf-8')
        launch_source = source[source.index('def launch('):]
        holder = launch_source.index('fence_holder = gpu_lock_guard.holder_pid()')
        pre = launch_source.index('resource_census(fence_holder=fence_holder)')
        acquire = launch_source.index('with gpu_lock_guard.acquire(script=ENTRY):')
        record = launch_source.index('record_fence_wait(custody, gpu_lock_guard, fence_holder)')
        inside = launch_source.index('resource_census()', acquire)
        spawn = launch_source.index('OwnedProcessRunner(windows_job_factory=factory)')
        self.assertLess(holder, pre)
        self.assertLess(pre, acquire)
        self.assertLess(acquire, record)
        self.assertLess(record, inside)
        self.assertLess(inside, spawn)
        self.assertEqual(launch_source.count('fence_holder=fence_holder'), 1)

    def test_the_card_is_sampled_inside_the_fence_and_before_it_only_without_a_tenant(self):
        source = SUBJECT_PATH.read_text(encoding='utf-8')
        launch_source = source[source.index('def launch('):]
        self.assertEqual(launch_source.count('resources.sample_device_at_launch('), 2)
        self.assertIn('if fence_holder is None:', launch_source)


if __name__ == '__main__':
    unittest.main()
