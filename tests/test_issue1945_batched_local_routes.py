# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue 1945: the batched local router (one launch set per sparse layer) against the per-chunk reference.

CPU fixtures only. The batched router is a DECLARED numerical treatment (one row-batched projection GEMM instead of
one vector GEMM per chunk): winner identity, epoch/pair order, first-slot ties, the zero-summary/no-history-gradient
rule for a chunk starting at 0, gradients through hidden[offset+start-1] for later chunks, a frozen owner, and the
all-finite predicate are asserted exactly; logits agree with the per-chunk arithmetic to fp32 accumulation-order
tolerance. No throughput, learning or routing-quality claim is made here.
"""
import math
import unittest

import torch
import torch.nn.functional as F

from ember.model.ember_v0_residency import (DeviceRouteGeometry, DeviceRouteIndex, resident_global_routes,
                                            resident_local_routes, route_index)
from ember.model.ember_v0_routing import _local_scores, _local_scores_rows, _unit_task_gate_rows


def per_chunk_reference(hidden, local_query, keys, sparse_depth, geometry, priors, candidates):
    """The retired per-chunk loop, restated independently of the module under test."""
    rows, ids = [], []
    for document, offset, start, size, epoch in geometry.chunks:
        summary = hidden[offset + start - 1].float() if start else torch.zeros(1024, device=hidden.device)
        pair = candidates[epoch]
        rows.append(_local_scores(summary, local_query, keys[sparse_depth].index_select(0, pair),
                                  priors[epoch].index_select(0, pair)))
        ids.append(pair)
    logits = torch.stack(rows)
    slots = torch.argmax(logits, dim=1)
    winners = torch.stack(ids).gather(1, slots[:, None])[:, 0]
    return winners, logits, _unit_task_gate_rows(logits, slots)


def fixture(lengths, seed, scale=.02):
    generator = torch.Generator().manual_seed(seed)
    embedded = torch.randn(sum(lengths), 1024, generator=generator) * scale
    hidden = (torch.randn(sum(lengths), 1024, generator=generator) * scale).requires_grad_()
    query = torch.randn(1024, 1024, generator=generator) * scale
    local = (torch.randn(1024, 1024, generator=generator) * scale).requires_grad_()
    keys = (torch.randn(12, 25, 1024, generator=generator) * scale).requires_grad_()
    geometry, priors, ranked, candidates, valid = resident_global_routes(embedded, lengths, query, keys)
    assert bool(valid)
    return hidden, local, keys, geometry, priors, candidates


class BatchedLocalRoutesTests(unittest.TestCase):
    def test_rows_helper_matches_scalar_helper_per_row(self):
        torch.manual_seed(7)
        summaries = torch.randn(5, 1024) * .02
        weight = torch.randn(1024, 1024) * .02
        keys = torch.randn(5, 2, 1024) * .02
        prior = torch.randn(5, 2)
        batched = _local_scores_rows(summaries, weight, keys, prior)
        self.assertEqual(tuple(batched.shape), (5, 2))
        for row in range(5):
            torch.testing.assert_close(batched[row], _local_scores(summaries[row], weight, keys[row], prior[row]),
                                       rtol=1e-5, atol=1e-5)
        with self.assertRaises(ValueError):
            _local_scores_rows(summaries, weight, keys[:, :1], prior)
        with self.assertRaises(ValueError):
            _local_scores_rows(summaries[0], weight, keys, prior)

    def test_batched_equals_per_chunk_reference_on_ragged_multi_epoch_fixture(self):
        hidden, local, keys, geometry, priors, candidates = fixture((1031, 257, 2048), 1945)
        winners, logits, gates, valid = resident_local_routes(hidden, local, keys, 3, geometry, priors, candidates)
        self.assertTrue(bool(valid))
        ref_winners, ref_logits, ref_gates = per_chunk_reference(hidden, local, keys, 3, geometry, priors, candidates)
        self.assertEqual(len(geometry.chunks), 15)  # 5 + 2 + 8 chunks, three documents, four epochs
        self.assertEqual(winners.tolist(), ref_winners.tolist())
        torch.testing.assert_close(logits, ref_logits, rtol=1e-5, atol=1e-5)
        torch.testing.assert_close(gates, ref_gates, rtol=1e-5, atol=1e-5)
        # Every logit row belongs to its chunk's epoch pair, in geometry order.
        for row, (_, _, _, _, epoch) in enumerate(geometry.chunks):
            self.assertIn(int(winners[row]), candidates[epoch].tolist())
        # Gates are unit forward values with a softmax derivative (not detached).
        torch.testing.assert_close(gates.detach(), torch.ones_like(gates), rtol=0, atol=0)
        self.assertTrue(gates.requires_grad)

    def test_gradients_match_reference_and_first_chunks_carry_no_history_gradient(self):
        hidden, local, keys, geometry, priors, candidates = fixture((1031, 257), 11)
        weights = torch.arange(1, len(geometry.chunks) + 1, dtype=torch.float32)
        winners, logits, gates, valid = resident_local_routes(hidden, local, keys, 5, geometry, priors, candidates)
        objective = (logits * torch.tensor([[1.0, -1.0]])).sum() + (gates * weights).sum()
        # priors carry the global-route graph shared by both paths: retain it for the reference backward.
        actual = torch.autograd.grad(objective, (hidden, local, keys), retain_graph=True)
        _, ref_logits, ref_gates = per_chunk_reference(hidden, local, keys, 5, geometry, priors, candidates)
        reference = torch.autograd.grad((ref_logits * torch.tensor([[1.0, -1.0]])).sum() + (ref_gates * weights).sum(),
                                        (hidden, local, keys))
        for a, r in zip(actual, reference):
            torch.testing.assert_close(a, r, rtol=1e-4, atol=1e-5)
        hidden_grad = actual[0]
        touched = {int(offset + start - 1) for _, offset, start, _, _ in geometry.chunks if start}
        for row in range(hidden_grad.shape[0]):
            if row in touched:
                self.assertGreater(float(hidden_grad[row].abs().sum()), 0.0, row)
            else:
                self.assertEqual(float(hidden_grad[row].abs().sum()), 0.0, row)
        # Chunks starting at 0 (one per document here) score a zero summary: history row 'offset-1' is untouched.
        first_rows = {int(offset + start - 1) for _, offset, start, _, _ in geometry.chunks if not start}
        self.assertTrue(first_rows.isdisjoint(touched))

    def test_frozen_owner_receives_no_gradient_and_hidden_still_does(self):
        hidden, local, keys, geometry, priors, candidates = fixture((600,), 3)
        frozen = local.detach().clone()
        self.assertFalse(frozen.requires_grad)
        winners, logits, gates, valid = resident_local_routes(hidden, frozen, keys, 1, geometry, priors, candidates)
        self.assertTrue(bool(valid))
        grads = torch.autograd.grad(logits.sum(), (hidden, keys))
        self.assertGreater(float(grads[0].abs().sum()), 0.0)
        self.assertGreater(float(grads[1].abs().sum()), 0.0)

    def test_near_tie_argmax_takes_the_first_slot_and_order_is_exact(self):
        # Zero hidden and zero keys make every chunk score exactly log_prior; equal priors are an exact tie.
        hidden = torch.zeros(1030, 1024)
        query = torch.zeros(1024, 1024)
        keys = torch.zeros(12, 25, 1024)
        geometry, priors, ranked, candidates, valid = resident_global_routes(hidden, (1030,), query, keys)
        self.assertTrue(bool(valid))
        winners, logits, gates, valid = resident_local_routes(hidden, query, keys, 0, geometry, priors, candidates)
        self.assertTrue(bool(valid))
        self.assertEqual(len(geometry.chunks), 5)
        self.assertEqual(winners.tolist(), [int(candidates[epoch][0]) for *_, epoch in geometry.chunks])
        torch.testing.assert_close(logits[:, 0], logits[:, 1], rtol=0, atol=0)
        # A near tie decided by the prior alone: the second slot wins only when its prior is strictly larger.
        biased = priors.clone()
        biased[:, candidates[0][1]] += 1e-3
        winners_b, logits_b, _, _ = resident_local_routes(hidden, query, keys, 0, geometry, biased, candidates)
        self.assertEqual(winners_b.tolist(), [int(candidates[epoch][1]) for *_, epoch in geometry.chunks])

    def test_zero_summary_first_chunk_matches_explicit_zero_and_nonfinite_hidden_trips_the_flag(self):
        hidden, local, keys, geometry, priors, candidates = fixture((300,), 21)
        winners, logits, gates, valid = resident_local_routes(hidden, local, keys, 2, geometry, priors, candidates)
        self.assertTrue(bool(valid))
        pair = candidates[0]
        expected0 = _local_scores(torch.zeros(1024), local, keys[2].index_select(0, pair), priors[0].index_select(0, pair))
        torch.testing.assert_close(logits[0], expected0, rtol=1e-5, atol=1e-5)
        # The only row a chunk starting at 0 could have read is offset-1 (== -1 here): poisoning the last row of hidden
        # must NOT change chunk 0's logits, because the zero summary never indexes it.
        poisoned = hidden.detach().clone()
        poisoned[-1] = 1e3
        _, logits_p, _, valid_p = resident_local_routes(poisoned, local, keys, 2, geometry, priors, candidates)
        self.assertTrue(bool(valid_p))
        torch.testing.assert_close(logits_p[0], logits[0], rtol=0, atol=0)
        nan_hidden = hidden.detach().clone()
        nan_hidden[255, 0] = float('nan')
        *_, valid_nan = resident_local_routes(nan_hidden, local, keys, 2, geometry, priors, candidates)
        self.assertFalse(bool(valid_nan))
        nan_keys = keys.detach().clone()
        nan_keys[2, int(pair[0]), 5] = float('inf')
        *_, valid_keys = resident_local_routes(hidden, local, nan_keys, 2, geometry, priors, candidates)
        self.assertFalse(bool(valid_keys))

    def test_prebound_index_is_reused_and_constructs_no_host_tensors_while_recorded(self):
        # The captured caller binds the index once outside capture; inside the recorded forward the router must not
        # build any tensor from Python data (that is a blocking host-to-device copy under CUDA graph capture).
        hidden, local, keys, geometry, priors, candidates = fixture((1031, 257), 17)
        lazy = resident_local_routes(hidden, local, keys, 4, geometry, priors, candidates)
        bound = route_index(geometry, hidden.device)
        self.assertIsInstance(bound, DeviceRouteIndex)
        self.assertEqual(bound.rows.tolist(), [offset + start - 1 if start else 0 for _, offset, start, _, _ in geometry.chunks])
        self.assertEqual(bound.started.tolist(), [bool(start) for _, _, start, _, _ in geometry.chunks])
        self.assertEqual(bound.epochs.tolist(), [epoch for *_, epoch in geometry.chunks])
        constructors = ('tensor', 'as_tensor', 'from_numpy', 'zeros', 'ones', 'empty', 'arange', 'full')
        originals = {name: getattr(torch, name) for name in constructors}

        def refuse(name):
            def _refuse(*args, **kwargs):
                raise AssertionError(f'torch.{name} constructed a tensor inside the bound local route')
            return _refuse
        for name in constructors:
            setattr(torch, name, refuse(name))
        try:
            for _ in range(2):  # the same bound index serves every replay
                recorded = resident_local_routes(hidden, local, keys, 4, geometry, priors, candidates, index=bound)
        finally:
            for name, fn in originals.items():
                setattr(torch, name, fn)
        for a, b in zip(recorded[:3], lazy[:3]):
            torch.testing.assert_close(a, b, rtol=0, atol=0)
        self.assertEqual(bool(recorded[3]), bool(lazy[3]))
        # A bound index from a different geometry, device-mismatched dtype, or wrong type is refused exactly.
        other = route_index(fixture((600,), 17)[3], hidden.device)
        with self.assertRaises(ValueError):
            resident_local_routes(hidden, local, keys, 4, geometry, priors, candidates, index=other)
        self.assertEqual((bound.zero.dtype, tuple(bound.zero.shape), float(bound.zero)), (torch.float32, (), 0.0))
        wrong_dtype = DeviceRouteIndex(bound.chunks, bound.rows.int(), bound.started, bound.epochs, bound.zero)
        with self.assertRaises(ValueError):
            resident_local_routes(hidden, local, keys, 4, geometry, priors, candidates, index=wrong_dtype)
        with self.assertRaises(ValueError):
            resident_local_routes(hidden, local, keys, 4, geometry, priors, candidates, index=(bound.rows, bound.started, bound.epochs))
        with self.assertRaises(ValueError):
            route_index(DeviceRouteGeometry((), (300,)), hidden.device)

    def test_geometry_validation_unchanged(self):
        hidden, local, keys, geometry, priors, candidates = fixture((300,), 5)
        with self.assertRaises(ValueError):
            resident_local_routes(hidden, local, keys, '2', geometry, priors, candidates)
        with self.assertRaises(ValueError):
            resident_local_routes(hidden[:-1], local, keys, 2, geometry, priors, candidates)
        # An empty geometry is refused by both the per-chunk reference (empty stack) and the batched path.
        with self.assertRaises((ValueError, RuntimeError)):
            resident_local_routes(hidden, local, keys, 2, DeviceRouteGeometry((), (300,)), priors, candidates)


if __name__ == '__main__':
    unittest.main()
