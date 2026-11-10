# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU reds for the fp32 master treatment (#2119 H49 sweep follow-up); no training claim, no GPU, tiny tensors."""
from pathlib import Path
import sys
import unittest

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import cia_fp32_master as M  # noqa: E402

ZERO = torch.zeros(())


def make(seed=0, n=4096, lr=1e-4):
    g = torch.Generator().manual_seed(seed)
    p = torch.nn.Parameter((torch.randn(n, generator=g) * 0.05).to(torch.bfloat16))
    q = torch.nn.Parameter((torch.randn(n // 2, generator=g) * 0.01).to(torch.bfloat16))
    opt = torch.optim.AdamW([p, q], lr=lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False, fused=True)
    return p, q, opt


def grads(p, q, step):
    gen = torch.Generator().manual_seed(1000 + step)
    p.grad = (torch.randn(p.shape, generator=gen) * 0.1).to(torch.bfloat16)
    q.grad = (torch.randn(q.shape, generator=gen) * 0.1).to(torch.bfloat16)


def master_step(opt, found_inf=ZERO):
    for group in opt.param_groups:
        M.step(opt, group, [x for x in group['params'] if x.grad is not None], found_inf)


class Fp32MasterNumerics(unittest.TestCase):
    def test_master_path_moves_more_elements_than_native_bf16(self):
        p0, q0, opt0 = make()
        start = p0.detach().clone()
        for s in range(50):
            grads(p0, q0, s)
            opt0.step()
        native = float((p0.detach() != start).float().mean())
        p1, q1, opt1 = make()
        M.enable(opt1)
        for s in range(50):
            grads(p1, q1, s)
            master_step(opt1)
        master = float((p1.detach() != start).float().mean())
        self.assertGreater(master, native)
        self.assertGreaterEqual(master, 1.5 * native)

    def test_bf16_view_is_the_rounded_master_and_equals_an_independent_fp32_reference(self):
        p, q, opt = make()
        M.enable(opt)
        ref_p, ref_q = (torch.nn.Parameter(x.detach().to(torch.float32).clone()) for x in (p, q))
        ref = torch.optim.AdamW([ref_p, ref_q], lr=1e-4, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False, fused=True)
        for s in range(30):
            grads(p, q, s)
            ref_p.grad, ref_q.grad = p.grad.float().clone(), q.grad.float().clone()
            ref.step()
            master_step(opt)
            self.assertEqual(M.check_invariant(opt), [])
        self.assertTrue(torch.equal(M.masters(opt)[p], ref_p.detach()))
        self.assertTrue(torch.equal(M.masters(opt)[q], ref_q.detach()))
        self.assertTrue(torch.equal(p.detach(), ref_p.detach().to(torch.bfloat16)))
        for x in (p, q):
            for key in ('step', 'exp_avg', 'exp_avg_sq'):
                self.assertEqual(opt.state[x][key].dtype, torch.float32)

    def test_found_inf_leaves_master_moments_step_and_bits_untouched(self):
        p, q, opt = make()
        M.enable(opt)
        grads(p, q, 0)
        master_step(opt)
        keep = [p.detach().clone(), M.masters(opt)[p].clone(), opt.state[p]['exp_avg'].clone(),
                opt.state[p]['exp_avg_sq'].clone(), opt.state[p]['step'].clone()]
        grads(p, q, 1)
        master_step(opt, torch.ones(()))
        now = [p.detach(), M.masters(opt)[p], opt.state[p]['exp_avg'], opt.state[p]['exp_avg_sq'], opt.state[p]['step']]
        for a, b in zip(keep, now):
            self.assertTrue(torch.equal(a, b))

    def test_bf16_parent_state_converts_exactly(self):
        p, q, opt = make()
        for s in range(5):
            grads(p, q, s)
            opt.step()
        before = {k: opt.state[p][k].clone() for k in ('exp_avg', 'exp_avg_sq', 'step')}
        M.enable(opt)
        self.assertTrue(torch.equal(opt.state[p]['exp_avg'], before['exp_avg'].float()))
        self.assertTrue(torch.equal(opt.state[p]['exp_avg_sq'], before['exp_avg_sq'].float()))
        self.assertTrue(torch.equal(opt.state[p]['step'], before['step']))
        self.assertTrue(torch.equal(M.masters(opt)[p], p.detach().float()))
        self.assertEqual(M.check_invariant(opt), [])

    def test_unsupported_optimizers_refuse(self):
        bad = torch.optim.AdamW([torch.nn.Parameter(torch.zeros(2, dtype=torch.bfloat16))], fused=True, foreach=False, amsgrad=True)
        with self.assertRaises(ValueError):
            M.enable(bad)
        fp32 = torch.optim.AdamW([torch.nn.Parameter(torch.zeros(2))], fused=True, foreach=False)
        with self.assertRaises(ValueError):
            M.enable(fp32)


if __name__ == '__main__':
    unittest.main()
