"""CPU checks of declared hour identity and completion accounting; no training claim."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
spec = importlib.util.spec_from_file_location('tested_launch_tail_runner', SOURCE)
runner = importlib.util.module_from_spec(spec)
sys.modules['tested_launch_tail_runner'] = runner
spec.loader.exec_module(runner)


def owned(returncode=0, cleanup=True, status='completed'):
    return types.SimpleNamespace(status=status, returncode=returncode, cleanup_verified=cleanup)


class LaunchTailTests(unittest.TestCase):
    def custody(self, terminal):
        directory = Path(tempfile.mkdtemp(prefix='launch-tail-'))
        if terminal is not None:
            (directory / 'worker-terminal.json').write_text(json.dumps(terminal), encoding='utf-8')
        return directory

    def test_completed_terminal_file_is_success(self):
        self.assertTrue(runner.launch_succeeded(owned(), None, self.custody({'status': 'completed'})))

    def test_terminated_worker_without_terminal_file_is_failure(self):
        # The first chained hour: wall kill, owned.json status "completed", no worker-terminal.json.
        self.assertFalse(runner.launch_succeeded(owned(0), None, self.custody(None)))

    def test_wall_terminated_run_with_rc0_is_failure_even_with_a_terminal_file(self):
        # The recorded shape of the first chained hour: status terminated, returncode 0, cleanup verified, no supervisor failure.
        self.assertFalse(runner.launch_succeeded(owned(0, True, 'terminated'), None, self.custody(None)))
        self.assertFalse(runner.launch_succeeded(owned(0, True, 'terminated'), None, self.custody({'status': 'completed'})))

    def test_failed_or_garbled_terminal_file_is_failure(self):
        self.assertFalse(runner.launch_succeeded(owned(), None, self.custody({'status': 'failed'})))
        directory = self.custody(None)
        (directory / 'worker-terminal.json').write_text('{', encoding='utf-8')
        self.assertFalse(runner.launch_succeeded(owned(), None, directory))

    def test_nonzero_exit_unverified_cleanup_and_supervisor_failure_are_failures(self):
        terminal = {'status': 'completed'}
        self.assertFalse(runner.launch_succeeded(owned(1), None, self.custody(terminal)))
        self.assertFalse(runner.launch_succeeded(owned(0, False), None, self.custody(terminal)))
        self.assertFalse(runner.launch_succeeded(owned(), 'oom', self.custody(terminal)))

    def test_hour_wall_covers_startup_hour_and_tail_bound(self):
        self.assertEqual(runner.HOUR_WALL_SECONDS, 256 + 3600 + 1800)

    def test_tail_stamp_appends_ordered_rows_and_refuses_unknown_phase(self):
        directory = self.custody(None)
        for phase in runner.TAIL_PHASES:
            runner.tail_stamp(directory, phase)
        rows = [json.loads(line) for line in (directory / 'tail-stamps.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([row['phase'] for row in rows], list(runner.TAIL_PHASES))
        self.assertEqual(sorted(row['monotonic_s'] for row in rows), [row['monotonic_s'] for row in rows])
        self.assertTrue(all(row['wall_utc'].endswith('Z') for row in rows))
        with self.assertRaises(ValueError):
            runner.tail_stamp(directory, 'bogus')


if __name__ == '__main__':
    unittest.main()
