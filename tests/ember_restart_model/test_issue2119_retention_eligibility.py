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

import contextlib
import copy
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock
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
        # ruling 63035: launch() no longer records the outcome; the scoring chain's finalize_retention_outcome is the only writer.
        self.assertIn('record_retention_outcome(identity, succeeded=marker[\'succeeded\'], custody=custody, parent=parent', source)
        self.assertIn("'status': 'run_complete_not_yet_scored'", source)
        self.assertEqual(source.count('= record_retention_outcome(identity'), 1)   # one call site (finalize): no second writer in launch()
        self.assertNotIn('eligible_descendant_published=succeeded', source)


class NegativeBindingTests(unittest.TestCase):
    """review 61972 R1/R2 and check 61974: missing or malformed bindings are never eligible; nothing defaults to eligible."""

    def setUp(self):
        self.rule = elig.parse_rule(rule_text())
        self.control = arm('control', loss=2.00, child=CONTROL_CHILD)

    def _treatment(self, **override):
        base = arm('treatment', loss=1.5, child=TREATMENT_CHILD)
        base.update(override)
        return base

    def test_a_published_arm_with_a_null_missing_or_malformed_child_digest_refuses(self):
        for child in (None, '', 'xyz', 'A' * 64, 123):
            with self.assertRaisesRegex(elig.EligibilityRefusal, 'child_manifest_sha256', msg=repr(child)):
                elig.adjudicate(self.rule, self.control, self._treatment(child_manifest_sha256=child))
        missing = self._treatment()
        del missing['child_manifest_sha256']
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'child_manifest_sha256'):
            elig.adjudicate(self.rule, self.control, missing)
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'child_manifest_sha256'):   # the control fallback needs its own binding
            elig.adjudicate(self.rule, arm('control', loss=2.0, child=None), self._treatment())

    def test_a_published_arm_with_a_missing_or_unknown_measurement_class_refuses(self):
        for set_class in (None, 'heldout', ''):
            with self.assertRaisesRegex(elig.EligibilityRefusal, 'measurement_set_class', msg=repr(set_class)):
                elig.adjudicate(self.rule, self.control, self._treatment(measurement_set_class=set_class))
        missing = self._treatment()
        del missing['measurement_set_class']
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'measurement_set_class'):
            elig.adjudicate(self.rule, self.control, missing)

    def test_a_published_arm_with_a_missing_parent_digest_refuses(self):
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'parent_manifest_sha256'):
            elig.adjudicate(self.rule, self.control, self._treatment(parent_manifest_sha256=None))

    def test_applied_positions_must_be_a_nonnegative_integer(self):
        for bad in (True, 1.5, '1000', None, -1):
            with self.assertRaisesRegex(elig.EligibilityRefusal, 'applied_positions', msg=repr(bad)):
                elig.adjudicate(self.rule, self.control, self._treatment(applied_positions=bad))
        missing = self._treatment()
        del missing['applied_positions']
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'applied_positions'):
            elig.adjudicate(self.rule, self.control, missing)

    def test_an_unpublished_arm_is_still_judged_without_binding_fields(self):
        verdict = elig.adjudicate(self.rule, self.control, arm('treatment', published=False, loss=None))
        self.assertEqual(verdict['verdict'], elig.CONTROL_ELIGIBLE)   # the legitimate control fallback is preserved

    def test_a_null_or_malformed_launch_rule_digest_refuses_in_the_adjudicator_and_the_caller(self):
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'not a sha256'):
            elig.adjudicate(self.rule, self.control, self._treatment(), expected_rule_sha256='nothex')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        custody = Path(tmp.name)
        identity = {'training_experiment_continuation_rule': rule_text(), 'parent_checkpoint': {'root': 'r', 'manifest_sha256': START}}
        for digest in (None, '', 'nothex'):
            (custody / elig.ARM_RESULTS_FILENAME).write_text(json.dumps(
                {'rule_sha256': digest, 'control': self.control, 'treatment': self._treatment()}), encoding='utf-8')
            self.assertFalse(elig.adjudicated_eligible_descendant(identity, run_succeeded=True, custody=custody), repr(digest))
            self.assertIn('launch rule digest', json.loads((custody / elig.REFUSAL_FILENAME).read_text())['refused'])

    def test_malformed_arm_results_never_raise_out_of_the_caller(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        custody = Path(tmp.name)
        identity = {'training_experiment_continuation_rule': rule_text(), 'parent_checkpoint': {'root': 'r', 'manifest_sha256': START}}
        good = {'rule_sha256': self.rule['rule_sha256'], 'control': self.control, 'treatment': self._treatment()}
        for payload in ({**good, 'treatment': dict(self._treatment(), applied_positions='lots')},
                        {**good, 'treatment': 'not-an-arm'}, {**good, 'control': None}, [1, 2], 'text', {'rule_sha256': 1}):
            (custody / elig.ARM_RESULTS_FILENAME).write_text(json.dumps(payload), encoding='utf-8')
            self.assertFalse(elig.adjudicated_eligible_descendant(identity, run_succeeded=True, custody=custody), repr(payload)[:60])


class ArmResultsWriterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.custody = Path(self._tmp.name)
        self.identity = {'training_experiment_continuation_rule': rule_text(), 'parent_checkpoint': {'root': 'r', 'manifest_sha256': START}}

    def test_a_written_record_round_trips_through_the_runner_caller(self):
        path = elig.write_arm_results(self.identity, control=arm('control', loss=2.0, child=CONTROL_CHILD),
                                      treatment=arm('treatment', loss=1.5, child=TREATMENT_CHILD), custody=self.custody)
        self.assertEqual(path.name, elig.ARM_RESULTS_FILENAME)
        self.assertTrue(elig.adjudicated_eligible_descendant(self.identity, run_succeeded=True, custody=self.custody))

    def test_the_writer_refuses_a_record_the_adjudicator_would_refuse_and_never_overwrites(self):
        with self.assertRaises(elig.EligibilityRefusal):
            elig.write_arm_results(self.identity, control=arm('control', loss=2.0, child=CONTROL_CHILD),
                                   treatment=arm('treatment', loss=1.5, child=None), custody=self.custody)
        self.assertFalse((self.custody / elig.ARM_RESULTS_FILENAME).exists())
        good = dict(control=arm('control', loss=2.0, child=CONTROL_CHILD), treatment=arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        elig.write_arm_results(self.identity, custody=self.custody, **good)
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'already exists'):
            elig.write_arm_results(self.identity, custody=self.custody, **good)

    def test_exclusive_creation_refuses_even_when_an_exists_check_would_have_said_no(self):
        """review 62079: the writer must not rely on exists() then write. A peer that creates the file between a check and the
        write is simulated by making exists() lie; the exclusive open still refuses and leaves the peer's bytes intact."""
        peer_bytes = b'{"peer": true}'
        (self.custody / elig.ARM_RESULTS_FILENAME).write_bytes(peer_bytes)
        good = dict(control=arm('control', loss=2.0, child=CONTROL_CHILD), treatment=arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        with unittest.mock.patch.object(Path, 'exists', lambda self: False):
            with self.assertRaisesRegex(elig.EligibilityRefusal, 'already exists'):
                elig.write_arm_results(self.identity, custody=self.custody, **good)
        self.assertEqual((self.custody / elig.ARM_RESULTS_FILENAME).read_bytes(), peer_bytes)

    def test_deliberate_red_check_then_write_overwrites_a_peer_that_created_the_file_in_between(self):
        target = self.custody / elig.ARM_RESULTS_FILENAME
        target.write_bytes(b'peer')
        with unittest.mock.patch.object(Path, 'exists', lambda self: False):
            if not target.exists():   # the pre-repair writer: the check passes, then it writes
                target.write_text('mine', encoding='utf-8')
        self.assertEqual(target.read_bytes(), b'mine')   # the peer's record was destroyed


class RunnerOutcomeSeamTests(unittest.TestCase):
    """The real runner outcome seam (cia_step_runner.record_retention_outcome) records a non-eligible experiment, and still
    records the outcome, when the arm record is malformed or the adjudicator itself raises."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('bound_eligibility_cia_step_runner', MODULE_DIR / 'cia_step_runner.py')
        cls.runner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.runner
        sys.path.insert(0, str(ROOT / 'src'))
        spec.loader.exec_module(cls.runner)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.custody = Path(self._tmp.name) / 'measurement-r1'   # the finalizer binds the marker to this directory name and run id
        self.custody.mkdir()
        self.identity = {'training_experiment_continuation_rule': rule_text(), 'parent_checkpoint': {'root': 'r', 'manifest_sha256': START}, 'run_id': 'r1'}
        self.rule = elig.parse_rule(rule_text())
        self.recorded = []
        recorded = self.recorded

        class Ledger:
            exclusive_lock = staticmethod(lambda target, timeout_seconds=30.0: contextlib.nullcontext())

            @staticmethod
            def ledger_path(parent):
                return Path(parent) / 'ledger'

            @staticmethod
            def ledger_root(parent=None):
                return Path(parent) / "receipts"

            @staticmethod
            def lineage_checkpoint_manifest_sha256(identity, *, receipts_root):
                return START

            @staticmethod
            def record_retention_experiment_outcome(**kwargs):
                recorded.append(kwargs)

        self.ledger = Ledger
        self.patch_ledger = unittest.mock.patch.object(self.runner, 'load_ledger_module', lambda: Ledger)
        self.patch_ledger.start()
        self.addCleanup(self.patch_ledger.stop)

    def _write_arms(self, treatment):
        (self.custody / elig.ARM_RESULTS_FILENAME).write_text(json.dumps({
            'rule_sha256': self.rule['rule_sha256'], 'control': arm('control', loss=2.0, child=CONTROL_CHILD),
            'treatment': treatment}), encoding='utf-8')

    def seam(self, *, succeeded=True):
        return self.runner.record_retention_outcome(self.identity, succeeded=succeeded, custody=self.custody, parent=self.custody,
                                                    run_id='r1', dispatch_started=0.0)

    def _marker(self, **over):
        marker = {'status': 'run_complete_not_yet_scored', 'succeeded': True, 'run_id': 'r1', 'custody_name': 'measurement-r1',
                  'dispatch_started': 100.0, 'run_complete_at': 200.0}
        marker.update(over)
        return marker

    def _mark_complete(self, succeeded=True, **over):
        (self.custody / 'run-complete.json').write_text(json.dumps(self._marker(succeeded=succeeded, **over)), encoding='utf-8')

    def finalize(self):
        return self.runner.finalize_retention_outcome(self.identity, custody=self.custody, parent=self.custody)

    def test_deliberate_red_a_scoring_chain_with_no_producer_leaves_the_outcome_absent(self):   # ruling 63035
        self._mark_complete()
        with self.assertRaisesRegex(RuntimeError, 'arm-results.json is absent'):
            self.finalize()
        self.assertEqual(self.recorded, [])
        self.assertFalse((self.custody / 'retention-outcome-recorded.json').exists())

    def test_finalize_without_the_run_complete_marker_records_nothing(self):
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        with self.assertRaisesRegex(RuntimeError, 'no run-complete marker'):
            self.finalize()
        self.assertEqual(self.recorded, [])

    def test_finalize_records_exactly_once_and_a_second_call_refuses(self):
        self._mark_complete()
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        self.assertTrue(self.finalize())
        self.assertEqual(len(self.recorded), 1)
        with self.assertRaisesRegex(RuntimeError, 'already recorded'):
            self.finalize()
        self.assertEqual(len(self.recorded), 1)

    def test_finalize_reads_succeeded_from_the_marker_so_a_failed_run_is_never_eligible(self):
        self._mark_complete(succeeded=False)
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        self.assertFalse(self.finalize())
        self.assertEqual([r['eligible_descendant_published'] for r in self.recorded], [False])

    def test_p1_4_a_malformed_or_foreign_marker_is_refused_before_any_ledger_mutation(self):   # review 63367 P1-4
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        cases = [
            {'succeeded': 'false'}, {'succeeded': 1}, {'succeeded': None}, {'run_id': ''}, {'run_id': 7}, {'run_id': 'other'},
            {'custody_name': 'measurement-other'}, {'custody_name': None},
            {'dispatch_started': float('nan')}, {'run_complete_at': float('inf')}, {'dispatch_started': True},
            {'dispatch_started': 300.0, 'run_complete_at': 200.0}, {'dispatch_started': 0}, {'dispatch_started': '100'},
        ]
        for over in cases:
            with self.subTest(over=repr(over)):
                (self.custody / 'run-complete.json').write_text(json.dumps(self._marker(**over)), encoding='utf-8')
                with self.assertRaises(RuntimeError):
                    self.finalize()
                self.assertEqual(self.recorded, [])
                self.assertFalse((self.custody / 'retention-outcome-recorded.json').exists())

    def test_p1_4_a_marker_with_a_missing_key_leaves_no_partial_accounting(self):
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        for key in ('succeeded', 'run_id', 'custody_name', 'dispatch_started', 'run_complete_at', 'status'):
            with self.subTest(missing=key):
                marker = self._marker()
                del marker[key]
                (self.custody / 'run-complete.json').write_text(json.dumps(marker), encoding='utf-8')
                with self.assertRaises(RuntimeError):
                    self.finalize()
                self.assertEqual(self.recorded, [])
                self.assertFalse((self.custody / 'retention-outcome-recorded.json').exists())

    def test_p1_4_a_marker_for_another_identity_is_refused(self):
        self._mark_complete()
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        self.identity['run_id'] = 'the-identity-of-another-run'
        with self.assertRaisesRegex(RuntimeError, 'identity being finalized'):
            self.finalize()
        self.assertEqual(self.recorded, [])

    def test_p1_4_a_truthy_string_succeeded_never_makes_valid_arms_eligible_in_the_adjudicator(self):
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        self.assertTrue(elig.adjudicated_eligible_descendant(self.identity, run_succeeded=True, custody=self.custody))
        for truthy in ('false', 'False', 'no', 1, [1]):
            with self.subTest(value=repr(truthy)):
                self.assertFalse(elig.adjudicated_eligible_descendant(self.identity, run_succeeded=truthy, custody=self.custody))

    def test_a_malformed_applied_positions_records_a_non_eligible_outcome_and_a_refusal(self):
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD, positions='lots'))
        self.assertFalse(self.seam())
        self.assertEqual([r['eligible_descendant_published'] for r in self.recorded], [False])
        self.assertIn('applied_positions', json.loads((self.custody / elig.REFUSAL_FILENAME).read_text())['refused'])

    def test_a_winning_arm_record_is_recorded_eligible(self):
        self._write_arms(arm('treatment', loss=1.5, child=TREATMENT_CHILD))
        self.assertTrue(self.seam())
        self.assertEqual([r['eligible_descendant_published'] for r in self.recorded], [True])

    def test_an_adjudicator_that_raises_still_records_a_non_eligible_outcome(self):
        class Raising:
            @staticmethod
            def adjudicated_eligible_descendant(identity, *, run_succeeded, custody):
                raise TypeError("int() argument must be a string, a bytes-like object or a real number, not 'NoneType'")

        with unittest.mock.patch.object(self.runner, 'load_eligibility_module', lambda: Raising):
            self.assertFalse(self.seam())
            self.assertEqual([r['eligible_descendant_published'] for r in self.recorded], [False])
            self.assertIn('TypeError', json.loads((self.custody / 'eligibility-refusal.json').read_text())['refused'])

    def test_deliberate_red_the_unguarded_seam_skips_the_outcome_when_the_adjudicator_raises(self):
        class Raising:
            @staticmethod
            def adjudicated_eligible_descendant(identity, *, run_succeeded, custody):
                raise TypeError('malformed applied_positions')

        def pre_repair_seam():   # the seam as it stood before this repair: no guard around the adjudicator call
            eligible = Raising.adjudicated_eligible_descendant(self.identity, run_succeeded=True, custody=self.custody)
            self.ledger.record_retention_experiment_outcome(eligible_descendant_published=eligible)

        with self.assertRaises(TypeError):
            pre_repair_seam()
        self.assertEqual(self.recorded, [])   # the outcome was skipped: budget accounting silently lost
        with unittest.mock.patch.object(self.runner, 'load_eligibility_module', lambda: Raising):
            self.seam()
        self.assertEqual(len(self.recorded), 1)   # the repaired seam records it


class RealLedgerFinalizerTests(unittest.TestCase):
    """review 63367 P1-3: the finalizer against the REAL ledger file and the REAL exclusive lock (no mocked ledger): an interrupted marker write
    does not double-charge the occupancy on retry, and two competing finalizers record exactly one outcome."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('real_ledger_cia_step_runner', MODULE_DIR / 'cia_step_runner.py')
        cls.runner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.runner
        sys.path.insert(0, str(ROOT / 'src'))
        spec.loader.exec_module(cls.runner)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.ledger = self.runner.load_ledger_module()
        # Only the lineage DERIVATION is pinned (the real one falls back to the repository's selected-head file, outside this fixture); the
        # file, the OS lock, the idempotence check and the append all stay real, and every finalizer call uses this one module object.
        self.ledger.lineage_checkpoint_manifest_sha256 = lambda identity, **kwargs: START
        loader = unittest.mock.patch.object(self.runner, 'load_ledger_module', lambda: self.ledger)
        loader.start()
        self.addCleanup(loader.stop)
        env = unittest.mock.patch.dict(os.environ, {self.ledger.LEDGER_ROOT_ENV: str(root / 'ledger-root')})
        env.start()
        self.addCleanup(env.stop)
        self.custody = root / 'receipts' / 'measurement-r1'
        self.custody.mkdir(parents=True)
        self.identity = {'training_experiment_continuation_rule': rule_text(), 'parent_checkpoint': {'root': 'r', 'manifest_sha256': START}, 'run_id': 'r1'}
        self.rule = elig.parse_rule(rule_text())
        (self.custody / elig.ARM_RESULTS_FILENAME).write_text(json.dumps({
            'rule_sha256': self.rule['rule_sha256'], 'control': arm('control', loss=2.0, child=CONTROL_CHILD),
            'treatment': arm('treatment', loss=1.5, child=TREATMENT_CHILD)}), encoding='utf-8')
        # a FAILED run is never eligible, so the real ledger appends (and charges) one non-eligible outcome row for it
        (self.custody / 'run-complete.json').write_text(json.dumps({
            'status': 'run_complete_not_yet_scored', 'succeeded': False, 'run_id': 'r1', 'custody_name': 'measurement-r1',
            'dispatch_started': 100.0, 'run_complete_at': 200.0}), encoding='utf-8')
        self.ledger_file = self.ledger.ledger_path(self.custody.parent)

    def finalize(self):
        return self.runner.finalize_retention_outcome(self.identity, custody=self.custody, parent=self.custody.parent)

    def outcome_rows(self):
        return [r for r in self.ledger.read_rows(self.ledger_file) if r.get('row_kind') == 'retention_experiment_outcome']

    def test_the_real_ledger_records_one_row_per_lineage_and_run_and_charges_it_once(self):
        lineage = self.ledger.lineage_checkpoint_manifest_sha256(self.identity, receipts_root=self.ledger.ledger_root(self.custody.parent))
        first = self.ledger.record_retention_experiment_outcome(path=self.ledger_file, lineage_sha=lineage, run_id='r1',
                                                                eligible_descendant_published=False, elapsed_seconds=500)
        again = self.ledger.record_retention_experiment_outcome(path=self.ledger_file, lineage_sha=lineage, run_id='r1',
                                                                eligible_descendant_published=False, elapsed_seconds=999)
        self.assertEqual(again, first)
        self.assertEqual(len(self.outcome_rows()), 1)
        self.assertEqual(self.ledger.diagnostic_occupancy_seconds(self.ledger.read_rows(self.ledger_file), lineage), 500)
        self.ledger.record_retention_experiment_outcome(path=self.ledger_file, lineage_sha=lineage, run_id='r2',
                                                        eligible_descendant_published=False, elapsed_seconds=40)
        self.assertEqual(self.ledger.diagnostic_occupancy_seconds(self.ledger.read_rows(self.ledger_file), lineage), 540)   # a different run still charges

    def test_an_interrupted_marker_write_then_a_retry_never_charges_the_occupancy_twice(self):
        lineage = self.ledger.lineage_checkpoint_manifest_sha256(self.identity, receipts_root=self.ledger.ledger_root(self.custody.parent))
        real_write_new = self.runner._write_new

        def fail_the_marker_once(path, value):
            if Path(path).name == self.runner.OUTCOME_RECORDED_FILENAME and not getattr(fail_the_marker_once, 'failed', False):
                fail_the_marker_once.failed = True
                raise OSError('simulated crash while creating the outcome marker')
            return real_write_new(path, value)

        with unittest.mock.patch.object(self.runner, '_write_new', fail_the_marker_once):
            with self.assertRaises(OSError):
                self.finalize()
            self.assertEqual(len(self.outcome_rows()), 1)                                  # the ledger append already landed
            self.assertFalse((self.custody / self.runner.OUTCOME_RECORDED_FILENAME).exists())   # but the marker did not
            charged = self.ledger.diagnostic_occupancy_seconds(self.ledger.read_rows(self.ledger_file), lineage)
            self.assertFalse(self.finalize())                                              # the retry completes the marker
        self.assertEqual(len(self.outcome_rows()), 1)                                      # no second row
        self.assertEqual(self.ledger.diagnostic_occupancy_seconds(self.ledger.read_rows(self.ledger_file), lineage), charged)
        self.assertTrue((self.custody / self.runner.OUTCOME_RECORDED_FILENAME).is_file())
        with self.assertRaisesRegex(RuntimeError, 'already recorded'):
            self.finalize()

    def test_r1_the_charged_occupancy_is_the_run_duration_whenever_the_finalizer_runs(self):   # review 63986 R1
        for finalize_at in (350.0, 90000.0):    # marker: dispatch_started 100, run_complete_at 200 => exactly 100 s of execution
            with self.subTest(finalize_at=finalize_at):
                self.setUp()
                with unittest.mock.patch.object(self.runner.time, 'time', lambda: finalize_at):
                    self.finalize()
                rows = self.outcome_rows()
                self.assertEqual([r['occupancy_seconds'] for r in rows], [100])
                self.assertEqual([r['finalization_delay_seconds'] for r in rows], [int(finalize_at - 200.0)])   # the wait is its own field
                self.assertEqual(self.ledger.diagnostic_occupancy_seconds(self.ledger.read_rows(self.ledger_file), START), 100)

    def test_two_competing_finalizers_record_exactly_one_outcome(self):
        barrier = threading.Barrier(2)
        results = []

        def run():
            barrier.wait()
            try:
                results.append(('ok', self.finalize()))
            except RuntimeError as error:
                results.append(('refused', str(error)))

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(sorted(kind for kind, _ in results), ['ok', 'refused'])
        self.assertIn('already recorded', [text for kind, text in results if kind == 'refused'][0])
        self.assertEqual(len(self.outcome_rows()), 1)
        self.assertTrue((self.custody / self.runner.OUTCOME_RECORDED_FILENAME).is_file())


if __name__ == '__main__':
    unittest.main()
