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
        pointer = {'hour_result_path': str(self.hour).replace('/', '\\'), 'hour_result_sha256': hour_sha, 'lineage_checkpoint_manifest_sha256': head,
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
        child = fresh.run_fresh([sys.executable, '-B', '-c', script])
        self.assertNotEqual(child['pid'], os.getpid())
        self.assertEqual(child['parent_pid'], os.getpid())
        self.assertEqual(child['child_exit'], 0)

    def test_a_child_claiming_the_parent_pid_refuses_DELIBERATE_RED(self):
        script = 'import json;print("%s"+json.dumps({"pid":%d,"result":{}}))' % (fresh.CHILD_MARKER, os.getpid())
        with self.assertRaisesRegex(fresh.LoadRefusal, 'not a fresh session'):
            fresh.run_fresh([sys.executable, '-B', '-c', script])

    def test_a_child_with_no_result_line_refuses(self):
        with self.assertRaisesRegex(fresh.LoadRefusal, 'no result'):
            fresh.run_fresh([sys.executable, '-B', '-c', 'print("nothing useful")'])

    def test_a_crashing_child_refuses(self):
        with self.assertRaisesRegex(fresh.LoadRefusal, 'no result'):
            fresh.run_fresh([sys.executable, '-B', '-c', 'raise SystemExit(9)'])


if __name__ == '__main__':
    unittest.main()
