# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ember.governance.scripts import cia_conformance_launch as body
from ember.governance.scripts import ember_dispatch_token


class DaemonEntry(unittest.TestCase):
    def argv(self):
        return [str(body.ROOT / body.RELATIVE_ENTRY), '--daemon-run', '--custody',
                str(Path('B:/candidate')), '--hidden-helper', str(Path('C:/hidden.py'))]

    def test_missing_daemon_authority_refuses_before_launch(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'argv', self.argv()), patch.object(body, 'launch') as launch:
            with self.assertRaisesRegex(ember_dispatch_token.DispatchTokenError, 'DISPATCH_REQUIRED'):
                body.main()
            launch.assert_not_called()

    def test_wrong_authenticated_cap_refuses_before_launch(self):
        for cap in (0, body.resources.HOST_MEMORY_BYTES - 1, float(body.resources.HOST_MEMORY_BYTES)):
            with self.subTest(cap=cap), patch.object(sys, 'argv', self.argv()), patch.object(ember_dispatch_token, 'consume_dispatch', return_value=cap), patch.object(body, 'launch') as launch:
                with self.assertRaisesRegex(ValueError, 'cap differs'):
                    body.main()
                launch.assert_not_called()

    def test_token_consumption_precedes_run_body_and_no_token_is_recorded(self):
        events = []
        def consume(root):
            self.assertEqual(root, body.ROOT)
            events.append('consume')
            return body.resources.HOST_MEMORY_BYTES
        def launch(custody, hidden, dispatch):
            events.append('launch')
            self.assertEqual(set(dispatch), {'job_id', 'daemon_pid', 'memory_cap'})
            self.assertEqual(dispatch['daemon_pid'], 123)
            return 0
        with patch.dict(os.environ, {'EMBER_LAB_DISPATCH_JOB_ID': 'fixture', 'EMBER_LAB_DISPATCH_DAEMON_PID': '123'}), patch.object(sys, 'argv', self.argv()), patch.object(ember_dispatch_token, 'consume_dispatch', side_effect=consume), patch.object(body, 'launch', side_effect=launch):
            self.assertEqual(body.main(), 0)
        self.assertEqual(events, ['consume', 'launch'])

    def test_reordered_argv_refuses_even_if_argparse_accepts_it(self):
        argv = self.argv()
        argv = [argv[0], *argv[2:], argv[1]]
        with patch.object(sys, 'argv', argv), patch.object(ember_dispatch_token, 'consume_dispatch') as consume:
            with self.assertRaisesRegex(ValueError, 'argv differs'):
                body.main()
            consume.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'Windows native command parsing')
class ControllerIdentity(unittest.TestCase):
    def fixture(self):
        import subprocess
        hidden = str(Path(__file__).resolve())
        executable = str(Path(sys.executable).resolve())
        argv = [executable, '-B', str(body.ROOT / body.RELATIVE_ENTRY),
                '--daemon-run', '--custody', str(Path('B:/candidate')),
                '--hidden-helper', hidden]
        owner = {'ProcessId': 10, 'ParentProcessId': 20,
                 'ExecutablePath': executable, 'CommandLine': subprocess.list2cmdline(argv)}
        parent = {'ProcessId': 20, 'ExecutablePath': executable}
        binding = {'daemon': {'fixture': True}, 'launch': {
            'custody': str(Path('B:/candidate/numerical')),
            'helpers': {str(Path.home() / '.codex/headless-python.ps1'): 'fixture', hidden: 'fixture'}}}
        return binding, owner, parent, argv

    def validate(self, binding, owner, parent):
        with patch.object(ember_dispatch_token, '_canonical_ember_lab_binary', return_value=Path(sys.executable)), patch.object(body.subject, 'daemon_identity', return_value={'fixture': True}):
            body.verify_controller_identity(body.ROOT, binding, owner, [owner, parent])

    def test_exact_identity_fixture_accepts(self):
        binding, owner, parent, _ = self.fixture()
        self.validate(binding, owner, parent)

    def test_native_extended_length_program_identity_accepts(self):
        import subprocess
        binding, owner, parent, argv = self.fixture()
        argv[0] = '\\\\?\\' + argv[0]
        owner['CommandLine'] = subprocess.list2cmdline(argv)
        self.validate(binding, owner, parent)

    def test_path_substring_or_import_call_cannot_impersonate_run_body(self):
        import subprocess
        for prefix in ('-c', '--worker'):
            binding, owner, parent, argv = self.fixture()
            owner['CommandLine'] = subprocess.list2cmdline([sys.executable, prefix, argv[2]])
            with self.assertRaisesRegex(ValueError, 'exact executable or argv'):
                self.validate(binding, owner, parent)

    def test_fabricated_parent_pid_does_not_authenticate_parent_image(self):
        binding, owner, parent, _ = self.fixture()
        parent['ExecutablePath'] = __file__
        with self.assertRaisesRegex(ValueError, 'bound canonical daemon'):
            self.validate(binding, owner, parent)

    def test_bound_daemon_identity_drift_refuses(self):
        binding, owner, parent, _ = self.fixture()
        binding['daemon'] = {'fixture': 'changed'}
        with self.assertRaisesRegex(ValueError, 'bound canonical daemon'):
            self.validate(binding, owner, parent)


if __name__ == '__main__':
    unittest.main()
