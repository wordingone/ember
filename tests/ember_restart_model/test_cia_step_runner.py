# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Measurement runner contracts using small token and CPU step fixtures.

These tests establish software behavior, not CIA-3B throughput qualification.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
SUBJECT_PATH = TOOLS / 'cia_step_runner.py'
SPEC = importlib.util.spec_from_file_location('bound_checkout_cia_step_runner', SUBJECT_PATH)
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)
assert Path(subject.__file__).resolve(strict=True) == SUBJECT_PATH.resolve(strict=True)


def temporary_directory():
    base = ROOT / 'target' / 'cia-step-runner-tests'
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class ClosedInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_directory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        tokenizer = canonical({'model': {'vocab': {str(i): i for i in range(16)}}})
        (self.root / 'tokenizer.json').write_bytes(tokenizer)
        self.shard = struct.pack('<10H', *range(10))
        (self.root / 'shard.bin').write_bytes(self.shard)
        self.receipt = {
            'ticket': 'TOKEN-SHARDS-V0',
            'premises': {'tokenizer_json': {'path': 'tokenizer.json', 'sha256': digest(tokenizer)}},
            'shards': [{'name': 'shard.bin', 'sha256': digest(self.shard), 'n_tokens': 10}],
            'total_stream_tokens': 10,
            'catalog_binding': {'shard_tokens': 10},
        }
        self.data = {
            'receipt_path': str(self.root / 'receipt.json'),
            'receipt_sha256': '',
            'tokenizer_path': str(self.root / 'tokenizer.json'),
            'tokenizer_sha256': digest(tokenizer),
            'shards_root': str(self.root),
            'shard_ledger_path': None,
            'shard_ledger_sha256': None,
            'cursor': {'shard_index': 0, 'token_offset': 0},
        }
        self.write_receipt()
        self.geometry = {'sequence_length': 2, 'documents_per_step': 2,
                         'warm_steps': 1, 'measured_steps': 1}

    def write_receipt(self):
        raw = canonical(self.receipt)
        (self.root / 'receipt.json').write_bytes(raw)
        self.data['receipt_sha256'] = digest(raw)

    def test_real_stream_binds_targets_positions_and_frozen_phases(self):
        prepared = subject.prepare_inputs(self.data, self.geometry)
        pack = prepared['packs'][0]
        self.assertEqual(pack['token_ids'], [0, 1, 2, 3])
        self.assertEqual(pack['target_ids'], [1, 2, 3, 4])
        self.assertEqual(pack['positions'], [[0, 0, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]])
        self.assertEqual(pack['document_starts'], [0, 2])
        self.assertEqual([p['phase'] for p in prepared['packs']], ['warm', 'measured'])
        self.assertEqual(prepared['binding']['cursor_end'], {'shard_index': 0, 'token_offset': 8})
        self.assertEqual(prepared['binding']['planned_positions'], 8)
        expected = [
            {'token_ids': [0, 1, 2, 3], 'target_ids': [1, 2, 3, 4],
             'positions': [[0, 0, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]], 'document_starts': [0, 2]},
            {'token_ids': [4, 5, 6, 7], 'target_ids': [5, 6, 7, 8],
             'positions': [[0, 0, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]], 'document_starts': [0, 2]},
        ]
        self.assertEqual(prepared['binding']['input_sha256'], digest(canonical(expected)))

    def test_missing_expected_receipt_hash_is_refused(self):
        self.data['receipt_sha256'] = ''
        with self.assertRaises(ValueError):
            subject.prepare_inputs(self.data, self.geometry)

    def test_changed_receipt_or_shard_bytes_are_refused(self):
        (self.root / 'shard.bin').write_bytes(struct.pack('<10H', *reversed(range(10))))
        with self.assertRaises(ValueError):
            subject.prepare_inputs(self.data, self.geometry)

    def test_discovered_ledger_requires_explicit_expected_hash(self):
        row = dict(self.receipt['shards'][0], schema_version='ember-catalog-train-shard-ledger-v1',
                   index=0, prev_row_sha256='0' * 64, token_start=0)
        row['row_sha256'] = digest(canonical(row))
        (self.root / 'shard-ledger-s10.jsonl').write_bytes(canonical(row) + b'\n')
        with self.assertRaises(ValueError):
            subject.prepare_inputs(self.data, self.geometry)

    def test_final_target_is_included_in_span_and_no_partial_pack_is_emitted(self):
        # Two 2-document steps need eight input positions PLUS the final target.
        self.data['cursor'] = {'shard_index': 0, 'token_offset': 2}
        with self.assertRaises(ValueError):
            subject.prepare_inputs(self.data, self.geometry)

    def test_loaded_pack_target_drift_is_refused_before_step_allocation(self):
        prepared = subject.prepare_inputs(self.data, self.geometry)
        prepared['packs'][0]['target_ids'][0] = 7
        with self.assertRaises(ValueError):
            subject.verify_prepared_inputs(prepared)

    def test_changed_ledger_bytes_are_refused_and_no_unbound_growth_is_read(self):
        row = dict(self.receipt['shards'][0], schema_version='ember-catalog-train-shard-ledger-v1',
                   index=0, prev_row_sha256='0' * 64, token_start=0)
        row['row_sha256'] = digest(canonical(row))
        ledger = self.root / 'shard-ledger-s10.jsonl'
        raw = canonical(row) + b'\n'
        ledger.write_bytes(raw)
        self.data['shard_ledger_path'] = str(ledger)
        self.data['shard_ledger_sha256'] = digest(raw)
        prepared = subject.prepare_inputs(self.data, self.geometry)
        ledger.write_bytes(raw + b'\n')
        # Previously loaded packs retain their exact frozen bytes.
        subject.verify_prepared_inputs(prepared)
        with self.assertRaises(ValueError):
            subject.prepare_inputs(self.data, self.geometry)

    def test_frozen_warm_and_measured_labels_cannot_be_reclassified(self):
        prepared = subject.prepare_inputs(self.data, self.geometry)
        prepared['packs'][0]['phase'] = 'measured'
        with self.assertRaises(ValueError):
            subject.verify_prepared_inputs(prepared)


class PredictionTests(unittest.TestCase):
    def setUp(self):
        self.identity = {
            'run_id': 'a' * 32, 'source_commit': 'b' * 40,
            'source_sha256': {'cia_step_runner.py': 'c' * 64},
            'config_sha256': 'd' * 64,
            'data': {'receipt_sha256': 'e' * 64, 'tokenizer_sha256': 'f' * 64,
                     'ledger_sha256': None, 'input_sha256': '1' * 64,
                     'cursor_start': {'shard_index': 0, 'token_offset': 0},
                     'cursor_end': {'shard_index': 0, 'token_offset': 8}},
            'seed': 2163, 'support': {'locus': 'core+expert-set', 'experts': [0, 1, 8, 18]},
            'optimizer': {'name': 'AdamW', 'foreach': False, 'lr': 0.001,
                          'betas': [0.9, 0.999], 'eps': 1e-8, 'weight_decay': 0.01,
                          'membership': 'complete_parameter_inventory'},
            'geometry': {'sequence_length': 2, 'documents_per_step': 2,
                         'warm_steps': 1, 'measured_steps': 1},
            'batch_documents': False,
            'resources': {'host_memory_bytes': 40 * 1024 ** 3,
                          'total_gpu_bytes': 20 * 1024 ** 3,
                          'allocator_bytes': 18 * 1024 ** 3, 'wall_seconds': 600,
                          'min_c_free_bytes': 150 * 1024 ** 3,
                          'min_b_free_bytes': 250 * 1024 ** 3,
                          'min_free_commit_bytes': 42 * 1024 ** 3,
                          'max_c_write_gib': 0.125, 'max_b_write_gib': 2.0},
        }
        self.prediction = {'schema': 'ember-cia-step-prediction-v1',
                           'identity': copy.deepcopy(self.identity),
                           'expected_step_seconds': 2.0, 'expected_positions_per_second': 2.0,
                           'basis': 'CPU software fixture; no measured CIA-3B timing'}

    def test_positive_consistent_prediction_is_accepted(self):
        subject.validate_prediction(self.prediction, expected_identity=self.identity, positions_per_step=4)

    def test_batch_geometry_support_and_seed_cannot_change(self):
        for key, value in [('batch_documents', True), ('seed', 7),
                           ('support', {'locus': 'core', 'experts': []}),
                           ('geometry', {'sequence_length': 1, 'documents_per_step': 4,
                                         'warm_steps': 0, 'measured_steps': 2})]:
            prediction = copy.deepcopy(self.prediction)
            prediction['identity'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                subject.validate_prediction(prediction, expected_identity=self.identity, positions_per_step=4)

    def test_nonfinite_nonpositive_boolean_or_inconsistent_rate_is_refused(self):
        for rate in [0, -1, float('nan'), float('inf'), True, 4.0]:
            prediction = copy.deepcopy(self.prediction)
            prediction['expected_positions_per_second'] = rate
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                subject.validate_prediction(prediction, expected_identity=self.identity, positions_per_step=4)

    def test_prediction_cannot_supply_qualification_result(self):
        self.prediction['pass'] = True
        with self.assertRaises(ValueError):
            subject.validate_prediction(self.prediction, expected_identity=self.identity, positions_per_step=4)

    def test_source_config_input_and_resource_identity_changes_are_refused(self):
        mutations = [
            ('source_commit', '2' * 40), ('config_sha256', '2' * 64),
            ('source_sha256', {'cia_step_runner.py': '2' * 64}),
            ('data', {**self.identity['data'], 'input_sha256': '2' * 64}),
            ('resources', {**self.identity['resources'], 'allocator_bytes': 16 * 1024 ** 3}),
        ]
        for key, value in mutations:
            prediction = copy.deepcopy(self.prediction)
            prediction['identity'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                subject.validate_prediction(prediction, expected_identity=self.identity, positions_per_step=4)

    def test_prediction_requires_nonempty_basis(self):
        for basis in [None, '', '  ', 7]:
            prediction = copy.deepcopy(self.prediction)
            prediction['basis'] = basis
            with self.subTest(basis=basis), self.assertRaises(ValueError):
                subject.validate_prediction(prediction, expected_identity=self.identity, positions_per_step=4)

    def execution_prediction(self, wall):
        prediction = copy.deepcopy(self.prediction)
        prediction['identity'].update(
            source_sha256={path: 'c' * 64 for path in subject.SOURCES},
            input_binding={}, gpu_uuid='GPU-ab12',
            dispatch_resources={'profile': 'cia_measurement',
                                'maximum_job_memory_bytes': 40 * 1024 ** 3,
                                'window_contract': 'headless_no_windows', 'vram_wall': wall})
        return prediction

    def test_execution_refuses_contradictory_gpu_uuid_before_file_reads(self):
        wall = {'applicability': 'required', 'contract': {'device_uuid': 'GPU-cd34'}}
        prediction = self.execution_prediction(wall)
        with patch.object(subject, 'file_sha256', side_effect=AssertionError('file read before device binding')):
            with self.assertRaises(ValueError):
                subject.prepare_execution(prediction)

    def test_execution_requires_explicit_vram_contract_before_file_reads(self):
        for wall in (None, {}, {'applicability': 'not_applicable'},
                     {'applicability': 'required', 'contract': None},
                     {'applicability': 'required', 'contract': {}}):
            prediction = self.execution_prediction(wall)
            with self.subTest(wall=wall), patch.object(
                    subject, 'file_sha256', side_effect=AssertionError('file read before device binding')):
                with self.assertRaises(ValueError):
                    subject.prepare_execution(prediction)


class HostEnvelopeTests(unittest.TestCase):
    def argv(self):
        return ['--daemon-run', '--live', '--custody', str(Path('B:/host-envelope')),
                '--hidden-helper', str(Path('C:/helpers/hidden.py')), '--prediction',
                str(Path('B:/host-envelope/prediction.json')), '--prediction-sha256', 'a' * 64]

    def test_authenticated_40_gib_cap_reaches_measurement_launch(self):
        from ember.governance.scripts import ember_dispatch_token
        budget = 40 * 1024 ** 3
        with patch.object(ember_dispatch_token, 'consume_dispatch', return_value=budget), \
             patch.dict('os.environ', {'EMBER_LAB_DISPATCH_JOB_ID': 'a' * 32,
                                      'EMBER_LAB_DISPATCH_DAEMON_PID': '123'}), \
             patch.object(subject, 'launch', return_value=0) as launch:
            self.assertEqual(subject.main(self.argv()), 0)
        self.assertEqual(launch.call_args.args[1]['memory_cap'], budget)
        self.assertEqual(subject.LIMITS['total_gpu_bytes'], 20 * 1024 ** 3)
        self.assertEqual(subject.LIMITS['allocator_bytes'], 18 * 1024 ** 3)
        self.assertEqual(subject.LIMITS['wall_seconds'], 600)

    def test_legacy_or_inexact_host_cap_refuses_before_launch(self):
        from ember.governance.scripts import ember_dispatch_token
        for budget in (20 * 1024 ** 3, 40 * 1024 ** 3 - 1, 40 * 1024 ** 3 + 1, True):
            with self.subTest(budget=budget), \
                 patch.object(ember_dispatch_token, 'consume_dispatch', return_value=budget), \
                 patch.dict('os.environ', {'EMBER_LAB_DISPATCH_JOB_ID': 'a' * 32,
                                          'EMBER_LAB_DISPATCH_DAEMON_PID': '123'}), \
                 patch.object(subject, 'launch', side_effect=AssertionError('launch before exact host binding')):
                with self.assertRaises(ValueError):
                    subject.main(self.argv())


class InvocationTests(unittest.TestCase):
    def test_direct_main_refuses_before_missing_prediction_is_read(self):
        from ember.governance.scripts.ember_dispatch_token import DispatchTokenError
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(DispatchTokenError):
                subject.main(['--live', '--prediction', 'missing-prediction.json',
                              '--custody', 'missing-custody'])

    def test_direct_worker_cannot_use_launch_json_as_ownership(self):
        with temporary_directory() as temporary:
            binding = Path(temporary) / 'launch.json'
            binding.write_text('{}', encoding='utf-8')
            with patch.dict('os.environ', {}, clear=True), self.assertRaises(ValueError):
                subject.worker(binding)


class StepOrderingTests(unittest.TestCase):
    def test_direct_cuda_step_refuses_before_device_work_without_owned_run(self):
        import torch
        with self.assertRaises(ValueError):
            subject.measure_step(None, None, {}, device=torch.device('cuda:0'))

    def test_failed_optimizer_update_cannot_return_applied_token_credit(self):
        # A real CPU autograd fixture checks context/optimizer ordering only.
        # The governed entry must separately require the full CIA-3B config and CUDA.
        import contextlib
        from types import SimpleNamespace
        import torch

        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(16, 4)
                self.output = torch.nn.Linear(4, 16)
                self.active = False
                self._cuda_execution = SimpleNamespace(cache=SimpleNamespace(
                    lease_count=0, miss_count=0, eviction_count=0,
                    transfer_bytes=0, transfer_seconds=0.0))

            @contextlib.contextmanager
            def candidate_step(self):
                self.active = True
                try:
                    yield
                finally:
                    self.active = False

            def embed_text(self, tokens):
                if not self.active:
                    raise AssertionError('embedding outside candidate context')
                return self.embedding(tokens)

            def forward(self, embedded, positions, *, document_starts, return_routes, batch_documents):
                if not self.active or document_starts != (0, 2) or not return_routes or batch_documents:
                    raise AssertionError('step input contract differs')
                return self.output(embedded), ()

        model = Model()
        events = []

        class FailingOptimizer(torch.optim.AdamW):
            def step(self, closure=None):
                if model.active:
                    raise AssertionError('optimizer inside candidate context')
                if not any(parameter.grad is not None for parameter in model.parameters()):
                    raise AssertionError('backward was not applied')
                events.append('optimizer_attempt')
                raise RuntimeError('fixture update failed')

        optimizer = FailingOptimizer(list(model.parameters()), foreach=False)
        pack = {'token_ids': [0, 1, 2, 3], 'target_ids': [1, 2, 3, 4],
                'positions': [[0, 0, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]],
                'document_starts': [0, 2], 'phase': 'measured'}
        rows = []
        with self.assertRaisesRegex(RuntimeError, 'fixture update failed'):
            rows.append(subject.measure_step(model, optimizer, pack, device=torch.device('cpu')))
        self.assertEqual(events, ['optimizer_attempt'])
        self.assertEqual(rows, [])
        self.assertFalse(model.active)


if __name__ == '__main__':
    unittest.main()
