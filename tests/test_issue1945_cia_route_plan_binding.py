# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import unittest
import torch
from ember.model.ember_v0_residency import ResidentExecution, DeviceRouteGeometry


class PlanBindingTests(unittest.TestCase):
    def test_bool_document_key_is_not_integer_identity(self):
        expected=((0,1,0),)
        with self.assertRaises(ValueError):
            ResidentExecution._plan_value({(False,1,0):((1,3),3)},expected)

    def test_plan_preserves_gradient_and_flags_candidate_pair_mismatch(self):
        execution=object.__new__(ResidentExecution)
        execution.active=execution.retired=execution.poisoned=False
        execution._geometry_lengths=(257,)
        execution.device=torch.device('cpu')
        execution.input_valid=torch.ones(3,dtype=torch.bool)
        execution.check=lambda:None
        plan={(0,layer,start):((1,3),3) for layer in range(1,24,2) for start in (0,256)}
        execution.bind_route_plan(plan)
        execution.check_route_plan(plan)
        geometry=DeviceRouteGeometry(((0,0,0,256,0),(0,0,256,1,0)),(257,))
        logits=torch.tensor([[.1,.7],[.9,-.3]],requires_grad=True)
        winners,gates=execution.planned_routes(0,geometry,torch.tensor([[1,3]]),
                                             torch.tensor([1,1]),logits,torch.ones(2))
        self.assertEqual(winners.tolist(),[3,3])
        actual=torch.autograd.grad((gates*torch.tensor([1.,2.])).sum(),logits)[0]
        reference=logits.detach().clone().requires_grad_()
        expected=torch.autograd.grad((reference.softmax(1)[:,1]*torch.tensor([1.,2.])).sum(),reference)[0]
        torch.testing.assert_close(actual,expected,rtol=0,atol=0)
        execution.planned_routes(0,geometry,torch.tensor([[1,2]]),torch.tensor([1,1]),logits,torch.ones(2))
        self.assertFalse(bool(execution.input_valid[2]))

if __name__=='__main__':
    unittest.main()
