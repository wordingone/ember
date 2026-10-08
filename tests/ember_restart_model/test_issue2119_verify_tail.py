"""Issue #2119 recovery acceptance: the terminal-state witness is persisted BEFORE the restore verification, and a verify-only tail reads it.

H35 trained a full hour, published its child, and lost the hour because the independent live-terminal facts existed only in memory when the
restore verification refused. These tests pin the repair without a GPU: the checkpoint and parameter-counter modules are replaced by fakes whose
answers the test controls, so the only things under test are the witness file, the tail's refusals and the order inside `run_hour`.
The deliberate red is the H35 shape itself: a hour killed between publish and verify, then the tail.

The tail is its own dispatched job (fresh run id, own custody); the lost hour's custody is a read-only input pinned by digest in the tail
prediction, and the tail's result lands in the tail's own custody (ruling 67346).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import inspect
import json
import os
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
LOST_ID = 'b' * 32
TAIL_ID = 'a' * 32


class FakeRunner:
    GIB = 1 << 30

    @staticmethod
    def _write_new(path, value):
        with Path(path).open('xb') as stream:
            stream.write(json.dumps(value, sort_keys=True).encode('utf-8'))

    @staticmethod
    def file_sha256(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def require_result_outside_lost_custody(identity, result_path):
        import cia_step_runner
        return cia_step_runner.require_result_outside_lost_custody(identity, result_path)


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
    """`self.custody` is the LOST hour's custody (read-only input); `self.tail_custody` is the tail's own."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.custody = self.root / ('measurement-' + LOST_ID)
        self.custody.mkdir()
        self.tail_custody = self.root / ('measurement-' + TAIL_ID)
        self.tail_custody.mkdir()
        self.child_sha = write_child(self.custody / 'trained-child')
        self.runner = FakeRunner
        self.terminal_state = dict(facts=FACTS, rng_state_sha256=RNG, data_cursor=dict(CURSOR))
        self.child = {'checkpoint_manifest_sha256': self.child_sha, 'data_cursor': dict(CURSOR), 'rng_state_sha256': RNG}

    def persist(self, state=None):
        return cia_hour.write_terminal_witness(self.runner, self.custody, self.child, state or self.terminal_state, {'measured_updates': 8})

    def identity_for(self, **pins):
        """The tail identity as frozen NOW: the pins are the digests of the bytes on disk at this call."""
        witness = self.custody / cia_hour.TERMINAL_WITNESS
        value = {'lost_custody': str(self.custody), 'lost_run_id': LOST_ID,
                 'witness_sha256': FakeRunner.file_sha256(witness) if witness.exists() else 'f' * 64,
                 'child_manifest_sha256': self.child_sha}
        value.update(pins)
        return {'config_sha256': 'e' * 64, 'run_id': TAIL_ID, 'gpu_uuid': 'GPU-x', 'verify_tail': value}

    def tail(self, identity=None, **pins):
        return cia_hour.verify_tail(self.runner, object(), object(), {}, identity or self.identity_for(**pins), self.custody)

    def listing(self, root):
        return sorted(str(p.relative_to(root)) for p in root.rglob('*'))


class WitnessTests(Fixture):
    def test_deliberate_red_killed_between_publish_and_verify_then_the_tail_completes_the_verification(self):
        # "process 1": publish happened, the witness was written, then the process died before verify_checkpoint_restore ran (no hour-result).
        self.persist()
        self.assertFalse((self.custody / 'hour-result.json').exists())
        before = self.listing(self.custody)
        # "process 2": a fresh call that shares nothing with process 1 but the lost custody it reads.
        with fake_modules():
            result = self.tail()
        self.assertEqual((result['status'], result['restored_state_matches'], result['hour_result_written'], result['head_advanced']),
                         ('RESTORE_VERIFIED_FROM_WITNESS', True, False, False))
        self.assertEqual(result['child_manifest_sha256'], self.child_sha)
        self.assertEqual(result['lost_run_id'], LOST_ID)
        self.assertEqual(result['witness_sha256'], FakeRunner.file_sha256(self.custody / cia_hour.TERMINAL_WITNESS))
        self.assertEqual(self.listing(self.custody), before)                        # nothing was written into the lost custody
        self.assertEqual(self.listing(self.tail_custody), [])                       # and verify_tail itself writes no result anywhere

    def test_the_h35_shape_no_witness_means_the_tail_has_nothing_to_verify(self):
        with fake_modules(), self.assertRaisesRegex(ValueError, 'absent or unreadable'):
            self.tail()
        self.assertEqual(self.listing(self.tail_custody), [])

    def test_a_witness_cannot_be_overwritten(self):
        self.persist()
        with self.assertRaises(FileExistsError):
            self.persist()

    def test_a_witness_replaced_between_the_read_and_the_restore_cannot_change_what_the_result_binds(self):
        self.persist()
        witness_path = self.custody / cia_hour.TERMINAL_WITNESS
        original = hashlib.sha256(witness_path.read_bytes()).hexdigest()
        identity = self.identity_for()

        def replace_after_read(*args, **kwargs):
            witness_path.write_bytes(witness_path.read_bytes() + b' ')     # other bytes, still parseable JSON
        with fake_modules(), patch.object(cia_hour, 'verify_checkpoint_restore', replace_after_read):
            result = self.tail(identity)
        self.assertNotEqual(hashlib.sha256(witness_path.read_bytes()).hexdigest(), original)    # the red bites: the file did change
        self.assertEqual(result['witness_sha256'], original)                                     # the result binds the bytes that were verified

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

    def test_a_witness_replaced_after_the_prediction_froze_refuses(self):
        self.persist()
        identity = self.identity_for()
        witness_path = self.custody / cia_hour.TERMINAL_WITNESS
        witness_path.write_bytes(witness_path.read_bytes() + b' ')
        with fake_modules(), self.assertRaisesRegex(ValueError, 'differ from the digest frozen'):
            self.tail(identity)

    def test_a_published_child_that_differs_from_the_frozen_digest_refuses(self):
        self.persist()
        with fake_modules(), self.assertRaisesRegex(ValueError, 'trained-child differs from the digest frozen'):
            self.tail(child_manifest_sha256='9' * 64)

    def test_a_witness_whose_facts_differ_from_the_reopened_bytes_refuses(self):
        self.persist(dict(self.terminal_state, facts=dict(FACTS, total=31)))
        with fake_modules(), self.assertRaisesRegex(ValueError, 'terminal live state differs'):
            self.tail()
        self.assertEqual(self.listing(self.tail_custody), [])

    def test_a_restore_that_does_not_reproduce_the_facts_refuses_and_writes_no_result(self):
        self.persist()
        with fake_modules(restored_facts=dict(FACTS, total=99)), self.assertRaisesRegex(ValueError, 'restored model or optimizer differs'):
            self.tail()
        self.assertEqual(self.listing(self.tail_custody), [])

    def test_a_cursor_that_differs_from_the_published_child_refuses(self):
        self.persist(dict(self.terminal_state, data_cursor=dict(CURSOR, tokens_seen=1)))
        with fake_modules(), self.assertRaisesRegex(ValueError, 'cursor differs'):
            self.tail()

    def test_an_hour_that_already_has_a_result_has_nothing_to_resume(self):
        self.persist()
        (self.custody / 'hour-result.json').write_text('{}')
        with fake_modules(), self.assertRaisesRegex(ValueError, 'nothing to resume'):
            self.tail()

    def test_a_malformed_witness_refuses(self):
        (self.custody / cia_hour.TERMINAL_WITNESS).write_text(json.dumps({'schema': 'x'}))
        with fake_modules(), self.assertRaisesRegex(ValueError, 'not the'):
            self.tail()


class ResultCustodyTests(Fixture):
    """ruling 67346 (2): the result lands in the tail's own custody, after its worker-terminal, once; nothing is ever written into the lost custody."""
    def setUp(self):
        super().setUp()
        self.persist()
        with fake_modules():
            self.identity = self.identity_for()
            self.result = self.tail(self.identity)

    def test_the_result_lands_in_the_tail_custody_after_its_worker_terminal(self):
        lost_before = self.listing(self.custody)
        with self.assertRaisesRegex(ValueError, 'only after its own worker-terminal'):
            cia_hour.write_verify_tail_result(self.runner, self.tail_custody, self.identity, self.result)
        self.assertFalse((self.tail_custody / cia_hour.VERIFY_TAIL_RESULT).exists())
        (self.tail_custody / 'worker-terminal.json').write_text('{"status": "completed", "applied_positions": 0}')
        digest = cia_hour.write_verify_tail_result(self.runner, self.tail_custody, self.identity, self.result)
        written = self.tail_custody / cia_hour.VERIFY_TAIL_RESULT
        self.assertEqual(digest, FakeRunner.file_sha256(written))
        record = json.loads(written.read_bytes())
        terminal = self.tail_custody / 'worker-terminal.json'
        self.assertEqual(record, dict(self.result, worker_terminal_sha256=FakeRunner.file_sha256(terminal), worker_terminal_applied_positions=0))
        self.assertEqual(self.listing(self.custody), lost_before)

    def test_the_result_records_the_witness_child_cursor_and_no_committed_cursor_advance(self):
        self.assertEqual(self.result['data_cursor'], CURSOR)                                    # the verified child (== witness) cursor identity
        self.assertEqual(self.result['data_cursor'], self.terminal_state['data_cursor'])
        self.assertIs(self.result['committed_cursor_advanced'], False)
        self.assertIs(self.result['head_advanced'], False)

    def test_a_terminal_that_is_not_completed_with_zero_applied_positions_refuses_and_writes_no_result(self):
        terminal = self.tail_custody / 'worker-terminal.json'
        for body in ('{"status": "completed", "applied_positions": 4096}', '{"status": "completed"}', '{"status": "completed", "applied_positions": true}',
                     '{"status": "completed", "applied_positions": 0.0}', '{"status": "failed", "applied_positions": 0}', 'not json', '[]'):
            terminal.write_text(body)
            with self.assertRaisesRegex(ValueError, 'applies no positions|unreadable'):
                cia_hour.write_verify_tail_result(self.runner, self.tail_custody, self.identity, self.result)
            self.assertFalse((self.tail_custody / cia_hour.VERIFY_TAIL_RESULT).exists(), body)
            terminal.unlink()

    def test_one_result_per_tail(self):
        (self.tail_custody / 'worker-terminal.json').write_text('{"status": "completed", "applied_positions": 0}')
        cia_hour.write_verify_tail_result(self.runner, self.tail_custody, self.identity, self.result)
        with self.assertRaises(FileExistsError):
            cia_hour.write_verify_tail_result(self.runner, self.tail_custody, self.identity, self.result)

    def test_a_result_path_inside_the_lost_custody_refuses_and_writes_nothing(self):
        (self.custody / 'worker-terminal.json').write_text('{"status": "completed", "applied_positions": 0}')      # even a custody that looks finished
        lost_before = self.listing(self.custody)
        with self.assertRaisesRegex(ValueError, 'inside the lost custody'):
            cia_hour.write_verify_tail_result(self.runner, self.custody, self.identity, self.result)
        self.assertEqual(self.listing(self.custody), lost_before)


import cia_verify_tail  # noqa: E402


class TailEntryTests(Fixture):
    def setUp(self):
        super().setUp()
        self.marker = self.root / 'window-marker'
        self.marker.write_text('open')
        self.persist()
        self.binding = {'launch': {'run_id': TAIL_ID, 'gpu_uuid': 'GPU-x'}}

    def preflight(self, identity=None, **kw):
        return cia_verify_tail.preflight(self.tail_custody, kw.get('binding', self.binding), identity or self.identity_for(),
                                         hour_module=cia_hour, window_marker=kw.get('marker', self.marker))

    def refuses(self, why, **kw):
        with self.assertRaisesRegex(cia_verify_tail.Refused, why):
            self.preflight(**kw)

    def test_a_complete_lost_custody_passes_preflight_and_returns_the_pinned_witness(self):
        witness, digest = self.preflight()
        self.assertEqual(digest, FakeRunner.file_sha256(self.custody / cia_hour.TERMINAL_WITNESS))
        self.assertEqual(witness['child_manifest_sha256'], self.child_sha)

    def test_it_refuses_without_a_governed_window(self):
        self.refuses('no governed GPU window', marker=self.root / 'absent-marker')

    def test_it_refuses_when_no_window_marker_is_bound_to_the_process(self):
        with patch.dict(os.environ, clear=False):
            os.environ.pop(cia_verify_tail.WINDOW_MARKER_ENV, None)
            with self.assertRaisesRegex(cia_verify_tail.Refused, 'is not set'):
                cia_verify_tail.preflight(self.tail_custody, self.binding, self.identity_for(), hour_module=cia_hour)

    def test_it_refuses_a_custody_that_never_wrote_a_witness(self):
        (self.custody / cia_hour.TERMINAL_WITNESS).unlink()
        self.refuses('no terminal witness')

    def test_it_refuses_a_malformed_witness_before_any_model_is_built(self):
        (self.custody / cia_hour.TERMINAL_WITNESS).write_text('{}')
        self.refuses('terminal witness is malformed')
        (self.custody / cia_hour.TERMINAL_WITNESS).write_text('not json')
        self.refuses('terminal witness is malformed')

    def test_it_refuses_the_minimal_witness_without_the_child_digest_or_top_level_cursor(self):
        minimal = {'schema': cia_hour.TERMINAL_WITNESS_SCHEMA, 'persisted_before_restore_verify': True,
                   'terminal_state': {'facts': {}, 'rng_state_sha256': {}, 'data_cursor': {}}}
        path = self.custody / cia_hour.TERMINAL_WITNESS
        path.write_text(json.dumps(minimal))
        self.refuses('required fields are missing or mistyped')
        good = json.loads(json.dumps(dict(minimal, child_manifest_sha256=self.child_sha, data_cursor=dict(CURSOR), hour_fields={})))
        path.write_text(json.dumps(good))
        self.preflight()                                                                      # the same record with its fields passes
        for mutate in (lambda w: w.pop('child_manifest_sha256'), lambda w: w.pop('data_cursor'), lambda w: w.pop('hour_fields'),
                       lambda w: w.update(child_manifest_sha256='XYZ'), lambda w: w.update(child_manifest_sha256=7),
                       lambda w: w.update(data_cursor=[]), lambda w: w.update(hour_fields='x'),
                       lambda w: w['terminal_state'].update(facts=[]), lambda w: w['terminal_state'].update(data_cursor='c')):
            broken = json.loads(json.dumps(good))
            mutate(broken)
            path.write_text(json.dumps(broken))
            self.refuses('terminal witness is malformed')

    def test_it_refuses_witness_bytes_or_a_child_that_differ_from_the_frozen_digests(self):
        identity = self.identity_for()
        path = self.custody / cia_hour.TERMINAL_WITNESS
        path.write_bytes(path.read_bytes() + b' ')
        self.refuses('differ from the digest frozen', identity=identity)
        path.write_bytes(path.read_bytes()[:-1])
        self.preflight(identity)                                                              # restored bytes pass again
        self.refuses('another child than the one frozen', identity=self.identity_for(child_manifest_sha256='9' * 64))

    def test_it_refuses_an_hour_that_has_a_result(self):
        (self.custody / 'hour-result.json').write_text('{}')
        self.refuses('nothing to resume')

    def test_it_refuses_without_a_published_child(self):
        import shutil
        shutil.rmtree(self.custody / 'trained-child')
        self.refuses('no published trained-child')

    def test_it_refuses_published_child_manifest_bytes_that_differ_from_the_frozen_digest_before_any_build(self):
        """review 67480 P2: a valid unchanged witness is not enough; the REAL manifest bytes are checked in preflight, read-only."""
        identity = self.identity_for()
        manifest = self.custody / 'trained-child' / 'checkpoint-manifest.json'
        original = manifest.read_bytes()
        witness_before = (self.custody / cia_hour.TERMINAL_WITNESS).read_bytes()
        manifest.write_bytes(original + b' ')
        self.refuses('manifest bytes differ from the digest frozen', identity=identity)
        self.assertEqual((self.custody / cia_hour.TERMINAL_WITNESS).read_bytes(), witness_before)    # the witness still matches its pin
        manifest.write_bytes(original)
        self.preflight(identity)                                                                    # restored bytes pass again
        manifest.unlink()
        self.refuses('no published checkpoint manifest', identity=identity)

    def test_preflight_reads_the_lost_custody_without_writing_into_it(self):
        before = self.listing(self.custody)
        stamps = {name: (self.custody / name).stat().st_mtime_ns for name in before if (self.custody / name).is_file()}
        self.preflight()
        self.assertEqual(self.listing(self.custody), before)
        self.assertEqual({name: (self.custody / name).stat().st_mtime_ns for name in stamps}, stamps)

    def test_it_refuses_a_lost_custody_that_is_not_the_measurement_directory_of_the_lost_run(self):
        self.refuses('is not a directory', identity=self.identity_for(lost_custody=str(self.root / 'absent')))
        self.refuses('not the measurement directory', identity=self.identity_for(lost_run_id='c' * 32))

    def test_the_prediction_and_the_launch_must_both_name_the_owned_tail_run_and_device(self):
        cia_verify_tail.check_run_identity(self.tail_custody, self.binding, self.identity_for())
        with self.assertRaisesRegex(cia_verify_tail.Refused, 'another run'):          # owned tail A, a self-consistent B launch/prediction pair
            cia_verify_tail.check_run_identity(self.tail_custody, {'launch': {'run_id': 'runB', 'gpu_uuid': 'GPU-x'}},
                                               dict(self.identity_for(), run_id='runB'))
        with self.assertRaisesRegex(cia_verify_tail.Refused, 'another run'):          # prediction alone names another run
            cia_verify_tail.check_run_identity(self.tail_custody, self.binding, dict(self.identity_for(), run_id='runB'))
        with self.assertRaisesRegex(cia_verify_tail.Refused, 'differs from the launch binding'):
            cia_verify_tail.check_run_identity(self.tail_custody, self.binding, dict(self.identity_for(), gpu_uuid='GPU-2'))

    def test_a_tail_that_carries_the_lost_hours_run_id_refuses(self):
        lost_binding = {'launch': {'run_id': LOST_ID, 'gpu_uuid': 'GPU-x'}}
        with self.assertRaisesRegex(cia_verify_tail.Refused, 'lost hour run id'):
            cia_verify_tail.check_run_identity(self.custody, lost_binding, dict(self.identity_for(), run_id=LOST_ID))

    def test_the_module_has_no_command_line_entry_and_builds_nothing(self):
        import io
        from contextlib import redirect_stdout
        built = []
        with patch.object(cia_hour, 'build_hour_model', lambda **kw: built.append(kw)):
            for argv in ([], ['--custody', str(self.custody)], ['--worker', str(self.tail_custody / 'launch.json')]):
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(cia_verify_tail.main(argv), 2)
                self.assertTrue(out.getvalue().startswith('REFUSE rc2: '))
        self.assertEqual(built, [])
        self.assertEqual(self.listing(self.tail_custody), [])
        for gone in ('authorize', 'bind_to_dispatch', 'run', 'pinned_entry_matches'):
            self.assertFalse(hasattr(cia_verify_tail, gone), gone)             # the boundary is the runner's verify_worker, not a second copy

    def test_run_verify_tail_hands_the_built_model_and_the_lost_custody_to_verify_tail(self):
        calls = []
        identity = self.identity_for()
        with patch.object(cia_hour, 'build_hour_model', lambda **kw: ('m', {'i': 1}, 'o')), \
                patch.object(cia_hour, 'verify_tail', lambda *a: calls.append(a) or {'status': 'RESTORE_VERIFIED_FROM_WITNESS'}):
            result = cia_hour.run_verify_tail(runner='R', config=None, prepared=None, prediction={'identity': identity}, binding=None,
                                              custody=self.tail_custody, device=None, compiler=None, applied=None)
        self.assertEqual(result['status'], 'RESTORE_VERIFIED_FROM_WITNESS')
        self.assertEqual(calls, [('R', 'm', 'o', {'i': 1}, identity, str(self.custody))])      # the LOST custody is read; the tail custody is untouched
        self.assertEqual(self.listing(self.tail_custody), [])


class WorkerBranchTests(unittest.TestCase):
    """ruling 67346 items 2 and 3: the worker boundary is verify_worker itself; the tail branch is taken only for a tail identity."""
    def source(self):
        import cia_step_runner as runner
        return inspect.getsource(runner.worker)

    def test_the_boundary_runs_first_then_the_tail_preflight_then_input_preparation(self):
        source = self.source()
        self.assertLess(source.index('verify_worker(binding, binding_path)'), source.index('load_tail_module().preflight('))
        self.assertLess(source.index('load_tail_module().preflight('), source.index('prepare_execution(prediction)'))
        self.assertIn('if verify_tail_mode(prediction', source)

    def test_the_tail_result_is_written_only_after_the_worker_terminal(self):
        source = self.source()
        self.assertLess(source.index("'worker-terminal.json'"), source.index('write_verify_tail_result('))
        self.assertIn('if verifying_tail:', source)

    def test_the_executor_choice_is_the_tail_only_for_a_tail_identity(self):
        source = self.source()
        self.assertIn("verifying_tail = 'verify_tail' in prediction['identity']", source)
        self.assertIn('hour_module.run_verify_tail if verifying_tail else', source)
        self.assertIn('hour_module.run_continuation if', source)

    def test_the_loaded_tail_module_is_the_pinned_tail_source(self):
        import cia_step_runner as runner
        module = runner.load_tail_module()
        self.assertEqual(module.ENTRY_RELATIVE, runner.TAIL_SOURCES[0])
        self.assertTrue(callable(module.preflight))


class SourcePinTests(unittest.TestCase):
    HOUR = {'schema': 'governed-hour-v1', 'arm': 'control', 'minimum_wall_seconds': 3600, 'minimum_measured_steps': 1024}
    LOST = LOST_ID

    def tail_identity(self, **changes):
        identity = {'run_id': TAIL_ID, 'hour': dict(self.HOUR), 'training_job_purpose': 'DIAGNOSTIC',
                    'geometry': dict(documents_per_step=4, sequence_length=1024, warm_steps=1, measured_steps=2),
                    'verify_tail': {'lost_custody': 'B:/ember-live-receipts/cia-hour-x/measurement-' + self.LOST,
                                    'lost_run_id': self.LOST, 'witness_sha256': 'c' * 64, 'child_manifest_sha256': 'd' * 64}}
        identity.update(changes)
        return identity

    def test_the_entry_point_is_pinned_by_a_tail_prediction_only(self):
        """ruling 67346 (1): an ordinary hour prediction passes without the tail source AND a verify_tail prediction requires it."""
        import cia_step_runner as runner
        entry = cia_verify_tail.ENTRY_RELATIVE
        self.assertNotIn(entry, runner.HOUR_SOURCES)
        self.assertEqual(runner.TAIL_SOURCES, (entry,))
        self.assertIn(entry, runner.allowed_experiment_sources({}))
        self.assertNotIn(entry, runner.required_sources({'hour': dict(self.HOUR)}))
        tail = self.tail_identity()
        self.assertIn(entry, runner.required_sources(tail))
        self.assertEqual(set(runner.required_sources(tail)) - set(runner.required_sources({'hour': dict(self.HOUR)})), {entry})
        self.assertTrue((ROOT / entry).is_file())

    def test_a_tail_binding_without_the_source_refuses_in_the_pin_check(self):
        import cia_step_runner as runner
        tail = self.tail_identity()
        without = {name: 'e' * 64 for name in runner.required_sources(tail) if name != cia_verify_tail.ENTRY_RELATIVE}
        self.assertNotEqual(set(without), set(runner.required_sources(tail)))
        with self.assertRaisesRegex(ValueError, 'source set differs'):
            runner.validate_experiment_sources(dict(tail, source_sha256=without), {'source_sha256': without})

    def test_an_ordinary_hour_binding_with_the_tail_source_refuses(self):
        import cia_step_runner as runner
        hour = {'hour': dict(self.HOUR)}
        extra = {name: 'e' * 64 for name in runner.required_sources(hour)}
        extra[cia_verify_tail.ENTRY_RELATIVE] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'source set differs'):
            runner.validate_experiment_sources(dict(hour, source_sha256=extra), {'source_sha256': extra})

    def test_the_tail_identity_key_set_is_exact_and_each_digest_is_checked(self):
        import cia_step_runner as runner
        self.assertTrue(runner.verify_tail_mode(self.tail_identity()))
        self.assertFalse(runner.verify_tail_mode({'hour': dict(self.HOUR)}))
        good = self.tail_identity()['verify_tail']
        mutations = [dict(good, extra=1), {k: v for k, v in good.items() if k != 'witness_sha256'},
                     dict(good, witness_sha256='C' * 64), dict(good, child_manifest_sha256='d' * 63),
                     dict(good, lost_run_id='B' * 32), dict(good, lost_run_id='b' * 31),
                     dict(good, lost_custody='B:/x/measurement-' + 'f' * 32), dict(good, lost_custody=''), 'not-a-dict']
        for value in mutations:
            with self.assertRaises(ValueError, msg=repr(value)):
                runner.verify_tail_mode(self.tail_identity(verify_tail=value))

    def test_a_tail_never_reuses_the_lost_run_id_and_trains_nothing(self):
        import cia_step_runner as runner
        with self.assertRaisesRegex(ValueError, 'fresh run id'):
            runner.verify_tail_mode(self.tail_identity(run_id=self.LOST))
        for changes in ({'training_job_purpose': 'CONTINUE_TRAINING'}, {'continuation': {}}, {'checkpoint_probe': {}},
                        {'parent_checkpoint': {}}, {'trajectory': {}}, {'measurement': {}}):
            with self.assertRaises(ValueError, msg=repr(changes)):
                runner.verify_tail_mode(self.tail_identity(**changes))
        with self.assertRaises(ValueError):
            runner.verify_tail_mode({k: v for k, v in self.tail_identity().items() if k != 'hour'})

    def test_a_tail_is_a_short_receipts_only_job(self):
        import cia_step_runner as runner
        limits = runner.resource_limits(self.tail_identity())
        self.assertEqual((limits['wall_seconds'], limits['max_b_write_gib']), (3400, 1))
        self.assertGreaterEqual(limits['wall_seconds'], 1.25 * (1200.6 + 1504.8))     # build span + restore span from the hour stamps, with the 1.25 margin

    def test_a_continuation_keeps_its_900_second_wall(self):
        import cia_step_runner as runner
        identity = {k: v for k, v in self.tail_identity().items() if k != 'verify_tail'}
        limits = runner.resource_limits(dict(identity, continuation={}))
        self.assertEqual((limits['wall_seconds'], limits['max_b_write_gib']), (900, 1))

    def test_a_result_path_inside_the_lost_custody_refuses(self):
        """ruling 67346 (2): nothing is ever written into the lost custody."""
        import cia_step_runner as runner
        with tempfile.TemporaryDirectory() as raw:
            lost = Path(raw) / ('measurement-' + self.LOST)
            tail = Path(raw) / ('measurement-' + TAIL_ID)
            identity = self.tail_identity()
            identity['verify_tail'] = dict(identity['verify_tail'], lost_custody=str(lost))
            for inside in (lost / 'verify-tail-result.json', lost / 'sub' / 'verify-tail-result.json', lost):
                with self.assertRaisesRegex(ValueError, 'inside the lost custody'):
                    runner.require_result_outside_lost_custody(identity, inside)
            runner.require_result_outside_lost_custody(identity, tail / 'verify-tail-result.json')

    def test_the_prediction_identity_key_whitelist_admits_verify_tail(self):
        import cia_step_runner as runner
        self.assertIn("'verify_tail'", inspect.getsource(runner.prepare_execution))
        self.assertIn('verify_tail_mode(identity)', inspect.getsource(runner.prepare_execution))


class TailPrepareScopeTests(unittest.TestCase):
    """ruling 67506: the training hour's checkpoint-probe and production-mixture checks are skipped ONLY for an identity verify_tail_mode has passed."""
    class Reached(Exception):
        pass

    KEYS = ('source_commit', 'source_sha256', 'config_sha256', 'data', 'seed', 'support', 'optimizer', 'batch_documents',
            'resources', 'input_binding', 'dispatch_resources')

    def identity(self, *, tail, **changes):
        identity = {key: {} for key in self.KEYS}
        identity.update(run_id=TAIL_ID if tail else 'c' * 32, gpu_uuid='GPU-x', hour=dict(SourcePinTests.HOUR),
                        training_job_purpose='DIAGNOSTIC' if tail else 'CONTINUE_TRAINING',
                        geometry=dict(documents_per_step=4, sequence_length=1024, warm_steps=1, measured_steps=2 if tail else 98158))
        if tail:
            identity['verify_tail'] = {'lost_custody': 'B:/ember-live-receipts/cia-hour-x/measurement-' + LOST_ID, 'lost_run_id': LOST_ID,
                                       'witness_sha256': 'c' * 64, 'child_manifest_sha256': 'd' * 64}
        else:
            identity['production_mixture'] = {'admitted': 'segment'}
            identity['checkpoint_probe'] = {'custody_root': 'B:/x'}
        identity.update(changes)
        return identity

    def prepare(self, identity):
        """Run prepare_execution up to the first geometry read; return what the hour module was asked."""
        import cia_step_runner as runner
        calls = []
        hour_module = types.SimpleNamespace(validate_checkpoint_probe=lambda *a: calls.append('probe'),
                                            validate_identity=lambda **k: calls.append('mixture') or {})

        def reached(*args, **kwargs):
            raise self.Reached()
        quiet = {name: (lambda *a, **k: None) for name in ('execution_mode', 'local_routing_mode', 'attention_selection', 'training_head',
                                                              'validate_experiment_plan', 'validate_training_job_purpose',
                                                              'validate_scored_pair_binding', 'validate_trajectory_resources')}
        with patch.multiple(runner, load_hour_module=lambda: hour_module, geometry_counts=reached, **quiet):
            try:
                runner.prepare_execution({'identity': identity})
            except self.Reached:
                return calls, True
            except ValueError as error:
                return calls, str(error)
        return calls, False

    def test_a_deliberately_ordinary_hour_still_requires_the_probe_and_mixture_checks(self):
        calls, outcome = self.prepare(self.identity(tail=False))
        self.assertEqual(calls, ['probe', 'mixture'])
        self.assertIs(outcome, True)

    def test_a_tail_that_passed_verify_tail_mode_needs_no_probe_and_no_mixture(self):
        calls, outcome = self.prepare(self.identity(tail=True))
        self.assertEqual(calls, [])
        self.assertIs(outcome, True)

    def test_a_tail_identity_that_claims_steps_a_data_segment_or_a_probe_is_refused_before_any_check(self):
        base = self.identity(tail=True)
        claims = (dict(geometry=dict(base['geometry'], measured_steps=98158)),       # claims the hour's updates
                  dict(geometry=dict(base['geometry'], measured_steps=3)),
                  dict(production_mixture={'admitted': 'segment'}),                  # claims a data segment
                  dict(scored_pair_binding_sha256='e' * 64),
                  dict(checkpoint_probe={'custody_root': 'B:/x'}),
                  dict(continuation={'x': 1}),
                  dict(parent_checkpoint={'root': 'B:/x', 'manifest_sha256': 'f' * 64}),
                  dict(geometry=None))
        for change in claims:
            calls, outcome = self.prepare(dict(base, **change))
            self.assertEqual(calls, [], change)
            self.assertIsInstance(outcome, str, change)                              # a ValueError message, never the sentinel

    def test_the_skip_is_keyed_on_verify_tail_mode_alone(self):
        import cia_step_runner as runner
        source = inspect.getsource(runner.prepare_execution)
        self.assertIn('tail = verify_tail_mode(identity)', source)
        self.assertIn('if hour and not tail:', source)
        self.assertLess(source.index('tail = verify_tail_mode(identity)'), source.index('if hour and not tail:'))


class LaunchBoundaryTests(unittest.TestCase):
    """review 67480 P1: launch() validates the tail custody is outside the lost tree BEFORE any mkdir, stamp or other write."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.lost = self.root / ('measurement-' + LOST_ID)
        (self.lost / 'nested').mkdir(parents=True)
        (self.lost / 'trained-child').mkdir()
        self.sibling = self.root / 'daemon-custody'
        self.sibling.mkdir()
        identity = {'run_id': TAIL_ID, 'hour': dict(SourcePinTests.HOUR), 'training_job_purpose': 'DIAGNOSTIC',
                    'geometry': dict(documents_per_step=4, sequence_length=1024, warm_steps=1, measured_steps=2),
                    'verify_tail': {'lost_custody': str(self.lost), 'lost_run_id': LOST_ID,
                                    'witness_sha256': 'c' * 64, 'child_manifest_sha256': 'd' * 64}}
        raw = json.dumps({'identity': identity}).encode()
        self.prediction = self.root / 'prediction.json'
        self.prediction.write_bytes(raw)
        self.digest = hashlib.sha256(raw).hexdigest()

    def launch(self, parent):
        import cia_step_runner as runner
        args = types.SimpleNamespace(live=True, prediction=self.prediction, prediction_sha256=self.digest, custody=parent,
                                     hidden_helper=self.root / 'absent-helper')
        with patch.dict(os.environ, {'EMBER_GATE_AUTHORIZED': '1'}):
            return runner.launch(args, {'job_id': TAIL_ID})

    def snapshot(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))

    def test_a_parent_equal_to_the_lost_custody_or_nested_in_it_creates_nothing(self):
        for parent in (self.lost, self.lost / 'nested'):
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, 'custody inside the lost custody is refused'):
                self.launch(parent)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse((parent / ('measurement-' + TAIL_ID)).exists())

    def test_a_sibling_parent_passes_the_containment_check_and_still_creates_nothing_before_later_gates(self):
        before = self.snapshot()
        with self.assertRaises(ValueError) as caught:                      # a non-B tmp parent trips the later drive gate, not containment
            self.launch(self.sibling)
        self.assertNotIn('inside the lost custody', str(caught.exception))
        self.assertEqual(self.snapshot(), before)

    def test_the_containment_check_runs_before_the_mkdir_in_launch(self):
        import cia_step_runner as runner
        source = inspect.getsource(runner.launch)
        self.assertLess(source.index('require_tail_custody_outside_lost_custody('), source.index('custody.mkdir()'))
        self.assertLess(source.index('require_tail_custody_outside_lost_custody('), source.index("tail_stamp(custody, 'segment_launch')"))

    def test_the_containment_function_refuses_the_lost_tree_and_admits_a_sibling(self):
        import cia_step_runner as runner
        identity = {'verify_tail': {'lost_custody': str(self.lost)}}
        for inside in (self.lost, self.lost / 'nested' / ('measurement-' + TAIL_ID), self.lost / ('measurement-' + TAIL_ID)):
            with self.assertRaisesRegex(ValueError, 'inside the lost custody'):
                runner.require_tail_custody_outside_lost_custody(identity, inside)
        runner.require_tail_custody_outside_lost_custody(identity, self.sibling / ('measurement-' + TAIL_ID))


class DriftTests(unittest.TestCase):
    def test_the_tail_builds_the_hour_model_with_the_same_text_run_hour_uses(self):
        def block(function):
            source = inspect.getsource(function)
            return source.split('# BEGIN hour-model-build')[1].split('# END hour-model-build')[0].split(chr(10), 1)[1]
        self.assertEqual(block(cia_hour.run_hour), block(cia_hour.build_hour_model))
        self.assertIn('AdamW', block(cia_hour.run_hour))


if __name__ == '__main__':
    unittest.main()
