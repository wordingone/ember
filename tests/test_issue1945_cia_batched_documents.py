# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# goal_id: EMBER-02
# workstream_id: EMBER-02A
"""Grouped expert execution across documents: same per-chunk numerics, one lease per expert per pass.

No throughput, paging or qualification credit. The stub-cache tests prove the grouped autograd function
against the single-chunk path on CPU without the full population; the opt-in test proves the batched
decoder path against the serial path on the real 3B CPU reference.
"""
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ember.model.ember_v0_residency import ExpertCache, _swiglu, paged_swiglu, paged_swiglu_group


class StubCache:
    """The lease/step surface paged_swiglu consumes, with counters; not an ExpertCache."""
    def __init__(self, bank, device):
        self.bank, self.device = bank, device
        self.active, self.step_id, self.pending = True, 1, 0
        self.lease_count, self.leased = 0, set()

    def check(self):
        if not self.active:
            raise RuntimeError('expert execution requires a candidate step')

    @contextmanager
    def lease(self, expert):
        if expert in self.leased:
            raise RuntimeError('reentrant expert lease')
        self.lease_count += 1
        self.leased.add(expert)
        try:
            yield self.bank[expert]
        finally:
            self.leased.remove(expert)


def make_bank(seed, experts=(3, 7), width=1024, hidden=256):
    generator = torch.Generator().manual_seed(seed)
    bank = {}
    for expert in experts:
        bank[expert] = {name: torch.nn.Parameter((torch.randn(shape, generator=generator) * 0.02).to(torch.bfloat16))
                        for name, shape in (('up', (hidden, width)), ('gate', (hidden, width)), ('down', (width, hidden)))}
    return bank


class GroupedPagedSwiGLUTests(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank(1945)
        self.cache = StubCache(self.bank, torch.device('cpu'))
        generator = torch.Generator().manual_seed(7)
        self.chunks = tuple((torch.randn(256, 1024, generator=generator) * 0.5).to(torch.bfloat16).requires_grad_(True)
                            for _ in range(3))

    def test_forward_is_bit_identical_to_separate_calls_and_leases_once(self):
        separate = [paged_swiglu(chunk, self.cache, 3) for chunk in self.chunks]
        separate_leases = self.cache.lease_count
        grouped = paged_swiglu_group(self.chunks, self.cache, 3)
        self.assertEqual(self.cache.lease_count - separate_leases, 1)
        self.assertEqual(separate_leases, 3)
        for a, b in zip(separate, grouped):
            torch.testing.assert_close(a, b, rtol=0, atol=0)
        with torch.no_grad():
            inference = paged_swiglu_group(tuple(c.detach() for c in self.chunks), self.cache, 3)
        for a, b in zip(separate, inference):
            torch.testing.assert_close(a.detach(), b, rtol=0, atol=0)

    def test_backward_matches_separate_calls_and_settles_pending(self):
        weights = self.bank[3]
        for w in weights.values():
            w.requires_grad_(True)
        # Serial reference: three separate calls, autograd accumulates weight gradients.
        separate = [paged_swiglu(chunk, self.cache, 3) for chunk in self.chunks]
        self.assertEqual(self.cache.pending, 3)
        sum(o.float().square().sum() for o in separate).backward()
        self.assertEqual(self.cache.pending, 0)
        reference_weight = {name: w.grad.clone() for name, w in weights.items()}
        reference_value = [c.grad.clone() for c in self.chunks]
        for w in weights.values():
            w.grad = None
        for c in self.chunks:
            c.grad = None
        grouped = paged_swiglu_group(self.chunks, self.cache, 3)
        self.assertEqual(self.cache.pending, 1)
        leases_before = self.cache.lease_count
        sum(o.float().square().sum() for o in grouped).backward()
        self.assertEqual(self.cache.lease_count - leases_before, 1)
        self.assertEqual(self.cache.pending, 0)
        for c, ref in zip(self.chunks, reference_value):
            torch.testing.assert_close(c.grad, ref, rtol=0, atol=0)
        for name, w in weights.items():
            # Summation order differs (explicit sum here vs autograd accumulation); bound it, do not assume it.
            ref = reference_weight[name].float()
            rel = (w.grad.float() - ref).norm() / ref.norm()
            self.assertLess(float(rel), 1e-2, name)

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, 'non-empty tuple'):
            paged_swiglu_group((), self.cache, 3)
        with self.assertRaisesRegex(ValueError, 'non-empty tuple'):
            paged_swiglu_group(list(self.chunks), self.cache, 3)
        grouped = paged_swiglu_group(self.chunks, self.cache, 7)
        self.cache.step_id += 1
        with self.assertRaisesRegex(RuntimeError, 'stale or repeated expert backward'):
            sum(o.float().sum() for o in grouped).backward()
        self.cache.active = False
        with self.assertRaisesRegex(RuntimeError, 'requires a candidate step'):
            paged_swiglu_group(self.chunks, self.cache, 3)

    def test_grouped_equals_plain_swiglu_per_chunk(self):
        weights = self.bank[7]
        expected = [_swiglu(c, weights['up'], weights['gate'], weights['down']) for c in self.chunks]
        for a, b in zip(expected, paged_swiglu_group(self.chunks, self.cache, 7)):
            torch.testing.assert_close(a, b, rtol=0, atol=0)


class ResidentCapacityTests(unittest.TestCase):
    """Real ExpertCache on CPU: the resident bound is explicit, defaults to 2, and is refused below 2."""
    def bank(self):
        return make_bank(2163, experts=(0, 1, 8), width=64, hidden=32)

    def lease_sequence(self, cache, experts):
        with cache.step():
            for expert in experts:
                with cache.lease(expert):
                    pass

    def test_default_bound_of_two_evicts_the_third_bundle(self):
        cache = ExpertCache(self.bank(), device=torch.device('cpu'))
        self.assertEqual(cache.resident_capacity, 2)
        self.lease_sequence(cache, (0, 1, 8, 0))
        self.assertEqual((cache.lease_count, cache.miss_count, cache.eviction_count, cache.peak_resident_bundles), (4, 4, 2, 2))

    def test_bound_of_three_keeps_three_bundles_resident(self):
        cache = ExpertCache(self.bank(), device=torch.device('cpu'), resident_capacity=3)
        self.lease_sequence(cache, (0, 1, 8, 0, 1, 8))
        self.assertEqual((cache.lease_count, cache.miss_count, cache.eviction_count, cache.peak_resident_bundles), (6, 3, 0, 3))

    def test_refusals(self):
        for bad in (1, 0, -2, 2.0, '2', True, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ExpertCache(self.bank(), device=torch.device('cpu'), resident_capacity=bad)


@unittest.skipUnless(os.environ.get('EMBER_CIA_CPU_CONFORMANCE') == '1',
                     'requires explicit full-population CPU resource envelope')
class BatchedDocumentsCPUReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ember.model.ember_v0_decoder import CIADecoder
        torch.set_num_threads(1)
        cls.model = CIADecoder()
        cls.model.apply_update_support('memory-only')
        cls.model.materialize_cpu(seed=2163)

    def run_tokens(self, tokens, **kwargs):
        positions = torch.zeros(len(tokens), 3, dtype=torch.long)
        positions[:, 0] = torch.arange(len(tokens))
        return self.model(self.model.embed_text(torch.tensor(tokens)), positions, **kwargs)

    @staticmethod
    def relative_l2(candidate, reference):
        return float((candidate.float() - reference.float()).norm() / reference.float().norm().clamp_min(1e-12))

    def test_batched_path_matches_serial_path(self):
        """Routes exact; logits within the declared rel-L2 bound (0.05) on both attention branches."""
        with torch.no_grad():
            for tokens, starts in (([1, 2, 9, 8, 5, 6], (0, 2, 4)),        # equal lengths: batched 4-D attention
                                   ([1, 2, 9, 8, 5, 6, 7], (0, 2, 5))):    # unequal lengths: per-document fallback
                serial, serial_routes = self.run_tokens(tokens, document_starts=starts, return_routes=True)
                batched, batched_routes = self.run_tokens(tokens, document_starts=starts,
                                                          return_routes=True, batch_documents=True)
                self.assertEqual(serial_routes, batched_routes)
                self.assertEqual(tuple(serial.shape), tuple(batched.shape))
                self.assertLessEqual(self.relative_l2(batched, serial), 0.05, msg=str(starts))
            single = self.run_tokens([1, 2, 3], batch_documents=True)
            self.assertLessEqual(self.relative_l2(single, self.run_tokens([1, 2, 3])), 0.05)
        with self.assertRaisesRegex(ValueError, 'batch_documents must be a bool'):
            self.run_tokens([1, 2], batch_documents=1)

    def test_batched_path_calls_each_expert_once_per_sparse_layer(self):
        """The grouped call site issues exactly one expert_block_group per (layer, expert) with one member."""
        calls = []
        original = type(self.model).expert_block_group

        def counting(model, values, *, expert, layer):
            calls.append((layer, expert, len(values), tuple(len(v) for v in values)))
            return original(model, values, expert=expert, layer=layer)
        type(self.model).expert_block_group = counting
        try:
            with torch.no_grad():
                _, routes = self.run_tokens([1, 2, 9, 8, 5, 6], document_starts=(0, 2, 4),
                                            return_routes=True, batch_documents=True)
        finally:
            type(self.model).expert_block_group = original
        expected = {(layer, expert) for _, layer, _, _, expert in routes}
        self.assertEqual({(layer, expert) for layer, expert, _, _ in calls}, expected)
        self.assertEqual(len(calls), len(expected))
        self.assertTrue(all(members == 1 for _, _, members, _ in calls))
        rows = {(layer, expert): 0 for layer, expert in expected}
        for document, layer, start, _, expert in routes:
            rows[(layer, expert)] += 2   # every document here is 2 tokens, one chunk each
        self.assertEqual({(layer, expert): sizes[0] for layer, expert, _, sizes in calls}, rows)

if __name__ == '__main__':
    unittest.main()
