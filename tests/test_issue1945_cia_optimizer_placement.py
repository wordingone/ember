# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import unittest
import torch
from ember.model.ember_v0_residency import _stage_optimizer_placement


class OptimizerPlacementTests(unittest.TestCase):
    def state(self):
        a=torch.nn.Parameter(torch.ones(3,4,dtype=torch.bfloat16))
        b=torch.nn.Parameter(torch.ones(4,dtype=torch.bfloat16))
        opt=torch.optim.AdamW([a,b],foreach=False)
        (a.float().square().sum()+b.float().square().sum()).backward()
        opt.step();opt.zero_grad(set_to_none=True)
        return {'a':a,'b':b},opt

    def test_retained_owner_moments_and_steps_remain_unchanged(self):
        owners,opt=self.state()
        before={p:{k:v.clone() for k,v in row.items()} for p,row in opt.state.items()}
        staged=_stage_optimizer_placement(opt,owners,{id(p):torch.device('cpu') for p in owners.values()})
        self.assertEqual({id(p) for p in staged},{id(p) for p in owners.values()})
        for p,row in staged.items():
            for key,value in row.items():
                torch.testing.assert_close(value,before[p][key],rtol=0,atol=0)
                self.assertIs(value,opt.state[p][key])
                self.assertEqual(value.dtype,torch.float32 if key=='step' else torch.bfloat16)

    def test_foreign_membership_and_wrong_moment_dtype_refused(self):
        owners,opt=self.state()
        destination={id(p):torch.device('cpu') for p in owners.values()}
        with self.assertRaises(ValueError):
            _stage_optimizer_placement(opt,{'a':owners['a']},destination)
        original=opt.state[owners['a']]['exp_avg']
        opt.state[owners['a']]['exp_avg']=original.float()
        with self.assertRaises(ValueError):
            _stage_optimizer_placement(opt,owners,destination)

if __name__=='__main__':
    unittest.main()
