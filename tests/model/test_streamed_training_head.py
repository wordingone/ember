# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Actual K4 decoder boundary and document-loss owner tests on CPU."""
import importlib
import inspect
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import torch
import torch.nn.functional as F

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from ember.model.ember_v0_decoder import CIADecoder


def dense_operator(e,c,y):
    return F.cross_entropy(e@c.T,y,reduction='sum')


class StreamedTrainingHead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)

    def module(self):
        self.assertTrue((ROOT/'src/ember/model/ember_v0_streamed_loss.py').is_file(),
                        'K4 document streamed loss is not implemented')
        return importlib.import_module('ember.model.ember_v0_streamed_loss')

    def test_real_final_segment_hidden_retains_norm_derivative(self):
        self.assertIn('head_output',inspect.signature(CIADecoder._resident_segment).parameters,
                      'K4 final segment has no explicit hidden output')
        torch.manual_seed(194520)
        norm=torch.randn(5,dtype=torch.float64,requires_grad=True)
        owner=torch.randn(11,5,dtype=torch.float64,requires_grad=True)
        stub=SimpleNamespace(_cuda_execution=None,_DOCUMENT_REDUCTION_ORDER='descending',
            _weight=lambda name:owner,_norm=lambda x,name:x*norm)
        x=torch.randn(8,5,dtype=torch.float64,requires_grad=True)
        residual=torch.randn_like(x,requires_grad=True)
        gates=torch.ones(8,dtype=x.dtype)
        carry=(x,residual,None,gates,None,None,None,torch.tensor([2]),torch.tensor([0]),torch.tensor([1]))
        hidden,*_=CIADecoder._resident_segment(stub,12,*carry,lengths=(2,2,2,2),
            geometry=None,repeats=None,head_output='hidden')
        logits,*_=CIADecoder._resident_segment(stub,12,*carry,lengths=(2,2,2,2),
            geometry=None,repeats=None)
        torch.testing.assert_close(logits,hidden@owner.T)
        hidden.sum().backward()
        self.assertIsNotNone(norm.grad)
        self.assertIsNone(owner.grad)

    def test_tied_owner_and_two_microbatches_have_one_denominator(self):
        module=self.module()
        torch.manual_seed(194521)
        w=torch.randn(11,5,dtype=torch.float64,requires_grad=True)
        wr=w.detach().clone().requires_grad_()
        tokens=torch.arange(12)%11;y=(tokens+2)%11
        loss=0
        for start in (0,6):
            e=w[tokens[start:start+6]]*.2
            part=module.document_streamed_loss(e,w,y[start:start+6],(3,3),12,
                                                operator=dense_operator)
            loss+=part.detach();part.backward()
        reference=F.cross_entropy((wr[tokens]*.2)@wr.T,y)
        reference.backward()
        torch.testing.assert_close(loss,reference,atol=1e-14,rtol=1e-14)
        torch.testing.assert_close(w.grad,wr.grad,atol=1e-14,rtol=1e-14)

    def test_gradient_document_reduction_is_descending(self):
        module=self.module();seen=[]
        class Sum(torch.autograd.Function):
            @staticmethod
            def forward(ctx,e,c,y):
                ctx.index=int(y[0]);ctx.save_for_backward(e,c)
                return e.float().sum()+c.float().sum()
            @staticmethod
            def backward(ctx,g):
                seen.append(ctx.index);e,c=ctx.saved_tensors
                return torch.ones_like(e)*g,torch.ones_like(c)*g,None
        e=torch.ones(4,3,requires_grad=True);c=torch.ones(4,3,requires_grad=True)
        module.document_streamed_loss(e,c,torch.arange(4),(1,1,1,1),4,operator=Sum.apply).backward()
        self.assertEqual(seen,[3,2,1,0])
        torch.testing.assert_close(e.grad,torch.full_like(e,.25))
        torch.testing.assert_close(c.grad,torch.ones_like(c))

    def test_invalid_target_or_denominator_cannot_submit_operator(self):
        module=self.module();e=torch.ones(4,3);c=torch.ones(5,3)
        def forbidden(*args):self.fail('Invalid exposure reached operator')
        for y,lengths,denom in [(torch.tensor([0,1,-100,2]),(2,2),4),
                                (torch.arange(4),(2,2),3),
                                (torch.arange(4),(2,1),4)]:
            with self.subTest(y=y,lengths=lengths,denom=denom):
                with self.assertRaises(ValueError):
                    module.document_streamed_loss(e,c,y,lengths,denom,operator=forbidden)

    def test_final_capture_surface_excludes_external_tied_owner(self):
        self.assertIn('head_output',inspect.signature(CIADecoder.bind_segmented_capture).parameters,
                      'K4 capture has no output grammar')
        weights={'final_norm__weight':torch.nn.Parameter(torch.ones(5)),
                 'embedding__weight':torch.nn.Parameter(torch.ones(11,5))}
        ex=SimpleNamespace(active=False,poisoned=False,retired=False,device=torch.device('cpu'),
             _geometry_lengths=(1024,)*4,_geometry_repeats=torch.ones(16,dtype=torch.long),
             input_valid=torch.tensor(True),_plan_candidates=None,_plan_winners=None)
        stub=SimpleNamespace(_resident_experts=(0,),_cuda_execution=ex,weights=weights,
                             _resident_segment=lambda *args,**kwargs:())
        step=CIADecoder.bind_segmented_capture(stub,local_routing_mode='per-chunk',head_output='hidden')
        final=step.segments[-1]
        self.assertTrue(any(p is weights['final_norm__weight'] for p in final.params))
        self.assertFalse(any(p is weights['embedding__weight'] for p in final.params))


if __name__=='__main__':unittest.main()
