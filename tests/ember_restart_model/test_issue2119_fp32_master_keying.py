# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU reds for how fp32 masters are keyed (#2119, lead review 82486 Q1): by the Parameter object, never by id(); no GPU, tiny tensors."""
from pathlib import Path
import gc
import sys
import types
import unittest
import copy

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
sys.path.insert(0, str(ROOT / 'src'))
import cia_fp32_master as M  # noqa: E402
from ember.model.ember_v0_residency import ExpertCache  # noqa: E402

ZERO = torch.zeros(())


def bank_and_optimizer(experts=3, n=64, lr=1e-3):
    g = torch.Generator().manual_seed(7)
    bank = {e: {'w': torch.nn.Parameter((torch.randn(n, generator=g) * 0.05).to(torch.bfloat16)),
                'v': torch.nn.Parameter((torch.randn(n // 2, generator=g) * 0.05).to(torch.bfloat16))} for e in range(experts)}
    params = [p for row in bank.values() for p in row.values()]
    opt = torch.optim.AdamW(params, lr=lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False, fused=True)
    return bank, params, opt


def step_all(opt, params, round_):
    gen = torch.Generator().manual_seed(500 + round_)
    for p in params:
        p.grad = (torch.randn(p.shape, generator=gen) * 0.1).to(torch.bfloat16)
    for group in opt.param_groups:
        M.step(opt, group, [x for x in group['params'] if x.grad is not None], ZERO)


class Fp32MasterKeying(unittest.TestCase):
    def test_paging_experts_out_and_in_keeps_invariant_and_only_the_owned_masters(self):
        bank, params, opt = bank_and_optimizer()
        M.enable(opt)
        step_all(opt, params, 0)
        table = M.masters(opt)
        owned = {id(p) for p in params}
        self.assertEqual({id(k) for k in table.keys()}, owned)
        cache = ExpertCache(bank, device=torch.device('cpu'), owner_parameters=lambda: {
            f'{e}.{n}': p for e, row in bank.items() for n, p in row.items()}, resident_capacity=2)
        for round_ in (1, 2, 3):
            with cache.step():
                # three experts through two slots: every one is paged out and back in at least once
                for expert in (0, 1, 2, 0, 2, 1):
                    with cache.lease(expert) as resident:
                        for name, copy_ in resident.items():
                            self.assertIsNot(copy_, bank[expert][name])
                            self.assertNotIn(copy_, table)
            self.assertGreater(cache.eviction_count, 0)
            step_all(opt, params, round_)
            self.assertEqual(M.check_invariant(opt), [], 'invariant I broke after a page out/in round')
            self.assertEqual({id(k) for k in table.keys()}, owned, 'a foreign master was attached or a master was lost')
            for p in params:
                self.assertTrue(torch.equal(p.detach(), table[p].to(torch.bfloat16)))
                self.assertEqual(table[p].dtype, torch.float32)

    def test_a_copy_of_a_parameter_never_inherits_its_master(self):
        bank, params, opt = bank_and_optimizer(experts=1)
        M.enable(opt)
        step_all(opt, params, 0)
        table = M.masters(opt)
        for p in params:
            self.assertIn(p, table)
            self.assertNotIn(p.detach(), table)
            self.assertNotIn(torch.nn.Parameter(p.detach().clone()), table)
            self.assertNotIn(copy.deepcopy(p), table)

    def test_a_freed_parameter_drops_its_master_and_a_new_one_does_not_reuse_it(self):
        holder = types.SimpleNamespace()
        table = M.masters(holder)
        for _ in range(64):
            p = torch.nn.Parameter(torch.zeros(8, dtype=torch.bfloat16))
            table[p] = torch.ones(8)
            self.assertEqual(len(table), 1)
            del p
            gc.collect()
            self.assertEqual(len(table), 0, 'the master outlived its Parameter')
            q = torch.nn.Parameter(torch.zeros(8, dtype=torch.bfloat16))  # the allocator may hand q the address p had
            self.assertNotIn(q, table)
            self.assertIsNone(table.get(q))
            del q

    def test_dropping_a_parameter_from_the_optimizer_does_not_leave_a_master_for_its_successor(self):
        bank, params, opt = bank_and_optimizer(experts=1)
        M.enable(opt)
        step_all(opt, params, 0)
        table = M.masters(opt)
        dropped = params[0]
        opt.param_groups[0]['params'].remove(dropped)
        opt.state.pop(dropped, None)
        bank[0].pop('w')
        params.remove(dropped)
        del dropped
        gc.collect()
        self.assertEqual(len(table), 1)
        successor = torch.nn.Parameter(torch.zeros(64, dtype=torch.bfloat16))
        self.assertNotIn(successor, table)
        self.assertEqual(M.check_invariant(opt), [])


if __name__ == '__main__':
    unittest.main()
