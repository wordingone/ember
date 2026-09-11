# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Small ownership-layout fixtures; not a full-model migration proof."""
import unittest
import torch
from ember.model.ember_v0_residency import _pack_resident_group, _validate_resident_group


class ResidentGroupLayoutTests(unittest.TestCase):
    def owners(self):
        return tuple(torch.nn.Parameter(torch.full((8, 16), float(index), dtype=torch.bfloat16))
                     for index in range(4))

    def test_parameter_objects_and_values_survive_disjoint_group_placement(self):
        owners = self.owners()
        identities = tuple(map(id, owners))
        old = tuple(parameter.detach().clone() for parameter in owners)
        storage = _pack_resident_group(owners, torch.device('cpu'))
        for index, parameter in enumerate(owners):
            parameter.data = storage[index]
        _validate_resident_group(owners, storage)
        self.assertEqual(tuple(map(id, owners)), identities)
        self.assertEqual(sum(parameter.numel() for parameter in owners), storage.numel())
        for parameter, expected in zip(owners, old):
            torch.testing.assert_close(parameter, expected, rtol=0, atol=0)
        owners[1].data.fill_(11)
        torch.testing.assert_close(owners[0], old[0], rtol=0, atol=0)
        torch.testing.assert_close(owners[2], old[2], rtol=0, atol=0)

    def test_alias_and_pending_gradient_refuse_before_packing(self):
        owners = self.owners()
        with self.assertRaises(ValueError):
            _pack_resident_group((owners[0], owners[0], owners[2], owners[3]), 'cpu')
        owners[1].grad = torch.ones_like(owners[1])
        with self.assertRaises(ValueError):
            _pack_resident_group(owners, 'cpu')

    def test_independent_parameter_alias_of_the_same_source_storage_refuses(self):
        owners = list(self.owners())
        owners[1] = torch.nn.Parameter(owners[0].detach())
        with self.assertRaises(ValueError):
            _pack_resident_group(tuple(owners), 'cpu')

    def test_wrong_owner_slice_and_replaced_backing_refuse(self):
        owners = self.owners()
        storage = _pack_resident_group(owners, 'cpu')
        for index, parameter in enumerate(owners):
            parameter.data = storage[index]
        with self.assertRaises(ValueError):
            _validate_resident_group(owners, storage.clone())
        owners[2].data = storage[1]
        with self.assertRaises(ValueError):
            _validate_resident_group(owners, storage)


if __name__ == '__main__':
    unittest.main(verbosity=2)
