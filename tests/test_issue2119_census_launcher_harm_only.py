# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The launcher resource census refuses only on harm to the run (lead ruling 81909, 2026-11-09).

H44 attempts 1-3 (2026-11-08 and 2026-11-09) died on a short-lived python from another lane, caught mid-start with no command
line or already exited when looked up. A process can only matter if it holds GPU memory or runs a training entry, so:
(a) an unreadable row not listed by nvidia-smi is ignored; (b) a GPU-listed unreadable row is re-read 3 times over 2 s and
refuses only if it stays live and unreadable; (c) an exited row is ignored; (d) the own-commit arm is gone.
Reds: a churn of pythons spawned and killed every 100 ms does not refuse the real host census; a live foreign GPU holder refuses.
"""
from pathlib import Path
import os
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ember.governance.scripts import cia_conformance_launch as launch

NOSLEEP = lambda seconds: None


def base():
    return [{'ProcessId': 1, 'ParentProcessId': 0, 'Name': 'codex.exe'},
            {'ProcessId': 2, 'ParentProcessId': 1, 'Name': 'python.exe'}]


def unreadable(pid=3, **extra):
    return dict({'ProcessId': pid, 'ParentProcessId': 0, 'Name': 'python.exe', 'PageFileUsage': None, 'CommandLine': None}, **extra)


def verdict(rows, gpu, reread):
    try:
        launch.reject_resource_conflicts(rows, 2, set(gpu), reread=reread, sleep=NOSLEEP)
        return 'pass'
    except ValueError:
        return 'refuse'


@unittest.skipUnless(sys.platform == 'win32', 'Windows process census')
class LauncherHarmOnlyCensus(unittest.TestCase):
    def test_a_unreadable_row_not_on_the_gpu_is_ignored(self):
        rows = base() + [unreadable()]
        self.assertEqual(verdict(rows, set(), lambda: rows), 'pass')

    def test_b_gpu_listed_unreadable_row_that_exits_or_vanishes_is_ignored(self):
        rows = base() + [unreadable()]
        self.assertEqual(verdict(rows, {3}, lambda: base()), 'pass')
        self.assertEqual(verdict(rows, {3}, lambda: base() + [unreadable(HasExited=True)]), 'pass')

    def test_b_gpu_listed_row_that_stays_live_and_unreadable_refuses_after_three_rereads(self):
        rows = base() + [unreadable()]
        calls = []

        def reread():
            calls.append(1)
            return rows
        self.assertEqual(verdict(rows, {3}, reread), 'refuse')
        self.assertEqual(len(calls), launch.UNREADABLE_REREADS)

    def test_b_gpu_listed_row_that_becomes_readable_is_classified_and_refuses_as_a_gpu_holder(self):
        rows = base() + [unreadable()]
        fresh = base() + [{'ProcessId': 3, 'ParentProcessId': 0, 'Name': 'python.exe', 'PageFileUsage': 2048,
                           'CommandLine': 'python.exe holder.py'}]
        self.assertEqual(verdict(rows, {3}, lambda: fresh), 'refuse')

    def test_c_exited_unreadable_row_is_ignored_without_reread(self):
        rows = base() + [unreadable(HasExited=True)]
        self.assertEqual(verdict(rows, {3}, lambda: self.fail('no reread for an exited row')), 'pass')

    def test_d_own_commit_alone_is_not_a_refusal_but_a_training_entry_is(self):
        big = base() + [{'ProcessId': 3, 'ParentProcessId': 0, 'Name': 'python.exe', 'PageFileUsage': 15 * 1024 ** 2,
                         'CommandLine': 'python.exe serve.py'}]
        self.assertEqual(verdict(big, set(), lambda: big), 'pass')
        train = base() + [{'ProcessId': 3, 'ParentProcessId': 0, 'Name': 'python.exe', 'PageFileUsage': 2048,
                           'CommandLine': 'python.exe train.py'}]
        self.assertEqual(verdict(train, set(), lambda: train), 'refuse')

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
        # Only the churn is under test: rows that existed before it are long-lived lanes judged by the training/GPU
        # predicates, which the foreign-holder red below covers.
        before = {row['ProcessId'] for row in launch.process_census()}
        worker = threading.Thread(target=churn, daemon=True)
        worker.start()
        try:
            deadline, rounds = time.monotonic() + 20, 0
            while time.monotonic() < deadline and rounds < 8:
                rows = [row for row in launch.process_census()
                        if row['ProcessId'] not in before or row['ProcessId'] == os.getpid()]
                launch.reject_resource_conflicts(rows, os.getpid(), set(), reread=launch.process_census)
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
            rows = launch.process_census()
            self.assertIn(holder.pid, {row['ProcessId'] for row in rows})
            with self.assertRaisesRegex(ValueError, 'requires coordination'):
                launch.reject_resource_conflicts(rows, os.getpid(), {holder.pid}, reread=launch.process_census)
        finally:
            holder.kill()
            holder.wait()

