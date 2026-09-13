# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Preserve merged head forward and reference-shaped backward GEMMs."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import torch
import torch.nn.functional as F


class HeadProjectionTests(unittest.TestCase):
    def test_forward_stays_merged_and_backward_uses_document_shapes(self):
        from ember.model.ember_v0_document_reduction import document_reduced_head
        torch.manual_seed(19)
        x=torch.randn(5,3,dtype=torch.float64,requires_grad=True)
        weight=torch.randn(7,3,dtype=torch.float64,requires_grad=True)
        upstream=torch.randn(5,7,dtype=torch.float64)
        calls=[]
        matmul=torch.Tensor.__matmul__
        def observe(a,b):
            calls.append((tuple(a.shape),tuple(b.shape)))
            return matmul(a,b)
        with patch.object(F,'linear',wraps=F.linear) as forward:
            result=document_reduced_head(x,weight,(2,3),'descending')
            self.assertEqual(forward.call_count,1)
            self.assertEqual(tuple(forward.call_args.args[0].shape),(5,3))
        with patch.object(torch.Tensor,'__matmul__',observe):
            result.backward(upstream)
        self.assertEqual(calls[:2],[((2,7),(7,3)),((3,7),(7,3))])
        self.assertEqual(calls[2:],[((7,3),(3,3)),((7,2),(2,3))])
        reference_x=x.detach().clone().requires_grad_(True)
        reference_weight=weight.detach().clone().requires_grad_(True)
        reference=torch.cat([F.linear(piece,reference_weight) for piece in reference_x.split((2,3))])
        reference.backward(upstream)
        torch.testing.assert_close(result,reference,rtol=0,atol=0)
        torch.testing.assert_close(x.grad,reference_x.grad,rtol=0,atol=0)
        torch.testing.assert_close(weight.grad,reference_weight.grad,rtol=0,atol=0)

    def test_terminal_segment_uses_head_operation(self):
        from ember.model import ember_v0_decoder as decoder
        values=torch.ones(5,3)
        weight=torch.ones(7,3)
        subject=SimpleNamespace(_cuda_execution=object(),_norm=lambda value,name:value,
            _weight=lambda name:weight,_DOCUMENT_REDUCTION_ORDER='descending')
        carry=(values,torch.zeros_like(values),None,torch.ones(5),None,None,None,None,None,None)
        with patch.object(decoder,'document_reduced_head',return_value=values) as head:
            output=decoder.CIADecoder._resident_segment(subject,12,*carry,
                lengths=(2,3),geometry=None,repeats=None)
        self.assertIs(output[0],values)
        self.assertEqual(head.call_count,1)
        self.assertEqual(head.call_args.args[2:],((2,3),'descending'))

    def test_frozen_weight_still_gets_document_input_gradient(self):
        from ember.model.ember_v0_document_reduction import document_reduced_head
        x=torch.ones(5,3,requires_grad=True)
        weight=torch.ones(7,3)
        document_reduced_head(x,weight,(2,3),'descending').sum().backward()
        self.assertTrue(torch.equal(x.grad,torch.full_like(x,7.)))
        self.assertIsNone(weight.grad)


if __name__=='__main__':
    unittest.main()
