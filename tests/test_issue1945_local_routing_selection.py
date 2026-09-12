# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Explicit local routing selection preserves both native numerical implementations."""
import importlib.util
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import torch
from ember.model.ember_v0_residency import resident_global_routes, resident_local_routes, route_index
from ember.model.ember_v0_routing import StepRouting, ChunkSpec


class LocalRoutingSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.assertIn('local_routing_mode', inspect.signature(resident_local_routes).parameters,
                      'The measured per-chunk implementation must be explicitly selectable')

    def fixture(self):
        rng = torch.Generator().manual_seed(1945)
        lengths = (1031, 257)
        embedded = torch.randn(sum(lengths), 1024, generator=rng) * .02
        hidden = (torch.randn(sum(lengths), 1024, generator=rng) * .02).requires_grad_()
        query = (torch.randn(1024, 1024, generator=rng) * .02).requires_grad_()
        local = (torch.randn(1024, 1024, generator=rng) * .02).requires_grad_()
        keys = (torch.randn(12, 25, 1024, generator=rng) * .02).requires_grad_()
        geometry, priors, _, candidates, valid = resident_global_routes(embedded, lengths, query, keys)
        self.assertTrue(bool(valid))
        return lengths, embedded, hidden, query, local, keys, geometry, priors, candidates

    def test_per_chunk_scores_and_gradients_match_actual_reference_exactly(self):
        lengths, embedded, hidden, query, local, keys, geometry, priors, candidates = self.fixture()
        winners, logits, gates, valid = resident_local_routes(hidden, local, keys, 3, geometry, priors, candidates,
                                                             local_routing_mode='per-chunk')
        self.assertTrue(bool(valid))
        weights = torch.arange(1, len(gates) + 1)
        actual_gradients = torch.autograd.grad((gates * weights).sum(), (hidden, local, keys), retain_graph=True)
        reference = StepRouting(query, local, keys, 'selection-fixture')
        chunks = []
        offset = 0
        for document, length in enumerate(lengths):
            selections = {start: reference.select_global(embedded[offset:offset + length], position=start,
                                                         document_start=0, request=str(document))
                          for start in range(0, length, 1024)}
            chunks.extend(ChunkSpec(document_offset=offset, start=start, selection=selections[start//1024*1024],
                                    request=str(document)) for start in range(0, length, 256))
            offset += length
        expected = reference.select_local_batch(hidden, chunks, sparse_depth=3)
        self.assertEqual(tuple(winners.tolist()), expected.experts)
        torch.testing.assert_close(logits, expected.logits, rtol=0, atol=0)
        torch.testing.assert_close(gates, expected.gates, rtol=0, atol=0)
        expected_gradients = torch.autograd.grad((expected.gates * weights).sum(), (hidden, local, keys))
        for actual, expected_gradient in zip(actual_gradients, expected_gradients):
            torch.testing.assert_close(actual, expected_gradient, rtol=0, atol=0)
        reference.close()

    def test_default_remains_exactly_batched(self):
        _, _, hidden, _, local, keys, geometry, priors, candidates = self.fixture()
        default = resident_local_routes(hidden, local, keys, 3, geometry, priors, candidates)
        explicit = resident_local_routes(hidden, local, keys, 3, geometry, priors, candidates,
                                         local_routing_mode='batched')
        for a, b in zip(default, explicit):
            torch.testing.assert_close(a, b, rtol=0, atol=0)

    def test_per_chunk_refuses_an_unrelated_bound_index(self):
        _, _, hidden, _, local, keys, geometry, priors, candidates = self.fixture()
        index = route_index(geometry, hidden.device)
        with self.assertRaises(ValueError):
            resident_local_routes(hidden, local, keys, 3, geometry, priors, candidates,
                                  index=index, local_routing_mode='per-chunk')

    def test_unknown_selector_refuses_before_tensor_access(self):
        for mode in ('', 'automatic', None, True, 1):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                resident_local_routes(None, None, None, 3, None, None, None, local_routing_mode=mode)


class GovernedRoutingSelectionTests(unittest.TestCase):
    def test_identity_binds_only_supported_capture_selection(self):
        path = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
        spec = importlib.util.spec_from_file_location('routing_selection_runner', path)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        self.assertTrue(callable(getattr(runner, 'local_routing_mode', None)),
                        'The governed caller must bind the local routing selection')
        self.assertEqual(runner.local_routing_mode({}), 'per-chunk')
        self.assertEqual(runner.local_routing_mode({'local_routing_mode': 'per-chunk'}), 'per-chunk')
        for execution in ('resident-segmented-capture', 'resident-dynamic-capture'):
            for mode in ('per-chunk', 'batched'):
                self.assertEqual(runner.local_routing_mode(dict(execution_mode=execution, local_routing_mode=mode)), mode)
        for value in ({'local_routing_mode': 'batched'},
                      {'execution_mode': 'resident-dynamic-capture', 'local_routing_mode': 'automatic'},
                      {'execution_mode': 'resident-dynamic-capture', 'local_routing_mode': None}):
            with self.subTest(identity=value), self.assertRaises(ValueError):
                runner.local_routing_mode(value)

    def test_real_start_consumer_accepts_matching_routes_and_refuses_a_changed_route(self):
        base = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
        def load(name):
            spec = importlib.util.spec_from_file_location('selection_' + name, base / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        runner, consumer = load('cia_step_runner'), load('cia_trajectory')
        self.assertTrue(callable(getattr(runner, 'local_routing_mode', None)))
        reference = dict(source_sha256={'source': 'a'*64}, optimizer={'name': 'AdamW'},
                         local_routing_mode=runner.local_routing_mode({}))
        treatment = dict(reference, optimizer={'name': 'AdamW', 'fused': True},
                         local_routing_mode=runner.local_routing_mode(dict(execution_mode='resident-dynamic-capture',
                                                                          local_routing_mode='per-chunk')))
        consumer.compare_start_identity(reference, treatment, arm='Tfused')
        changed = dict(treatment, local_routing_mode=runner.local_routing_mode(dict(execution_mode='resident-dynamic-capture')))
        with self.assertRaises(ValueError):
            consumer.compare_start_identity(reference, changed, arm='Tfused')


if __name__ == '__main__':
    unittest.main()
