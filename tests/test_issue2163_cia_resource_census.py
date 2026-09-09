# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ember.governance.scripts import cia_conformance_launch as launch


@unittest.skipUnless(sys.platform == 'win32', 'Windows process command-line semantics')
class ResourceCensus(unittest.TestCase):
    def setUp(self):
        self.rows = [{'ProcessId': 1, 'ParentProcessId': 0, 'Name': 'codex.exe'},
                     {'ProcessId': 2, 'ParentProcessId': 1, 'Name': 'python.exe'}]

    def add(self, commit=2048, command='python.exe telemetry_meter.py --seat peer'):
        self.rows.append({'ProcessId': 3, 'ParentProcessId': 0, 'Name': 'python.exe',
                          'PageFileUsage': commit, 'CommandLine': command})

    def test_small_telemetry_and_owned_ancestry_pass(self):
        self.add()
        launch.reject_resource_conflicts(self.rows, 2, {2})

    def test_large_commit_or_training_entry_or_gpu_context_refuses(self):
        for commit, command, gpu in ((1024**2, 'python.exe unknown.py', set()),
                                     (2048, 'python.exe train.py', set()),
                                     (2048, 'python.exe unknown.py', {3})):
            with self.subTest(commit=commit, command=command, gpu=gpu):
                self.setUp(); self.add(commit, command)
                with self.assertRaisesRegex(ValueError, 'resource-consuming'):
                    launch.reject_resource_conflicts(self.rows, 2, gpu)

    def test_missing_classification_refuses(self):
        self.add(None)
        with self.assertRaisesRegex(ValueError, 'cannot classify'):
            launch.reject_resource_conflicts(self.rows, 2)

    def test_exited_gpu_pid_is_not_retained(self):
        launch.reject_resource_conflicts(self.rows, 2, {999})

    def test_wddm_desktop_graphics_is_not_a_python_trainer(self):
        self.rows.append({'ProcessId': 4, 'ParentProcessId': 0, 'Name': 'dwm.exe'})
        launch.reject_resource_conflicts(self.rows, 2, {4})

    def test_quoted_windows_training_path_and_harmless_similar_name(self):
        self.assertTrue(launch.training_command('"C:\\Program Files\\Python310\\python.exe" "B:\\work folder\\pretrain.py"'))
        self.assertFalse(launch.training_command('python.exe "B:\\work folder\\constraint.py"'))
        self.assertFalse(launch.training_command('python.exe training_closure.py'))


if __name__ == '__main__':
    unittest.main()
