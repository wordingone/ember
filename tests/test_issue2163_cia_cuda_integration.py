# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
"""Candidate integration checks; metadata and CPU fixtures do not establish CUDA execution."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import weakref
import torch
from ember.model.cia_decoder import CIADecoder
from ember.model import cia_residency
import test_issue2163_cia_residency as fixtures
fixtures.ExpertCache = cia_residency.ExpertCache
fixtures.paged_swiglu = cia_residency.paged_swiglu



class CUDAIntegrationTests(unittest.TestCase):
    def test_activation_refuses_meta_and_non_cuda_devices(self):
        model = CIADecoder()
        with self.assertRaisesRegex(ValueError, 'CPU'):
            model.activate_cuda('cuda:0')
        with self.assertRaises(ValueError):
            model.activate_cuda('cpu')

    def test_complete_bundle_mapping_preserves_global_names(self):
        parameters = CIADecoder().parameter_inventory()
        bundles = cia_residency.expert_bundles(parameters)
        self.assertEqual(set(bundles), set(range(25)))
        for expert, row in bundles.items():
            self.assertEqual(len(row), 36)
            self.assertEqual(sum(value.numel() for value in row.values()), 113246208)
            for name, value in row.items():
                self.assertTrue(name.startswith(f'experts.{expert}.'))
                self.assertIs(value, parameters[name])
        del parameters['experts.24.layers.23.down.weight']
        with self.assertRaises(ValueError): cia_residency.expert_bundles(parameters)

    def test_generic_module_migration_cannot_bypass_placement(self):
        model = CIADecoder()
        with self.assertRaisesRegex(ValueError, 'placement'):
            model.to(dtype=torch.float32)

    def test_owner_core_replacement_refuses_backward(self):
        bank, _ = fixtures.ResidencyMechanics().make()
        owners = {f'{i}.{name}': value for i, row in bank.items() for name, value in row.items()}
        owners['core'] = torch.nn.Parameter(torch.ones(2))
        cache = cia_residency.ExpertCache(bank, device=torch.device('cpu'), owner_parameters=lambda: owners)
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            with cache.step():
                result = cia_residency.paged_swiglu(torch.ones(1, 4, dtype=torch.float64), cache, 0)
                owners['core'] = torch.nn.Parameter(torch.ones(2))
                result.sum().backward()

    def test_owned_callback_does_not_hide_cache_bank_replacement(self):
        bank, _ = fixtures.ResidencyMechanics().make()
        owners = {f'{i}.{name}': value for i, row in bank.items() for name, value in row.items()}
        cache = cia_residency.ExpertCache(bank, device=torch.device('cpu'), owner_parameters=lambda: owners)
        with self.assertRaisesRegex(RuntimeError, 'changed|ownership'):
            with cache.step():
                result = cia_residency.paged_swiglu(torch.ones(1, 4, dtype=torch.float64), cache, 0)
                bank[0]['up'] = torch.nn.Parameter(bank[0]['up'].detach().clone())
                result.sum().backward()

    def test_activation_faults_restore_ownership_and_clear_temporaries(self):
        # Fault-injected CPU storage tests cleanup control flow, not CUDA allocation.
        for phase in ('transfer', 'synchronize', 'execution'):
            parameters = {'shared.a': torch.nn.Parameter(torch.ones(2)),
                          'shared.b': torch.nn.Parameter(torch.ones(3))}
            pointers = {name: value.data_ptr() for name, value in parameters.items()}
            model = SimpleNamespace(_parameter_device='cpu', _execution_device=torch.device('cpu'),
                                    _cuda_execution=None, parameter_inventory=lambda: parameters)
            temporaries = []
            def transfer(value, *args, **kwargs):
                if phase == 'transfer' and temporaries:
                    raise RuntimeError('injected transfer failure')
                copied = value.clone()
                temporaries.append(weakref.ref(copied))
                return copied
            with patch.object(torch.Tensor, 'to', transfer), \
                 patch('torch.cuda.synchronize', side_effect=RuntimeError('injected synchronize failure') if phase == 'synchronize' else None), \
                 patch.object(cia_residency, 'CUDAExecution', side_effect=RuntimeError('injected execution failure')):
                try:
                    CIADecoder.activate_cuda(model, 'cuda:0')
                except RuntimeError as error:
                    retained = error
                else:
                    self.fail('injected failure did not propagate')
            self.assertEqual(model._parameter_device, 'cpu')
            self.assertIsNone(model._cuda_execution)
            self.assertEqual({name: value.data_ptr() for name, value in parameters.items()}, pointers)
            self.assertTrue(all(reference() is None for reference in temporaries))
            trace = retained.__traceback__
            while trace:
                if trace.tb_frame.f_code.co_name == 'activate_cuda':
                    self.assertEqual(trace.tb_frame.f_locals['moved'], {})
                trace = trace.tb_next

    def test_step_initialization_failure_leaves_no_active_lease(self):
        bank, _ = fixtures.ResidencyMechanics().make()
        def invalid_owner():
            raise ValueError('invalid owner')
        cache = cia_residency.ExpertCache(bank, device=torch.device('cpu'), owner_parameters=invalid_owner)
        with self.assertRaisesRegex(ValueError, 'invalid owner'):
            with cache.step(): self.fail('invalid owner admitted')
        self.assertFalse(cache.active)

    def test_completion_failure_cleans_and_refuses_reuse(self):
        bank, cache = fixtures.ResidencyMechanics().make()
        cache.device = torch.device('cuda:0')
        with patch('torch.cuda.synchronize', side_effect=RuntimeError('injected completion failure')):
            with self.assertRaisesRegex(RuntimeError, 'completion'):
                with cache.step(): pass
        self.assertFalse(cache.active)
        self.assertEqual(cache.resident_count, 0)
        with self.assertRaisesRegex(RuntimeError, 'fresh execution'):
            with cache.step(): self.fail('poisoned execution reused')


if __name__ == '__main__':
    unittest.main()
