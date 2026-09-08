# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Full inventory identity only: no materialization, optimization or recovery claim."""
import copy
import os
import sys
import unittest
from pathlib import Path
import torch

ROOT = Path(os.environ.get('CIA_TEST_ROOT', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import checkpoint_artifacts as artifacts
from src.ember.model.cia_decoder import CIADecoder


class CIAOptimizerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.model = CIADecoder()
        self.parameters = self.model.parameter_inventory()
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=0.01, foreach=False)

    def identity(self):
        return artifacts.cia_optimizer_identity(self.model, self.optimizer)

    def test_complete_named_identity_and_deterministic_reconstruction(self):
        identity = self.identity()
        self.assertEqual(identity['schema_version'], 'ember-cia-optimizer-identity-v1')
        self.assertEqual(identity['parameter_elements'], 3_082_539_008)
        self.assertEqual(identity['param_groups'][0]['params'], list(self.parameters))
        self.assertEqual(identity['param_groups'][0]['hyperparameters']['betas'], [0.9, 0.999])
        other = CIADecoder()
        other_optimizer = torch.optim.AdamW(other.parameter_inventory().values(), lr=0.01, foreach=False)
        self.assertEqual(identity, artifacts.cia_optimizer_identity(other, other_optimizer))
        self.assertEqual(len(identity['implementation_source_sha256']), 64)
        self.assertEqual(len(identity['architecture_sha256']), 64)

    def test_restart_sensitive_group_settings_are_bound(self):
        original = self.identity()
        group = self.optimizer.param_groups[0]
        for key, value in [('betas', (0.8, 0.99)), ('eps', 1e-7), ('lr', 0.02),
                           ('weight_decay', 0.2), ('amsgrad', True), ('maximize', True),
                           ('foreach', True)]:
            old = group[key]
            group[key] = value
            self.assertNotEqual(original, self.identity(), key)
            group[key] = old
        group['params'] = list(reversed(group['params']))
        self.assertNotEqual(original, self.identity())

    def test_all_groups_are_bound_and_snapshot_does_not_alias_runtime(self):
        values = list(self.parameters.values())
        self.optimizer = torch.optim.AdamW([{'params': values[:2], 'lr': 0.01},
                                           {'params': values[2:], 'lr': 0.02}], foreach=False)
        first = self.identity()
        snapshot = copy.deepcopy(first)
        self.optimizer.param_groups[1]['eps'] = 1e-6
        self.assertNotEqual(first, self.identity())
        self.assertEqual(first, snapshot)

    def test_missing_duplicate_foreign_and_nonfinite_refused(self):
        group = self.optimizer.param_groups[0]
        values = list(group['params'])
        for malformed in [values[:-1], [*values, values[0]],
                          [*values[:-1], torch.nn.Parameter(torch.empty(1, device='meta'))]]:
            group['params'] = malformed
            with self.assertRaisesRegex(ValueError, 'membership'):
                self.identity()
        group['params'] = values
        group['eps'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.identity()

    def test_unsupported_runtime_and_tensor_hyperparameter_refused(self):
        self.optimizer.param_groups[0]['lr'] = torch.tensor(0.01)
        with self.assertRaisesRegex(ValueError, 'hyperparameter'):
            self.identity()
        self.optimizer = torch.optim.SGD(self.parameters.values(), lr=0.01)
        with self.assertRaisesRegex(ValueError, 'AdamW'):
            self.identity()

    def test_runtime_revision_and_orphan_optimizer_state_refused(self):
        object.__setattr__(self.model.config, 'revision', 'undeclared-revision')
        with self.assertRaises(ValueError):
            self.identity()
        self.model = CIADecoder()
        self.parameters = self.model.parameter_inventory()
        self.optimizer = torch.optim.AdamW(self.parameters.values(), lr=0.01, foreach=False)
        self.optimizer.state[torch.nn.Parameter(torch.empty(1, device='meta'))] = {}
        with self.assertRaisesRegex(ValueError, 'state membership'):
            self.identity()

    def test_effective_defaults_are_bound(self):
        before = self.identity()
        self.optimizer.defaults['differentiable'] = True
        self.assertNotEqual(before, self.identity())

    def test_runtime_overrides_and_hooks_refused(self):
        self.optimizer.step = lambda: None
        with self.assertRaisesRegex(ValueError, 'override'):
            self.identity()
        del self.optimizer.step
        handle = self.optimizer.register_step_pre_hook(lambda *args: None)
        try:
            with self.assertRaisesRegex(ValueError, 'hook'):
                self.identity()
        finally:
            handle.remove()

    def test_actual_inheritance_dependencies_are_bound(self):
        from unittest.mock import patch
        before = self.identity()
        for cls in type(self.optimizer).__mro__:
            if cls.__module__.startswith('torch.optim.'):
                self.assertIn(cls.__module__, before['implementation_dependencies'])
        inherited = next(cls for cls in type(self.optimizer).__mro__[1:]
                         if 'step' in vars(cls))
        with patch.object(inherited, 'step', lambda *args, **kwargs: None):
            self.assertNotEqual(before, self.identity())


if __name__ == '__main__':
    unittest.main()
