"""Issue #2119 rows 5/14: prospective, dispatch-time retention eligibility with a control fallback.

Each test names a requirement of the closing artifact: a rejected treatment leaves the control eligible; a won treatment is
eligible and the control is never added; a moved baseline, an edited rule and selection on the protected set refuse; no published
arm gives no eligible descendant; the runner's caller never says eligible by default. One deliberate red: the master behaviour
(`eligible = launch_succeeded`) marks a treatment that LOST its metric as eligible; the adjudicator does not.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import retention_eligibility as elig  # noqa: E402

START = 'a' * 64
CONTROL_CHILD, TREATMENT_CHILD = 'c' * 64, 'd' * 64


def rule_text(**override):
    rule = {'schema': elig.RULE_SCHEMA, 'frozen_start_manifest_sha256': START, 'control_arm_id': 'control',
            'treatment_arm_id': 'treatment',
            'selection': {'metric': 'heldout_loss', 'direction': 'lower', 'min_delta': 0.01, 'evaluation_set_class': 'developmental'}}
    rule.update(override)
    return json.dumps(rule)


def arm(arm_id, *, published=True, loss=2.0, child=None, parent=START, positions=1000, set_class='developmental'):
    return {'arm_id': arm_id, 'published': published, 'parent_manifest_sha256': parent if published else None,
            'child_manifest_sha256': child, 'metric': {'heldout_loss': loss} if loss is not None else {},
            'measurement_set_class': set_class, 'applied_positions': positions}


class RetentionEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.rule = elig.parse_rule(rule_text())
        self.control = arm('control', loss=2.00, child=CONTROL_CHILD, positions=1000)

    def test_a_rejected_treatment_leaves_the_control_eligible(self):
        treatment = arm('treatment', loss=2.05, child=TREATMENT_CHILD, positions=900)   # worse
        verdict = elig.adjudicate(self.rule, self.control, treatment)
        self.assertEqual((verdict['verdict'], verdict['eligible_arm'], verdict['retained_applied_positions']),
                         (elig.CONTROL_ELIGIBLE, 'control', 1000))

    def test_a_treatment_that_wins_by_the_frozen_margin_is_eligible_and_the_control_is_not_added(self):
        treatment = arm('treatment', loss=1.90, child=TREATMENT_CHILD, positions=900)
        verdict = elig.adjudicate(self.rule, self.control, treatment)
        self.assertEqual((verdict['verdict'], verdict['eligible_arm'], verdict['retained_applied_positions']),
                         (elig.TREATMENT_ELIGIBLE, 'treatment', 900))   # 900, never 1900

    def test_a_win_smaller_than_min_delta_is_rejected(self):
        treatment = arm('treatment', loss=1.995, child=TREATMENT_CHILD)
        self.assertEqual(elig.adjudicate(self.rule, self.control, treatment)['verdict'], elig.CONTROL_ELIGIBLE)

    def test_a_treatment_that_did_not_publish_leaves_the_control_eligible(self):
        verdict = elig.adjudicate(self.rule, self.control, arm('treatment', published=False, loss=None))
        self.assertEqual(verdict['verdict'], elig.CONTROL_ELIGIBLE)

    def test_no_arm_published_gives_none_eligible_and_zero_retained(self):
        verdict = elig.adjudicate(self.rule, arm('control', published=False, loss=None), arm('treatment', published=False, loss=None))
        self.assertEqual((verdict['verdict'], verdict['eligible_arm'], verdict['retained_applied_positions']),
                         (elig.NONE_ELIGIBLE, None, 0))

    def test_a_moved_baseline_refuses(self):
        treatment = arm('treatment', loss=1.90, child=TREATMENT_CHILD, parent='b' * 64)
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'baseline moved'):
            elig.adjudicate(self.rule, self.control, treatment)

    def test_a_rule_edited_after_launch_refuses(self):
        edited = elig.parse_rule(rule_text(selection={'metric': 'heldout_loss', 'direction': 'lower', 'min_delta': 0.0,
                                                      'evaluation_set_class': 'developmental'}))
        self.assertNotEqual(edited['rule_sha256'], self.rule['rule_sha256'])
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'edited after launch'):
            elig.adjudicate(edited, self.control, arm('treatment', loss=1.9, child=TREATMENT_CHILD),
                            expected_rule_sha256=self.rule['rule_sha256'])

    def test_selection_on_protected_evaluation_data_refuses(self):
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'developmental'):
            elig.parse_rule(rule_text(selection={'metric': 'heldout_loss', 'direction': 'lower', 'min_delta': 0.01,
                                                 'evaluation_set_class': 'protected'}))
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'protected set'):
            elig.adjudicate(self.rule, self.control, arm('treatment', loss=1.9, child=TREATMENT_CHILD, set_class='protected'))

    def test_identical_arms_and_a_missing_metric_refuse(self):
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'no experiment happened'):
            elig.adjudicate(self.rule, self.control, arm('treatment', loss=1.9, child=CONTROL_CHILD))
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'no finite'):
            elig.adjudicate(self.rule, self.control, arm('treatment', loss=None, child=TREATMENT_CHILD))

    def test_the_rule_must_carry_every_part_of_the_frozen_record(self):
        full = json.loads(rule_text())
        for missing in ('frozen_start_manifest_sha256', 'control_arm_id', 'treatment_arm_id', 'selection'):
            partial = {k: v for k, v in full.items() if k != missing}
            with self.assertRaises(elig.EligibilityRefusal, msg=missing):
                elig.parse_rule(json.dumps(partial))
        with self.assertRaises(elig.EligibilityRefusal):
            elig.parse_rule(rule_text(control_arm_id='treatment'))   # arms must be distinct

    def test_the_identity_rule_must_start_where_the_identity_starts(self):
        identity = {'training_experiment_continuation_rule': rule_text(), 'parent_checkpoint': {'root': 'r', 'manifest_sha256': START}}
        self.assertEqual(elig.validate_identity_rule(identity)['frozen_start_manifest_sha256'], START)
        identity['parent_checkpoint'] = {'root': 'r', 'manifest_sha256': 'b' * 64}
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'frozen start differs'):
            elig.validate_identity_rule(identity)
        with self.assertRaises(elig.EligibilityRefusal):
            elig.validate_identity_rule({'training_experiment_continuation_rule': 'free text rule', 'parent_checkpoint': {'manifest_sha256': START}})


class RunnerCallerTests(unittest.TestCase):
    """The runner's caller: eligibility is never True by default."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.custody = Path(self._tmp.name)
        self.identity = {'training_experiment_continuation_rule': rule_text(),
                         'parent_checkpoint': {'root': 'r', 'manifest_sha256': START}}
        self.rule = elig.parse_rule(rule_text())

    def _arms(self, treatment_loss, **extra):
        payload = {'rule_sha256': self.rule['rule_sha256'], 'control': arm('control', loss=2.0, child=CONTROL_CHILD),
                   'treatment': arm('treatment', loss=treatment_loss, child=TREATMENT_CHILD)}
        payload.update(extra)
        (self.custody / elig.ARM_RESULTS_FILENAME).write_text(json.dumps(payload), encoding='utf-8')

    def call(self, *, succeeded=True):
        return elig.adjudicated_eligible_descendant(self.identity, run_succeeded=succeeded, custody=self.custody)

    def test_a_succeeded_run_with_no_arm_results_is_not_eligible(self):
        self.assertFalse(self.call())

    def test_a_failed_run_is_not_eligible_even_with_a_winning_record(self):
        self._arms(1.5)
        self.assertFalse(self.call(succeeded=False))

    def test_a_winning_treatment_and_a_rejected_one_are_both_eligible_descendants_of_their_own_arm(self):
        self._arms(1.5)
        self.assertTrue(self.call())
        self.assertEqual(json.loads((self.custody / 'eligibility-verdict.json').read_text())['verdict'], elig.TREATMENT_ELIGIBLE)
        self._arms(2.5)
        self.assertTrue(self.call())   # the control is the eligible fallback
        self.assertEqual(json.loads((self.custody / 'eligibility-verdict.json').read_text())['verdict'], elig.CONTROL_ELIGIBLE)

    def test_a_refusal_is_recorded_and_is_not_eligible(self):
        self._arms(1.5, rule_sha256='0' * 64)   # the arm producer recorded a different rule digest at launch
        self.assertFalse(self.call())
        self.assertIn('edited after launch', json.loads((self.custody / elig.REFUSAL_FILENAME).read_text())['refused'])

    def test_deliberate_red_launch_success_as_eligibility_marks_a_losing_treatment_eligible(self):
        def master_behaviour(identity, *, run_succeeded, custody):   # eligibility = the run's own launch-success flag
            return run_succeeded

        self._arms(2.5)   # the treatment LOST its metric; the control is the right eligible arm, but the treatment is rejected
        losing = json.loads((self.custody / elig.ARM_RESULTS_FILENAME).read_text())
        verdict = elig.adjudicate(self.rule, losing['control'], losing['treatment'])
        self.assertNotEqual(verdict['eligible_arm'], 'treatment')                       # the adjudicator rejects the treatment
        self.assertTrue(master_behaviour(self.identity, run_succeeded=True, custody=self.custody))   # the master rule says "eligible"
        self.assertEqual(verdict['retained_applied_positions'], 1000)                   # and counts the control's positions only


class RunnerWiringTests(unittest.TestCase):
    """The runner imports and uses the adjudicator at both seams (a source-level binding, so a revert is a red)."""

    def test_the_runner_validates_the_rule_at_dispatch_and_calls_the_adjudicator_for_the_outcome(self):
        source = (MODULE_DIR / 'cia_step_runner.py').read_text(encoding='utf-8')
        self.assertIn('load_eligibility_module().validate_identity_rule(identity)', source)
        self.assertIn('adjudicated_eligible_descendant(identity, run_succeeded=succeeded, custody=custody)', source)
        self.assertNotIn('eligible_descendant_published=succeeded', source)


if __name__ == '__main__':
    unittest.main()
