# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
"""Fixed-tensor mechanics only; not CUDA, model-capacity or throughput evidence."""
import unittest
import torch
import torch.nn.functional as F
from ember.model.cia_residency import ExpertCache, paged_swiglu


class ResidencyMechanics(unittest.TestCase):
    def make(self):
        generator = torch.Generator().manual_seed(241)
        bank = {i: {name: torch.nn.Parameter(torch.randn(shape, generator=generator, dtype=torch.float64))
                    for name, shape in [('up', (6, 4)), ('gate', (6, 4)), ('down', (4, 6))]}
                for i in range(3)}
        return bank, ExpertCache(bank, device=torch.device('cpu'))

    def test_repeated_expert_backward_after_eviction_matches_direct(self):
        bank, cache = self.make()
        controls = {i: {key: value.detach().clone().requires_grad_() for key, value in rows.items()}
                    for i, rows in bank.items()}
        x = torch.arange(8, dtype=torch.float64).reshape(2, 4).requires_grad_()
        y = x.detach().clone().requires_grad_()
        def direct(value, expert):
            row = controls[expert]
            return F.linear(F.silu(F.linear(value, row['gate'])) * F.linear(value, row['up']), row['down'])
        with cache.step():
            actual = sum(paged_swiglu(x, cache, i) for i in [0, 1, 2, 0])
            expected = sum(direct(y, i) for i in [0, 1, 2, 0])
            torch.testing.assert_close(actual, expected)
            actual.square().sum().backward()
            expected.square().sum().backward()
        torch.testing.assert_close(x.grad, y.grad)
        for i in bank:
            for key in bank[i]:
                torch.testing.assert_close(bank[i][key].grad, controls[i][key].grad)
        self.assertLessEqual(cache.peak_resident_bundles, 2)
        self.assertEqual(cache.pending, 0)

    def test_stale_parameter_and_replacement_refuse(self):
        for replace in (False, True):
            bank, cache = self.make()
            with self.assertRaisesRegex(RuntimeError, 'changed|modified'):
                with cache.step():
                    result = paged_swiglu(torch.ones(1, 4, dtype=torch.float64), cache, 0)
                    if replace:
                        bank[0]['up'] = torch.nn.Parameter(bank[0]['up'].detach().clone())
                    else:
                        with torch.no_grad(): bank[0]['up'].add_(1)
                    result.sum().backward()

    def test_incomplete_backward_refuses_and_cleans(self):
        bank, cache = self.make()
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            with cache.step(): paged_swiglu(torch.ones(1, 4, dtype=torch.float64), cache, 0)
        self.assertFalse(cache.active)
        self.assertEqual(cache.resident_count, 0)

    def test_old_graph_refuses_in_new_step(self):
        bank, cache = self.make()
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            with cache.step():
                result = paged_swiglu(torch.ones(1, 4, dtype=torch.float64), cache, 0)
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            with cache.step(): result.sum().backward()

    def test_two_live_leases_refuse_third_and_exception_cleans(self):
        bank, cache = self.make()
        with self.assertRaisesRegex(RuntimeError, 'two expert slots'):
            with cache.step(), cache.lease(0), cache.lease(1), cache.lease(2):
                self.fail('third lease admitted')
        self.assertFalse(cache.active)
        self.assertEqual(cache.resident_count, 0)

    def test_no_grad_step_completes_without_backward(self):
        bank, cache = self.make()
        with cache.step(), torch.no_grad():
            result = paged_swiglu(torch.ones(1, 4, dtype=torch.float64), cache, 0)
            self.assertFalse(result.requires_grad)
        self.assertEqual(cache.pending, 0)

    def test_source_alias_and_non_cpu_ownership_refuse(self):
        bank, _ = self.make()
        bank[1]['up'] = torch.nn.Parameter(bank[0]['up'].detach())
        with self.assertRaisesRegex(ValueError, 'alias'):
            ExpertCache(bank, device=torch.device('cpu'))
        bank, _ = self.make()
        bank[0]['up'] = torch.nn.Parameter(torch.empty(6, 4, device='meta'))
        with self.assertRaisesRegex(ValueError, 'CPU'):
            ExpertCache(bank, device=torch.device('cpu'))

    def test_update_support_flag_changes_refuse(self):
        bank, cache = self.make()
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            with cache.step():
                result = paged_swiglu(torch.ones(1, 4, dtype=torch.float64), cache, 0)
                bank[0]['up'].requires_grad_(False)
                result.sum().backward()


if __name__ == '__main__':
    unittest.main()
