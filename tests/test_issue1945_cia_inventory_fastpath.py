# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
"""Per-lease owner identity reads the live registry; full schema validation runs at step bind and step end.

Fixed CPU tensors and the meta-device decoder only: this establishes the refusal boundary (every planted mutation is
refused at the NEXT lease with nothing executed between) and the validator call schedule, not CUDA execution or
throughput.
"""
import dataclasses
import unittest
import torch
from ember.model import ember_v0_residency
from ember.model.ember_v0_decoder import CIADecoder
import test_issue2163_cia_residency as fixtures
fixtures.ExpertCache = ember_v0_residency.ExpertCache
fixtures.paged_swiglu = ember_v0_residency.paged_swiglu


class LiveOwnerRegistry(unittest.TestCase):
    def make(self):
        bank, _ = fixtures.ResidencyMechanics().make()
        owners = {f'{i}.{name}': value for i, row in bank.items() for name, value in row.items()}
        owners['core'] = torch.nn.Parameter(torch.arange(4, dtype=torch.float64).reshape(2, 2))
        calls = dict(validate=0, live=0, declaration=0)
        owners['__declared__'] = dict(config=dict(width=4, experts=3), placement='cpu')

        def validate():
            calls['validate'] += 1

        def live():
            calls['live'] += 1
            return {name: value for name, value in owners.items() if name != '__declared__'}

        def declaration():
            calls['declaration'] += 1
            declared = owners['__declared__']
            return (tuple(sorted(declared['config'].items())), declared['placement'])
        cache = ember_v0_residency.ExpertCache(bank, device=torch.device('cpu'), owner_parameters=live, owner_validate=validate,
                                               owner_declaration=declaration)
        return bank, owners, cache, calls

    def assert_refused_at_next_lease(self, mutate, pattern='changed'):
        bank, owners, cache, calls = self.make()
        reached = []
        with self.assertRaisesRegex(RuntimeError, pattern):
            with cache.step():
                with cache.lease(0):
                    pass
                mutate(bank, owners)
                with cache.lease(1):
                    reached.append('leased')
        self.assertEqual(reached, [], 'a lease was admitted after the mutation')
        self.assertFalse(cache.active)
        self.assertEqual(cache.resident_count, 0)

    def test_owner_object_replacement_refused_at_next_lease(self):
        def mutate(bank, owners):
            owners['core'] = torch.nn.Parameter(owners['core'].detach().clone())
        self.assert_refused_at_next_lease(mutate)

    def test_owner_data_swap_without_version_change_refused_at_next_lease(self):
        # `.data =` moves the storage address and leaves _version unchanged, so a version-only check would miss it.
        def mutate(bank, owners):
            before = owners['core']._version
            owners['core'].data = owners['core'].data.clone()
            self.assertEqual(owners['core']._version, before)
        self.assert_refused_at_next_lease(mutate)

    def test_owner_storage_offset_change_refused_at_next_lease(self):
        def mutate(bank, owners):
            base = torch.zeros(5, dtype=torch.float64)
            base[1:] = owners['core'].data.reshape(-1)
            owners['core'].data = base[1:].view(2, 2)
            self.assertEqual(owners['core'].storage_offset(), 1)
        self.assert_refused_at_next_lease(mutate)

    def test_owner_layout_change_same_storage_same_shape_refused_at_next_lease(self):
        # A transposed view of the same square storage keeps id, _version, data_ptr, storage_offset, storage bytes,
        # shape, dtype, device and requires_grad; only the stride moves. parameter_inventory refuses non-contiguous
        # storage, so the per-lease signature must see the layout too.
        def mutate(bank, owners):
            core = owners['core']
            before = (id(core), core._version, core.data_ptr(), core.storage_offset(), core.untyped_storage().nbytes(),
                      tuple(core.shape), core.dtype, core.device, core.requires_grad)
            core.data = core.data.T
            after = (id(core), core._version, core.data_ptr(), core.storage_offset(), core.untyped_storage().nbytes(),
                     tuple(core.shape), core.dtype, core.device, core.requires_grad)
            self.assertEqual(before, after)
            self.assertFalse(core.is_contiguous())
        self.assert_refused_at_next_lease(mutate)

    def test_owner_in_place_write_refused_at_next_lease(self):
        def mutate(bank, owners):
            with torch.no_grad():
                owners['core'].add_(1)
        self.assert_refused_at_next_lease(mutate)

    def test_owner_requires_grad_flip_refused_at_next_lease(self):
        def mutate(bank, owners):
            owners['core'].requires_grad_(False)
        self.assert_refused_at_next_lease(mutate)

    def test_owner_key_removal_refused_at_next_lease(self):
        def mutate(bank, owners):
            del owners['core']
        self.assert_refused_at_next_lease(mutate)

    def test_owner_extra_registration_refused_at_next_lease(self):
        def mutate(bank, owners):
            owners['extra'] = torch.nn.Parameter(torch.ones(2, dtype=torch.float64))
        self.assert_refused_at_next_lease(mutate)

    def test_bank_object_replacement_refused_at_next_lease(self):
        def mutate(bank, owners):
            bank[0]['up'] = torch.nn.Parameter(bank[0]['up'].detach().clone())
        self.assert_refused_at_next_lease(mutate, 'changed|ownership')

    def test_bank_in_place_write_refused_at_next_lease(self):
        def mutate(bank, owners):
            with torch.no_grad():
                bank[2]['down'].add_(1)
        self.assert_refused_at_next_lease(mutate)

    def test_declared_config_in_place_edit_refused_at_next_lease(self):
        # The declaration is a VALUE snapshot: editing the same dict object in place is a change.
        def mutate(bank, owners):
            owners['__declared__']['config']['width'] = 8
        self.assert_refused_at_next_lease(mutate)

    def test_declared_config_object_replacement_refused_at_next_lease(self):
        def mutate(bank, owners):
            owners['__declared__']['config'] = {}
        self.assert_refused_at_next_lease(mutate)

    def test_declared_placement_change_refused_at_next_lease(self):
        def mutate(bank, owners):
            owners['__declared__']['placement'] = 'cuda:0'
        self.assert_refused_at_next_lease(mutate)

    def test_validator_runs_at_bind_and_step_end_only(self):
        bank, owners, cache, calls = self.make()
        with cache.step():
            self.assertEqual(calls['validate'], 1)
            live_at_bind, declared_at_bind = calls['live'], calls['declaration']
            for expert in (0, 1, 2, 0, 1):
                with cache.lease(expert):
                    pass
            self.assertEqual(calls['validate'], 1, 'per-lease checks must not re-run the full validation')
            self.assertGreaterEqual(calls['live'] - live_at_bind, 5, 'every lease reads the live registry')
            self.assertGreaterEqual(calls['declaration'] - declared_at_bind, 5, 'every lease reads the declaration')
        self.assertEqual(calls['validate'], 2)

    def test_validator_failure_at_step_end_propagates(self):
        bank, owners, cache, calls = self.make()
        state = dict(fail=False)

        def validate():
            calls['validate'] += 1
            if state['fail']:
                raise ValueError('undeclared or missing registered model parameters')
        cache.owner_validate = validate
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            with cache.step():
                with cache.lease(0):
                    pass
                state['fail'] = True
        self.assertFalse(cache.active)
        self.assertEqual(cache.resident_count, 0)

    def test_validator_failure_at_bind_leaves_no_active_step(self):
        bank, owners, cache, calls = self.make()

        def validate():
            raise ValueError('candidate census mismatch')
        cache.owner_validate = validate
        with self.assertRaisesRegex(ValueError, 'census'):
            with cache.step():
                self.fail('step admitted with a failing validator')
        self.assertFalse(cache.active)

    def test_existing_fixture_without_validator_unchanged(self):
        bank, cache = fixtures.ResidencyMechanics().make()
        self.assertIsNone(cache.owner_validate)
        with cache.step():
            with cache.lease(0):
                pass


class DecoderLiveParameters(unittest.TestCase):
    def setUp(self):
        self.model = CIADecoder()

    def test_live_view_matches_validated_inventory_under_raw_names(self):
        validated = self.model.parameter_inventory()
        live = self.model.live_parameters()
        self.assertEqual(set(live), {'weights.' + name.replace('.', '__') for name in validated})
        self.assertTrue(all(live['weights.' + name.replace('.', '__')] is validated[name] for name in validated))

    def test_root_registration_visible_live_and_refused_by_validator(self):
        self.model.register_parameter('extra', torch.nn.Parameter(torch.empty(2, device='meta')))
        self.assertIn('extra', self.model.live_parameters())
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            self.model.parameter_inventory()

    def test_root_registration_under_an_encoded_weights_name_does_not_collide(self):
        # Raw registered names: a root parameter carrying an existing encoded weights key stays a distinct key
        # ('<name>' beside 'weights.<name>'), never overwriting the legitimate weight in the live view.
        name = next(iter(self.model.weights))
        self.model.register_parameter(name, torch.nn.Parameter(torch.empty(1, device='meta')))
        live = self.model.live_parameters()
        self.assertIn(name, live)
        self.assertIn('weights.' + name, live)
        self.assertIsNot(live[name], live['weights.' + name])
        self.assertIs(live['weights.' + name], self.model.weights[name])
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            self.model.parameter_inventory()

    def test_child_module_registration_visible_live_and_refused_by_validator(self):
        self.model.adapter = torch.nn.Linear(2, 2, device='meta')
        live = self.model.live_parameters()
        self.assertIn('adapter.weight', live)
        self.assertIn('adapter.bias', live)
        with self.assertRaisesRegex(ValueError, 'undeclared'):
            self.model.parameter_inventory()

    def test_duplicate_registration_visible_live(self):
        name = next(iter(self.model.weights))
        self.model.register_parameter('twin', self.model.weights[name])
        live = self.model.live_parameters()
        self.assertIs(live['twin'], live['weights.' + name])

    def test_owner_declaration_is_a_value_snapshot_of_config_and_placement(self):
        first = self.model.owner_declaration()
        self.assertEqual(first, self.model.owner_declaration())
        self.assertIsInstance(first, tuple)
        self.assertEqual(first[1][2], "'meta'")
        self.assertEqual(first[2][2], "device(type='meta')")
        # The config is a frozen dataclass whose contract refuses any field change at construction, so the only
        # reachable mutation is replacing the object; that replacement must move the snapshot.
        with self.assertRaisesRegex(ValueError, 'separate candidate revision'):
            dataclasses.replace(self.model.config, resident_experts=self.model.config.resident_experts + 1)
        self.model.config = {}
        self.assertNotEqual(first, self.model.owner_declaration(), 'a config replacement must move the snapshot')

    def assert_late_registration_refuses_next_lease(self, register):
        # Composed exactly as CUDAExecution wires the production cache: live tensor registry plus declaration snapshot.
        bank, _ = fixtures.ResidencyMechanics().make()
        model = self.model
        owned = {f'{i}.{name}': value for i, row in bank.items() for name, value in row.items()}

        def live():
            return {**owned, **model.live_parameters()}
        cache = ember_v0_residency.ExpertCache(bank, device=torch.device('cpu'), owner_parameters=live,
                                               owner_declaration=model.owner_declaration)
        reached = []
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            with cache.step():
                with cache.lease(0):
                    pass
                register(model)
                with cache.lease(1):
                    reached.append('leased')
        self.assertEqual(reached, [])

    def test_late_root_registration_refuses_next_lease_through_live_owner(self):
        self.assert_late_registration_refuses_next_lease(
            lambda model: model.register_parameter('late', torch.nn.Parameter(torch.empty(1, device='meta'))))

    def test_late_colliding_root_registration_refuses_next_lease_through_live_owner(self):
        name = next(iter(self.model.weights))
        self.assert_late_registration_refuses_next_lease(
            lambda model: model.register_parameter(name, torch.nn.Parameter(torch.empty(1, device='meta'))))

    def test_late_child_registration_refuses_next_lease_through_live_owner(self):
        def register(model):
            model.adapter = torch.nn.Linear(2, 2, device='meta')
        self.assert_late_registration_refuses_next_lease(register)

    def test_execution_placement_change_refuses_next_lease_through_declaration(self):
        # Registered tensors all stay on meta; only the declared execution device moves.
        def mutate(model):
            model._execution_device = torch.device('cpu')
        self.assert_late_registration_refuses_next_lease(mutate)

    def test_parameter_placement_change_refuses_next_lease_through_declaration(self):
        def mutate(model):
            model._parameter_device = 'cpu'
        self.assert_late_registration_refuses_next_lease(mutate)

    def test_config_replacement_refuses_next_lease_through_declaration(self):
        def mutate(model):
            model.config = {}
        self.assert_late_registration_refuses_next_lease(mutate)

    def test_config_replaced_by_its_repr_string_refuses_next_lease_through_declaration(self):
        # Same printed value, different type: the snapshot carries the exact type with the field values.
        def mutate(model):
            model.config = repr(model.config)
        self.assert_late_registration_refuses_next_lease(mutate)

    def test_execution_placement_replaced_by_plain_string_refuses_next_lease_through_declaration(self):
        def mutate(model):
            model._execution_device = 'meta'
        self.assert_late_registration_refuses_next_lease(mutate)

    def test_owner_declaration_carries_exact_types(self):
        declared = self.model.owner_declaration()
        self.assertEqual(declared[0][1], type(self.model.config).__qualname__)
        self.assertEqual(declared[2][1], 'device')
        self.model._execution_device = 'meta'
        self.assertNotEqual(declared, self.model.owner_declaration())


if __name__ == '__main__':
    unittest.main()
