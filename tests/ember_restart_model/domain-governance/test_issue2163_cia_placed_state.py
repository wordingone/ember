# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Small physical state mechanics; identity fixture is not full model admission."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import checkpoint_artifacts as artifacts


class PlacedStateIntegration(unittest.TestCase):
    def setUp(self):
        self.parameters = {'weight': torch.nn.Parameter(torch.zeros(8, dtype=torch.bfloat16))}
        self.model = type('Fixture', (), {'parameter_inventory': lambda _: self.parameters})()
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=.01, foreach=False)
        self.optimizer.state[self.parameters['weight']] = {
            'step': torch.tensor(2.), 'exp_avg': torch.zeros(8, dtype=torch.bfloat16),
            'exp_avg_sq': torch.ones(8, dtype=torch.bfloat16)}
        self.identity = {'param_groups': [{'params': ['weight']}]}
        self.identity_patch = patch.object(artifacts, 'cia_optimizer_identity', return_value=self.identity)
        self.identity_patch.start()
        self.addCleanup(self.identity_patch.stop)

    def capture(self):
        return artifacts.capture_cia_placed_optimizer_state(self.model, self.optimizer, max_state_bytes=36)

    def prepare(self, payload):
        return artifacts.prepare_cia_placed_optimizer_state(self.model, self.optimizer, payload, max_state_bytes=36)

    def test_round_trip_preserves_detached_state_and_identity(self):
        original_parameter = self.parameters['weight']
        payload = self.capture()
        self.assertEqual(payload['schema_version'], 'ember-cia-placed-optimizer-state-v2')
        self.assertEqual(payload['placement'], {'weight': {'device': 'cpu', 'requires_grad': True}})
        prepared = self.prepare(payload)
        live = self.optimizer.state[original_parameter]
        for name, value in prepared['state'][0].items():
            torch.testing.assert_close(value, live[name], rtol=0, atol=0)
            self.assertNotEqual(value.data_ptr(), payload['state']['weight'][name].data_ptr())
        self.assertIs(self.parameters['weight'], original_parameter)
        self.assertEqual(live['step'].item(), 2)

    def test_corruption_refused_before_device_copy(self):
        original = self.capture()
        for corruption in ('negative', 'missing', 'clock', 'placement', 'support', 'identity'):
            payload = copy.deepcopy(original)
            if corruption == 'negative': payload['state']['weight']['exp_avg_sq'][0] = -1
            elif corruption == 'missing': del payload['state']['weight']['step']
            elif corruption == 'clock': payload['state']['weight']['step'].fill_(.5)
            elif corruption == 'placement': payload['placement']['weight']['device'] = 'cuda:0'
            elif corruption == 'support': payload['placement']['weight']['requires_grad'] = False
            else: payload['identity'] = {}
            with patch.object(torch.Tensor, 'to', side_effect=AssertionError('copied invalid state')):
                with self.assertRaises(ValueError, msg=corruption):
                    self.prepare(payload)

    def test_lazy_absent_and_empty_states_remain_distinct(self):
        self.optimizer.state.clear()
        self.assertEqual(self.prepare(self.capture())['state'], {})
        self.optimizer.state[self.parameters['weight']] = {}
        self.assertEqual(self.prepare(self.capture())['state'], {0: {}})

    def test_meta_is_not_physical_even_without_moments(self):
        self.parameters['weight'] = torch.nn.Parameter(torch.empty(8, dtype=torch.bfloat16, device='meta'))
        self.optimizer = torch.optim.AdamW(self.parameters.values(), foreach=False)
        with self.assertRaisesRegex(ValueError, 'physical'):
            self.capture()

    def test_parameter_alias_is_refused_before_capture_copy(self):
        self.optimizer.state[self.parameters['weight']]['exp_avg'] = self.parameters['weight'].detach()
        with patch.object(torch.Tensor, 'to', side_effect=AssertionError('copied aliased state')):
            with self.assertRaisesRegex(ValueError, 'alias'):
                self.capture()

    def test_live_state_replacement_during_copy_refused(self):
        original = torch.Tensor.to
        changed = False
        def copying(value, *args, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                fields = self.optimizer.state[self.parameters['weight']]
                self.optimizer.state[self.parameters['weight']] = dict(fields)
            return original(value, *args, **kwargs)
        with patch.object(torch.Tensor, 'to', copying):
            with self.assertRaisesRegex(ValueError, 'live optimizer state changed'):
                self.capture()

    def test_live_state_removal_during_copy_refused(self):
        original = torch.Tensor.to
        changed = False
        def copying(value, *args, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                self.optimizer.state.clear()
            return original(value, *args, **kwargs)
        with patch.object(torch.Tensor, 'to', copying):
            with self.assertRaisesRegex(ValueError, 'live optimizer state changed'):
                self.capture()


if __name__ == '__main__':
    unittest.main()
