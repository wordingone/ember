# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Named state fixtures on full meta inventory; not actual checkpoint recovery."""
import copy
import sys
import unittest
from pathlib import Path
import torch
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import checkpoint_artifacts as artifacts
from ember.model.ember_v0_decoder import CIADecoder


class CIAOptimizerStateTests(unittest.TestCase):
    def setUp(self):
        self.model = CIADecoder()
        self.parameters = self.model.parameter_inventory()
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=0.01, foreach=False)
        self.name = 'final_norm.weight'
        self.fixture = {'step': torch.tensor(7.0),
                        'exp_avg': torch.full((1024,), 0.125, dtype=torch.bfloat16),
                        'exp_avg_sq': torch.full((1024,), 0.25, dtype=torch.bfloat16)}
        self.optimizer.state[self.parameters[self.name]] = self.fixture

    def capture(self, limit=1 << 20):
        return artifacts.capture_cia_optimizer_state(self.model, self.optimizer, max_state_bytes=limit)

    def prepare(self, payload):
        return artifacts.prepare_cia_optimizer_state(self.model, self.optimizer, payload, max_state_bytes=1 << 20)

    def test_exact_named_state_and_detached_preparation(self):
        payload = self.capture()
        self.assertEqual(set(payload['state']), {self.name})
        prepared = self.prepare(payload)
        ids = self.optimizer.state_dict()['param_groups'][0]['params']
        expected_id = ids[list(self.parameters).index(self.name)]
        self.assertEqual(set(prepared['state']), {expected_id})
        for key, tensor in self.fixture.items():
            torch.testing.assert_close(prepared['state'][expected_id][key], tensor, rtol=0, atol=0)
            self.assertNotEqual(prepared['state'][expected_id][key].data_ptr(), tensor.data_ptr())
        payload['state'][self.name]['step'].fill_(9)
        self.assertEqual(self.fixture['step'].item(), 7)
        self.assertEqual(prepared['state'][expected_id]['step'].item(), 7)

    def test_identity_or_payload_corruption_refused_without_mutation(self):
        original = self.capture()
        for corrupt in ('shape', 'nan', 'negative_variance', 'clock', 'dtype', 'missing', 'unknown'):
            payload = copy.deepcopy(original)
            state = payload['state'][self.name]
            if corrupt == 'shape': state['exp_avg'] = torch.zeros(1, dtype=torch.bfloat16)
            if corrupt == 'nan': state['exp_avg'][0] = float('nan')
            if corrupt == 'negative_variance': state['exp_avg_sq'][0] = -1
            if corrupt == 'clock': state['step'].fill_(1.5)
            if corrupt == 'dtype': state['exp_avg'] = state['exp_avg'].float()
            if corrupt == 'missing': del state['exp_avg_sq']
            if corrupt == 'unknown': payload['state']['not-a-parameter'] = state
            with self.assertRaises(ValueError, msg=corrupt): self.prepare(payload)
            self.assertEqual(self.fixture['step'].item(), 7)
        self.optimizer.param_groups[0]['betas'] = (0.8, 0.99)
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.prepare(original)

    def test_byte_cap_and_amsgrad_state(self):
        with self.assertRaisesRegex(ValueError, 'byte'):
            self.capture(1)
        self.optimizer.param_groups[0]['amsgrad'] = True
        with self.assertRaises(ValueError): self.capture()
        self.fixture['max_exp_avg_sq'] = self.fixture['exp_avg_sq'].clone()
        self.prepare(self.capture())
        self.fixture['max_exp_avg_sq'][0] = 0
        with self.assertRaises(ValueError): self.capture()

    def test_lazy_empty_state_preserved(self):
        self.optimizer.state.clear()
        self.assertEqual(self.prepare(self.capture())['state'], {})
        self.optimizer.state[self.parameters[self.name]] = {}
        self.assertEqual(list(self.prepare(self.capture())['state'].values()), [{}])


if __name__ == '__main__':
    unittest.main()
