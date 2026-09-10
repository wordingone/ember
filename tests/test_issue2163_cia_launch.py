# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ember.governance.scripts import cia_conformance_launch as launch


class FixedLaunchTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows resource census')
    def test_census_refuses_resource_conflict_without_killing_it(self):
        rows = [{'ProcessId': 1, 'ParentProcessId': 0, 'Name': 'codex.exe'},
                {'ProcessId': 2, 'ParentProcessId': 1, 'Name': 'python.exe'}]
        launch.reject_resource_conflicts(rows, 2)
        rows.append({'ProcessId': 3, 'ParentProcessId': 0, 'Name': 'python.exe',
                     'PageFileUsage': 1024**2, 'CommandLine': 'python.exe unknown.py'})
        with self.assertRaisesRegex(ValueError, 'resource-consuming'):
            launch.reject_resource_conflicts(rows, 2)

    def test_worker_refuses_extra_command_before_importing_test(self):
        from tempfile import TemporaryDirectory
        import json
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'subject.json'
            path.write_text(json.dumps({'launch': {'worker_argv': ['expected']}}))
            with patch.object(sys, 'argv', ['other']), patch.object(launch.runpy, 'run_path') as execute:
                with self.assertRaisesRegex(ValueError, 'worker argv'):
                    launch.worker(path)
                execute.assert_not_called()

    def test_missing_or_changed_limits_fail_before_resource_access(self):
        with self.assertRaisesRegex(ValueError, 'fields differ'):
            launch.verify_envelope(launch.ROOT, {'launch': {}})

    def test_launch_is_not_an_arbitrary_command_interface(self):
        with patch.object(sys, 'argv', ['launcher', '--live', '--command', 'arbitrary']):
            with self.assertRaises(SystemExit):
                launch.main()

    def test_python_descendants_use_the_hidden_wrapper(self):
        command = launch.python_command(Path('headless.ps1'), Path('hidden.py'), 'fixed.py', '--live')
        self.assertEqual(command, ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                                  '-File', 'headless.ps1', '--', '-B', 'hidden.py', 'fixed.py', '--live'])

    def test_a_refusing_consumer_records_its_terminal_state_in_custody(self):
        """A governed refusal that reaches custody empty costs another single-use unit to re-ask.

        Measured 2026-09-10: a unit whose consumer refused after about 16 seconds landed with both
        relayed logs at zero bytes, while the same command outside the job object produced 1,245
        bytes of refusal. So the worker writes its own account on the near side of the relay.
        """
        from tempfile import TemporaryDirectory
        import json
        with TemporaryDirectory() as temp:
            custody = Path(temp)
            path = custody / 'subject.json'
            path.write_text(json.dumps({'launch': {'worker_argv': ['bound'], 'custody': str(custody)}}))
            failure = ValueError('deliberate consumer refusal')
            with patch.object(sys, 'argv', ['bound']), \
                    patch.object(launch.runpy, 'run_path', side_effect=failure):
                with self.assertRaisesRegex(ValueError, 'deliberate consumer refusal'):
                    launch.worker(path)
            terminal = json.loads((custody / 'worker-terminal.json').read_text(encoding='utf-8'))
            self.assertEqual(terminal['terminal'], 'ValueError')
            self.assertEqual(terminal['detail'], 'deliberate consumer refusal')
            self.assertIn('deliberate consumer refusal', terminal['traceback'])
            self.assertTrue((custody / 'worker-stdout.log').exists())
            self.assertTrue((custody / 'worker-stderr.log').exists())

    def test_the_consumers_own_output_reaches_custody_and_the_real_stream(self):
        from tempfile import TemporaryDirectory
        import io
        import json
        with TemporaryDirectory() as temp:
            custody = Path(temp)
            path = custody / 'subject.json'
            path.write_text(json.dumps({'launch': {'worker_argv': ['bound'], 'custody': str(custody)}}))
            real = io.StringIO()

            def emit(*args, **kwargs):
                print('CIA_CUDA_PHASE fixture', flush=True)

            with patch.object(sys, 'argv', ['bound']), patch.object(sys, 'stdout', real), \
                    patch.object(launch.runpy, 'run_path', side_effect=emit):
                launch.worker(path)
            # Tee, never redirect: losing the relayed copy must not lose the custody copy, and
            # writing the custody copy must not remove the relayed one.
            self.assertIn('CIA_CUDA_PHASE fixture', real.getvalue())
            self.assertIn('CIA_CUDA_PHASE fixture',
                          (custody / 'worker-stdout.log').read_text(encoding='utf-8'))
            self.assertFalse((custody / 'worker-terminal.json').exists())


if __name__ == '__main__':
    unittest.main()
