# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Finite attention-unit tests; these do not establish full-model qualification."""
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import torch
import torch.nn.functional as F
from torch.nn.attention import SDPBackend, sdpa_kernel
from ember.model.ember_v0_decoder import CIADecoder, _document_sdpa


class DocumentAttentionTests(unittest.TestCase):
    def exercise(self, lengths):
        generator = torch.Generator().manual_seed(1945)
        total = sum(lengths)
        tensors = tuple(torch.randn(total, 4, 8, generator=generator).requires_grad_()
                        for _ in range(3))
        reference_inputs = tuple(t.detach().clone().requires_grad_() for t in tensors)
        pieces = []
        offset = 0
        for length in lengths:
            q, k, v = (t[offset:offset + length].transpose(0, 1) for t in reference_inputs)
            pieces.append(F.scaled_dot_product_attention(q, k, v, is_causal=True).transpose(0, 1))
            offset += length
        expected = torch.cat(pieces)
        with patch.object(F, 'scaled_dot_product_attention', wraps=F.scaled_dot_product_attention) as call:
            actual = _document_sdpa(*tensors, lengths)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0].ndim, 4)
        torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-6)
        upstream = torch.randn(actual.shape, generator=generator)
        actual.backward(upstream)
        expected.backward(upstream)
        for actual_input, expected_input in zip(tensors, reference_inputs):
            torch.testing.assert_close(actual_input.grad, expected_input.grad, rtol=3e-5, atol=3e-6)

    def test_equal_documents_share_one_causal_call(self):
        self.exercise((8, 8, 8, 8))

    def test_mixed_lengths_and_single_position_preserve_causality_and_gradients(self):
        self.exercise((1, 7, 3, 8))

    def test_document_boundary_prevents_cross_document_values(self):
        q = torch.ones(6, 2, 4)
        k = torch.ones_like(q)
        v = torch.cat((torch.ones(2, 2, 4), torch.full((4, 2, 4), 100.0)))
        result = _document_sdpa(q, k, v, (2, 4))
        torch.testing.assert_close(result, v)

    def test_invalid_lengths_refuse_before_kernel(self):
        value = torch.ones(4, 2, 4)
        for lengths in ((), (0, 4), (True, 3), (3,), (2, 3)):
            with self.subTest(lengths=lengths), patch.object(F, 'scaled_dot_product_attention') as call:
                with self.assertRaises(ValueError):
                    _document_sdpa(value, value, value, lengths)
                call.assert_not_called()


@contextmanager
def exact_math():
    previous = torch.backends.cuda.fp16_bf16_reduction_math_sdp_allowed()
    try:
        torch.backends.cuda.allow_fp16_bf16_reduction_math_sdp(False)
        with sdpa_kernel(SDPBackend.MATH):
            yield
    finally:
        torch.backends.cuda.allow_fp16_bf16_reduction_math_sdp(previous)


class AttentionRecomputeTests(unittest.TestCase):
    def inputs(self):
        generator = torch.Generator().manual_seed(1945)
        return tuple(torch.randn(4, 2, 8, generator=generator).requires_grad_()
                     for _ in range(3))

    def test_selection_is_instance_bound_exact_bool_and_default_off(self):
        plain, recomputed = CIADecoder(), CIADecoder(attention_recompute=True)
        self.assertIs(plain.attention_recompute, False)
        self.assertIs(recomputed.attention_recompute, True)
        with self.assertRaises(AttributeError):
            recomputed.attention_recompute = False
        for selection in (None, 0, 1, 'non_reentrant_checkpoint'):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                CIADecoder(attention_recompute=selection)

    def test_actual_recomputation_preserves_outputs_gradients_and_frozen_lengths(self):
        model = CIADecoder(attention_recompute=True)
        for partition in ((1, 3), (2, 2), (1, 1, 1, 1)):
            with self.subTest(partition=partition), exact_math():
                inputs = self.inputs()
                reference = tuple(t.detach().clone().requires_grad_() for t in inputs)
                lengths = list(partition)
                expected = _document_sdpa(*reference, partition)
                expected_grads = torch.autograd.grad(expected.square().sum(), reference)
                with patch.object(F, 'scaled_dot_product_attention', wraps=F.scaled_dot_product_attention) as call:
                    rng_before = torch.get_rng_state().clone()
                    actual = model._document_attention(*inputs, lengths)
                    self.assertEqual(call.call_count, 1)
                    lengths[:] = [4]  # Caller mutation cannot change backward document membership.
                    actual_grads = torch.autograd.grad(actual.square().sum(), inputs)
                    self.assertEqual(call.call_count, 2)
                    self.assertTrue(torch.equal(torch.get_rng_state(), rng_before))
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                for actual_grad, expected_grad in zip(actual_grads, expected_grads):
                    torch.testing.assert_close(actual_grad, expected_grad, rtol=0, atol=0)

    def test_capture_owner_declaration_binds_exact_recompute_selection(self):
        model = CIADecoder(attention_recompute=True)
        declaration = model.owner_declaration()
        model._attention_recompute = False
        self.assertNotEqual(model.owner_declaration(), declaration)
        model._attention_recompute = 1
        self.assertNotEqual(model.owner_declaration(), declaration)
        with self.assertRaisesRegex(ValueError, 'attention_recompute'):
            model.parameter_inventory()

    def test_default_path_needs_no_backend_override_or_recomputation(self):
        inputs = self.inputs()
        with patch.object(F, 'scaled_dot_product_attention', wraps=F.scaled_dot_product_attention) as call:
            result = CIADecoder()._document_attention(*inputs, (1, 3))
            torch.autograd.grad(result.sum(), inputs)
        self.assertEqual(call.call_count, 1)

    def test_forward_refuses_nonexclusive_math_before_kernel(self):
        with exact_math(), sdpa_kernel([SDPBackend.MATH, SDPBackend.FLASH_ATTENTION]):
            with patch.object(F, 'scaled_dot_product_attention') as call:
                with self.assertRaisesRegex(ValueError, 'exclusive MATH'):
                    CIADecoder(attention_recompute=True)._document_attention(*self.inputs(), (1, 3))
                call.assert_not_called()

    def test_backward_rechecks_backend_and_precision_before_recomputation(self):
        for changed in ('backend', 'precision'):
            with self.subTest(changed=changed), exact_math():
                inputs = self.inputs()
                result = CIADecoder(attention_recompute=True)._document_attention(*inputs, (1, 3))
                try:
                    if changed == 'backend':
                        torch.backends.cuda.enable_flash_sdp(True)
                    else:
                        torch.backends.cuda.allow_fp16_bf16_reduction_math_sdp(True)
                    with patch.object(F, 'scaled_dot_product_attention') as call:
                        with self.assertRaisesRegex(ValueError, 'exclusive MATH'):
                            torch.autograd.grad(result.sum(), inputs)
                        call.assert_not_called()
                finally:
                    torch.backends.cuda.enable_flash_sdp(False)
                    torch.backends.cuda.allow_fp16_bf16_reduction_math_sdp(False)

    def test_nonresident_routes_refuse_enabled_selection_before_projection(self):
        model = CIADecoder(attention_recompute=True)
        with patch.object(model, '_linear') as project:
            for operation, args in ((model._attention, (None, None, 'unused')),
                                    (model._batched_attention, (None, None, (1,), 'unused'))):
                with self.subTest(operation=operation.__name__), self.assertRaisesRegex(ValueError, 'resident'):
                    operation(*args)
            project.assert_not_called()

    def test_both_resident_routes_recompute_through_the_instance(self):
        # Small CPU projection fixtures exercise the actual call sites, rotation,
        # attention and backward without materializing the full model or CUDA.
        def project(values, name, *unused):
            return values[:, :256] if name.endswith(('.k.weight', '.v.weight')) else values

        for batched in (False, True):
            with self.subTest(batched=batched), exact_math():
                model = CIADecoder(attention_recompute=True)
                model._resident_experts = (0, 1)
                values = torch.randn(4, 1024, generator=torch.Generator().manual_seed(1945)).requires_grad_()
                positions = torch.zeros(4, 3, dtype=torch.long)
                with patch.object(model, '_linear', side_effect=project), \
                        patch.object(model, '_document_linear', side_effect=project), \
                        patch.object(model, '_norm', side_effect=lambda value, name: value), \
                        patch.object(model, '_document_attention', wraps=model._document_attention) as entry, \
                        patch.object(F, 'scaled_dot_product_attention', wraps=F.scaled_dot_product_attention) as call:
                    result = (model._batched_attention(values, positions, (1, 3), 'attention')
                              if batched else model._attention(values, positions, 'attention'))
                    self.assertEqual(call.call_count, 1)
                    gradient, = torch.autograd.grad(result.square().sum(), values)
                    self.assertTrue(torch.isfinite(gradient).all())
                    entry.assert_called_once()
                    self.assertEqual(entry.call_args.args[-1], (1, 3) if batched else (4,))
                    self.assertEqual(call.call_count, 2)
