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
from ember.model.ember_v0_residency import _swiglu, paged_swiglu, paged_swiglu_group


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

    def test_batched_path_equals_serial_path_exactly(self):
        with torch.no_grad():
            serial, serial_routes = self.run_tokens([1, 2, 9, 8, 5, 6], document_starts=(0, 2, 4), return_routes=True)
            batched, batched_routes = self.run_tokens([1, 2, 9, 8, 5, 6], document_starts=(0, 2, 4),
                                                      return_routes=True, batch_documents=True)
            torch.testing.assert_close(serial, batched, rtol=0, atol=0)
            self.assertEqual(serial_routes, batched_routes)
            single = self.run_tokens([1, 2, 3], batch_documents=True)
            torch.testing.assert_close(single, self.run_tokens([1, 2, 3]), rtol=0, atol=0)
        with self.assertRaisesRegex(ValueError, 'batch_documents must be a bool'):
            self.run_tokens([1, 2], batch_documents=1)


if __name__ == '__main__':
    unittest.main()
