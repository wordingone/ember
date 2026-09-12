# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Small checkpoint mechanics fixtures; no full-model qualification claim."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import torch

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path[:0] = [str(BASE), str(ROOT / 'src'), str(ROOT)]
SOURCE = Path(os.environ.get('CIA_CHECKPOINT_SOURCE', str(BASE)))
def load(name):
    spec = importlib.util.spec_from_file_location('hour_' + name, SOURCE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
artifacts = load('checkpoint_artifacts')
counter = load('parameter_counter')

class FusedStateTests(unittest.TestCase):
    def test_fused_physical_state_roundtrip_preserves_next_update(self):
        parameter = torch.nn.Parameter(torch.ones(8, dtype=torch.bfloat16))
        model = type('Fixture', (), {'parameter_inventory': lambda _: {'weight': parameter}})()
        optimizer = torch.optim.AdamW([parameter], lr=.01, foreach=False, fused=True)
        parameter.grad = torch.ones_like(parameter)
        optimizer.step()
        identity = {'param_groups': [{'params': ['weight']}]}
        with patch.object(artifacts, 'cia_optimizer_identity', return_value=identity):
            payload = artifacts.capture_cia_placed_optimizer_state(model, optimizer, max_state_bytes=36)
            prepared = artifacts.prepare_cia_placed_optimizer_state(model, optimizer, payload, max_state_bytes=36)
        original = parameter.detach().clone()
        parameter.grad = torch.ones_like(parameter)
        optimizer.step()
        expected = parameter.detach().clone()
        with torch.no_grad(): parameter.copy_(original)
        optimizer.load_state_dict(prepared)
        parameter.grad = torch.ones_like(parameter)
        optimizer.step()
        torch.testing.assert_close(parameter, expected, rtol=0, atol=0)
        self.assertEqual(optimizer.state[parameter]['step'].item(), 2)

class SparseLineageTests(unittest.TestCase):
    def arguments(self):
        parent = dict(data_cursor=dict(global_step=0, tokens_seen=0), expert_genesis_sha256={},
                      checkpoint_manifest_sha256='a'*64, _parent_counter_receipt_sha256='b'*64,
                      placement={'dense': {'requires_grad': True}, 'sparse': {'requires_grad': True},
                                 'inactive': {'requires_grad': False}})
        child = copy.deepcopy(parent)
        child['data_cursor'] = dict(global_step=3, tokens_seen=12)
        child['lineage'] = dict(owner_update_counts=dict(dense=3, sparse=1))
        before = dict(parameters=dict(dense='a', sparse='b', inactive='c'), optimizer={},
                      elements=dict(dense=1, sparse=1, inactive=1))
        after = copy.deepcopy(before)
        after['parameters'].update(dense='d', sparse='e')
        after['optimizer'] = dict(dense=dict(step=3), sparse=dict(step=1))
        return [Path('fixture'), parent, before, child, after]

    def test_sparse_owner_clock_is_measured_and_bounded(self):
        result = counter._cia_derive_first_lineage(*self.arguments())
        self.assertEqual(result['owner_update_counts'], {'dense': 3, 'sparse': 1})
        self.assertEqual(result['updated_parameters'], ['dense', 'sparse'])

    def test_uniform_transition_retains_v1_without_new_fields(self):
        args = self.arguments()
        del args[3]['lineage']
        args[4]['optimizer']['sparse']['step'] = 3
        result = counter._cia_derive_first_lineage(*args)
        self.assertEqual(result['schema_version'], 'ember-cia-first-descendant-v1')
        self.assertNotIn('owner_update_counts', result)

    def test_sparse_transition_without_recorded_counts_refuses(self):
        args = self.arguments()
        del args[3]['lineage']
        with self.assertRaisesRegex(ValueError, 'recorded per-owner'):
            counter._cia_derive_first_lineage(*args)

    def test_inactive_state_or_out_of_range_clock_refuses(self):
        for mode in ('decrease', 'excess', 'inactive_bytes', 'inactive_moments', 'frozen', 'wrong_count'):
            args = self.arguments()
            if mode == 'decrease': args[4]['optimizer']['sparse']['step'] = -1
            elif mode == 'excess': args[4]['optimizer']['sparse']['step'] = 4
            elif mode == 'inactive_bytes': args[4]['parameters']['inactive'] = 'd'
            elif mode == 'inactive_moments': args[4]['optimizer']['inactive'] = dict(step=0, exp_avg='d')
            elif mode == 'wrong_count': args[3]['lineage']['owner_update_counts']['sparse'] = 2
            else:
                args[1]['placement']['sparse']['requires_grad'] = False
                args[3]['placement']['sparse']['requires_grad'] = False
            with self.assertRaises(ValueError, msg=mode): counter._cia_derive_first_lineage(*args)



class ResidentCheckpointBoundaryTests(unittest.TestCase):
    def fixture(self):
        from types import SimpleNamespace
        from ember.model.ember_v0_residency import ResidentExecution
        parameter = torch.nn.Parameter(torch.ones(8, dtype=torch.bfloat16))
        model = SimpleNamespace(parameter_inventory=lambda: {'weight': parameter},
            _resident_experts=(0, 1, 2, 3), _execution_device=torch.device('cpu'))
        execution = object.__new__(ResidentExecution)
        execution.model = model
        execution.cache = execution
        execution.device = model._execution_device
        execution.ids = model._resident_experts
        execution.active = execution.poisoned = execution.retired = False
        execution.pending = 0
        execution.segmented = None
        model._cuda_execution = execution
        return model, execution, parameter

    def test_resident_boundary_uses_actual_execution_state_without_paging_fields(self):
        model, execution, parameter = self.fixture()
        self.assertFalse(hasattr(execution, 'entries'))
        self.assertFalse(hasattr(execution, 'leased'))
        self.assertEqual(artifacts._cia_quiescent_parameters(model), {'weight': parameter})
        for field, value in (('active', True), ('pending', 1), ('poisoned', True), ('retired', True),
                             ('ids', (4, 5, 6, 7)), ('model', object()), ('cache', object())):
            prior = getattr(execution, field)
            setattr(execution, field, value)
            with self.assertRaisesRegex(ValueError, 'quiescent resident'):
                artifacts._cia_quiescent_parameters(model)
            setattr(execution, field, prior)
        parameter.grad = torch.ones_like(parameter)
        with self.assertRaisesRegex(ValueError, 'cleared gradients'):
            artifacts._cia_quiescent_parameters(model)

    def test_recorded_or_captured_operations_must_be_invalidated_before_checkpoint(self):
        from types import SimpleNamespace
        model, execution, _ = self.fixture()
        capture = SimpleNamespace(execution=execution, captured=False, _recording=False, _recorded={})
        execution.segmented = capture
        artifacts._cia_quiescent_parameters(model)
        for field, value in (('captured', True), ('_recording', True), ('_recorded', {0: object()}), ('execution', object())):
            prior = getattr(capture, field)
            setattr(capture, field, value)
            with self.assertRaisesRegex(ValueError, 'invalidated capture'):
                artifacts._cia_quiescent_parameters(model)
            setattr(capture, field, prior)

    def test_paging_boundary_still_refuses_entries_and_leases(self):
        from types import SimpleNamespace
        model, _, _ = self.fixture()
        cache = SimpleNamespace(active=False, pending=0, entries={}, leased=set(), poisoned=False)
        model._cuda_execution = SimpleNamespace(cache=cache)
        artifacts._cia_quiescent_parameters(model)
        for field, value in (('entries', {1: object()}), ('leased', {1})):
            prior = getattr(cache, field)
            setattr(cache, field, value)
            with self.assertRaisesRegex(ValueError, 'quiescent candidate cache'):
                artifacts._cia_quiescent_parameters(model)
            setattr(cache, field, prior)


if __name__ == '__main__': unittest.main()


class GroupedParameterStorageTests(unittest.TestCase):
    def parameters(self):
        packed = torch.arange(32, dtype=torch.bfloat16).reshape(4, 8)
        return {str(index): torch.nn.Parameter(packed[index]) for index in range(4)}

    def snapshot(self, parameters, state):
        return artifacts._cia_snapshot_placed_moments(parameters, state, max_state_bytes=1024)

    def test_disjoint_grouped_slices_allow_empty_optimizer_state(self):
        parameters = self.parameters()
        self.assertEqual(len({value.untyped_storage().data_ptr() for value in parameters.values()}), 1)
        self.assertEqual(self.snapshot(parameters, {}), {})

    def test_disjoint_grouped_slices_copy_independent_moments(self):
        parameters = self.parameters()
        state = {name: {'step': torch.tensor(1.), 'exp_avg': torch.ones_like(value),
                        'exp_avg_sq': torch.ones_like(value)} for name, value in parameters.items()}
        snapshot = self.snapshot(parameters, state)
        for name, fields in state.items():
            for key, value in fields.items():
                torch.testing.assert_close(snapshot[name][key], value, rtol=0, atol=0)
                self.assertNotEqual(snapshot[name][key].data_ptr(), value.data_ptr())

    def test_partial_parameter_overlap_is_refused_before_any_copy(self):
        packed = torch.zeros(16, dtype=torch.bfloat16)
        parameters = {'a': torch.nn.Parameter(packed[:8]), 'b': torch.nn.Parameter(packed[4:12])}
        with patch.object(torch.Tensor, 'to', side_effect=AssertionError('copy before validation')):
            with self.assertRaisesRegex(ValueError, 'overlap'):
                self.snapshot(parameters, {})

    def test_moment_parameter_overlap_is_still_refused(self):
        parameter = torch.nn.Parameter(torch.zeros(8, dtype=torch.bfloat16))
        with patch.object(torch.Tensor, 'to', side_effect=AssertionError('copy before validation')):
            with self.assertRaisesRegex(ValueError, 'aliases'):
                self.snapshot({'a': parameter}, {'a': {'exp_avg': parameter.detach()}})

    def test_noncontiguous_parameter_uses_conservative_backing_span(self):
        packed = torch.zeros(16, dtype=torch.bfloat16)
        parameters = {'a': torch.nn.Parameter(packed[::2]), 'b': torch.nn.Parameter(packed[1::2])}
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.snapshot(parameters, {})

    def test_empty_parameter_view_has_no_occupied_bytes(self):
        parameters = self.parameters()
        parameters['empty'] = torch.nn.Parameter(parameters['0'].detach()[:0])
        self.assertEqual(self.snapshot(parameters, {}), {})


if __name__ == '__main__':
    unittest.main()
