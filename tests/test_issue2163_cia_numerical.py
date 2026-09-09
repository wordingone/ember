# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# goal_id: EMBER-02
# workstream_id: EMBER-02A
"""Opt-in full-population CPU mechanics; no trained-capability claim."""
import hashlib
import os
import sys
import unittest
from pathlib import Path
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ember.model.cia_decoder import CIADecoder


def digest(tensor):
    return hashlib.sha256(tensor.detach().contiguous().reshape(-1).view(torch.uint8).numpy()).hexdigest()


@unittest.skipUnless(os.environ.get('EMBER_CIA_CPU_CONFORMANCE') == '1',
                     'requires explicit full-population CPU resource envelope')
class NumericalCIATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.model = CIADecoder()
        cls.model.apply_update_support('memory-only')
        cls.model.materialize_cpu(seed=2163)
        assert all(not p.requires_grad for p in cls.model.parameters())

    def setUp(self):
        self.model.apply_update_support('memory-only')

    def run_tokens(self, tokens, **kwargs):
        positions = torch.zeros(len(tokens), 3, dtype=torch.long)
        positions[:, 0] = torch.arange(len(tokens))
        return self.model(self.model.embed_text(torch.tensor(tokens)), positions, **kwargs)

    def test_01_physical_population_and_expert_diversity(self):
        parameters = self.model.parameter_inventory()
        self.assertEqual(sum(p.numel() for p in parameters.values()), 3_082_539_008)
        self.assertTrue(all(p.device.type == 'cpu' for p in parameters.values()))
        digests = []
        for expert in range(25):
            h = hashlib.sha256()
            for name, p in parameters.items():
                if name.startswith(f'experts.{expert}.'):
                    h.update(bytes.fromhex(digest(p)))
            digests.append(h.hexdigest())
        self.assertEqual(len(set(digests)), 25)

    def test_011_undeclared_physical_storage_refused(self):
        key = 'experts__0__layers__1__up__weight'
        original = self.model.weights[key]
        backing = torch.zeros(original.numel() + 1, dtype=original.dtype)
        self.model.weights[key] = torch.nn.Parameter(backing[:-1].view(original.shape), requires_grad=False)
        try:
            with self.assertRaisesRegex(ValueError, 'storage does not match'):
                self.model.parameter_inventory()
        finally:
            self.model.weights[key] = original

    def test_012_internally_overlapping_parameter_refused(self):
        key = 'experts__0__layers__1__up__weight'
        original = self.model.weights[key]
        backing = torch.zeros_like(original)
        overlapping = backing.as_strided(original.shape, (0, 1))
        self.model.weights[key] = torch.nn.Parameter(overlapping, requires_grad=False)
        try:
            with self.assertRaisesRegex(ValueError, 'storage does not match'):
                self.model.parameter_inventory()
        finally:
            self.model.weights[key] = original

    def test_013_overlapping_external_storages_refused(self):
        names = ('experts__0__layers__1__up__weight', 'experts__0__layers__1__gate__weight')
        originals = [self.model.weights[name] for name in names]
        count = originals[0].numel()
        backing = bytearray(count * 2 + 2)
        try:
            for offset, name in enumerate(names):
                tensor = torch.frombuffer(backing, dtype=torch.bfloat16, count=count, offset=offset * 2).view(originals[offset].shape)
                self.model.weights[name] = torch.nn.Parameter(tensor, requires_grad=False)
            with self.assertRaisesRegex(ValueError, 'storage alias'):
                self.model.parameter_inventory()
        finally:
            for name, parameter in zip(names, originals):
                self.model.weights[name] = parameter

    def test_02_real_causal_logits_and_document_isolation(self):
        with torch.no_grad():
            original, routes = self.run_tokens([1, 2, 3, 4], return_routes=True)
            changed = self.run_tokens([1, 2, 9, 8])
            prefix = self.run_tokens([1, 2])
            packed = self.run_tokens([1, 2, 9, 8], document_starts=(0, 2))
            self.assertTrue(torch.isfinite(original).all())
            torch.testing.assert_close(original[:2], changed[:2], rtol=0, atol=0)
            torch.testing.assert_close(original[:2], prefix, rtol=0.02, atol=0.02)
            torch.testing.assert_close(packed[:2], prefix, rtol=0, atol=0)
            self.assertEqual(len(routes), 12)

    def test_025_non_bos_routing_boundaries(self):
        # Full numerical decoder at both causal cutoffs, not a tiny stand-in.
        with torch.no_grad():
            tokens = (torch.arange(1025) % 97 + 1).tolist()
            original, routes = self.run_tokens(tokens, return_routes=True)
            changed, changed_routes = self.run_tokens(tokens[:-1] + [109], return_routes=True)
            torch.testing.assert_close(original[:1024], changed[:1024], rtol=0, atol=0)
            self.assertEqual(routes, changed_routes)
            self.assertEqual(len(routes), 60)
            self.assertTrue(any(row[2] == 256 for row in routes))
            self.assertTrue(any(row[2] == 1024 for row in routes))
            # Independently reproduce the global history selection at epoch two.
            from ember.model.cia_routing import select_global
            weights = self.model.parameter_inventory()
            keys = torch.stack([weights[f'router.layers.{layer}.keys'] for layer in range(1, 24, 2)])
            expected = select_global(self.model.embed_text(torch.tensor(tokens)),
                weights['router.global_query.weight'], keys, position=1024,
                document_start=0, generation='independent-test', request='independent-test')
            self.assertTrue(all(row[3] == expected.experts for row in routes if row[2] == 1024))

    def test_026_integrated_local_router_gradient(self):
        self.model.apply_update_support('router-only')
        logits = self.run_tokens((torch.arange(257) % 97 + 1).tolist())
        loss = torch.nn.functional.cross_entropy(logits[-1:].float(), torch.tensor([109]))
        loss.backward()
        weights = self.model.parameter_inventory()
        gradient = weights['router.local_query.weight'].grad
        self.assertTrue(torch.isfinite(gradient).all())
        self.assertGreater(torch.count_nonzero(gradient).item(), 0)
        self.assertTrue(all(p.grad is None for name, p in weights.items() if not name.startswith('router.')))

    def test_03_numerical_backward_and_exact_update_support(self):
        self.model.apply_update_support('core+expert-set', experts=(0,))
        parameters = self.model.parameter_inventory()
        before = {name: digest(p) for name, p in parameters.items()}
        optimizer = torch.optim.AdamW(parameters.values(), lr=0.01, foreach=False)
        logits = self.run_tokens([1, 2, 3, 4])
        loss = torch.nn.functional.cross_entropy(logits[:-1].float(), torch.tensor([2, 3, 4]))
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        for name in ('embedding.weight', 'experts.0.layers.1.up.weight'):
            self.assertIsNotNone(parameters[name].grad)
            self.assertTrue(torch.isfinite(parameters[name].grad).all())
            self.assertGreater(torch.count_nonzero(parameters[name].grad).item(), 0)
        optimizer.step()
        changed = {name for name, p in parameters.items() if before[name] != digest(p)}
        self.assertIn('embedding.weight', changed)
        self.assertIn('experts.0.layers.1.up.weight', changed)
        self.assertTrue(changed.issubset({name for name, p in parameters.items() if p.requires_grad}))
        retained = {name: {k: digest(v) for k, v in optimizer.state[p].items()}
                    for name, p in parameters.items() if p in optimizer.state}
        self.model.apply_update_support('memory-only')
        optimizer.step()
        for name, state in retained.items():
            self.assertEqual(state, {k: digest(v) for k, v in optimizer.state[parameters[name]].items()})
        self.assertTrue(all(p.grad is None for p in parameters.values()))


if __name__ == '__main__':
    unittest.main()
