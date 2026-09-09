# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# goal_id: EMBER-02
# workstream_id: EMBER-02A
"""Fixed-tensor routing mechanics, not a subscale learning subject."""
import sys
import unittest
from pathlib import Path
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model.ember_v0_routing import select_global, select_local


class CIARoutingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.weight = torch.eye(1024)
        self.keys = torch.zeros(12, 25, 1024)
        self.keys[:, 0, 0] = 1
        self.keys[:, 1, 0] = -1
        self.keys[:, 2, 1] = 1
        self.values = torch.zeros(2304, 1024)
        self.values[:, 0] = 1

    def global_(self, values=None, **kwargs):
        args = dict(position=1024, document_start=0, generation="g1", request="r1")
        args.update(kwargs)
        return select_global(self.values if values is None else values, self.weight, self.keys, **args)

    def local_(self, selection, hidden=None, **kwargs):
        args = dict(position=1024, document_start=0, generation="g1", request="r1", sparse_depth=0)
        args.update(kwargs)
        return select_local(self.values if hidden is None else hidden, self.weight, self.keys, selection, **args)

    def test_global_unchanged_by_current_or_future_epoch(self):
        original = self.global_()
        changed = self.values.clone()
        changed[1024:] *= -1
        altered = self.global_(changed)
        self.assertEqual(original.experts, altered.experts)
        torch.testing.assert_close(original.log_prior, altered.log_prior)
        self.assertEqual(original.history_digest, altered.history_digest)

    def test_visible_history_can_change_selection(self):
        other = self.values.clone()
        other[:1024] *= -1
        self.assertNotEqual(self.global_().experts, self.global_(other).experts)

    def test_no_batch_pooling_interface(self):
        with self.assertRaises(ValueError):
            self.global_(self.values.unsqueeze(0))

    def test_other_request_does_not_change_first_request(self):
        first = self.global_()
        self.global_(-self.values, request="r2")
        again = self.global_()
        self.assertEqual(first.experts, again.experts)
        torch.testing.assert_close(first.log_prior, again.log_prior)

    def test_packed_document_first_epoch_uses_fixed_bos(self):
        first = self.global_(position=1200, document_start=1200)
        other = self.global_(-self.values, position=1200, document_start=1200)
        self.assertEqual(first.experts, (0, 1))
        self.assertEqual(first.experts, other.experts)

    def test_incremental_prefix_matches_full_input(self):
        full = self.global_()
        prefix = self.global_(self.values[:1024])
        self.assertEqual(full.experts, prefix.experts)
        self.assertEqual(full.history_digest, prefix.history_digest)

    def test_local_reads_last_visible_vector_not_segment_average(self):
        selection = self.global_()
        a = self.values.clone()
        b = a.clone()
        b[768:1023] *= -1
        b[1024:] *= -1
        left, right = self.local_(selection, a), self.local_(selection, b)
        self.assertEqual(left.expert, right.expert)
        torch.testing.assert_close(left.logits, right.logits)
        self.assertEqual(left.history_digest, right.history_digest)
        self.assertEqual(left.history_cutoff, 1024)

    def test_mismatched_plan_identity_and_epoch_refused(self):
        selection = self.global_()
        for kw in (dict(request="r2"), dict(generation="g2"), dict(document_start=1), dict(position=2048)):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.local_(selection, **kw)

    def test_invalid_inputs_refused(self):
        for kw in (dict(position=True), dict(document_start=-1), dict(generation=""), dict(position=99999)):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.global_(**kw)
        broken = self.values.clone()
        broken[0, 0] = float("nan")
        with self.assertRaises(ValueError):
            self.global_(broken)

    def test_selection_prior_mutation_refused(self):
        selection = self.global_()
        selection.log_prior[0] = -100
        with self.assertRaisesRegex(ValueError, "prior changed"):
            self.local_(selection)

    def test_expert_list_must_match_prior(self):
        from dataclasses import replace
        selection = replace(self.global_(), experts=(3, 4))
        with self.assertRaisesRegex(ValueError, "expert identities"):
            self.local_(selection)

    def test_changed_keys_refused(self):
        selection = self.global_()
        self.keys[0, 0, 0] = -1
        with self.assertRaisesRegex(ValueError, "keys changed"):
            self.local_(selection)

    def test_incompatible_selector_version_refused(self):
        from dataclasses import replace
        selection = replace(self.global_(), selector_version="different-policy")
        with self.assertRaisesRegex(ValueError, "selector version"):
            self.local_(selection)

    def test_local_last_visible_vector_changes_route(self):
        selection = self.global_()
        changed = self.values.clone()
        changed[1023] = 0
        changed[1023, 1] = 1
        self.assertNotEqual(self.local_(selection).expert, self.local_(selection, changed).expert)

    def test_local_incremental_prefix_matches_full_input(self):
        selection = self.global_()
        a, b = self.local_(selection), self.local_(selection, self.values[:1024])
        self.assertEqual(a.expert, b.expert)
        self.assertEqual(a.history_digest, b.history_digest)

    def test_global_summary_stops_history_gradient(self):
        values = self.values.clone().requires_grad_()
        weight = self.weight.clone().requires_grad_()
        selection = select_global(values, weight, self.keys, position=1024, document_start=0, generation="g", request="r")
        selection.log_prior[0].backward()
        self.assertIsNone(values.grad)
        self.assertIsNotNone(weight.grad)

    def test_unit_task_gate_preserves_forward_and_softmax_gradient(self):
        from ember.model.ember_v0_routing import unit_task_gate
        logits = torch.tensor([0.2, -0.4], requires_grad=True)
        gate = unit_task_gate(logits, 0)
        self.assertEqual(gate.item(), 1.0)
        (3 * gate).backward()
        p = logits.detach().softmax(0)
        torch.testing.assert_close(logits.grad, 3 * torch.stack((p[0] * p[1], -p[0] * p[1])))

    def test_unit_task_gate_rejects_invalid_state(self):
        from ember.model.ember_v0_routing import unit_task_gate
        for values, index in (([0., 1.], True), ([0., 1.], 2), ([float('nan'), 1.], 0)):
            with self.assertRaises(ValueError):
                unit_task_gate(torch.tensor(values), index)

    def test_unit_task_gate_preserves_finite_float64_range(self):
        from ember.model.ember_v0_routing import unit_task_gate
        logits = torch.tensor([1e300, 0.0], dtype=torch.float64, requires_grad=True)
        gate = unit_task_gate(logits, 0)
        self.assertEqual(gate.item(), 1.0)
        gate.backward()
        self.assertTrue(torch.isfinite(logits.grad).all())


if __name__ == "__main__":
    unittest.main()
