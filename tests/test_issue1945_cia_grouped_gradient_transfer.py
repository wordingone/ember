# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Grouped gradient order and bounded transfers through the real expert cache.

CPU cases need no CUDA initialization. CUDA cases require the explicit test-only
EMBER_CIA_GROUPED_GRADIENT_CUDA=1 flag and the controller's owned 3 GiB host /
120 s envelope. Their fixed tensors are small; allocator allowance is 1 GiB.
These are numerical/copy-count unit fixtures, not full-model or throughput runs.
"""
from collections import Counter
import os
from pathlib import Path
import sys
import unittest

import torch
import torch.nn.functional as F
from torch.utils._python_dispatch import TorchDispatchMode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model.ember_v0_residency import ExpertCache, paged_swiglu, paged_swiglu_group


NAMES = ("up", "gate", "down")
CUDA_OPT_IN = "EMBER_CIA_GROUPED_GRADIENT_CUDA"


class ObserveCudaToCpuCopies(TorchDispatchMode):
    """Observe successful real transfers; do not replace any tensor operation."""

    def __init__(self):
        super().__init__()
        self.copies = []

    def __torch_dispatch__(self, func, types, args=(), kwargs=None):
        kwargs = {} if kwargs is None else kwargs
        result = func(*args, **kwargs)
        source, target = None, None
        if func == torch.ops.aten._to_copy.default:
            source, target = args[0], result
        elif func == torch.ops.aten.copy_.default:
            target, source = args[:2]
        if (isinstance(source, torch.Tensor) and isinstance(target, torch.Tensor)
                and source.device.type == "cuda" and target.device.type == "cpu"):
            self.copies.append((str(func), tuple(source.shape), source.dtype,
                                source.numel() * source.element_size()))
        return result


def fixture(device, *, lengths=(7, 3, 1), frozen=()):
    # Powers of two keep setup exact. The three upstream scales make the BF16
    # sequential sum observably different from accumulating in FP32 then casting.
    weights = {
        name: torch.nn.Parameter(torch.full(shape, value, dtype=torch.bfloat16),
                                 requires_grad=name not in frozen)
        for name, shape, value in (("up", (32, 64), 0.03125),
                                   ("gate", (32, 64), 0.0625),
                                   ("down", (64, 32), 0.015625))
    }
    values = tuple(torch.full((length, 64), 0.125, dtype=torch.bfloat16, device=device,
                              requires_grad=True) for length in lengths)
    upstream = []
    for length, scale in zip(lengths, (256.0, 1.0, -256.0)):
        gradient = torch.zeros((length, 64), dtype=torch.bfloat16, device=device)
        gradient[0].fill_(scale)
        upstream.append(gradient)
    return weights, values, tuple(upstream)


def explicit_sequential_reference(weights, values, upstream):
    """Independent autograd math, with each BF16 weight gradient copied before sum."""
    outputs, value_gradients = [], []
    sums = {name: None for name in NAMES}
    wide_sums = {name: None for name in NAMES}
    for value, output_gradient in zip(values, upstream):
        x = value.detach().clone().requires_grad_(True)
        up, gate, down = (weights[name].detach().to(device=value.device, copy=True).requires_grad_(True)
                          for name in NAMES)
        result = F.linear(F.silu(F.linear(x, gate)) * F.linear(x, up), down)
        gradients = torch.autograd.grad(result, (x, up, gate, down), output_gradient)
        outputs.append(result.detach())
        value_gradients.append(gradients[0])
        for name, gradient in zip(NAMES, gradients[1:]):
            if weights[name].requires_grad:
                moved = gradient.to(device="cpu", copy=True)
                sums[name] = moved if sums[name] is None else sums[name] + moved
                widened = moved.float()
                wide_sums[name] = widened if wide_sums[name] is None else wide_sums[name] + widened
    return tuple(outputs), tuple(value_gradients), sums, wide_sums


class GroupedGradientChecks:
    def run_grouped(self, device, *, lengths=(7, 3, 1), frozen=()):
        weights, values, upstream = fixture(device, lengths=lengths, frozen=frozen)
        reference = explicit_sequential_reference(weights, values, upstream)
        cache = ExpertCache({3: weights}, device=device)
        observer = ObserveCudaToCpuCopies()
        with cache.step():
            outputs = paged_swiglu_group(values, cache, 3)
            self.assertEqual(cache.pending, 1)
            self.assertEqual(cache.lease_count, 1)
            self.assertEqual(cache.leased, set())
            for actual, expected in zip(outputs, reference[0]):
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
            # Reference transfers and forward cache population are outside observation.
            with observer:
                torch.autograd.backward(outputs, upstream)
            self.assertEqual(cache.pending, 0)
            self.assertEqual(cache.lease_count, 2)
            self.assertEqual(cache.leased, set())
        self.assertFalse(cache.active)
        self.assertFalse(cache.poisoned)
        self.assertEqual(cache.pending, 0)
        self.assertEqual(cache.entries, {})
        self.assertEqual(cache.leased, set())
        self.assertEqual(cache.miss_count, 1)
        for value, expected in zip(values, reference[1]):
            self.assertIsNotNone(value.grad)
            torch.testing.assert_close(value.grad, expected, rtol=0, atol=0)
        for name in NAMES:
            if name in frozen:
                self.assertIsNone(weights[name].grad)
                self.assertIsNone(reference[2][name])
            else:
                self.assertIsNotNone(weights[name].grad)
                self.assertEqual(weights[name].grad.device.type, "cpu")
                self.assertEqual(weights[name].grad.dtype, torch.bfloat16)
                torch.testing.assert_close(weights[name].grad, reference[2][name], rtol=0, atol=0)
        return observer.copies, reference


class GroupedGradientCPU(GroupedGradientChecks, unittest.TestCase):
    def test_partial_chunks_preserve_ordered_bf16_sum(self):
        copies, reference = self.run_grouped(torch.device("cpu"))
        self.assertEqual(copies, [])
        # This fixture must distinguish the required rounded sum from a wider
        # accumulator; otherwise a precision/order change could pass unnoticed.
        self.assertFalse(torch.equal(reference[2]["down"], reference[3]["down"].to(torch.bfloat16)))

    def test_partial_chunks_preserve_frozen_weight_and_value_gradients(self):
        copies, _ = self.run_grouped(torch.device("cpu"), frozen=("gate",))
        self.assertEqual(copies, [])

    def test_single_chunk_matches_real_single_chunk_cache_path(self):
        weights, values, upstream = fixture(torch.device("cpu"), lengths=(3,))
        grouped_cache = ExpertCache({3: weights}, device=torch.device("cpu"))
        with grouped_cache.step():
            grouped = paged_swiglu_group(values, grouped_cache, 3)[0]
            grouped.backward(upstream[0])
        expected_weights = {name: value.grad.clone() for name, value in weights.items()}
        expected_value = values[0].grad.clone()
        for value in weights.values():
            value.grad = None
        values[0].grad = None
        single_cache = ExpertCache({3: weights}, device=torch.device("cpu"))
        with single_cache.step():
            single = paged_swiglu(values[0], single_cache, 3)
            single.backward(upstream[0])
        torch.testing.assert_close(grouped, single, rtol=0, atol=0)
        torch.testing.assert_close(values[0].grad, expected_value, rtol=0, atol=0)
        for name in NAMES:
            torch.testing.assert_close(weights[name].grad, expected_weights[name], rtol=0, atol=0)
        for cache in (grouped_cache, single_cache):
            self.assertEqual((cache.pending, cache.lease_count), (0, 2))
            self.assertFalse(cache.active)
            self.assertEqual(cache.entries, {})
            self.assertEqual(cache.leased, set())


@unittest.skipUnless(os.environ.get(CUDA_OPT_IN) == "1",
                     "requires explicit test-only CUDA grant and owned resource envelope")
class GroupedGradientCUDA(GroupedGradientChecks, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not torch.cuda.is_available():
            raise RuntimeError("explicit CUDA unit replay requested without available CUDA")
        cls.device = torch.device("cuda:0")
        cls.allowance = 1 << 30
        total = torch.cuda.get_device_properties(cls.device).total_memory
        if total < cls.allowance:
            raise RuntimeError("CUDA device cannot provide the fixed 1 GiB allowance")
        torch.cuda.set_per_process_memory_fraction(cls.allowance / total, cls.device)

    def test_three_required_weight_copies_independent_of_member_count(self):
        for lengths in ((7,), (7, 3, 1)):
            with self.subTest(lengths=lengths):
                copies, _ = self.run_grouped(self.device, lengths=lengths)
                self.assertLessEqual(torch.cuda.max_memory_allocated(self.device), self.allowance)
                self.assertEqual(len(copies), 3, f"one transfer per required weight, observed {copies}")
                self.assertEqual(Counter(shape for _, shape, _, _ in copies), {(32, 64): 2, (64, 32): 1})
                self.assertEqual(sum(size for _, _, _, size in copies), 12_288)
                self.assertTrue(all(dtype == torch.bfloat16 for _, _, dtype, _ in copies))

    def test_partial_chunks_copy_only_two_required_weights_when_gate_is_frozen(self):
        copies, _ = self.run_grouped(self.device, frozen=("gate",))
        self.assertLessEqual(torch.cuda.max_memory_allocated(self.device), self.allowance)
        self.assertEqual(len(copies), 2, f"frozen weight has no gradient transfer, observed {copies}")
        self.assertEqual(Counter(shape for _, shape, _, _ in copies), {(32, 64): 1, (64, 32): 1})
        self.assertEqual(sum(size for _, _, _, size in copies), 8_192)
        self.assertTrue(all(dtype == torch.bfloat16 for _, _, dtype, _ in copies))


if __name__ == "__main__":
    unittest.main()
