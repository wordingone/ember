# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import unittest
import torch
from ember.model.ember_v0_routing import StepRouting,ChunkSpec
from ember.model.ember_v0_residency import resident_global_routes,resident_local_routes


class DeviceRoutingTests(unittest.TestCase):
    def test_reference_scores_winners_and_gradient(self):
        torch.manual_seed(1945)
        # Include a second epoch and a ragged segment; gradients use float32 here.
        lengths=(1031,257)
        embedded=torch.randn(sum(lengths),1024)*.02
        hidden=torch.randn_like(embedded).requires_grad_()
        query=(torch.randn(1024,1024)*.02).requires_grad_()
        local=(torch.randn(1024,1024)*.02).requires_grad_()
        keys=(torch.randn(12,25,1024)*.02).requires_grad_()
        geometry,priors,ranked,candidates,valid=resident_global_routes(embedded,lengths,query,keys)
        self.assertTrue(bool(valid))
        winners,logits,gates,valid=resident_local_routes(hidden,local,keys,3,geometry,priors,candidates)
        self.assertTrue(bool(valid))
        actual_grads=torch.autograd.grad((gates*torch.arange(1,len(gates)+1)).sum(),(hidden,local,keys),retain_graph=True)
        with self.subTest('actual reference consumer'):
            routing=StepRouting(query,local,keys,'unit-generation')
            specs=[]
            offset=epoch=0
            for doc,length in enumerate(lengths):
                selected={}
                for start in range(0,length,1024):
                    selection=routing.select_global(embedded[offset:offset+length],position=start,document_start=0,request=str(doc))
                    torch.testing.assert_close(priors[epoch],selection.log_prior,rtol=0,atol=0)
                    self.assertEqual(tuple(ranked[epoch].tolist()),selection.experts)
                    selected[start]=selection
                    epoch+=1
                specs.extend(ChunkSpec(document_offset=offset,start=start,selection=selected[start//1024*1024],request=str(doc))
                             for start in range(0,length,256))
                offset+=length
            reference=routing.select_local_batch(hidden,specs,sparse_depth=3)
            self.assertEqual(tuple(winners.tolist()),reference.experts)
            # #1945 batched local router: the projection is one row-batched GEMM instead of one vector GEMM per
            # chunk, a DECLARED numerical treatment. Winner identity stays exact; logits, gates and gradients agree
            # to fp32 accumulation-order tolerance (observed 1.4e-6 absolute on this fixture), never bit-for-bit.
            torch.testing.assert_close(logits,reference.logits,rtol=1e-5,atol=1e-5)
            torch.testing.assert_close(gates,reference.gates,rtol=1e-5,atol=1e-5)
            expected_grads=torch.autograd.grad((reference.gates*torch.arange(1,len(gates)+1)).sum(),(hidden,local,keys))
            for actual,expected in zip(actual_grads,expected_grads):
                torch.testing.assert_close(actual,expected,rtol=1e-4,atol=1e-5)
            routing.close()

    def test_ties_and_nonfinite_predicate(self):
        embedded=torch.zeros(257,1024)
        query=torch.zeros(1024,1024)
        keys=torch.zeros(12,25,1024)
        geometry,priors,ranked,candidates,valid=resident_global_routes(embedded,(257,),query,keys)
        self.assertEqual(ranked.tolist(),[[0,1]])
        winners,_,_,valid=resident_local_routes(embedded,query,keys,0,geometry,priors,candidates)
        self.assertTrue(bool(valid))
        self.assertEqual(winners.tolist(),[0,0])
        hidden=embedded.clone()
        hidden[255,0]=float('nan')
        *_,valid=resident_local_routes(hidden,query,keys,0,geometry,priors,candidates)
        self.assertFalse(bool(valid))


if __name__=='__main__':
    unittest.main()
