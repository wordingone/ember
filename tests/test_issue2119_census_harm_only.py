# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The resource census refuses only on harm to the run (lead ruling 81909, 2026-11-09).

H44 attempts 1 and 2 (2026-11-08 23:15Z and 23:31Z) died with 'cannot classify model process resources': a short-lived python
from another lane was caught mid-start with no command line. A process can only matter if it holds GPU memory, so:
(a) an unreadable row not listed by nvidia-smi is ignored; (b) a GPU-listed unreadable row is re-read 3 times over 2 s and
refuses only if it stays live and unreadable; (c) an exited row is ignored. Both copies of the predicate must agree.
Reds: a churn of pythons spawned and killed every 100 ms does not refuse the real census; a foreign GPU holder still refuses.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
SPEC = importlib.util.spec_from_file_location('harm_only_cia_step_runner', TOOLS / 'cia_step_runner.py')
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
from ember.governance.scripts import cia_conformance_launch as launch

NOSLEEP = lambda seconds: None


def base():
    return [{'ProcessId': 1, 'ParentProcessId': 0, 'Name': 'codex.exe'},
            {'ProcessId': 2, 'ParentProcessId': 1, 'Name': 'python.exe'}]


def unreadable(pid=3):
    return {'ProcessId': pid, 'ParentProcessId': 0, 'Name': 'python.exe', 'PageFileUsage': None, 'CommandLine': None}


def both(rows, gpu, reread):
    verdicts = []
    for call in (lambda: launch.reject_resource_conflicts(rows, 2, set(gpu), reread=reread, sleep=NOSLEEP),
                 lambda: runner.reject_unowned_model_processes(rows, set(gpu), 2, reread=reread, sleep=NOSLEEP)):
        try:
            call()
            verdicts.append('pass')
        except ValueError:
            verdicts.append('refuse')
    return verdicts


@unittest.skipUnless(sys.platform == 'win32', 'Windows process census')
class HarmOnlyCensus(unittest.TestCase):
    def test_a_unreadable_row_not_on_the_gpu_is_ignored(self):
        rows = base() + [unreadable()]
        self.assertEqual(both(rows, set(), lambda: rows), ['pass', 'pass'])

    def test_b_gpu_listed_unreadable_row_that_exits_or_vanishes_is_ignored(self):
        rows = base() + [unreadable()]
        gone = base()
        exited = base() + [dict(unreadable(), HasExited=True)]
        self.assertEqual(both(rows, {3}, lambda: gone), ['pass', 'pass'])
        self.assertEqual(both(rows, {3}, lambda: exited), ['pass', 'pass'])

    def test_b_gpu_listed_row_that_stays_live_and_unreadable_refuses_after_three_rereads(self):
        rows = base() + [unreadable()]
        calls = []
        def reread():
            calls.append(1)
            return rows
        self.assertEqual(both(rows, {3}, reread), ['refuse', 'refuse'])
        self.assertEqual(len(calls), 2 * runner.UNREADABLE_REREADS)

    def test_b_gpu_listed_row_that_becomes_readable_is_classified_and_refuses_as_a_gpu_holder(self):
        rows = base() + [unreadable()]
        fresh = base() + [{'ProcessId': 3, 'ParentProcessId': 0, 'Name': 'python.exe', 'PageFileUsage': 2048,
                           'CommandLine': 'python.exe holder.py'}]
        self.assertEqual(both(rows, {3}, lambda: fresh), ['refuse', 'refuse'])

    def test_c_exited_unreadable_row_is_ignored_without_reread(self):
        rows = base() + [dict(unreadable(), HasExited=True)]
        self.assertEqual(both(rows, {3}, lambda: self.fail('no reread for an exited row')), ['pass', 'pass'])

    def test_red_churn_of_short_lived_pythons_does_not_refuse_the_real_census(self):
        stop = threading.Event()
        spawned = []
        def churn():
            while not stop.is_set():
                proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.05)'],
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                spawned.append(proc.pid)
                time.sleep(0.1)
                proc.kill()
                proc.wait()
        # Only the churn is under test: rows that existed before it (other seats' long-lived lanes) are judged by the
        # commit/training predicates, which the refusal audit (lead ruling 81910) covers separately.
        before = {r['ProcessId'] for r in runner.process_census()}
        worker = threading.Thread(target=churn, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 20
            rounds = 0
            while time.monotonic() < deadline and rounds < 8:
                rows = [r for r in runner.process_census() if r['ProcessId'] not in before or r['ProcessId'] == os_pid()
                        or r['ProcessId'] in ancestors_of(os_pid())]
                runner.reject_unowned_model_processes(rows, set(), os_pid(), reread=runner.process_census)
                launch.reject_resource_conflicts(rows, os_pid(), set(), reread=runner.process_census)
                rounds += 1
        finally:
            stop.set()
            worker.join(5)
        self.assertGreater(len(spawned), 5)
        self.assertGreater(rounds, 0)

    def test_red_a_live_foreign_gpu_holder_still_refuses(self):
        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            time.sleep(0.5)
            rows = runner.process_census()
            self.assertIn(holder.pid, {r['ProcessId'] for r in rows})
            with self.assertRaisesRegex(ValueError, 'requires coordination'):
                runner.reject_unowned_model_processes(rows, {holder.pid}, os_pid(), reread=runner.process_census)
            with self.assertRaisesRegex(ValueError, 'requires coordination'):
                launch.reject_resource_conflicts(rows, os_pid(), {holder.pid}, reread=runner.process_census)
        finally:
            holder.kill()
            holder.wait()


def ancestors_of(pid):
    rows = {r['ProcessId']: r for r in runner.process_census()}
    seen = set()
    while pid in rows and pid not in seen:
        seen.add(pid)
        pid = rows[pid]['ParentProcessId']
    return seen


def os_pid():
    import os
    return os.getpid()


if __name__ == '__main__':
    unittest.main()
