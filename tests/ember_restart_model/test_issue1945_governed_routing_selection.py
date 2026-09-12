# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Governed callers bind routing selection and refuse mismatched start identities."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))


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
