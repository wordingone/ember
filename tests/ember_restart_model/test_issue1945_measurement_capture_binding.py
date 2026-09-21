# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute the measurement worker's capture-binding statements without CUDA.

The source AST supplies the actual call, condition, mode assignment and routing
helpers. Only the surrounding worker setup is replaced by small Python objects;
the escaped call is neither reconstructed nor supplied an ambient identity.
This covers the binding boundary, not worker admission or model execution.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
SUBJECT_PATH = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
CAPTURE_MODES = ('resident-segmented-capture', 'resident-dynamic-capture')


def exactly_one(nodes, description):
    if len(nodes) != 1:
        raise RuntimeError(f'expected one actual worker {description}, found {len(nodes)}')
    return nodes[0]


def assigned_name(node, name):
    return (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name)


def load_worker_capture_block():
    tree = ast.parse(SUBJECT_PATH.read_bytes(), filename=str(SUBJECT_PATH))
    worker = exactly_one([node for node in tree.body
                          if isinstance(node, ast.FunctionDef) and node.name == 'worker'], 'function')
    guarded = exactly_one([node for node in worker.body if isinstance(node, ast.Try)], 'guarded body')
    mode = exactly_one([node for node in guarded.body if assigned_name(node, 'mode')], 'mode assignment')
    capture = exactly_one([node for node in guarded.body if assigned_name(node, 'capture')], 'capture assignment')
    binding = exactly_one([
        node for node in guarded.body if isinstance(node, ast.If)
        and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and child.func.attr == 'bind_segmented_capture' for child in ast.walk(node))
    ], 'capture conditional')
    helpers = []
    for name in ('EXECUTION_MODES', 'MODE_SOURCES'):
        helpers.append(exactly_one([node for node in tree.body if assigned_name(node, name)], name))
    for name in ('execution_mode', 'local_routing_mode', 'training_head', 'capture_loss_kwargs'):
        helpers.append(exactly_one([node for node in tree.body
                                   if isinstance(node, ast.FunctionDef) and node.name == name], name))
    wrapper = ast.FunctionDef(
        name='exercise_capture_binding',
        args=ast.arguments(posonlyargs=[],
                           args=[ast.arg(arg=name) for name in
                                 ('prediction', 'model', 'first_lengths', 'device', 'routing_buffers')],
                           vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
        body=[mode, capture, binding, ast.Return(value=ast.Name(id='capture', ctx=ast.Load()))],
        decorator_list=[], returns=None,
    )
    ast.copy_location(wrapper, worker)
    module = ast.fix_missing_locations(ast.Module(body=[*helpers, wrapper], type_ignores=[]))
    namespace = {'__name__': 'measurement_worker_capture_binding'}
    exec(compile(module, str(SUBJECT_PATH), 'exec'), namespace)
    return namespace['exercise_capture_binding'], namespace


class BindingRecorder:
    def __init__(self):
        self.calls = []
        self.result = object()

    def bind_segmented_capture(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class MeasurementCaptureBindingTests(unittest.TestCase):
    def setUp(self):
        self.execute, self.namespace = load_worker_capture_block()
        self.assertNotIn('identity', self.namespace)
        self.model = BindingRecorder()
        self.buffers = SimpleNamespace(collector=object(), raw=object())
        self.buffer_calls = []
        self.lengths = (1024, 1024, 1024, 1024)
        self.device = object()

    def routing_buffers(self, lengths, device):
        self.buffer_calls.append((lengths, device))
        return self.buffers

    def invoke(self, prediction):
        return self.execute(prediction, self.model, self.lengths, self.device, self.routing_buffers)

    def assert_binding(self, prediction, execution, expected_route):
        self.model.calls.clear()
        self.buffer_calls.clear()
        result = self.invoke(prediction)
        self.assertIs(result, self.model.result)
        self.assertEqual(self.buffer_calls, [(self.lengths, self.device)])
        self.assertEqual(len(self.model.calls), 1)
        actual = self.model.calls[0]
        self.assertEqual(actual['local_routing_mode'], expected_route)
        self.assertIs(actual['collector'], self.buffers.collector)
        self.assertEqual(actual['static_state'], (self.buffers.raw,))
        self.assertEqual(actual['warmup_steps'], 2)
        self.assertTrue(callable(actual['loss_fn']))
        if execution == 'resident-dynamic-capture':
            self.assertIs(actual['capture_experts'], True)
        else:
            self.assertNotIn('capture_experts', actual)
        self.assertNotIn('identity', self.namespace)

    def test_both_capture_modes_bind_explicit_per_chunk_and_batched_routes(self):
        for execution in CAPTURE_MODES:
            for route in ('per-chunk', 'batched'):
                with self.subTest(execution=execution, route=route):
                    self.assert_binding({'identity': {'execution_mode': execution, 'local_routing_mode': route}},
                                        execution, route)

    def test_both_capture_modes_preserve_omitted_route_default(self):
        for execution in CAPTURE_MODES:
            with self.subTest(execution=execution):
                prediction = {'identity': {'execution_mode': execution}}
                self.assert_binding(prediction, execution, 'batched')
                self.assertNotIn('local_routing_mode', prediction['identity'])

    def test_unknown_or_null_route_refuses_before_capture_binder_side_effect(self):
        for execution in CAPTURE_MODES:
            for route in ('unknown-route', None):
                with self.subTest(execution=execution, route=route):
                    self.model.calls.clear()
                    with self.assertRaisesRegex(ValueError, 'local routing mode is outside its fixed set'):
                        self.invoke({'identity': {'execution_mode': execution, 'local_routing_mode': route}})
                    self.assertEqual(self.model.calls, [])

    def test_nested_prediction_identity_wins_over_contradictory_outer_fields(self):
        # An outer mapping with plausible fields must not silently supply the
        # treatment or its default when the worker has a bound nested identity.
        prediction = {'execution_mode': 'resident-dynamic-capture', 'local_routing_mode': 'batched',
                      'identity': {'execution_mode': 'resident-segmented-capture',
                                   'local_routing_mode': 'per-chunk'}}
        self.assert_binding(prediction, 'resident-segmented-capture', 'per-chunk')

    def test_eager_control_does_not_allocate_routing_buffers_or_bind_capture(self):
        self.assertIsNone(self.invoke({'identity': {}}))
        self.assertEqual(self.buffer_calls, [])
        self.assertEqual(self.model.calls, [])


if __name__ == '__main__':
    unittest.main()
