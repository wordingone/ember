"""Issue #2119 row 9: the fresh-session head load. Synthetic pointer, hour result and head directory in a temp dir; the real admission is injected
(the real one reads the multi-GiB checkpoint and is run once under a declared tenant, its receipt is the row 9 evidence). Each guard carries a deliberate red."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import fresh_session_head_load as fresh  # noqa: E402


class LoadHeadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.calls = []
        self.receipts = self.root / 'receipts'
        self.measurement = self.receipts / 'measurement-x'
        self.child = self.measurement / 'trained-child'
        self.child.mkdir(parents=True)
        manifest = json.dumps({'max_restore_payload_bytes': 1234, 'k': 1}, sort_keys=True).encode()
        (self.child / 'checkpoint-manifest.json').write_bytes(manifest)
        self.head = hashlib.sha256(manifest).hexdigest()
        hour = json.dumps({'child_manifest_sha256': self.head}, sort_keys=True).encode()
        self.hour = self.measurement / 'hour-result.json'
        self.hour.write_bytes(hour)
        self.write_pointer(self.head, hashlib.sha256(hour).hexdigest())

    def write_pointer(self, head, hour_sha):
        pointer = {'hour_result_path': str(self.hour), 'hour_result_sha256': hour_sha, 'lineage_checkpoint_manifest_sha256': head,
                   'published_at': 1.0, 'schema': 'ember-selected-continuation-head-v1', 'seeded_reason': ''}
        (self.receipts / 'selected-continuation-head.json').write_text(json.dumps(pointer, sort_keys=True), encoding='utf-8')

    def strict_admit(self, path, expected, cap):
        self.calls.append((Path(path), expected, cap))
        if expected != self.head:
            raise ValueError('CIA parent manifest digest differs from its bound identity')
        return {'global_step': 7, 'genesis_kind': 'VERIFIED_DESCENDANT_PARENT'}

    def test_loads_the_pointer_head_with_the_pointer_digest_and_manifest_cap(self):
        result = fresh.load_head(self.receipts, controls=True, admit=self.strict_admit)
        self.assertEqual(self.calls[0], (self.child, self.head, 1234))      # the real admission
        self.assertEqual(self.calls[1][1], '0' * 64)                         # then the wrong-digest control, which must differ
        self.assertEqual(result['admission']['outcome'], 'ADMITTED')
        self.assertEqual(result['admission']['global_step'], 7)
        self.assertEqual(result['control_wrong_digest']['outcome'], 'REFUSED')
        self.assertEqual(result['lineage_head'], self.head)
        self.assertEqual(result['pointer_sha256'], hashlib.sha256((self.receipts / 'selected-continuation-head.json').read_bytes()).hexdigest())

    def test_one_load_binds_every_later_read_to_the_pointer_generation_it_parsed_DELIBERATE_RED(self):
        import selected_continuation_head as sch
        pointer_file = self.receipts / 'selected-continuation-head.json'
        first_generation = hashlib.sha256(pointer_file.read_bytes()).hexdigest()
        real_parse = sch.parse_selected_continuation_head

        def parse_then_a_writer_replaces_the_pointer(raw):
            parsed = real_parse(raw)
            self.write_pointer('f' * 64, '0' * 64)                      # a concurrent writer publishes the next generation right after this load parsed the first
            return parsed
        with unittest.mock.patch.object(sch, 'parse_selected_continuation_head', parse_then_a_writer_replaces_the_pointer):
            result = fresh.load_head(self.receipts, admit=self.strict_admit)
        second_generation = hashlib.sha256(pointer_file.read_bytes()).hexdigest()
        self.assertNotEqual(first_generation, second_generation)
        self.assertEqual(result['pointer_sha256'], first_generation)     # the receipt names the bytes that were parsed, not whatever is on disk afterwards
        self.assertEqual(result['lineage_head'], self.head)
        self.assertEqual(result['admission']['outcome'], 'ADMITTED')

    def test_hour_result_bytes_must_hash_to_the_pointer_DELIBERATE_RED(self):
        self.write_pointer(self.head, '0' * 64)
        with self.assertRaisesRegex(fresh.LoadRefusal, 'do not hash'):
            fresh.load_head(self.receipts, admit=lambda *a: (_ for _ in ()).throw(AssertionError('admission must not run')))

    def test_head_manifest_bytes_must_hash_to_the_pointer_head(self):
        (self.child / 'checkpoint-manifest.json').write_bytes(b'{"max_restore_payload_bytes": 1}')
        with self.assertRaisesRegex(fresh.LoadRefusal, 'manifest bytes do not hash'):
            fresh.load_head(self.receipts, admit=self.strict_admit)

    def test_missing_pointer_and_missing_head_directory_refuse(self):
        with self.assertRaisesRegex(fresh.LoadRefusal, 'no selected-continuation-head pointer'):
            fresh.load_head(self.root / 'elsewhere', admit=self.strict_admit)
        with self.assertRaisesRegex(fresh.LoadRefusal, 'no checkpoint-manifest.json'):
            fresh.load_head(self.receipts, head_dir=self.root / 'absent', admit=self.strict_admit)

    def test_a_refusing_admission_is_recorded_not_raised(self):
        def refuse(path, expected, cap):
            raise ValueError('component digest mismatch')
        result = fresh.load_head(self.receipts, admit=refuse)
        self.assertEqual(result['admission']['outcome'], 'REFUSED')
        self.assertIn('component digest mismatch', result['admission']['error'])


class ChildExitTests(unittest.TestCase):
    def run_child(self, result, *extra):
        out = io.StringIO()
        with unittest.mock.patch.object(fresh, 'load_head', return_value=result), contextlib.redirect_stdout(out):
            code = fresh.child_main(['--receipts-root', '.', *extra])
        return code, out.getvalue()

    def test_admitted_with_a_refused_control_exits_zero(self):
        code, out = self.run_child({'admission': {'outcome': 'ADMITTED'}, 'control_wrong_digest': {'outcome': 'REFUSED'}}, '--controls')
        self.assertEqual(code, 0)
        self.assertIn(fresh.CHILD_MARKER, out)

    def test_a_control_that_does_not_refuse_exits_4_DELIBERATE_RED(self):
        code, _ = self.run_child({'admission': {'outcome': 'ADMITTED'}, 'control_wrong_digest': {'outcome': 'ADMITTED'}}, '--controls')
        self.assertEqual(code, 4)

    def test_a_refused_admission_exits_4(self):
        code, _ = self.run_child({'admission': {'outcome': 'REFUSED'}})
        self.assertEqual(code, 4)


class RunFreshTests(unittest.TestCase):
    def test_child_is_a_different_process_and_facts_are_recorded(self):
        script = 'import json,os;print("noise");print("%s"+json.dumps({"pid":os.getpid(),"result":{}}))' % fresh.CHILD_MARKER
        child = fresh.run_fresh(fresh.python_argv('-c', script))
        self.assertNotEqual(child['pid'], os.getpid())
        self.assertEqual(child['parent_pid'], os.getpid())
        self.assertEqual(child['child_exit'], 0)

    def test_a_child_claiming_the_parent_pid_refuses_DELIBERATE_RED(self):
        script = 'import json;print("%s"+json.dumps({"pid":%d,"result":{}}))' % (fresh.CHILD_MARKER, os.getpid())
        with self.assertRaisesRegex(fresh.LoadRefusal, 'not a fresh session'):
            fresh.run_fresh(fresh.python_argv('-c', script))

    def test_a_child_with_no_result_line_refuses(self):
        with self.assertRaisesRegex(fresh.LoadRefusal, 'no result'):
            fresh.run_fresh(fresh.python_argv('-c', 'print("nothing useful")'))

    def test_a_crashing_child_refuses(self):
        with self.assertRaisesRegex(fresh.LoadRefusal, 'no result'):
            fresh.run_fresh(fresh.python_argv('-c', 'raise SystemExit(9)'))


class ChildBoundaryTests(unittest.TestCase):
    """The fresh child is a hidden, wrapped process on Windows, never a bare sys.executable child."""
    WRAPPED = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', 'helpers/.codex/headless-python.ps1', '--', '-B', 'child.py']

    def hidden(self):
        class Startup:
            wShowWindow = 0
        return {'creationflags': 0x08000000, 'startupinfo': Startup(), 'shell': False}

    def test_a_hidden_wrapped_child_passes_the_boundary(self):
        self.assertEqual(fresh.child_boundary_problems(self.WRAPPED, self.hidden(), windows=True), [])
        self.assertEqual(fresh.child_boundary_problems([sys.executable, '-B', 'child.py'], {'shell': False}, windows=False), [])

    def test_a_bare_sys_executable_child_on_windows_fails_the_boundary_DELIBERATE_RED(self):
        problems = fresh.child_boundary_problems([sys.executable, '-B', 'child.py'], {}, windows=True)
        self.assertEqual(len(problems), 3, problems)
        self.assertIn('mandatory headless-python.ps1 wrapper', problems[0])
        self.assertTrue(any('CREATE_NO_WINDOW' in p for p in problems) and any('STARTUPINFO' in p for p in problems))

    def test_each_missing_piece_is_named_on_its_own_DELIBERATE_RED(self):
        self.assertEqual(len(fresh.child_boundary_problems(self.WRAPPED, dict(self.hidden(), creationflags=0), windows=True)), 1)
        self.assertEqual(len(fresh.child_boundary_problems(self.WRAPPED, dict(self.hidden(), startupinfo=None), windows=True)), 1)
        self.assertEqual(len(fresh.child_boundary_problems(['python', 'child.py'], self.hidden(), windows=True)), 1)
        self.assertEqual(len(fresh.child_boundary_problems(self.WRAPPED, dict(self.hidden(), shell=True), windows=True)), 1)

    def test_run_fresh_refuses_a_bare_child_before_spawning_anything_on_windows_DELIBERATE_RED(self):
        with unittest.mock.patch.object(fresh.os, 'name', 'nt'), unittest.mock.patch.object(fresh, 'hidden_kwargs', return_value={'shell': False}), \
                unittest.mock.patch.object(fresh.subprocess, 'run', side_effect=AssertionError('must not spawn')):
            with self.assertRaisesRegex(fresh.LoadRefusal, 'process boundary'):
                fresh.run_fresh([sys.executable, '-B', 'child.py'])

    def test_the_real_launch_command_and_kwargs_satisfy_the_boundary(self):
        command, kwargs = fresh.python_argv('child.py'), fresh.hidden_kwargs()
        self.assertEqual(fresh.child_boundary_problems(command, kwargs, windows=os.name == 'nt'), [])
        if os.name == 'nt':
            self.assertEqual(command[:5], ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File'])
            self.assertTrue(kwargs['creationflags'] & 0x08000000)
        else:
            self.assertEqual(command[0], sys.executable)


if __name__ == '__main__':
    unittest.main()
