# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Check actual decoder segment boundaries against its frozen eager implementation."""
import importlib.util
from pathlib import Path
import sys
import unittest
import torch

from types import SimpleNamespace
from ember.model import ember_v0_decoder as candidate
from ember.model import ember_v0_residency as residency
from ember.model import ember_v0_capture as capture

path = Path(__file__).resolve().parent/'fixtures/issue1945_cia_eager_reference.py'
spec = importlib.util.spec_from_file_location('cia_segments_eager_reference',path)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
reference = SimpleNamespace(CIADecoder=SimpleNamespace(_resident_documents_forward=fixture.resident_eager_reference))

class Execution:
    step_id = 1
    active = poisoned = retired = False
    segmented = None
    def __init__(self):
        self.calls = []
        self.device = torch.device('cpu')
        self._geometry_lengths = (1031,257)
        self._geometry_repeats = torch.tensor([256,256,256,256,7,256,1])
        self._plan_candidates = self._plan_winners = None
        self.input_valid = torch.ones(3,dtype=torch.bool)
    def check(self): pass
    def check_route_plan(self, plan): assert plan is None
    def require_valid(self, value, reason): assert bool(value), reason
    def planned_routes(self, depth, geometry, candidates, winners, logits, gates):
        return winners, gates
    def geometry_repeats(self, lengths, sizes):
        return torch.tensor(sizes, dtype=torch.long)
    def grouped_block(self, values, experts, layer):
        self.calls.append(layer)
        return values * (experts[:, None].to(values.dtype) + 1) * .001

class SmallDenseModel(torch.nn.Module):
    """Real routing and decoder sequencing; small elementwise dense/expert fixtures."""
    def __init__(self, decoder):
        super().__init__()
        torch.manual_seed(1945)
        self.keys = torch.nn.Parameter(torch.randn(12,25,1024) * .01)
        self.global_query = torch.nn.Parameter(torch.randn(1024,1024) * .01)
        self.local_query = torch.nn.Parameter(torch.randn(1024,1024) * .01)
        self.scale = torch.nn.Parameter(torch.linspace(.01,.02,24))
        self.output = torch.nn.Parameter(torch.randn(7,1024) * .01)
        self._cuda_execution = Execution()
        self.shared_calls = []
        self._resident_experts = (0,1,8,18)
        self._resident_documents_forward = decoder._resident_documents_forward.__get__(self)
        if hasattr(decoder, '_resident_segment'):
            self._resident_segment = decoder._resident_segment.__get__(self)
        if hasattr(decoder,'bind_segmented_capture'):
            self.bind_segmented_capture = decoder.bind_segmented_capture.__get__(self)
    @property
    def weights(self):
        result = {'router.global_query.weight':self.global_query,
                  'router.local_query.weight':self.local_query,'embedding.weight':self.output}
        result.update({f'router.layers.{i}.keys':self.keys for i in range(1,24,2)})
        result.update({f'layers.{i}.attention.query.weight':self.scale for i in range(24)})
        return {name.replace('.','__'):value for name,value in result.items()}
    def _weight(self, name):
        if name == 'router.global_query.weight': return self.global_query
        if name == 'router.local_query.weight': return self.local_query
        return self.keys[int(name.split('.')[2]) // 2]
    def _norm(self, values, name): return values * .99
    def _batched_attention(self, values, positions, lengths, prefix):
        return values * self.scale[int(prefix.split('.')[1])]
    def _swiglu(self, values, prefix):
        return torch.nn.functional.silu(values) * self.scale[int(prefix.split('.')[1])]
    def _document_swiglu(self, values, prefix, lengths):
        # This stub records sequencing; the decoder caller suite checks gradient arithmetic.
        assert sum(lengths) == len(values)
        self.shared_calls.append(prefix)
        return self._swiglu(values, prefix)
    def _linear(self, values, name): return torch.nn.functional.linear(values, self.output)

class SegmentTests(unittest.TestCase):
    def test_plan_rebinding_requires_fresh_capture_binding(self):
        model = SmallDenseModel(candidate.CIADecoder)
        execution = model._cuda_execution
        step = model.bind_segmented_capture()
        residency.ResidentExecution.bind_route_plan(execution,None)
        self.assertIs(execution.segmented,step)
        self.assertTrue(step._cia_invalidated)

    def test_support_change_invalidates_captured_owner_surface(self):
        model = SmallDenseModel(candidate.CIADecoder)
        execution = model._cuda_execution
        execution.cache = execution
        model.parameter_inventory = lambda: {name.replace('__','.'):p for name,p in model.weights.items()}
        step = model.bind_segmented_capture()
        candidate.CIADecoder.apply_update_support(model,'core-only')
        self.assertTrue(step._cia_invalidated)

    def test_actual_forward_records_and_runs_bound_capture_harness(self):
        self.assertTrue(hasattr(candidate.CIADecoder,'bind_segmented_capture'))
        model = SmallDenseModel(candidate.CIADecoder)
        reports = []
        collector = lambda kind,row: reports.append((kind,row))
        step = model.bind_segmented_capture(collector=collector, loss_fn=lambda logits,targets:logits.square().sum())
        torch.manual_seed(88)
        embedded = (torch.randn(1288,1024)*.03).requires_grad_()
        positions = torch.zeros(1288,3,dtype=torch.long)
        documents = [(embedded[:1031],positions[:1031],0),(embedded[1031:],positions[1031:],1)]
        with step.record():
            expected,_ = model._resident_documents_forward(documents,collector=collector)
            step.loss(torch.cat(expected),None).backward()
        expected_grads = [p.grad.clone() for p in model.parameters()]
        expected_input = embedded.grad.clone()
        self.assertEqual(len(step._recorded),13)
        step.capture()
        embedded.grad.zero_()
        actual,_ = model._resident_documents_forward(documents,collector=collector)
        step.loss(torch.cat(actual),None).backward()
        torch.testing.assert_close(torch.cat(actual),torch.cat(expected),rtol=0,atol=0)
        torch.testing.assert_close(embedded.grad,expected_input,rtol=0,atol=0)
        for p,expected_grad in zip(model.parameters(),expected_grads):
            torch.testing.assert_close(p.grad,expected_grad,rtol=0,atol=0)
        with self.assertRaises(ValueError):
            model._resident_documents_forward(documents,collector=lambda *args:None)

    def test_capture_region_preserves_real_step_state(self):
        from types import SimpleNamespace
        self.assertTrue(hasattr(residency.ResidentExecution,'capture_region'))
        execution = object.__new__(residency.ResidentExecution)
        execution.active = execution.retired = execution.poisoned = False
        execution.pending = 0
        execution.step_id = 7
        execution.bound = 'previous-bound'
        execution.routed = [torch.tensor([1,2])]
        execution.routing_valid = torch.tensor(False)
        execution.input_valid = torch.tensor([True,False,True])
        execution.identity = lambda: 'current-owner'
        execution.model = SimpleNamespace(_cuda_execution=execution,parameter_inventory=lambda: None)
        old_routed = execution.routed
        addresses = (execution.routing_valid.data_ptr(),execution.input_valid.data_ptr())
        with execution.capture_region():
            self.assertTrue(execution.active)
            self.assertEqual(execution.bound,'current-owner')
            execution.check()
            execution.input_valid.fill_(False)
            execution.routing_valid.fill_(True)
            execution.routed.append(torch.tensor([3]))
        self.assertFalse(execution.active)
        self.assertEqual(execution.step_id,7)
        self.assertEqual(execution.bound,'previous-bound')
        self.assertIs(execution.routed,old_routed)
        self.assertEqual(len(execution.routed),1)
        self.assertEqual(execution.input_valid.tolist(),[True,False,True])
        self.assertFalse(bool(execution.routing_valid))
        self.assertEqual(addresses,(execution.routing_valid.data_ptr(),execution.input_valid.data_ptr()))
        execution.active = True
        with self.assertRaises(RuntimeError):
            with execution.capture_region(): self.fail('active step admitted for capture')

    def test_thirteen_segments_preserve_outputs_all_gradients_and_routes(self):
        self.assertTrue(hasattr(candidate.CIADecoder, '_resident_segment'))
        models = [SmallDenseModel(module.CIADecoder) for module in (reference, candidate)]
        results = []
        for model in models:
            torch.manual_seed(77)
            embedded = (torch.randn(1288,1024) * .03).requires_grad_()
            positions = torch.zeros(1288,3,dtype=torch.long)
            reports = []
            outputs, trace = model._resident_documents_forward(
                [(embedded[:1031],positions[:1031],0),(embedded[1031:],positions[1031:],1)],
                collector=lambda kind, row: reports.append((kind,row)))
            value = torch.cat(outputs)
            value.square().sum().backward()
            results.append((value,embedded.grad,[p.grad for p in model.parameters()],trace.materialize(),reports))
            self.assertEqual(model._cuda_execution.calls, list(range(1,24,2)))
        torch.testing.assert_close(results[0][0],results[1][0],rtol=0,atol=0)
        torch.testing.assert_close(results[0][1],results[1][1],rtol=0,atol=0)
        for left,right in zip(results[0][2],results[1][2]):
            self.assertIsNotNone(left)
            torch.testing.assert_close(left,right,rtol=0,atol=0)
        self.assertGreater(float(results[1][2][1].abs().sum()),0, 'global prior gradient must cross all local segments')
        self.assertEqual(results[0][3], results[1][3])
        self.assertEqual(len(results[1][4]),13)
        for (kind,left),(other,right) in zip(results[0][4],results[1][4]):
            self.assertEqual(kind,other)
            for name,value in left.items():
                if isinstance(value,torch.Tensor):
                    torch.testing.assert_close(value,right[name],rtol=0,atol=0)

if __name__ == '__main__': unittest.main()
