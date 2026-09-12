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

if __name__ == '__main__': unittest.main()
