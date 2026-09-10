# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounds and refusals of revision CIA3-R1-N61-numerical-split-v1, on fixed tensors.

These are mechanics tests. They establish that each prospectively fixed bound actually refuses when
it is crossed, and that the comparison cannot silently pass on absent evidence. They are not a
model subject, and they establish nothing about either backend: the fixtures here are small fixed
tensors, never a learned network.

Every bound below carries a deliberate red -- a case constructed to fail it -- because a bound that
has only ever been observed passing is indistinguishable from a bound that cannot fail.
"""
from pathlib import Path
import sys
import unittest

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ember.governance.scripts.cia_numerical_split import (
    DIFFERING_CUDA_MARGIN_MAX, LOCAL_ROUTES, NumericalSplitRefusal,
    SELECTOR_SCORE_ABSOLUTE_MAX, SHARED_VECTOR_RELATIVE_L2_MAX, compare_global_selections,
    compare_local_routes, cross_evaluate_selector, digest_of, local_route_report,
    refuse_if_inadmissible, route_plan)
from ember.model.ember_v0_decoder import CIADecoder
from ember.model.ember_v0_routing import GlobalObservation, LocalObservation


def local(key, candidates=(0, 1), chosen=0, margin=1.0, summary=None):
    document, layer, segment_start = key
    vector = torch.ones(8) if summary is None else summary
    return LocalObservation(document=document, layer=layer, segment_start=segment_start,
                            candidates=candidates, chosen=chosen,
                            logits=(margin, 0.0), margin=margin, summary=vector,
                            keys_slice=torch.zeros(2, 8), prior_slice=torch.zeros(2),
                            history_digest=f"digest-{segment_start}")


def full_set(overrides=None):
    """One observation per (layer, segment) the fixed fixture produces: 12 depths x 5 segments.

    Keyed by the route triple rather than by keyword, because the route triple IS the identity the
    comparison indexes on and a test that could not name it would be testing a different shape.
    """
    overrides = overrides or {}
    observations = []
    for layer in range(1, 24, 2):
        for segment_start in range(0, 1280, 256):
            key = (0, layer, segment_start)
            observations.append(local(key, **overrides.get(key, {})))
    return observations


class ComparisonCoverage(unittest.TestCase):
    def test_agreeing_backends_report_every_route_not_only_the_differing_ones(self):
        comparisons = compare_local_routes(full_set(), full_set())
        self.assertEqual(len(comparisons), LOCAL_ROUTES)
        report = local_route_report(comparisons)
        self.assertEqual(report["local_routes"], LOCAL_ROUTES)
        self.assertEqual(report["differing_routes"], 0)
        self.assertEqual(report["inadmissible_routes"], 0)
        self.assertEqual(len(report["routes"]), LOCAL_ROUTES)
        self.assertIsNone(report["max_differing_cuda_margin"])
        refuse_if_inadmissible(comparisons)

    def test_short_measurement_is_refused_rather_than_reported_as_agreement(self):
        # A run that observed six routes and found no difference must not read like a run that
        # observed sixty. Coverage is evidence, so its absence is a refusal.
        with self.assertRaisesRegex(NumericalSplitRefusal, "expected 60 local selections"):
            compare_local_routes(full_set()[:6], full_set()[:6])

    def test_non_corresponding_routes_are_refused(self):
        cuda = full_set()
        cuda[0] = local((0, 1, 9999))
        with self.assertRaisesRegex(NumericalSplitRefusal, "do not correspond"):
            compare_local_routes(full_set(), cuda)

    def test_duplicate_observation_is_refused(self):
        duplicated = full_set()
        duplicated[1] = duplicated[0]
        with self.assertRaisesRegex(NumericalSplitRefusal, "duplicate"):
            compare_local_routes(duplicated, full_set())


class DifferingSelectionBound(unittest.TestCase):
    def test_an_exact_tie_is_admissible_and_names_the_lower_candidate(self):
        # Exact zero margins occur on the real fixed fixture, measured on the full CPU population.
        # A tie resolves by argmax over ID-sorted candidates, so zero means the lower ID won, and
        # it is the closest a decision can be -- which is exactly where the bound must not refuse.
        key = (0, 1, 0)
        cpu = full_set({key: {"chosen": 0, "margin": 0.0}})
        cuda = full_set({key: {"chosen": 1, "margin": -0.0000031}})
        row = next(item for item in compare_local_routes(cpu, cuda) if item.key == key)
        self.assertTrue(row.differs)
        self.assertTrue(row.admissible)
        self.assertEqual(row.cpu_margin, 0.0)

    def test_near_tie_differing_selection_is_admissible(self):
        key = (0, 21, 768)
        cpu = full_set({key: {"chosen": 0, "margin": 0.0424120426}})
        cuda = full_set({key: {"chosen": 1, "margin": -0.000027179718}})
        comparisons = compare_local_routes(cpu, cuda)
        row = next(item for item in comparisons if item.key == key)
        self.assertTrue(row.differs)
        self.assertTrue(row.admissible)
        # The CPU margin is reported and never gates: the CUDA selection is the one in question.
        self.assertGreater(abs(row.cpu_margin), DIFFERING_CUDA_MARGIN_MAX)
        report = local_route_report(comparisons)
        self.assertEqual(report["differing_routes"], 1)
        refuse_if_inadmissible(comparisons)

    def test_differing_selection_outside_the_cuda_margin_band_is_refused(self):
        key = (0, 21, 768)
        cpu = full_set({key: {"chosen": 0, "margin": 0.5}})
        cuda = full_set({key: {"chosen": 1, "margin": -0.5}})
        comparisons = compare_local_routes(cpu, cuda)
        row = next(item for item in comparisons if item.key == key)
        self.assertFalse(row.admissible)
        with self.assertRaisesRegex(NumericalSplitRefusal, "candidate CUDA margin"):
            refuse_if_inadmissible(comparisons)

    def test_agreeing_selection_is_never_gated_by_the_margin_band(self):
        # The band admits a DIFFERING winner. A confidently agreeing route is not a near-tie and
        # must not be measured against it.
        key = (0, 21, 768)
        wide = full_set({key: {"chosen": 0, "margin": 12.0}})
        refuse_if_inadmissible(compare_local_routes(wide, wide))


class SharedVectorBound(unittest.TestCase):
    def _pair(self, scale):
        key = (0, 3, 512)
        base = torch.ones(8)
        moved = base.clone()
        moved[0] += scale * float(base.norm())
        return key, full_set({key: {"summary": base}}), full_set({key: {"summary": moved}})

    def test_upstream_divergence_inside_the_bound_is_admissible(self):
        key, cpu, cuda = self._pair(SHARED_VECTOR_RELATIVE_L2_MAX / 2)
        row = next(item for item in compare_local_routes(cpu, cuda) if item.key == key)
        self.assertLess(row.shared_vector_relative_l2, SHARED_VECTOR_RELATIVE_L2_MAX)
        self.assertTrue(row.admissible)

    def test_upstream_divergence_beyond_the_bound_is_refused_even_when_winners_agree(self):
        # This is the case the previous revision could not express: both backends chose the same
        # expert, and the activations they chose it from had already diverged.
        key, cpu, cuda = self._pair(SHARED_VECTOR_RELATIVE_L2_MAX * 2)
        comparisons = compare_local_routes(cpu, cuda)
        row = next(item for item in comparisons if item.key == key)
        self.assertEqual(row.cpu_chosen, row.cuda_chosen)
        self.assertFalse(row.admissible)
        with self.assertRaisesRegex(NumericalSplitRefusal, "shared-vector relative L2"):
            refuse_if_inadmissible(comparisons)

    def test_nonfinite_shared_vector_is_refused_not_skipped(self):
        key = (0, 3, 512)
        broken = torch.ones(8)
        broken[0] = float("nan")
        with self.assertRaisesRegex(NumericalSplitRefusal, "not finite"):
            compare_local_routes(full_set(), full_set({key: {"summary": broken}}))

    def test_one_sided_empty_summary_is_refused_rather_than_reported_as_zero_delta(self):
        """cpu has no history to summarize and cuda does: a real disagreement, still refused.

        The relative delta is undefined here, so the previous revision refused on the undefined
        division alone. It still refuses, but now for the reason that is actually wrong: the two
        backends disagree about what an absent history produces. Reporting a relative delta of
        0.0 remains forbidden, which is the property this test has always been about.
        """
        key = (0, 3, 512)
        comparisons = compare_local_routes(full_set({key: {"summary": torch.zeros(8)}}), full_set())
        row = next(item for item in comparisons if item.key == key)
        self.assertIsNone(row.shared_vector_relative_l2, 'an undefined ratio is never a number')
        self.assertGreater(row.shared_vector_absolute_l2, 0)
        self.assertFalse(row.admissible)
        with self.assertRaisesRegex(NumericalSplitRefusal, "disagree about an absent history"):
            refuse_if_inadmissible(comparisons)

    def test_the_defined_empty_summary_on_both_backends_is_measured_not_refused(self):
        """The fixture's own first segments, which no run could previously get past.

        `select_local` publishes a zero vector at a document's first segment, where there is no
        preceding shared-path vector. That is 12 of the fixed fixture's 60 routes -- one per
        routing layer at segment 0 -- so refusing every zero reference made a fifth of the
        comparison permanently uncomputable and the gate unpassable on any inputs.

        Both backends are obliged to produce the SAME empty summary, so the bound here is absolute
        equality, which is strictly tighter than the relative bound it replaces. The relative delta
        is published as null rather than as a number nobody computed, and the report says how many
        routes that covers so its maximum cannot be misread as covering all sixty.
        """
        empty = {key: {"summary": torch.zeros(8)}
                 for key in ((0, layer, 0) for layer in range(1, 24, 2))}
        comparisons = compare_local_routes(full_set(empty), full_set(empty))
        refuse_if_inadmissible(comparisons)
        undefined = [row for row in comparisons if row.shared_vector_relative_l2 is None]
        self.assertEqual(len(undefined), 12)
        self.assertEqual({row.key[2] for row in undefined}, {0})
        for row in undefined:
            self.assertEqual(row.shared_vector_absolute_l2, 0.0)
            self.assertTrue(row.admissible)
        report = local_route_report(comparisons)
        self.assertEqual(report["undefined_relative_routes"], 12)
        self.assertEqual(report["max_zero_reference_absolute_l2"], 0.0)
        self.assertEqual(report["local_routes"], 60)
        # The maximum is taken over the 48 routes that HAVE a defined ratio, never over a set
        # silently padded with zeros for the twelve that do not.
        self.assertIsNotNone(report["max_shared_vector_relative_l2"])
        self.assertEqual(report["bounds"]["zero_reference_absolute_l2_max"], 0.0)


class ContextAndCandidateRefusals(unittest.TestCase):
    def test_candidate_pair_mismatch_is_a_failure_not_a_near_tie(self):
        key = (0, 5, 256)
        with self.assertRaisesRegex(NumericalSplitRefusal, "candidate pair mismatch"):
            compare_local_routes(full_set(), full_set({key: {"candidates": (2, 7)}}))

    def test_global_expert_pair_difference_is_a_failure(self):
        cpu = [GlobalObservation(0, 0, (0, 1), torch.zeros(25), "h", "k", "p", "cpu")]
        cuda = [GlobalObservation(0, 0, (0, 8), torch.zeros(25), "h", "k", "p", "cuda")]
        with self.assertRaisesRegex(NumericalSplitRefusal, "global expert pair differs"):
            compare_global_selections(cpu, cuda)

    def test_global_comparison_reports_the_prior_delta_for_agreeing_pairs(self):
        prior = torch.zeros(25)
        moved = prior.clone()
        moved[3] = 0.25
        rows = compare_global_selections(
            [GlobalObservation(0, 0, (0, 1), prior, "h", "k", "p", "cpu")],
            [GlobalObservation(0, 0, (0, 1), moved, "h", "k", "p", "cuda")])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["max_absolute_prior_delta"], 0.25, places=7)

    def test_missing_global_observation_is_refused(self):
        with self.assertRaisesRegex(NumericalSplitRefusal, "do not correspond"):
            compare_global_selections([], [])


class SelectorCrossEvaluation(unittest.TestCase):
    @staticmethod
    def scorer(summary, weight, keys, prior):
        return (keys.to(torch.float64) @ (weight.to(torch.float64) @ summary.to(torch.float64))
                + prior.to(torch.float64)).to(torch.float32)

    def observations(self):
        torch.manual_seed(2163)
        rows = []
        for index, key in enumerate(((0, 1, 0), (0, 1, 256), (0, 3, 0))):
            rows.append(LocalObservation(
                document=key[0], layer=key[1], segment_start=key[2], candidates=(0, 1),
                chosen=index % 2, logits=(0.0, 0.0), margin=0.0, summary=torch.randn(4),
                keys_slice=torch.randn(2, 4), prior_slice=torch.zeros(2),
                history_digest=f"d{index}"))
        return rows

    def test_identical_inputs_and_identical_parameters_agree_within_the_bound(self):
        weight = torch.randn(4, 4)
        result = cross_evaluate_selector(self.observations(),
                                         {"cpu": weight, "cpu-replica": weight.clone()},
                                         self.scorer)
        self.assertEqual(result["backends"], ["cpu", "cpu-replica"])
        self.assertLessEqual(result["max_absolute_selector_score_error"],
                             SELECTOR_SCORE_ABSOLUTE_MAX)
        self.assertEqual(len(result["evaluations"]), 3)
        self.assertEqual(result["parameter_sha256"], digest_of(weight))

    def test_differing_parameters_are_refused_before_any_score_is_compared(self):
        # A score difference measured on differing parameters says nothing about the selector,
        # which is the only thing this leg exists to isolate.
        weight = torch.randn(4, 4)
        other = weight.clone()
        other[0, 0] += 1.0
        with self.assertRaisesRegex(NumericalSplitRefusal, "parameter identities differ"):
            cross_evaluate_selector(self.observations(), {"cpu": weight, "cuda": other},
                                    self.scorer)

    def test_score_error_beyond_the_bound_is_refused(self):
        weight = torch.randn(4, 4)
        calls = {"n": 0}

        def drifting(summary, projection, keys, prior):
            calls["n"] += 1
            value = self.scorer(summary, projection, keys, prior)
            return value + (SELECTOR_SCORE_ABSOLUTE_MAX * 8 if calls["n"] % 2 == 0 else 0.0)

        with self.assertRaisesRegex(NumericalSplitRefusal, "selector-score error"):
            cross_evaluate_selector(self.observations(),
                                    {"cpu": weight, "cpu-replica": weight.clone()}, drifting)

    def test_disagreeing_winner_on_identical_inputs_is_refused(self):
        weight = torch.randn(4, 4)
        calls = {"n": 0}

        def flipping(summary, projection, keys, prior):
            calls["n"] += 1
            value = self.scorer(summary, projection, keys, prior)
            return value.flip(0) if calls["n"] % 2 == 0 else value

        with self.assertRaisesRegex(NumericalSplitRefusal, "different winners"):
            cross_evaluate_selector(self.observations(),
                                    {"cpu": weight, "cpu-replica": weight.clone()}, flipping)

    def test_one_backend_is_not_a_cross_evaluation(self):
        with self.assertRaisesRegex(NumericalSplitRefusal, "at least two backends"):
            cross_evaluate_selector(self.observations(), {"cpu": torch.randn(4, 4)}, self.scorer)


class FixedRoutePlan(unittest.TestCase):
    def test_a_complete_plan_is_built_from_a_complete_measurement(self):
        plan = route_plan(full_set())
        self.assertEqual(len(plan), LOCAL_ROUTES)
        self.assertEqual(plan[(0, 21, 768)], ((0, 1), 0))

    def test_an_incomplete_plan_is_refused(self):
        with self.assertRaisesRegex(NumericalSplitRefusal, "complete plan"):
            route_plan(full_set()[:10])

    def test_planned_winner_is_consumed_when_the_candidate_pair_matches(self):
        self.assertEqual(CIADecoder._planned_expert({(0, 1, 0): ((3, 9), 9)}, (0, 1, 0), (3, 9)), 9)

    def test_candidate_pair_drift_is_refused_rather_than_substituted(self):
        # If the two executions did not consider the same experts, a matching winner would be a
        # coincidence and a differing one would be blamed on the selector; in both cases the
        # divergence is already upstream.
        with self.assertRaisesRegex(ValueError, "candidate pair drift"):
            CIADecoder._planned_expert({(0, 1, 0): ((3, 9), 9)}, (0, 1, 0), (3, 8))

    def test_missing_plan_entry_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no entry"):
            CIADecoder._planned_expert({(0, 1, 0): ((3, 9), 9)}, (0, 1, 256), (3, 9))

    def test_planned_expert_outside_the_candidate_pair_is_refused(self):
        with self.assertRaisesRegex(ValueError, "is not a candidate"):
            CIADecoder._planned_expert({(0, 1, 0): ((3, 9), 4)}, (0, 1, 0), (3, 9))


if __name__ == "__main__":
    unittest.main()
