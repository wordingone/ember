"""CPU checks of declared hour identity and completion accounting; no training claim."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import ast
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


TOOLS = SOURCE.parent


def stamp_calls(path, function):
    """(lineno, phase) for every tail_stamp(...) call lexically inside `function` of `path`, in source order (nested defs included)."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
    found = []
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and getattr(call.func, 'attr', getattr(call.func, 'id', None)) == 'tail_stamp':
            found.append((call.lineno, call.args[1].value))
    return sorted(found)


class RealCallOrderTests(unittest.TestCase):
    """The declared TAIL_PHASES must equal the order the real call sites execute, derived from the code (not from TAIL_PHASES)."""

    def derived_order(self):
        hour = TOOLS / 'cia_hour.py'
        launch = stamp_calls(SOURCE, 'launch')
        worker = stamp_calls(SOURCE, 'worker')
        run_hour = dict((phase, line) for line, phase in stamp_calls(hour, 'run_hour'))
        verifier = [phase for _, phase in stamp_calls(hour, 'checkpoint_publisher')]
        self.assertEqual(verifier, ['quarantine', 'counter'])  # the checkpoint verifier runs inside the publish call below
        self.assertEqual([p for _, p in launch], ['segment_launch', 'segment_complete'])
        self.assertEqual([p for _, p in worker], ['worker_terminal'])
        self.assertLess(run_hour['child_publish_start'], run_hour['hour_result'])
        self.assertLess(run_hour['hour_result'], run_hour['pointer_cas'])
        # publish() (which calls the verifier) is invoked between child_publish_start and hour_result in run_hour.
        source = hour.read_text(encoding='utf-8').splitlines()
        publish_line = next(i + 1 for i, text in enumerate(source) if text.strip().startswith("child = publish('trained-child'"))
        self.assertTrue(run_hour['child_publish_start'] < publish_line < run_hour['hour_result'])
        # Control flow: launch() start, then the worker runs run_hour then stamps worker_terminal, then launch() completes.
        return ['segment_launch', 'child_publish_start'] + verifier + ['hour_result', 'pointer_cas', 'worker_terminal', 'segment_complete']

    def test_declared_phase_order_is_the_order_the_real_calls_execute(self):
        self.assertEqual(self.derived_order(), list(runner.TAIL_PHASES))

    def test_worker_terminal_is_written_after_run_hour_returns(self):
        text = SOURCE.read_text(encoding='utf-8')
        call = text.index('execute(runner=sys.modules[__name__]')
        self.assertLess(call, text.index("tail_stamp(custody, 'worker_terminal')"))

    def test_the_old_order_fails_the_derivation_red(self):
        old = ['segment_launch', 'child_publish_start', 'quarantine', 'counter', 'worker_terminal', 'hour_result', 'pointer_cas']
        self.assertNotEqual(self.derived_order(), old)

    def test_segment_complete_follows_owned_receipt_and_needs_verified_cleanup(self):
        text = SOURCE.read_text(encoding='utf-8')
        owned_write = text.index("_write_new(custody / 'owned.json', receipt)")
        complete = text.index("tail_stamp(custody, 'segment_complete')")
        self.assertLess(owned_write, complete)
        self.assertIn('if result.cleanup_verified:', text[owned_write:complete])
        self.assertLess(complete, text.index('succeeded = launch_succeeded('))


if __name__ == '__main__':
    unittest.main()
