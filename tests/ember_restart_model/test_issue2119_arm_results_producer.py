"""Issue #2119 rows 5/14: the arm-results producer closes the gap between a scored pair and the runner's outcome seam.

Requirements: with both arms scored the producer writes `arm-results.json` and the adjudicator names the right eligible arm; with
the file absent the outcome reads NOT eligible (deliberate red: the producer is what moves it); a record the adjudicator would
refuse is refused at the producer and nothing is written; a second call never overwrites; a published arm without its scored
receipt, or an unpublished arm with one, is refused; a protected-set arm is refused.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import arm_results_producer as producer  # noqa: E402
import retention_eligibility as elig  # noqa: E402

START = 'a' * 64
CONTROL_CHILD, TREATMENT_CHILD = 'c' * 64, 'd' * 64
METRIC = 'heldout_loss'
DECL, PROTECTED_DECL, MIXTURE = 'e' * 64, 'f' * 64, '9' * 64
DECLARATION_CLASSES = {DECL: 'developmental', PROTECTED_DECL: 'protected'}
PLAN, LEDGER, CKPT_RECEIPT, SCORER, TOKENIZER = '1' * 64, '2' * 64, '3' * 64, '4' * 64, '5' * 64
REQUIRED = {'episode_plan_sha256': PLAN, 'shard_ledger_sha256': LEDGER, 'mixture_identity_sha256': MIXTURE, 'frozen_declaration_sha256': DECL,
            'checkpoint_receipt_sha256': CKPT_RECEIPT, 'scorer_sha256': SCORER, 'tokenizer_sha256': TOKENIZER}


def identity():
    rule = {'schema': elig.RULE_SCHEMA, 'frozen_start_manifest_sha256': START, 'control_arm_id': 'control',
            'treatment_arm_id': 'treatment',
            'selection': {'metric': METRIC, 'direction': 'lower', 'min_delta': 0.01, 'evaluation_set_class': 'developmental'}}
    return {'training_experiment_continuation_rule': json.dumps(rule), 'parent_checkpoint': {'manifest_sha256': START}}


class ArmResultsProducerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.custody = Path(self._tmp.name)

    def receipt(self, name, loss, *, child=None, declaration=DECL, mixture=MIXTURE, plan=PLAN, schema='ember-2119-child-episode-nll-v1', extra=None):
        path = self.custody / name
        body = {'schema': schema, 'condition': 'child-direct-episodes', 'label': name,
                'bindings': {'checkpoint_manifest_sha256': child, 'frozen_declaration_sha256': declaration, 'mixture_identity_sha256': mixture,
                             'episode_plan_sha256': plan, 'shard_ledger_sha256': LEDGER, 'checkpoint_receipt_sha256': CKPT_RECEIPT,
                             'scorer_sha256': SCORER, 'tokenizer_sha256': TOKENIZER},
                'arms': {'fresh': {'mean_nll': loss}}}
        body.update(extra or {})
        path.write_text(json.dumps(body), encoding='utf-8')
        return path

    def arm(self, arm_id, receipt, child, *, positions=1000, required=REQUIRED, classes=DECLARATION_CLASSES, expected_sha='auto'):
        if expected_sha == 'auto':   # the frozen-binding entry's digest of the scored receipt's bytes (None when there is no receipt)
            expected_sha = hashlib.sha256(Path(receipt).read_bytes()).hexdigest() if receipt is not None and Path(receipt).is_file() else None
        return producer.arm_from_scored_receipt(arm_id, receipt, metric_name=METRIC, metric_path='arms.fresh.mean_nll',
                                                parent_manifest_sha256=START, child_manifest_sha256=child, applied_positions=positions,
                                                required_bindings=required, declaration_classes=classes, expected_receipt_sha256=expected_sha)

    def test_two_scored_arms_are_written_and_the_adjudicator_names_the_winner(self):
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        treatment = self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD), TREATMENT_CHILD, positions=900)
        path = producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        self.assertEqual(path.name, elig.ARM_RESULTS_FILENAME)
        self.assertTrue(elig.adjudicated_eligible_descendant(identity(), run_succeeded=True, custody=self.custody))
        self.assertEqual(json.loads((self.custody / 'eligibility-verdict.json').read_text())['eligible_arm'], 'treatment')

    def test_a_rejected_treatment_leaves_the_control_eligible_through_the_producer(self):
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        treatment = self.arm('treatment', self.receipt('t.json', 2.10, child=TREATMENT_CHILD), TREATMENT_CHILD)
        producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        self.assertTrue(elig.adjudicated_eligible_descendant(identity(), run_succeeded=True, custody=self.custody))
        self.assertEqual(json.loads((self.custody / 'eligibility-verdict.json').read_text())['eligible_arm'], 'control')

    def test_deliberate_red_without_the_producer_the_outcome_reads_not_eligible(self):
        self.assertFalse(elig.adjudicated_eligible_descendant(identity(), run_succeeded=True, custody=self.custody))
        self.assertFalse((self.custody / elig.ARM_RESULTS_FILENAME).exists())

    def test_a_record_the_adjudicator_would_refuse_is_refused_here_and_nothing_is_written(self):
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        treatment = self.arm('treatment', self.receipt('t.json', 1.90, child=CONTROL_CHILD), CONTROL_CHILD)   # same checkpoint: no experiment
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'same checkpoint'):
            producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        self.assertFalse((self.custody / elig.ARM_RESULTS_FILENAME).exists())

    def test_a_second_call_never_overwrites(self):
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        treatment = self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD), TREATMENT_CHILD)
        producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        before = (self.custody / elig.ARM_RESULTS_FILENAME).read_bytes()
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'already exists'):
            producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        self.assertEqual((self.custody / elig.ARM_RESULTS_FILENAME).read_bytes(), before)

    def test_a_published_arm_without_its_scored_receipt_is_refused(self):
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'receipt is absent'):
            self.arm('treatment', self.custody / 'missing.json', TREATMENT_CHILD)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'receipt is absent'):
            self.arm('treatment', None, TREATMENT_CHILD)

    def test_an_unpublished_arm_with_a_receipt_is_refused(self):
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'no published child manifest'):
            self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD), None)

    def test_a_receipt_without_the_metric_or_with_a_non_number_is_refused(self):
        bad = self.receipt('bad.json', 0.0, child=TREATMENT_CHILD, extra={'arms': {'fresh': {}}})
        with self.assertRaisesRegex(producer.ArmProducerRefusal, "no 'arms.fresh.mean_nll'"):
            self.arm('treatment', bad, TREATMENT_CHILD)
        bad = self.receipt('bad.json', 'nan', child=TREATMENT_CHILD)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'not a finite number'):
            self.arm('treatment', bad, TREATMENT_CHILD)

    def test_a_protected_set_arm_is_refused_at_the_producer(self):
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        treatment = self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD, declaration=PROTECTED_DECL), TREATMENT_CHILD,
                             required=dict(REQUIRED, frozen_declaration_sha256=PROTECTED_DECL))   # class comes from the receipt's declaration, not a label
        with self.assertRaisesRegex(elig.EligibilityRefusal, 'protected set'):
            producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        self.assertFalse((self.custody / elig.ARM_RESULTS_FILENAME).exists())

    def test_an_unpublished_treatment_with_a_published_control_leaves_the_control_eligible(self):
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        treatment = self.arm('treatment', None, None)
        producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        self.assertTrue(elig.adjudicated_eligible_descendant(identity(), run_succeeded=True, custody=self.custody))

    def test_a_failed_run_is_never_eligible_even_with_arm_results(self):
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        treatment = self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD), TREATMENT_CHILD)
        producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=treatment)
        self.assertFalse(elig.adjudicated_eligible_descendant(identity(), run_succeeded=False, custody=self.custody))

    # Kai 63367 P1-1: the producer binds the scored receipt to the declared arm from the receipt itself (no caller labels).
    def test_repair1_a_receipt_scored_on_another_checkpoint_is_refused_for_this_arm(self):
        control_receipt = self.receipt('c.json', 2.00, child=CONTROL_CHILD)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'not the declared child'):
            self.arm('treatment', control_receipt, TREATMENT_CHILD)   # the control's number offered for the treatment arm
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'not the declared child'):
            self.arm('treatment', self.receipt('t.json', 1.90, child=None), TREATMENT_CHILD)

    def test_repair1_a_receipt_from_another_lineage_or_population_is_refused(self):
        for key, bad in (('frozen_declaration_sha256', '6' * 64), ('mixture_identity_sha256', '7' * 64), ('episode_plan_sha256', '8' * 64)):
            with self.subTest(key=key):
                kwargs = {'declaration': bad} if key == 'frozen_declaration_sha256' else {'mixture': bad} if key == 'mixture_identity_sha256' else {'plan': bad}
                receipt = self.receipt('t.json', 1.90, child=TREATMENT_CHILD, **kwargs)
                with self.assertRaisesRegex(producer.ArmProducerRefusal, 'binding|trusted measurement class'):
                    self.arm('treatment', receipt, TREATMENT_CHILD)

    def test_repair1_an_unscored_or_wrong_schema_receipt_is_refused(self):
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'unscored'):
            self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD, extra={'status': 'NOT_MEASURED'}), TREATMENT_CHILD)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'unscored'):
            self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD,
                                               extra={'arms': {'fresh': {'mean_nll': 1.9, 'status': 'NOT_MEASURED'}}}), TREATMENT_CHILD)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'not a scored-receipt schema'):
            self.arm('treatment', self.receipt('t.json', 1.90, child=TREATMENT_CHILD, schema='some-other-receipt'), TREATMENT_CHILD)

    def test_repair1_the_measurement_class_comes_from_the_receipt_declaration_not_the_caller(self):
        protected = self.receipt('t.json', 1.90, child=TREATMENT_CHILD, declaration=PROTECTED_DECL)
        protected_required = dict(REQUIRED, frozen_declaration_sha256=PROTECTED_DECL)
        arm = self.arm('treatment', protected, TREATMENT_CHILD, required=protected_required)
        self.assertEqual(arm['measurement_set_class'], 'protected')      # a protected score cannot be relabelled developmental
        with self.assertRaises(TypeError):
            producer.arm_from_scored_receipt('treatment', protected, metric_name=METRIC, metric_path='arms.fresh.mean_nll',
                                             parent_manifest_sha256=START, child_manifest_sha256=TREATMENT_CHILD, applied_positions=1,
                                             measurement_set_class='developmental')   # the label parameter no longer exists
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'trusted measurement class'):
            self.arm('treatment', protected, TREATMENT_CHILD, required=protected_required, classes={DECL: 'developmental'})   # unknown declaration

    def test_r2_the_bindings_are_mandatory_and_never_default(self):   # Kai 63986 R2: population, mixture, run, source
        receipt = self.receipt('t.json', 1.90, child=TREATMENT_CHILD)
        for key in producer.MANDATORY_BINDING_KEYS:
            with self.subTest(missing=key):
                partial = {k: v for k, v in REQUIRED.items() if k != key}
                with self.assertRaisesRegex(producer.ArmProducerRefusal, 'mandatory bindings'):
                    self.arm('treatment', receipt, TREATMENT_CHILD, required=partial)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'mandatory bindings'):
            self.arm('treatment', receipt, TREATMENT_CHILD, required={})
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'mandatory bindings'):
            self.arm('treatment', receipt, TREATMENT_CHILD, required=dict(REQUIRED, scorer_sha256='not-a-digest'))
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'declaration-to-class map'):
            self.arm('treatment', receipt, TREATMENT_CHILD, classes={})
        with self.assertRaises(TypeError):   # no default: a caller that omits the bindings entirely cannot call the producer
            producer.arm_from_scored_receipt('treatment', receipt, metric_name=METRIC, metric_path='arms.fresh.mean_nll',
                                             parent_manifest_sha256=START, child_manifest_sha256=TREATMENT_CHILD, applied_positions=1)

    def test_r2_the_scored_receipt_bytes_must_match_the_frozen_receipt_digest(self):
        receipt = self.receipt('t.json', 1.90, child=TREATMENT_CHILD)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'no frozen digest'):
            self.arm('treatment', receipt, TREATMENT_CHILD, expected_sha=None)
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'differ from the frozen receipt digest'):
            self.arm('treatment', receipt, TREATMENT_CHILD, expected_sha='0' * 64)

    def test_repair1_the_source_receipt_identity_is_retained_on_the_arm_record(self):
        receipt = self.receipt('t.json', 1.90, child=TREATMENT_CHILD)
        arm = self.arm('treatment', receipt, TREATMENT_CHILD)
        self.assertEqual(arm['source_receipt_sha256'], hashlib.sha256(receipt.read_bytes()).hexdigest())
        self.assertEqual(arm['source_receipt_schema'], 'ember-2119-child-episode-nll-v1')
        control = self.arm('control', self.receipt('c.json', 2.00, child=CONTROL_CHILD), CONTROL_CHILD)
        path = producer.produce_arm_results(identity(), custody=self.custody, control=control, treatment=arm)
        written = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(written['treatment']['source_receipt_sha256'], arm['source_receipt_sha256'])


if __name__ == '__main__':
    unittest.main()
