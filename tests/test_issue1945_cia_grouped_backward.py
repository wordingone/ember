# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Grouped first-order backward through the real CIA expert cache.

CPU profiling observes executed operators and autograd engine nodes, not time.
CUDA cases require EMBER_CIA_GROUPED_BACKWARD_CUDA=1 and a controller-owned
3 GiB host / 120 s process envelope; they set a fixed 1 GiB allocator allowance.
Default collection and CPU cases do not initialize CUDA. These small fixtures
do not establish full-model numerical conformance or throughput qualification.
"""
from collections import Counter
import gc
import os
from pathlib import Path
import sys
import unittest

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model.ember_v0_residency import ExpertCache, paged_swiglu_group


NAMES = ("up", "gate", "down")
CUDA_OPT_IN = "EMBER_CIA_GROUPED_BACKWARD_CUDA"
SILU_ENGINE = "autograd::engine::evaluate_function: SiluBackward0"
MM_ENGINE = "autograd::engine::evaluate_function: MmBackward0"


def cpu_profile():
    # Explicit CPU activity also records dispatch when a separately authorized
    # CUDA case runs. GPU activity collection is unnecessary for call counts.
    return torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU])


def counts(profile):
    return Counter({event.key: event.count for event in profile.key_averages()})


def fixture(device, *, layout="contiguous", frozen=(), frozen_inputs=()):
    generator = torch.Generator(device="cpu").manual_seed(1945)
    weights = {
        name: torch.nn.Parameter(
            (torch.randn(shape, generator=generator, device="cpu") / 16).to(torch.bfloat16),
            requires_grad=name not in frozen,
        )
        for name, shape in (("up", (32, 64)), ("gate", (32, 64)), ("down", (64, 32)))
    }
    shapes = ((7, 64), (3, 64), (1, 64))
    if layout == "rank3":
        shapes = ((2, 3, 64), (1, 2, 64))
    elif layout == "column_major":
        shapes = ((7, 64), (3, 64))
    elif layout != "contiguous":
        raise ValueError("unknown fixture layout")
    pattern = ((torch.arange(64, device=device) % 11).float() / 64 + 0.125).to(torch.bfloat16)
    values, upstream = [], []
    for index, (shape, scale) in enumerate(zip(shapes, (256.0, 1.0, -256.0))):
        value = pattern.expand(shape).clone()
        if layout == "column_major":
            value = value.t().contiguous().t()
        value.requires_grad_(index not in frozen_inputs)
        gradient = torch.zeros(shape, dtype=torch.bfloat16, device=device)
        gradient.reshape(-1, 64)[0].fill_(scale)
        values.append(value)
        upstream.append(gradient)
    return weights, tuple(values), tuple(upstream)


def framework_reference(weights, values, upstream):
    """Framework derivatives, retaining per-member BF16 addition on the device.

    This computes no hand-written derivative and imports no production math
    helper. Detached reference leaves never write into the actual cache bank.
    """
    outputs, value_gradients = [], []
    summed = {name: None for name in NAMES}
    for value, output_gradient in zip(values, upstream):
        x = value.detach().clone(memory_format=torch.preserve_format).requires_grad_(True)
        up, gate, down = (
            weights[name].detach().to(device=value.device, copy=True).requires_grad_(True)
            for name in NAMES
        )
        result = F.linear(F.silu(F.linear(x, gate)) * F.linear(x, up), down)
        gradients = torch.autograd.grad(result, (x, up, gate, down), output_gradient)
        outputs.append(result.detach())
        value_gradients.append(gradients[0])
        for name, gradient in zip(NAMES, gradients[1:]):
            if weights[name].requires_grad:
                summed[name] = gradient if summed[name] is None else summed[name] + gradient
    return tuple(outputs), tuple(value_gradients), {
        name: None if gradient is None else gradient.to(device="cpu", copy=True)
        for name, gradient in summed.items()
    }


class GroupedBackwardChecks:
    def assert_native_dispatch(self, observed, members):
        # Two projection recomputations plus six derivative matrix products.
        # The previous nested-autograd path also recomputes the final output.
        self.assertEqual(observed["aten::mm"], 8 * members, observed)
        self.assertEqual(observed["aten::silu_backward"], members, observed)
        self.assertEqual(observed[SILU_ENGINE], 0, observed)
        self.assertEqual(observed[MM_ENGINE], 0, observed)

    def run_case(self, device, *, layout="contiguous", frozen=(), frozen_inputs=(), unused_middle=False):
        weights, values, upstream = fixture(device, layout=layout, frozen=frozen, frozen_inputs=frozen_inputs)
        if layout == "contiguous":
            self.assertTrue(all(value.ndim == 2 and value.is_contiguous() for value in values))
        elif layout == "column_major":
            self.assertTrue(all(value.ndim == 2 and not value.is_contiguous() for value in values))
        else:
            self.assertTrue(all(value.ndim == 3 for value in values))
        expected_upstream = list(upstream)
        used = tuple(range(len(values)))
        if unused_middle:
            self.assertEqual(len(values), 3)
            expected_upstream[1] = torch.zeros_like(upstream[1])
            used = (0, 2)
        reference = framework_reference(weights, values, tuple(expected_upstream))
        cache = ExpertCache({3: weights}, device=device)
        with cache.step():
            outputs = paged_swiglu_group(values, cache, 3)
            self.assertEqual(cache.pending, 1)
            self.assertEqual(cache.lease_count, 1)
            for actual, expected in zip(outputs, reference[0]):
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
            # Neither the reference nor the actual forward is in this region.
            # Omitting output 1 exercises real autograd upstream materialization.
            with cpu_profile() as profile:
                torch.autograd.backward(tuple(outputs[i] for i in used),
                                        tuple(upstream[i] for i in used))
            observed = counts(profile)
            self.assertEqual(cache.pending, 0)
            self.assertEqual(cache.lease_count, 2)
            self.assertEqual(cache.leased, set())
        self.assertFalse(cache.active)
        self.assertFalse(cache.poisoned)
        self.assertEqual(cache.entries, {})
        self.assertEqual(cache.leased, set())
        self.assertEqual(cache.pending, 0)
        for index, (value, expected) in enumerate(zip(values, reference[1])):
            if index in frozen_inputs:
                self.assertFalse(value.requires_grad)
                self.assertIsNone(value.grad)
            else:
                self.assertTrue(value.requires_grad)
                self.assertIsNotNone(value.grad)
                torch.testing.assert_close(value.grad, expected, rtol=0, atol=0)
        if unused_middle:
            torch.testing.assert_close(values[1].grad, torch.zeros_like(values[1]), rtol=0, atol=0)
        for name, weight in weights.items():
            if name in frozen:
                self.assertIsNone(weight.grad)
                self.assertIsNone(reference[2][name])
            else:
                self.assertIsNotNone(weight.grad)
                self.assertEqual(weight.grad.device.type, "cpu")
                self.assertEqual(weight.grad.dtype, torch.bfloat16)
                torch.testing.assert_close(weight.grad, reference[2][name], rtol=0, atol=0)
        return observed, len(values)


class GroupedBackwardCPU(GroupedBackwardChecks, unittest.TestCase):
    def test_framework_reference_calibrates_operator_and_engine_observer(self):
        weights, values, upstream = fixture(torch.device("cpu"))
        with cpu_profile() as profile:
            reference = framework_reference(weights, values, upstream)
        observed = counts(profile)
        members = len(values)
        self.assertEqual(observed["aten::mm"], 9 * members, observed)
        self.assertEqual(observed["aten::silu_backward"], members, observed)
        self.assertEqual(observed[SILU_ENGINE], members, observed)
        self.assertEqual(observed[MM_ENGINE], 3 * members, observed)
        self.assertTrue(all(torch.isfinite(value).all().item() for value in reference[1]))
        self.assertTrue(all(weight.grad is None for weight in weights.values()))
        self.assertTrue(all(value.grad is None for value in values))

    def test_native_partial_chunks_match_reference_without_inner_autograd(self):
        observed, members = self.run_case(torch.device("cpu"))
        self.assert_native_dispatch(observed, members)

    def test_frozen_weights_and_unused_middle_output_preserve_input_gradients(self):
        cases = ((NAMES, (), True), (("gate",), (0,), False))
        for frozen, frozen_inputs, unused_middle in cases:
            with self.subTest(frozen=frozen, frozen_inputs=frozen_inputs, unused_middle=unused_middle):
                observed, members = self.run_case(torch.device("cpu"), frozen=frozen,
                                                 frozen_inputs=frozen_inputs, unused_middle=unused_middle)
                # Frozen weights may avoid their matrix gradients, but must not
                # suppress input gradients or reintroduce a nested graph.
                self.assertEqual(observed[SILU_ENGINE], 0, observed)
                self.assertEqual(observed[MM_ENGINE], 0, observed)
                self.assertEqual(observed["aten::silu_backward"], members, observed)

    def test_rank_three_values_preserve_framework_fallback(self):
        self.run_case(torch.device("cpu"), layout="rank3")

    def test_column_major_values_preserve_framework_fallback(self):
        self.run_case(torch.device("cpu"), layout="column_major")


@unittest.skipUnless(os.environ.get(CUDA_OPT_IN) == "1",
                     "requires explicit CUDA grant and owned 3 GiB host / 120 s envelope")
class GroupedBackwardCUDA(GroupedBackwardChecks, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not torch.cuda.is_available():
            raise RuntimeError("explicit CUDA unit replay requested without available CUDA")
        cls.device = torch.device("cuda:0")
        cls.allowance = 1 << 30
        free, total = torch.cuda.mem_get_info(cls.device)
        if free < cls.allowance or total < cls.allowance:
            raise RuntimeError("CUDA device cannot provide the fixed 1 GiB allowance")
        torch.cuda.set_per_process_memory_fraction(cls.allowance / total, cls.device)
        torch.cuda.reset_peak_memory_stats(cls.device)

    def tearDown(self):
        gc.collect()
        torch.cuda.synchronize(self.device)
        torch.cuda.empty_cache()
        self.assertLessEqual(torch.cuda.max_memory_allocated(self.device), self.allowance)
        self.assertLessEqual(torch.cuda.max_memory_reserved(self.device), self.allowance)

    def test_native_partial_chunks_match_cuda_reference_without_inner_autograd(self):
        observed, members = self.run_case(self.device)
        self.assert_native_dispatch(observed, members)

    def test_cuda_frozen_weights_and_unused_middle_output_preserve_input_gradients(self):
        observed, members = self.run_case(self.device, frozen=NAMES, unused_middle=True)
        self.assertEqual(observed[SILU_ENGINE], 0, observed)
        self.assertEqual(observed[MM_ENGINE], 0, observed)
        self.assertEqual(observed["aten::silu_backward"], members, observed)


if __name__ == "__main__":
    unittest.main()
