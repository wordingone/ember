# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Explicit dynamic expert selection preserves segment owners and eager sequencing."""
import unittest
import torch
from types import SimpleNamespace
from unittest.mock import patch
from test_issue1945_cia_segments import SmallDenseModel, Execution
from ember.model import ember_v0_decoder as decoder
from ember.model import ember_v0_residency as residency


class DynamicExecution(Execution):
    def __init__(self):
        super().__init__()
        self.routing_valid = torch.ones((), dtype=torch.bool)
        self.id_tensor = torch.tensor([0, 1, 8, 18])
        self.slot_tensor = torch.arange(4)
        self.backends = []

    def grouped_block(self, values, experts, layer, *, backend='native'):
        self.backends.append(backend)
        return super().grouped_block(values, experts, layer)


class Model(SmallDenseModel):
    def __init__(self):
        super().__init__(decoder.CIADecoder)
        self._cuda_execution = DynamicExecution()
        self.expert_parameters = torch.nn.ParameterDict({
            f'experts__{expert}__layers__{layer}__{projection}__weight': torch.nn.Parameter(torch.ones(1))
            for expert in self._resident_experts for layer in range(1, 24, 2)
            for projection in ('up', 'gate', 'down')})

    @property
    def weights(self):
        return dict(super().weights, **self.expert_parameters)


class DynamicIntegrationTests(unittest.TestCase):
    def test_grouped_autograd_returns_gradients_to_mixed_actual_owner_slots(self):
        # An empty group and individually frozen owners expose an off-by-one in the
        # non-tensor backend argument's position on the custom-autograd input surface.
        torch.manual_seed(41)
        shapes = ((4, 6, 4), (4, 6, 4), (4, 4, 6))
        stores = [torch.randn(shape, dtype=torch.float64) * .03 for shape in shapes]
        owners = [torch.nn.Parameter(store[group], requires_grad=(index % 3 != 1))
                  for index, (store, group) in enumerate((s, g) for s in stores for g in range(4))]
        value = torch.randn(7, 4, dtype=torch.float64, requires_grad=True)
        offsets = torch.tensor([3, 3, 4, 7], dtype=torch.int32)
        def cpu_grouped(a, b, *, offs):
            start, parts = 0, []
            for group, end in enumerate(offs.tolist()):
                parts.append(a[start:end] @ b[group])
                start = end
            return torch.cat(parts)
        original = residency._grouped_swiglu
        backends = []
        def observed(a, up, gate, down, offs, backend='native', chunk_ends=None):
            backends.append(backend)
            return original(a, up, gate, down, offs, 'native')
        execution = SimpleNamespace(check=lambda: None, layer_groups=lambda layer: tuple(stores),
                                    pending=0, step_id=4)
        with patch.object(residency.F, 'grouped_mm', cpu_grouped), patch.object(residency, '_grouped_swiglu', observed):
            actual = residency._ResidentGroupedSwiGLU.apply(value, offsets, execution, 1, 'dynamic', None, *owners)
            actual.square().sum().backward()
            actual_grads = [value.grad.clone()] + [p.grad.clone() if p.grad is not None else None for p in owners]
            self.assertEqual(execution.pending, 0)
            self.assertEqual(backends, ['dynamic'])
            value.grad = None
            for owner in owners:
                owner.grad = None
            groups = [torch.stack(owners[index:index+4]) for index in (0, 4, 8)]
            expected = original(value, *groups, offsets)
            expected.square().sum().backward()
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        for got, owner in zip(actual_grads, [value, *owners]):
            if owner.grad is None:
                self.assertIsNone(got)
            else:
                torch.testing.assert_close(got, owner.grad, rtol=0, atol=0)

    def test_dynamic_capture_binds_each_actual_expert_owner_once(self):
        model = Model()
        step = model.bind_segmented_capture(capture_experts=True)
        for index, segment in enumerate(step.segments[:12]):
            expected = {id(parameter) for name, parameter in model.expert_parameters.items()
                        if f'__layers__{2*index+1}__' in name}
            actual = {id(parameter) for parameter in segment.params}
            self.assertEqual(len(expected), 12)
            self.assertTrue(expected <= actual)
            self.assertEqual(len(actual), len(segment.params))
        for value in (model._cuda_execution.routing_valid, model._cuda_execution.id_tensor,
                      model._cuda_execution.slot_tensor):
            self.assertTrue(any(value is actual for actual in step.static_state))

    def test_explicit_dynamic_capture_keeps_one_grouped_call_per_layer(self):
        outputs = []
        for dynamic in (False, True):
            model = Model()
            step = model.bind_segmented_capture(capture_experts=dynamic)
            embedded = torch.randn(1288, 1024) * .03
            positions = torch.zeros(1288, 3, dtype=torch.long)
            documents = [(embedded[:1031], positions[:1031], 0),
                         (embedded[1031:], positions[1031:], 1)]
            with step.record():
                result, _ = model._resident_documents_forward(documents)
            outputs.append(torch.cat(result).detach())
            self.assertEqual(model.shared_calls, [f'layers.{layer}.shared' for layer in range(24)])
            self.assertEqual(model._cuda_execution.calls, list(range(1, 24, 2)))
            self.assertEqual(model._cuda_execution.backends, [('dynamic' if dynamic else 'native')] * 12)
        torch.testing.assert_close(outputs[0], outputs[1], rtol=0, atol=0)

    def test_selection_requires_an_exact_boolean(self):
        for value in (1, 'dynamic', None):
            with self.assertRaises(ValueError):
                Model().bind_segmented_capture(capture_experts=value)


if __name__ == '__main__':
    unittest.main()
