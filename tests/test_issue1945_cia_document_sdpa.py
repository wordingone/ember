# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Finite attention-unit tests; these do not establish full-model qualification."""
import unittest
from unittest.mock import patch
import torch
import torch.nn.functional as F
from ember.model.ember_v0_decoder import _document_sdpa


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
