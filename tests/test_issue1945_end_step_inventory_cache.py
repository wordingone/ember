# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
"""end_step runs the full parameter inventory only when the owner structure or registration differs from the last
passing one; an unchanged step (versions excluded, as _structure documents) reuses that proof."""
import types
import unittest
from unittest import mock
import torch
from ember.model import ember_v0_residency as residency


def owner(shape=(2, 2), version=0, declaration='cfg'):
    return ((declaration, 'a', 'b', 'c', 'd', 'layout', 'e'), (('w', ('id', version, shape)),))


class EndStepInventoryCache(unittest.TestCase):
    def make(self):
        ex = object.__new__(residency.ResidentExecution)
        model = types.SimpleNamespace(calls=0, fail=False)

        def inventory():
            model.calls += 1
            if model.fail:
                raise ValueError('candidate census mismatch')
        model.parameter_inventory = inventory
        model._cuda_execution = ex
        ex.model, ex.device = model, torch.device('cpu')
        ex.retired = ex.poisoned = False
        ex.pending, ex.routed, ex.ids = 0, [], ()
        ex.input_valid = torch.ones(3, dtype=torch.bool)
        ex.routing_valid = torch.tensor(True)
        state = dict(owner=owner(), registration=('w',))
        ex.identity = lambda: state['owner']
        ex._registration = lambda: state['registration']
        return ex, model, state

    def run_step(self, ex, state):
        ex.active, ex.bound = True, state['owner']
        with mock.patch.object(residency.torch.cuda, 'synchronize'):
            ex.end_step()

    def test_unchanged_steps_run_the_inventory_once(self):
        ex, model, state = self.make()
        for version in range(4):
            state['owner'] = owner(version=version)
            self.run_step(ex, state)
        self.assertEqual(model.calls, 1)

    def test_a_structure_change_reruns_the_inventory_and_its_refusal_propagates(self):
        ex, model, state = self.make()
        self.run_step(ex, state)
        state['owner'], model.fail = owner(shape=(4, 1)), True
        with self.assertRaisesRegex(ValueError, 'census'):
            self.run_step(ex, state)
        self.assertEqual(model.calls, 2)
        self.assertTrue(ex.poisoned)

    def test_a_registration_or_declaration_change_reruns_the_inventory(self):
        ex, model, state = self.make()
        self.run_step(ex, state)
        state['registration'] = ('w', 'extra')
        self.run_step(ex, state)
        state['owner'] = owner(declaration='cfg2')
        self.run_step(ex, state)
        self.assertEqual(model.calls, 3)


if __name__ == '__main__':
    unittest.main()
