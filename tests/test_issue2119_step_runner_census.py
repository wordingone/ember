# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The worker-side resource census of cia_step_runner.py classifies an exited Python object the way the launcher census does.

On 2026-10-08 the governed hour's probe worker died at ``cia_step_runner.resource_census`` with
``unowned model resource process requires coordination: 69952`` although pid 69952 had exited (a handle nothing owns keeps the
object listed, 14.67 GiB of commit charged, and nvidia-smi still lists its context). The launcher copy of the census was cured
in #2344; this file pins the second copy and requires both copies to agree on the same rows.
"""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
SUBJECT_PATH = TOOLS / 'cia_step_runner.py'
SPEC = importlib.util.spec_from_file_location('bound_checkout_cia_step_runner_census', SUBJECT_PATH)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
assert Path(runner.__file__).resolve(strict=True) == SUBJECT_PATH.resolve(strict=True)
from ember.governance.scripts import cia_conformance_launch as launch

GIB_KIB = 1024 ** 2


def python_row(pid, exited, commit=15 * GIB_KIB, command='python.exe serve_owned_cia_batch.py', parent=0):
    row = {'ProcessId': pid, 'ParentProcessId': parent, 'Name': 'python.exe', 'PageFileUsage': commit,
           'CommandLine': command}
    if exited is not ...:
        row['HasExited'] = exited
    return row


def base_rows():
    return [{'ProcessId': 1, 'ParentProcessId': 0, 'Name': 'codex.exe'},
            {'ProcessId': 2, 'ParentProcessId': 1, 'Name': 'python.exe'}]


@unittest.skipUnless(sys.platform == 'win32', 'Windows process command-line semantics')
class StepRunnerCensus(unittest.TestCase):
    def check(self, rows, gpu=()):
        runner.reject_unowned_model_processes(rows, set(gpu), 2)

    def test_exited_object_with_charged_commit_is_not_a_tenant(self):
        self.check(base_rows() + [python_row(3, True)])

    def test_exited_object_that_nvidia_smi_still_lists_is_not_a_tenant(self):
        # the pid 69952 shape: exited, 14.67 GiB charged, its context still listed by nvidia-smi
        self.check(base_rows() + [python_row(3, True)], gpu={3})

    def test_live_or_unknown_state_still_refuses(self):
        for exited in (False, None, ...):
            for gpu in (set(), {3}):
                with self.subTest(exited=exited, gpu=gpu):
                    with self.assertRaisesRegex(ValueError, 'requires coordination'):
                        self.check(base_rows() + [python_row(3, exited)], gpu)

    def test_live_small_gpu_listed_python_still_refuses(self):
        with self.assertRaisesRegex(ValueError, 'requires coordination'):
            self.check(base_rows() + [python_row(3, False, commit=2048, command='python.exe unknown.py')], {3})

    def test_a_live_trainer_next_to_an_exited_object_still_refuses(self):
        rows = base_rows() + [python_row(3, True), python_row(4, False, commit=2048, command='python.exe train.py')]
        with self.assertRaisesRegex(ValueError, 'requires coordination: 4'):
            self.check(rows)

    def test_a_refusal_names_the_process(self):
        # Without name, parent and command line a transient pid could not be attributed (pid 79712, 2026-10-08).
        rows = base_rows() + [python_row(4, False, commit=2048, command='python.exe train.py --x', parent=1)]
        with self.assertRaises(ValueError) as caught:
            self.check(rows)
        text = str(caught.exception)
        for needle in ('4', 'python.exe', 'parent=1', 'train.py --x'):
            self.assertIn(needle, text)

    def test_launcher_copy_refusal_names_the_process_too(self):
        rows = base_rows() + [python_row(4, False, commit=2048, command='python.exe train.py --x', parent=1)]
        with self.assertRaises(ValueError) as caught:
            launch.reject_resource_conflicts(rows, 2, set())
        text = str(caught.exception)
        for needle in ('[4]', 'python.exe', 'parent=1', 'train.py --x'):
            self.assertIn(needle, text)

    def test_census_command_reports_the_exit_state_of_python_rows(self):
        seen = []

        def fake(command, **_):
            seen.append(command)

            class Result:
                stdout = json.dumps([{'ProcessId': 1, 'ParentProcessId': 0, 'Name': 'x.exe'}])
            return Result()
        with patch.object(runner, 'run_readonly', fake):
            runner.process_census()
        self.assertIn('HasExited', ' '.join(seen[0]))
        self.assertIn('GetProcessById', ' '.join(seen[0]))

    def test_resource_census_real_path_passes_an_exited_gpu_listed_object_and_refuses_a_live_one(self):
        def fake_run(command, **_):
            class Result:
                stdout = '3\n'
            return Result()
        for exited, refuses in ((True, False), (False, True), (None, True)):
            with self.subTest(exited=exited):
                rows = base_rows() + [python_row(3, exited)]
                with patch.object(runner, 'run_readonly', fake_run), patch.object(runner, 'process_census', lambda: rows), \
                        patch.object(runner.os, 'getpid', lambda: 2):
                    if refuses:
                        with self.assertRaisesRegex(ValueError, 'requires coordination'):
                            runner.resource_census()
                    else:
                        self.assertEqual(runner.resource_census(), rows)

    def test_both_census_copies_agree_on_the_same_rows(self):
        # Two copies of one predicate is how the class survived #2344: every case must give the same verdict in both.
        cases = []
        for exited in (True, False, None, ...):
            for gpu in (set(), {3}):
                for commit, command in ((15 * GIB_KIB, 'python.exe serve.py'), (2048, 'python.exe unknown.py'),
                                        (2048, 'python.exe train.py'), (2048, 'python.exe telemetry_meter.py')):
                    cases.append((exited, gpu, commit, command))
        for exited, gpu, commit, command in cases:
            with self.subTest(exited=exited, gpu=gpu, commit=commit, command=command):
                rows = base_rows() + [python_row(3, exited, commit, command)]
                verdicts = []
                for call in (lambda: launch.reject_resource_conflicts(rows, 2, gpu),
                             lambda: runner.reject_unowned_model_processes(rows, set(gpu), 2)):
                    try:
                        call()
                        verdicts.append('pass')
                    except ValueError:
                        verdicts.append('refuse')
                self.assertEqual(verdicts[0], verdicts[1])

    def test_real_host_exited_python_row_passes_the_real_process_census(self):
        # No fixture: the real Win32_Process census of this host. If an exited Python object is present (pid 69952 on
        # 2026-10-08) it must be reported as exited and must not refuse; if none is present the case is not applicable.
        rows = runner.process_census()
        exited = [row for row in rows if str(row['Name']).lower() in ('python.exe', 'pythonw.exe', 'py.exe')
                  and row.get('HasExited') is True]
        if not exited:
            self.skipTest('no exited python object on this host')
        runner.reject_unowned_model_processes(exited, {int(row['ProcessId']) for row in exited}, 2)


if __name__ == '__main__':
    unittest.main()
