# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU execution selection and frozen starting-identity boundaries."""
import copy
import contextlib
import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
BASE = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
def load(name):
    spec = importlib.util.spec_from_file_location('attention_test_' + name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
runner, trajectory, hour = (load(name) for name in ('cia_step_runner', 'cia_trajectory', 'cia_hour'))


def treatment():
    return dict(execution_mode='resident-dynamic-capture', optimizer={'fused': True},
        trajectory=dict(schema='reference-noise-floor-64-v1', arm='Tfused', comparison_id='a'*32),
        attention_backend='math', attention_recompute='non_reentrant_checkpoint')


class AttentionSelectionTests(unittest.TestCase):
    def test_admission_normalizes_absence_and_refuses_contradictory_selection(self):
        self.assertTrue(callable(getattr(runner, 'attention_selection', None)))
        self.assertEqual(runner.attention_selection({}),
                         dict(attention_backend='unforced', attention_recompute='none'))
        selected = treatment()
        self.assertEqual(runner.attention_selection(selected),
                         dict(attention_backend='math', attention_recompute='non_reentrant_checkpoint'))
        invalid = [dict(selected, attention_backend=value) for value in (None, True, 'flash', 'unforced')]
        invalid += [dict(selected, attention_recompute=value) for value in (None, True, 'none', 'reentrant')]
        invalid += [dict(selected, optimizer={'fused': False}), dict(selected, execution_mode=None)]
        missing_backend = dict(selected); missing_backend.pop('attention_backend'); invalid.append(missing_backend)
        missing_recompute = dict(selected); missing_recompute.pop('attention_recompute'); invalid.append(missing_recompute)
        wrong_arm = copy.deepcopy(selected); wrong_arm['trajectory']['arm'] = 'Tdynamic'; invalid.append(wrong_arm)
        for identity in invalid:
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                runner.attention_selection(identity)

    def test_probe_refuses_changed_backend_or_recomputation(self):
        base = dict(source_commit='head', source_sha256={}, config_sha256='config', data={},
                    seed=1, support={}, production_mixture={})
        for change in ({'attention_backend': 'math'},
                       {'attention_backend': 'math', 'attention_recompute': 'non_reentrant_checkpoint'}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'attention'):
                hour.validate_probe_inputs(runner, base, dict(base, **change))

    def test_fused_transition_keeps_default_references_and_exact_sources(self):
        base = dict(source_commit='head', source_sha256={'decoder':'a'*64}, optimizer={'name':'AdamW'})
        normalized = dict(base, attention_backend='unforced', attention_recompute='none')
        trajectory.compare_start_identity(base, normalized, arm='R2')
        selected = dict(normalized, optimizer={'name':'AdamW', 'fused':True},
                        attention_backend='math', attention_recompute='non_reentrant_checkpoint')
        trajectory.compare_start_identity(base, selected, arm='Tfused')
        for arm in ('R1', 'R2', 'Tdynamic'):
            with self.subTest(arm=arm), self.assertRaises(ValueError):
                trajectory.compare_start_identity(base, selected, arm=arm)
        for changes in ({'source_commit':'different'}, {'source_sha256':{'decoder':'b'*64}},
                        {'attention_backend':'unforced'}, {'attention_recompute':'unknown'}, {'attention_recompute':'none'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                trajectory.compare_start_identity(base, dict(selected, **changes), arm='Tfused')

    def test_backend_context_restores_nondefault_flags_after_return_and_failure(self):
        self.assertTrue(callable(getattr(runner, 'attention_context', None)))
        cuda = torch.backends.cuda
        def flags():
            return (cuda.math_sdp_enabled(), cuda.flash_sdp_enabled(), cuda.mem_efficient_sdp_enabled(),
                    cuda.cudnn_sdp_enabled(), cuda.fp16_bf16_reduction_math_sdp_allowed())
        setters = (cuda.enable_math_sdp, cuda.enable_flash_sdp, cuda.enable_mem_efficient_sdp,
                   cuda.enable_cudnn_sdp, cuda.allow_fp16_bf16_reduction_math_sdp)
        original = flags()
        try:
            for setter, value in zip(setters, (False, True, False, True, True)): setter(value)
            prior = flags()
            with runner.attention_context({}): self.assertEqual(flags(), prior)
            def early_return():
                with runner.attention_context(treatment()):
                    self.assertEqual(flags(), (True, False, False, False, False))
                    return 7
            self.assertEqual(early_return(), 7)
            self.assertEqual(flags(), prior)
            with self.assertRaisesRegex(RuntimeError, 'fixture'):
                with runner.attention_context(treatment()): raise RuntimeError('fixture')
            self.assertEqual(flags(), prior)
        finally:
            for setter, value in zip(setters, original): setter(value)
        self.assertFalse(torch.cuda.is_initialized())

    def test_decoder_constructor_options_preserve_absent_default(self):
        self.assertTrue(callable(getattr(runner, 'decoder_kwargs', None)))
        self.assertEqual(runner.decoder_kwargs({}), {})
        self.assertEqual(runner.decoder_kwargs(treatment()), {'attention_recompute': True})

    def test_real_admission_rejects_attention_before_input_or_model_work(self):
        keys = ('run_id', 'source_commit', 'source_sha256', 'config_sha256', 'data', 'seed',
                'support', 'optimizer', 'geometry', 'batch_documents', 'resources', 'input_binding',
                'gpu_uuid', 'dispatch_resources')
        identity = dict.fromkeys(keys)
        identity['attention_backend'] = 'unknown'
        with patch.object(runner, 'file_sha256', side_effect=AssertionError('premature source read')):
            with self.assertRaisesRegex(ValueError, 'attention'):
                runner.prepare_execution({'identity': identity})

    def test_worker_holds_attention_context_across_each_early_return_or_failure(self):
        from ember.governance.scripts import cia_conformance_resources as resources
        from ember.model import ember_v0_decoder, ember_v0_contract
        cuda = torch.backends.cuda
        def flags():
            return (cuda.math_sdp_enabled(), cuda.flash_sdp_enabled(), cuda.mem_efficient_sdp_enabled(),
                    cuda.cudnn_sdp_enabled(), cuda.fp16_bf16_reduction_math_sdp_allowed())
        original, rng = flags(), torch.get_rng_state()
        old_tf32 = (cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32)
        setters = (cuda.enable_math_sdp, cuda.enable_flash_sdp, cuda.enable_mem_efficient_sdp,
                   cuda.enable_cudnn_sdp, cuda.allow_fp16_bf16_reduction_math_sdp)
        try:
            for setter, value in zip(setters, (False, True, False, True, True)): setter(value)
            prior = flags()
            for branch in ('trajectory', 'hour', 'continuation'):
                for fails in (False, True):
                    identity = treatment()
                    identity.update(run_id='a'*32, gpu_uuid='GPU-fixture', seed=2163,
                                    geometry=dict(sequence_length=1024, documents_per_step=4))
                    if branch != 'trajectory':
                        identity.pop('trajectory')
                        identity['hour'] = dict(schema='governed-hour-v1', arm='treatment',
                            minimum_wall_seconds=3600, minimum_measured_steps=1024)
                    if branch == 'continuation': identity['continuation'] = {}
                    terminal, observed = [], []
                    def execute(**kwargs):
                        observed.append(flags())
                        kwargs['applied'](4096)
                        if fails: raise RuntimeError('fixture execution failure')
                    module = SimpleNamespace(run_trajectory_arm=execute, run_hour=execute, run_continuation=execute)
                    binding = {'launch': {'prediction_sha256':'b'*64, 'gpu_uuid':'GPU-fixture'}}
                    with self.subTest(branch=branch, fails=fails), contextlib.ExitStack() as scope:
                        for owner, name, value in (
                            (resources, 'require_owned_job', lambda *a, **k: None),
                            (runner, 'verify_worker', lambda *a: None),
                            (runner, 'load_prediction', lambda *a: ({'identity':identity}, b'')),
                            (runner, 'prepare_execution', lambda *a: ({}, {})),
                            (runner, 'run_readonly', lambda *a, **k: SimpleNamespace(stdout='GPU-fixture')),
                            (runner, 'load_trajectory_module', lambda: module),
                            (runner, 'load_hour_module', lambda: module),
                            (runner, '_write_new', lambda path, value: terminal.append(value)),
                            (ember_v0_decoder, 'bind_triton_c_compiler', lambda: {}),
                            (ember_v0_contract, 'validate_cia_architecture', lambda config: None),
                            (torch.cuda, 'is_available', lambda: True), (torch.cuda, 'device_count', lambda: 1),
                            (torch.cuda, 'get_device_properties', lambda device: SimpleNamespace(total_memory=24*1024**3)),
                            (torch.cuda, 'set_per_process_memory_fraction', lambda *a: None)):
                            scope.enter_context(patch.object(owner, name, value))
                        scope.enter_context(patch.object(Path, 'read_bytes', return_value=runner.canonical(binding)))
                        path = Path('B:/fixture/measurement-' + identity['run_id'])/'launch.json'
                        if fails:
                            with self.assertRaisesRegex(RuntimeError, 'fixture execution'):
                                runner.worker(path)
                        else:
                            self.assertEqual(runner.worker(path), 0)
                    self.assertEqual(observed, [(True, False, False, False, False)])
                    self.assertEqual(flags(), prior)
                    self.assertEqual(terminal[-1]['applied_positions'], 4096)
                    self.assertEqual(terminal[-1]['status'], 'failed' if fails else 'completed')
        finally:
            for setter, value in zip(setters, original): setter(value)
            cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32 = old_tf32
            torch.set_rng_state(rng)
        self.assertFalse(torch.cuda.is_initialized())
