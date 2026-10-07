"""Issue #2119 recovery acceptance: the terminal-state witness is persisted BEFORE the restore verification, and a resumable verify tail reads it.

H35 trained a full hour, published its child, and lost the hour because the independent live-terminal facts existed only in memory when the
restore verification refused. These tests pin the repair without a GPU: the checkpoint and parameter-counter modules are replaced by fakes whose
answers the test controls, so the only things under test are the witness file, the tail's refusals and the order inside `run_hour`.
The deliberate red is the H35 shape itself: a hour killed between publish and verify, then the tail.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
for entry in (str(MODULE_DIR), str(ROOT / 'src')):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import cia_hour  # noqa: E402

CURSOR = {'shard': '0', 'record_index': 4096, 'global_step': 8, 'tokens_seen': 8192}
FACTS = {'inventory': ('a', 'b'), 'counts': {1: 10, 2: 20}, 'total': 30}     # a tuple and int keys: JSON turns them into a list and str keys
RNG = {'cpu': 'c' * 64, 'cuda': 'd' * 64}


class FakeRunner:
    GIB = 1 << 30

    @staticmethod
    def _write_new(path, value):
        with Path(path).open('xb') as stream:
            stream.write(json.dumps(value, sort_keys=True).encode('utf-8'))

    @staticmethod
    def file_sha256(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_child(root: Path, *, tokens=8192) -> str:
    root.mkdir(parents=True)
    raw = json.dumps({'schema_version': 'fixture', 'data_cursor': dict(CURSOR, tokens_seen=tokens), 'rng_state_sha256': RNG}, sort_keys=True).encode()
    (root / 'checkpoint-manifest.json').write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fake_modules(*, facts=FACTS, restored_facts=None, child_for_receipt=None):
    """checkpoint_artifacts / parameter_counter stand-ins: the reopened bytes yield `facts`; the restored state yields `restored_facts or facts`."""
    def published_checkpoint_receipt(root):
        manifest = json.loads((Path(root) / 'checkpoint-manifest.json').read_bytes())
        sha = hashlib.sha256((Path(root) / 'checkpoint-manifest.json').read_bytes()).hexdigest()
        return {**manifest, 'checkpoint_manifest_sha256': sha, 'checkpoint': {'byte_sha256': sha}}

    artifacts = types.SimpleNamespace(
        published_checkpoint_receipt=published_checkpoint_receipt,
        load_checkpoint_artifacts=lambda *a, **k: {'data_cursor': dict(CURSOR)},
        capture_cia_placed_optimizer_state=lambda *a, **k: {'state': 'native'},
        _cia_lineage_facts=lambda inventory, state: restored_facts if restored_facts is not None else facts)

    def realization_receipt(root, child, *, model_config_sha256, _facts=None):
        _facts.update(facts)

    counter = types.SimpleNamespace(_cia_realization_receipt=realization_receipt)
    return patch.dict(sys.modules, {'checkpoint_artifacts': artifacts, 'parameter_counter': counter})


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.custody = Path(self._tmp.name)
        self.child_sha = write_child(self.custody / 'trained-child')
        self.runner = FakeRunner
        self.identity = {'config_sha256': 'e' * 64}
        self.terminal_state = dict(facts=FACTS, rng_state_sha256=RNG, data_cursor=dict(CURSOR))
        self.child = {'checkpoint_manifest_sha256': self.child_sha, 'data_cursor': dict(CURSOR), 'rng_state_sha256': RNG}

    def persist(self, state=None):
        return cia_hour.write_terminal_witness(self.runner, self.custody, self.child, state or self.terminal_state, {'measured_updates': 8})

    def tail(self):
        return cia_hour.verify_tail(self.runner, object(), object(), {}, self.identity, self.custody)


class WitnessTests(Fixture):
    def test_deliberate_red_killed_between_publish_and_verify_then_the_tail_completes_the_verification(self):
        # "process 1": publish happened, the witness was written, then the process died before verify_checkpoint_restore ran (no hour-result).
        self.persist()
        self.assertFalse((self.custody / 'hour-result.json').exists())
        # "process 2": a fresh call that shares nothing with process 1 but the custody directory.
        with fake_modules():
            result = self.tail()
        self.assertEqual((result['status'], result['restored_state_matches'], result['hour_result_written'], result['head_advanced']),
                         ('RESTORE_VERIFIED_FROM_WITNESS', True, False, False))
        self.assertEqual(json.loads((self.custody / cia_hour.VERIFY_TAIL_RESULT).read_bytes())['child_manifest_sha256'], self.child_sha)
        self.assertEqual(result['witness_sha256'], FakeRunner.file_sha256(self.custody / cia_hour.TERMINAL_WITNESS))

    def test_the_h35_shape_no_witness_means_the_tail_has_nothing_to_verify(self):
        with fake_modules(), self.assertRaisesRegex(ValueError, 'absent or unreadable'):
            self.tail()
        self.assertFalse((self.custody / cia_hour.VERIFY_TAIL_RESULT).exists())

    def test_a_witness_cannot_be_overwritten(self):
        self.persist()
        with self.assertRaises(FileExistsError):
            self.persist()

    def test_a_json_round_trip_of_tuples_and_int_keys_still_verifies(self):
        self.persist()
        persisted = json.loads((self.custody / cia_hour.TERMINAL_WITNESS).read_bytes())
        self.assertEqual(persisted['terminal_state']['facts']['inventory'], ['a', 'b'])      # not equal to FACTS until normalised
        self.assertNotEqual(persisted['terminal_state']['facts'], FACTS)
        with fake_modules():
            self.assertEqual(self.tail()['status'], 'RESTORE_VERIFIED_FROM_WITNESS')


class TailRefusalTests(Fixture):
    def test_a_witness_for_another_child_refuses(self):
        self.child = dict(self.child, checkpoint_manifest_sha256='9' * 64)
        self.persist()
        with fake_modules(), self.assertRaisesRegex(ValueError, 'another child'):
            self.tail()

    def test_a_witness_whose_facts_differ_from_the_reopened_bytes_refuses(self):
        self.persist(dict(self.terminal_state, facts=dict(FACTS, total=31)))
        with fake_modules(), self.assertRaisesRegex(ValueError, 'terminal live state differs'):
            self.tail()
        self.assertFalse((self.custody / cia_hour.VERIFY_TAIL_RESULT).exists())

    def test_a_restore_that_does_not_reproduce_the_facts_refuses_and_writes_no_result(self):
        self.persist()
        with fake_modules(restored_facts=dict(FACTS, total=99)), self.assertRaisesRegex(ValueError, 'restored model or optimizer differs'):
            self.tail()
        self.assertFalse((self.custody / cia_hour.VERIFY_TAIL_RESULT).exists())

    def test_a_cursor_that_differs_from_the_published_child_refuses(self):
        self.persist(dict(self.terminal_state, data_cursor=dict(CURSOR, tokens_seen=1)))
        with fake_modules(), self.assertRaisesRegex(ValueError, 'cursor differs'):
            self.tail()

    def test_an_hour_that_already_has_a_result_has_nothing_to_resume(self):
        self.persist()
        (self.custody / 'hour-result.json').write_text('{}')
        with fake_modules(), self.assertRaisesRegex(ValueError, 'nothing to resume'):
            self.tail()

    def test_one_tail_per_hour(self):
        self.persist()
        with fake_modules():
            self.tail()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                self.tail()

    def test_a_malformed_witness_refuses(self):
        (self.custody / cia_hour.TERMINAL_WITNESS).write_text(json.dumps({'schema': 'x'}))
        with fake_modules(), self.assertRaisesRegex(ValueError, 'not the'):
            self.tail()


class RunHourOrderTests(unittest.TestCase):
    def test_run_hour_persists_the_witness_after_the_terminal_state_and_before_the_restore_verification(self):
        source = inspect.getsource(cia_hour.run_hour)
        state = source.index("terminal_state = continuation_state(")
        witness = source.index("write_terminal_witness(")
        verify = source.index("verify_checkpoint_restore(runner, model, optimizer, inventory, identity, custody, child, before=terminal_state)")
        self.assertLess(state, witness)
        self.assertLess(witness, verify)

    def test_the_live_path_compares_without_a_normalizer(self):
        # the in-memory comparison must stay as strict as before: the run_hour call passes no `normalize`
        source = inspect.getsource(cia_hour.run_hour)
        self.assertNotIn('normalize=', source)


import cia_verify_tail  # noqa: E402


class TailEntryTests(Fixture):
    def setUp(self):
        super().setUp()
        self.marker = self.custody / 'window-marker'
        self.marker.write_text('open')
        self.lost = self.custody / 'lost-hour'
        self.lost.mkdir()
        # a lost hour custody: published child + witness + launch binding + prediction
        write_child(self.lost / 'trained-child')
        (self.lost / cia_hour.TERMINAL_WITNESS).write_text('{}')
        (self.lost / 'launch.json').write_text(json.dumps({'launch': {'prediction_sha256': 'a' * 64, 'run_id': 'r', 'gpu_uuid': 'GPU-x'}}))
        (self.lost / 'prediction.json').write_text('{}')

    def refuses(self, why, **kw):
        with self.assertRaisesRegex(cia_verify_tail.Refused, why):
            cia_verify_tail.preflight(self.lost, window_marker=kw.get('marker', self.marker))

    def test_a_complete_lost_custody_passes_preflight(self):
        self.assertEqual(cia_verify_tail.preflight(self.lost, window_marker=self.marker)['launch']['run_id'], 'r')

    def test_it_refuses_without_a_governed_window(self):
        self.refuses('no governed GPU window', marker=self.custody / 'absent-marker')

    def test_it_refuses_a_custody_that_never_wrote_a_witness(self):
        (self.lost / cia_hour.TERMINAL_WITNESS).unlink()
        self.refuses('no terminal witness')

    def test_it_refuses_an_hour_that_has_a_result_or_a_tail_result(self):
        (self.lost / 'hour-result.json').write_text('{}')
        self.refuses('nothing to resume')
        (self.lost / 'hour-result.json').unlink()
        (self.lost / cia_hour.VERIFY_TAIL_RESULT).write_text('{}')
        self.refuses('already exists')

    def test_it_refuses_without_a_published_child_a_binding_or_a_prediction(self):
        (self.lost / 'prediction.json').unlink()
        self.refuses('prediction.json is absent')
        (self.lost / 'launch.json').write_text('not json')
        self.refuses('launch.json is absent or unreadable')
        import shutil
        shutil.rmtree(self.lost / 'trained-child')
        self.refuses('no published trained-child')

    def test_main_prints_refuse_rc2_and_exits_2_before_building_anything(self):
        import io
        from contextlib import redirect_stdout
        with patch.object(cia_verify_tail, 'WINDOW_MARKER', self.custody / 'absent-marker'), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cia_verify_tail.main(['--custody', str(self.lost)]), 2)
        self.assertTrue(out.getvalue().startswith('REFUSE rc2: '))
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cia_verify_tail.main([]), 2)

    def test_run_verify_tail_hands_the_built_model_and_the_lost_custody_to_verify_tail(self):
        calls = []
        with patch.object(cia_hour, 'build_hour_model', lambda **kw: ('m', {'i': 1}, 'o')),                 patch.object(cia_hour, 'verify_tail', lambda *a: calls.append(a) or {'status': 'RESTORE_VERIFIED_FROM_WITNESS'}):
            result = cia_hour.run_verify_tail(runner='R', config=None, prepared=None, prediction={'identity': {'k': 1}}, binding=None,
                                              custody=self.lost, device=None, compiler=None, applied=None)
        self.assertEqual(result['status'], 'RESTORE_VERIFIED_FROM_WITNESS')
        self.assertEqual(calls, [('R', 'm', 'o', {'i': 1}, {'k': 1}, self.lost)])


class DriftTests(unittest.TestCase):
    def test_the_tail_builds_the_hour_model_with_the_same_text_run_hour_uses(self):
        def block(function):
            source = inspect.getsource(function)
            return source.split('# BEGIN hour-model-build')[1].split('# END hour-model-build')[0].split(chr(10), 1)[1]
        self.assertEqual(block(cia_hour.run_hour), block(cia_hour.build_hour_model))
        self.assertIn('AdamW', block(cia_hour.run_hour))


if __name__ == '__main__':
    unittest.main()
