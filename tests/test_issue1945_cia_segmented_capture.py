# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Segmented capture harness (#1945 G1): ownership, carried gradients, exemplar refusal, warm-up state proof.

CPU cases run the harness in its eager mode (no graphs) against a three-segment stand-in with an eager block between
segments, exactly the decoder's shape: S0(x, positions) -> carry, eager block replaces slot 1, S1 -> carry, S2 -> logits.
The CUDA cases (opt-in EMBER_CIA_CAPTURE_CUDA=1, so a shared GPU is never touched by accident) graph the same segments
and require the captured step's loss and owner grads to equal the eager step's. No throughput or conformance claim.
"""
import os
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model import ember_v0_capture as subject  # noqa: E402

WIDTH = 16


class Owner(torch.nn.Module):
    """Three segments over owner parameters, plus the eager block that sits between S0/S1 and S1/S2."""

    def __init__(self):
        super().__init__()
        self.register_buffer("valid", torch.ones((), dtype=torch.bool))  # in-place accumulator a segment mutates
        g = torch.Generator().manual_seed(1945)
        self.w0 = torch.nn.Parameter(torch.randn(WIDTH, WIDTH, generator=g) * 0.1)
        self.w1 = torch.nn.Parameter(torch.randn(WIDTH, WIDTH, generator=g) * 0.1)
        self.w2 = torch.nn.Parameter(torch.randn(WIDTH, 4, generator=g) * 0.1)
        self.prior = torch.nn.Parameter(torch.zeros(WIDTH))

    def s0(self, x, positions):
        self.valid.logical_and_(torch.isfinite(x).all())
        h = torch.tanh(x @ self.w0) + positions.to(x.dtype)[:, None] * 0.01
        return h, h * 0.5, self.prior + h.mean(0)  # shared, normed-expert-input slot, differentiable prior carry

    def s1(self, shared, expert_residual, prior):
        h = shared + expert_residual
        return h, torch.tanh(h @ self.w1), prior * 1.5

    def s2(self, shared, expert_residual, prior):
        h = shared + expert_residual + prior[None, :]
        return (h @ self.w2,)

    @staticmethod
    def eager_block(slot):  # the decoder's grouped expert block: eager, data-dependent, between segments
        return slot * (slot.abs() > 0.05).to(slot.dtype)

    def segments(self):
        return (subject.SegmentSpec(0, self.s0, (self.w0, self.prior), static_state=(self.valid,), name="s0"),
                subject.SegmentSpec(1, self.s1, (self.w1,), name="s1"),
                subject.SegmentSpec(2, self.s2, (self.w2,), name="s2"))

    def step(self, harness, x, positions):
        shared, slot, prior = harness.run(0, x, positions)
        shared, slot, prior = harness.run(1, shared, self.eager_block(slot), prior)
        (logits,) = harness.run(2, shared, self.eager_block(slot), prior)
        return logits


def inputs(device, seed=7, rows=8):
    g = torch.Generator().manual_seed(seed)
    return (torch.randn(rows, WIDTH, generator=g).to(device), torch.arange(rows, device=device),
            torch.randint(0, 4, (rows,), generator=g).to(device))


def loss_fn(logits, targets):
    return torch.nn.functional.cross_entropy(logits.float(), targets)


class Execution:
    """Stand-in for ResidentExecution: capture_region() must be entered exactly once per capture and exited."""
    step_id = 0

    def __init__(self):
        self.regions = []

    def capture_region(self):
        owner = self

        class Region:
            def __enter__(self):
                owner.regions.append("enter")

            def __exit__(self, *exc):
                owner.regions.append("exit")
                return False
        return Region()


def harness_for(model, device):
    return subject.SegmentedStep(model.segments(), device=device).bind(Execution(), loss_fn=loss_fn)


class ContractTests(unittest.TestCase):
    def test_run_before_record_refuses(self):
        model = Owner()
        h = harness_for(model, "cpu")
        with self.assertRaises(subject.CaptureStateError):
            h.run(0, *inputs("cpu")[:2])

    def test_recorded_step_matches_plain_eager_and_capture_proves_state(self):
        model = Owner()
        x, positions, targets = inputs("cpu")
        reference = Owner()
        reference.load_state_dict(model.state_dict())
        ref_logits = reference.s2(*(lambda s, sl, p: (s, Owner.eager_block(sl), p))(
            *reference.s1(*(lambda s, sl, p: (s, Owner.eager_block(sl), p))(*reference.s0(x, positions)))))[0]
        loss_fn(ref_logits, targets).backward()
        h = harness_for(model, "cpu")
        optimizer = torch.optim.AdamW(model.parameters(), foreach=False)
        with h.record():
            logits = model.step(h, x, positions)
        torch.testing.assert_close(logits, ref_logits, rtol=0, atol=0)
        loss_fn(logits, targets).backward()
        for a, b in zip(model.parameters(), reference.parameters()):
            torch.testing.assert_close(a.grad, b.grad, rtol=0, atol=0)
        optimizer.step()
        h.zero_grad()
        storage = [p.grad.data_ptr() for p in model.parameters()]
        before = [p.detach().clone() for p in model.parameters()]
        rng = torch.get_rng_state()
        model.valid.fill_(False)  # a value the warm-up would otherwise overwrite: static_state is restored exactly
        h.capture(optimizer=optimizer)
        self.assertEqual(h.execution.regions, ["enter", "exit"])  # synthetic calls ran inside the execution's region
        self.assertFalse(bool(model.valid))
        model.valid.fill_(True)
        self.assertEqual(h.captures, 1)
        self.assertFalse(h.captured)  # CPU: eager mode, the state proof still ran
        for p, b in zip(model.parameters(), before):
            torch.testing.assert_close(p.detach(), b, rtol=0, atol=0)
            self.assertEqual(int(p.grad.count_nonzero()), 0)
        self.assertEqual([p.grad.data_ptr() for p in model.parameters()], storage)  # static-accumulate kept storage
        self.assertTrue(torch.equal(torch.get_rng_state(), rng))
        # A second step through the recorded harness is the eager reference again, grads accumulate in place.
        logits2 = model.step(h, x, positions)
        loss_fn(logits2, targets).backward()
        self.assertEqual([p.grad.data_ptr() for p in model.parameters()], storage)
        self.assertGreater(float(model.w0.grad.abs().sum()), 0.0)

    def test_exemplar_mismatch_refuses_before_running(self):
        model = Owner()
        h = harness_for(model, "cpu")
        x, positions, _ = inputs("cpu")
        with h.record():
            model.step(h, x, positions)
        calls = []
        model.w0.register_hook(lambda g: calls.append(g))
        for bad in ((x[:4], positions[:4]), (x.double(), positions), (x.requires_grad_(), positions)):
            with self.subTest(bad=[str(t.dtype) + str(tuple(t.shape)) + str(t.requires_grad) for t in bad]):
                with self.assertRaises(subject.ExemplarMismatch):
                    h.run(0, *bad)
        x.requires_grad_(False)
        with self.assertRaises(subject.ExemplarMismatch):
            h.run(1, x, x)  # wrong arity for S1
        self.assertEqual(calls, [])

    def test_bind_and_record_invalidate_capture(self):
        model = Owner()
        h = harness_for(model, "cpu")
        x, positions, _ = inputs("cpu")
        with h.record():
            model.step(h, x, positions)
        h.capture()
        h.bind(Execution())
        with self.assertRaises(subject.CaptureStateError):
            h.run(0, x, positions)
        with h.record():
            model.step(h, x, positions)
        with h.record():  # re-recording drops the previous exemplars first
            pass
        with self.assertRaises(subject.CaptureStateError):
            h.capture()

    def test_spec_and_constructor_refusals(self):
        model = Owner()
        with self.assertRaises(ValueError):
            subject.SegmentSpec(-1, model.s0)
        with self.assertRaises(ValueError):
            subject.SegmentSpec(0, model.s0, (torch.ones(2),))
        with self.assertRaises(ValueError):
            subject.SegmentedStep((subject.SegmentSpec(0, model.s0, static_state=(model.w0,)),), device="cpu")
        with self.assertRaises(ValueError):
            subject.SegmentedStep(model.segments()[1:], device="cpu")
        with self.assertRaises(ValueError):
            subject.SegmentedStep(model.segments(), device="cpu", grad_mode="set-to-none")
        with self.assertRaises(subject.CaptureStateError):
            subject.SegmentedStep(model.segments(), device="cpu").capture()
        h = harness_for(model, "cpu")
        self.assertEqual(h.receipt()["segments"], 3)
        self.assertEqual(h.receipt()["grad_mode"], "static-accumulate")

    def test_loss_is_runner_owned(self):
        model = Owner()
        h = subject.SegmentedStep(model.segments(), device="cpu").bind(Execution())
        with self.assertRaises(subject.CaptureStateError):
            h.loss(torch.zeros(2, 4), torch.zeros(2, dtype=torch.long))


@unittest.skipUnless(os.environ.get("EMBER_CIA_CAPTURE_CUDA") == "1" and torch.cuda.is_available(),
                     "CUDA capture cases are opt-in (EMBER_CIA_CAPTURE_CUDA=1)")
class CudaCaptureTests(unittest.TestCase):
    def test_captured_step_equals_eager_step_and_replays(self):
        device = torch.device("cuda")
        model = Owner().to(device)
        reference = Owner().to(device)
        reference.load_state_dict(model.state_dict())
        x, positions, targets = inputs(device)
        h = harness_for(model, device)
        opt = torch.optim.AdamW(model.parameters(), foreach=False)
        with h.record():
            model.step(h, x, positions)
        h.zero_grad()
        h.capture(optimizer=opt)
        self.assertTrue(h.captured)
        ref_h = harness_for(reference, device)
        for step in range(3):
            xs, ps, ts = inputs(device, seed=100 + step)
            h.zero_grad()
            loss = loss_fn(model.step(h, xs, ps), ts)
            loss.backward()
            with ref_h.record():
                ref_loss = loss_fn(reference.step(ref_h, xs, ps), ts)
            ref_h.zero_grad()
            ref_loss.backward()
            torch.testing.assert_close(loss, ref_loss, rtol=1e-5, atol=1e-6)
            for name, a, b in zip(model.state_dict(), model.parameters(), reference.parameters()):
                with self.subTest(step=step, owner=name):
                    self.assertGreater(float(a.grad.abs().sum()), 0.0)  # every owner grad is closed under capture
                    torch.testing.assert_close(a.grad, b.grad, rtol=1e-4, atol=1e-6)

    def test_static_float_carry_keeps_its_role_under_capture(self):
        """A frozen float carry (router keys under frozen-router support) recorded carry-static must come back static from
        the graphed segment; the differentiable carry beside it keeps its grad role and its gradient."""
        device = torch.device("cuda")
        w = torch.nn.Parameter(torch.randn(WIDTH, WIDTH, device=device) * 0.1)
        frozen = torch.randn(WIDTH, device=device)  # requires_grad False: a frozen-support parameter's value
        specs = (subject.SegmentSpec(0, lambda x: (torch.tanh(x @ w), frozen * 2.0), (w,)),
                 subject.SegmentSpec(1, lambda y, k: (torch.tanh(y @ w) + k[None, :],), (w,)))
        h = subject.SegmentedStep(specs, device=device).bind(Execution())
        x = torch.randn(8, WIDTH, device=device)
        with h.record():
            y, k = h.run(0, x)
            self.assertFalse(k.requires_grad)
            (z,) = h.run(1, y, k)
        del y, k, z
        h.zero_grad()
        h.capture()
        self.assertTrue(h.captured)
        y, k = h.run(0, x)
        self.assertTrue(y.requires_grad)
        self.assertFalse(k.requires_grad)  # restored carry-static role; the next segment accepts it
        (z,) = h.run(1, y, k)
        z.sum().backward()
        expected = torch.autograd.grad((torch.tanh(torch.tanh(x @ w) @ w) + (frozen * 2.0)[None, :]).sum(), w)[0]
        torch.testing.assert_close(w.grad, expected, rtol=1e-4, atol=1e-6)
        torch.testing.assert_close(k, frozen * 2.0, rtol=0, atol=0)

    def test_tied_owner_accumulates_across_two_captured_segments(self):
        device = torch.device("cuda")
        w = torch.nn.Parameter(torch.randn(WIDTH, WIDTH, device=device) * 0.1)
        specs = (subject.SegmentSpec(0, lambda x: (torch.tanh(x @ w),), (w,)),
                 subject.SegmentSpec(1, lambda y: (torch.tanh(y @ w),), (w,)))
        h = subject.SegmentedStep(specs, device=device).bind(Execution())
        x = torch.randn(8, WIDTH, device=device)
        with h.record():
            (y,) = h.run(0, x)
            h.run(1, y)
        del y  # the exemplar step's autograd graph must not outlive the record (AccumulateGrad stream binding)
        h.zero_grad()
        h.capture()
        (y,) = h.run(0, x)
        (z,) = h.run(1, y)
        z.sum().backward()
        expected = torch.autograd.grad(torch.tanh(torch.tanh(x @ w) @ w).sum(), w)[0]
        torch.testing.assert_close(w.grad, expected, rtol=1e-4, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
