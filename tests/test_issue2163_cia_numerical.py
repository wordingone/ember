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
from ember.model.ember_v0_decoder import CIADecoder


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
            from ember.model.ember_v0_routing import select_global
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

    _observation_cache = None

    def observed_fixture(self):
        """Measure the fixed 1025-token forward once; every plan test reads the same measurement."""
        if type(self)._observation_cache is None:
            from ember.model.ember_v0_routing import GlobalObservation, LocalObservation
            tokens = (torch.arange(1025) % 97 + 1).tolist()
            observed = []
            with torch.no_grad():
                logits, routes = self.run_tokens(tokens, return_routes=True,
                                                 route_observer=observed.append)
            local = tuple(row for row in observed if type(row) is LocalObservation)
            globals_ = tuple(row for row in observed if type(row) is GlobalObservation)
            self.assertEqual(len(local) + len(globals_), len(observed))
            type(self)._observation_cache = (tokens, logits, routes, local, globals_)
        return type(self)._observation_cache

    def test_027_observation_records_the_run_without_changing_it(self):
        from ember.governance.scripts.cia_numerical_split import (
            GLOBAL_SELECTIONS_PER_DOCUMENT, LOCAL_ROUTES)
        tokens, logits, routes, local, globals_ = self.observed_fixture()
        with torch.no_grad():
            unobserved = self.run_tokens(tokens)
        # An observer that perturbs the computation measures a run nobody else will ever make.
        torch.testing.assert_close(logits, unobserved, rtol=0, atol=0)
        self.assertEqual(len(local), LOCAL_ROUTES)
        self.assertEqual(len(globals_), GLOBAL_SELECTIONS_PER_DOCUMENT)
        self.assertEqual(len({row.key for row in local}), LOCAL_ROUTES)
        self.assertEqual(sorted(row.epoch_start for row in globals_), [0, 1024])
        by_key = {row.key: row for row in local}
        for document, layer, start, candidates, chosen in routes:
            row = by_key[(document, layer, start)]
            # The record has to describe the route the run actually took, not a parallel selection.
            self.assertEqual(row.candidates, tuple(sorted(candidates)))
            self.assertEqual(row.chosen, chosen)
            self.assertIn(chosen, row.candidates)
            self.assertEqual(row.summary.shape, (1024,))
            self.assertEqual(row.keys_slice.shape, (2, 1024))
            self.assertEqual(row.prior_slice.shape, (2,))
            self.assertEqual(row.margin, row.logits[0] - row.logits[1])
            # Signed in ascending candidate order, ties to the lower ID. The fixture contains
            # exact zeros, so a strict `> 0` reads the winner backwards at the closest decisions.
            self.assertEqual(row.chosen, row.candidates[0 if row.margin >= 0 else 1])
            self.assertTrue(torch.isfinite(row.summary).all())

    def test_028_a_fixed_plan_is_consumed_and_steers_the_computation(self):
        from ember.governance.scripts.cia_numerical_split import route_plan
        tokens, logits, routes, local, _ = self.observed_fixture()
        plan = route_plan(local)
        self.assertEqual(len(plan), len(routes))
        with torch.no_grad():
            replayed, replayed_routes = self.run_tokens(tokens, return_routes=True, route_plan=plan)
        self.assertEqual(replayed_routes, routes)
        torch.testing.assert_close(replayed, logits, rtol=0, atol=0)
        # A plan that cannot change the computation is decoration, so prove one that does.
        steered = dict(plan)
        key = next(row.key for row in local if row.chosen != row.candidates[0])
        candidates, winner = steered[key]
        other = candidates[0] if winner == candidates[1] else candidates[1]
        steered[key] = (candidates, other)
        with torch.no_grad():
            forced, forced_routes = self.run_tokens(tokens, return_routes=True, route_plan=steered)
        self.assertEqual(next(row[-1] for row in forced_routes if row[:3] == key), other)
        self.assertFalse(torch.equal(forced, logits))

    def test_029_a_plan_that_does_not_describe_this_run_is_refused(self):
        from ember.governance.scripts.cia_numerical_split import route_plan
        tokens, _, _, local, _ = self.observed_fixture()
        plan = route_plan(local)
        key = min(plan)
        candidates, winner = plan[key]
        absent = {name: value for name, value in plan.items() if name != key}
        drifted = dict(plan)
        drifted[key] = ((23, 24), winner)
        impossible = dict(plan)
        impossible[key] = (candidates, next(i for i in range(25) if i not in candidates))
        for broken, expected in ((absent, 'has no entry for'),
                                 (drifted, 'candidate pair drift'),
                                 (impossible, 'is not a candidate')):
            with torch.no_grad(), self.assertRaisesRegex(ValueError, expected):
                self.run_tokens(tokens, route_plan=broken)

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
