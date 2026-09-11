# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Inductor-fused RMSNorm and three-axis rotation on the CIA CUDA candidate path.

CPU cases prove the eager reference is unchanged and that no compiled twin is built off CUDA.
CUDA cases require EMBER_CIA_FUSED_ELEMENTWISE_CUDA=1 (they compile with inductor); they prove the
fused twins match the eager reference forward and backward inside the bar the grouped-backward unit
set (rel-L2 <= 0.05; observed ~1e-3) and launch fewer device kernels per call. These fixtures do not
establish full-model numerical conformance or throughput qualification.
"""
import os
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model import ember_v0_decoder as subject  # noqa: E402

CUDA_CASES = os.environ.get("EMBER_CIA_FUSED_ELEMENTWISE_CUDA") == "1" and torch.cuda.is_available()


def reference_norm(values, weight):
    scale = (values.float().square().mean(-1, keepdim=True) + 1e-6).rsqrt()
    return (values.float() * scale).to(values.dtype) * weight


def rel_l2(actual, expected):
    expected = expected.float()
    return float(((actual.float() - expected).norm() / expected.norm().clamp_min(1e-12)).item())


def kernel_count(function, *args):
    from torch.profiler import ProfilerActivity, profile
    function(*args)
    torch.cuda.synchronize()
    with profile(activities=[ProfilerActivity.CUDA]) as trace:
        function(*args)
        torch.cuda.synchronize()
    return sum(1 for event in trace.events() if event.device_type.name == "CUDA")


class CpuReferenceTests(unittest.TestCase):
    def setUp(self):
        subject._FUSED.clear()
        generator = torch.Generator().manual_seed(11)
        self.values = torch.randn(37, 1024, generator=generator).to(torch.bfloat16)
        self.weight = torch.randn(1024, generator=generator).to(torch.bfloat16)
        self.heads = torch.randn(37, 16, 64, generator=generator).to(torch.bfloat16)
        self.positions = torch.stack([torch.arange(37), torch.arange(37) % 5, torch.arange(37) % 7], dim=1)

    def test_rms_norm_is_the_previous_inline_formula_bit_for_bit(self):
        self.assertTrue(torch.equal(subject._rms_norm(self.values, self.weight), reference_norm(self.values, self.weight)))

    def test_meta_decoder_norm_uses_the_eager_reference_and_builds_no_twin(self):
        model = subject.CIADecoder()
        out = model._norm(torch.empty(5, 1024, device="meta", dtype=torch.bfloat16), "final_norm.weight")
        self.assertEqual((tuple(out.shape), out.dtype, out.device.type), ((5, 1024), torch.bfloat16, "meta"))
        self.assertEqual(subject._FUSED, {})

    def test_cpu_rotation_never_builds_a_twin_and_still_refuses_bad_shapes(self):
        rotated = subject.rotate_three_axis(self.heads, self.positions)
        self.assertEqual((tuple(rotated.shape), rotated.dtype), ((37, 16, 64), torch.bfloat16))
        self.assertEqual(subject._FUSED, {})
        with self.assertRaises(ValueError):
            subject.rotate_three_axis(self.heads[..., :32], self.positions)
        with self.assertRaises(ValueError):
            subject.rotate_three_axis(self.heads, self.positions.float())


@unittest.skipUnless(CUDA_CASES, "EMBER_CIA_FUSED_ELEMENTWISE_CUDA=1 with CUDA required")
class CudaFusedTests(unittest.TestCase):
    def setUp(self):
        subject._FUSED.clear()
        self.device = torch.device("cuda:0")
        generator = torch.Generator().manual_seed(23)
        self.values = torch.randn(1024, 1024, generator=generator).to(torch.bfloat16).to(self.device)
        self.weight = torch.randn(1024, generator=generator).to(torch.bfloat16).to(self.device)
        self.heads = torch.randn(1024, 16, 64, generator=generator).to(torch.bfloat16).to(self.device)
        self.positions = torch.stack([torch.arange(1024), torch.arange(1024) % 32, torch.arange(1024) % 32], dim=1).to(self.device)

    def _forward_backward(self, function, *inputs):
        leaves = [tensor.detach().clone().requires_grad_(tensor.is_floating_point()) for tensor in inputs]
        out = function(*leaves)
        out.float().square().mean().backward()
        return out.detach(), [leaf.grad for leaf in leaves if leaf.requires_grad]

    def test_fused_norm_matches_reference_forward_and_backward(self):
        eager_out, eager_grads = self._forward_backward(reference_norm, self.values, self.weight)
        fused_out, fused_grads = self._forward_backward(subject.fused_elementwise("norm"), self.values, self.weight)
        self.assertLessEqual(rel_l2(fused_out, eager_out), 0.05)
        for fused, eager in zip(fused_grads, eager_grads):
            self.assertLessEqual(rel_l2(fused, eager), 0.05)

    def test_fused_rotation_matches_reference_forward_and_backward(self):
        def eager(values, positions):  # the reference body, bypassing the CUDA dispatch line
            with torch.compiler.set_stance("force_eager"):
                pieces, offset = [], 0
                for axis, width in enumerate((32, 16, 16)):
                    part = values[..., offset:offset + width]
                    inverse = 10000.0 ** (-torch.arange(0, width, 2, device=values.device, dtype=torch.float32) / width)
                    angle = positions[:, axis].float()[:, None, None] * inverse[None, None, :]
                    even, odd = part[..., 0::2].float(), part[..., 1::2].float()
                    rotated = torch.stack((even * angle.cos() - odd * angle.sin(), even * angle.sin() + odd * angle.cos()), dim=-1)
                    pieces.append(rotated.flatten(-2).to(values.dtype))
                    offset += width
                return torch.cat(pieces, dim=-1)
        eager_out, eager_grads = self._forward_backward(eager, self.heads, self.positions)
        fused_out, fused_grads = self._forward_backward(subject.rotate_three_axis, self.heads, self.positions)
        self.assertIn("rotate", subject._FUSED)
        self.assertLessEqual(rel_l2(fused_out, eager_out), 0.05)
        self.assertLessEqual(rel_l2(fused_grads[0], eager_grads[0]), 0.05)

    def test_fused_norm_launches_fewer_kernels_than_eager(self):
        eager = kernel_count(reference_norm, self.values, self.weight)
        fused = kernel_count(subject.fused_elementwise("norm"), self.values, self.weight)
        self.assertGreaterEqual(eager, 6)
        self.assertGreater(fused, 0, "profiler recorded no compiled kernels; the count claim is unproven")
        self.assertLessEqual(fused, eager // 2)


if __name__ == "__main__":
    unittest.main()
