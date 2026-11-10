# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU reds for the two fp32-master optimizer call sites the numerics tests did not reach (#2119, lead review 82486 item 6):
SegmentOptimizer._launch (the early per-segment step on the side stream) and the non-deferred measure_step branch
(ungated_optimizer_step). Each must take the master path when the treatment is on, never the native fused kernel, and must keep
invariant I (param == bf16(master)). CUDA streams and events are stubbed; the optimizer maths is real (fused AdamW on CPU)."""
from contextlib import contextmanager
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
sys.path.insert(0, str(ROOT / 'src'))
import cia_fp32_master as M  # noqa: E402
import cia_step_runner as R  # noqa: E402


def build(master, n=64, experts=(('a', 0), ('b', 1))):
    g = torch.Generator().manual_seed(11)
    dense = torch.nn.Parameter((torch.randn(n, generator=g) * 0.05).to(torch.bfloat16))
    owners = {key: [torch.nn.Parameter((torch.randn(n, generator=g) * 0.05).to(torch.bfloat16))] for key in (0, 1)}
    params = [dense] + [p for ps in owners.values() for p in ps]
    optimizer = torch.optim.AdamW(params, lr=1e-2, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01, foreach=False, fused=True)
    if master:
        M.enable(optimizer)
    return dense, owners, params, optimizer


def load_grads(params, round_):
    gen = torch.Generator().manual_seed(900 + round_)
    for p in params:
        p.grad = (torch.randn(p.shape, generator=gen) * 0.1).to(torch.bfloat16)


class Side:
    def wait_event(self, event):
        pass


class Event:
    def record(self, stream):
        pass


@contextmanager
def no_cuda():
    @contextmanager
    def stream(_):
        yield
    with mock.patch.object(torch.cuda, 'Event', Event), mock.patch.object(torch.cuda, 'current_stream', lambda device=None: None), \
            mock.patch.object(torch.cuda, 'stream', stream):
        yield


def segment_optimizer(optimizer, owners, params):
    seg = object.__new__(R.SegmentOptimizer)
    seg.optimizer, seg.device, seg.side = optimizer, torch.device('cpu'), Side()
    seg.owner_of = {id(p): key for key, ps in owners.items() for p in ps}
    seg.keys = tuple(sorted(owners))
    seg.position = {key: k for k, key in enumerate(seg.keys)}
    seg.group_index = {id(p): 0 for p in params}
    return seg


def armed(skip_owner=None):
    skip = torch.zeros(2)
    if skip_owner is not None:
        skip[skip_owner] = 1.0
    return dict(dense=torch.zeros(()), skip=skip, stepped=set())


class SegmentLaunch(unittest.TestCase):
    def test_treatment_launch_steps_masters_and_keeps_the_invariant(self):
        dense, owners, params, optimizer = build(True)
        seg = segment_optimizer(optimizer, owners, params)
        for round_ in range(3):
            load_grads(params, round_)
            state = armed()
            with no_cuda():
                seg._launch(params, state)
            self.assertEqual(state['stepped'], {id(p) for p in params})
            self.assertEqual(M.check_invariant(optimizer), [])
        table = M.masters(optimizer)
        for p in params:
            self.assertIn(p, table)
            self.assertEqual(table[p].dtype, torch.float32)
            self.assertEqual(optimizer.state[p]['exp_avg'].dtype, torch.float32)
            self.assertEqual(optimizer.state[p]['exp_avg_sq'].dtype, torch.float32)
            self.assertTrue(torch.equal(p.detach(), table[p].to(torch.bfloat16)))

    def test_a_gated_expert_owner_does_not_move_and_its_clock_does_not_advance(self):
        dense, owners, params, optimizer = build(True)
        seg = segment_optimizer(optimizer, owners, params)
        load_grads(params, 0)
        with no_cuda():
            seg._launch(params, armed())          # one real step so every owner has state
        before = {id(p): (p.detach().clone(), M.masters(optimizer)[p].clone(), float(optimizer.state[p]['step'])) for p in params}
        load_grads(params, 1)
        with no_cuda():
            seg._launch(params, armed(skip_owner=seg.position[1]))
        skipped = owners[1][0]
        weight, master, step = before[id(skipped)]
        self.assertTrue(torch.equal(skipped.detach(), weight))
        self.assertTrue(torch.equal(M.masters(optimizer)[skipped], master))
        self.assertEqual(float(optimizer.state[skipped]['step']), step)
        self.assertGreater(float(optimizer.state[owners[0][0]]['step']), before[id(owners[0][0])][2])
        self.assertEqual(M.check_invariant(optimizer), [])

    def test_the_native_launch_is_untouched_when_no_treatment_is_declared(self):
        dense, owners, params, optimizer = build(False)
        seg = segment_optimizer(optimizer, owners, params)
        load_grads(params, 0)
        with no_cuda():
            seg._launch(params, armed())
        self.assertFalse(M.enabled(optimizer))
        self.assertEqual(len(M.masters(optimizer)), 0)
        for p in params:
            self.assertEqual(optimizer.state[p]['exp_avg'].dtype, torch.bfloat16)


class UngatedStep(unittest.TestCase):
    def test_the_non_deferred_branch_steps_masters_for_the_treatment_and_natively_otherwise(self):
        for master in (True, False):
            dense, owners, params, optimizer = build(master)
            for round_ in range(3):
                load_grads(params, round_)
                R.ungated_optimizer_step(optimizer)
            self.assertEqual(M.enabled(optimizer), master)
            for p in params:
                dtype = torch.float32 if master else torch.bfloat16
                self.assertEqual(optimizer.state[p]['exp_avg_sq'].dtype, dtype)
                if master:
                    self.assertTrue(torch.equal(p.detach(), M.masters(optimizer)[p].to(torch.bfloat16)))
            self.assertEqual(M.check_invariant(optimizer), [])

    def test_parameters_without_a_gradient_are_left_alone(self):
        dense, owners, params, optimizer = build(True)
        load_grads(params, 0)
        params[1].grad = None
        before = params[1].detach().clone()
        R.ungated_optimizer_step(optimizer)
        self.assertTrue(torch.equal(params[1].detach(), before))
        self.assertNotIn(params[1], M.masters(optimizer))


class Wiring(unittest.TestCase):
    def test_measure_step_calls_the_helper_and_launch_calls_the_master_step(self):
        import inspect
        self.assertIn('ungated_optimizer_step(optimizer)', inspect.getsource(R.measure_step))
        self.assertIn('cia_fp32_master.step(', inspect.getsource(R.SegmentOptimizer._launch))
        self.assertIn('cia_fp32_master.step(', inspect.getsource(R.gated_optimizer_step))


if __name__ == '__main__':
    unittest.main()
