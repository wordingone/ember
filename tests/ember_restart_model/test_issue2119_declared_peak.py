# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The hour declares its job memory peak and a peak near the cap refuses at preflight (#2119, H50).

H50 died in the restore verify at a job peak of 43,271,577,600 B (40.30 GiB) against the 40 GiB limit; nothing had declared a peak. The
prediction now carries `predicted_peak_job_memory_bytes`, a TRAINING hour's prediction within 4 GiB of the cap refuses, an absent one refuses, and only a
checkpoint probe carries `probe_verify_resident_bytes`, which must sit under the declared peak. The margin does not bind the no-training modes (the probe,
the verify-only tail, the continuation worker): they declare the level they really reach and are admitted when it is at most the cap (review r1 item 1, lead
ruling 82978). An hour that consumes a probe declares `before_verify_resident_bytes`, the level its probe must have held (review r1 item 2). These reds were first written beside the
other prediction tests (test_cia_step_runner.py, which no CI job collects); they live here so the issue 2119 wiring job runs them.
"""
import copy
import unittest
from unittest.mock import patch

import test_cia_step_runner as steps

subject = steps.subject


class DeclaredPeak(unittest.TestCase):
    setUp = steps.PredictionTests.setUp         # the same small identity and prediction fixture, not a second copy of it

    GIB = 1024 ** 3

    def with_peak(self, value):
        prediction = copy.deepcopy(self.prediction)
        prediction['predicted_peak_job_memory_bytes'] = value
        return prediction

    def test_a_predicted_peak_within_four_gib_of_the_job_limit_refuses(self):
        # #2119: H50 died at a job peak of 43,271,577,600 B (40.30 GiB) against the 40 GiB limit with no peak ever declared.
        # 37 vs 40 refuses, 35 passes.
        self.assertEqual(self.identity['resources']['host_memory_bytes'], 40 * self.GIB)
        with self.assertRaisesRegex(ValueError, 'within 4294967296 bytes of the job memory limit'):
            subject.validate_prediction(self.with_peak(37 * self.GIB), expected_identity=self.identity, positions_per_step=4)
        subject.validate_prediction(self.with_peak(35 * self.GIB), expected_identity=self.identity, positions_per_step=4)

    def test_the_four_gib_margin_boundary_is_exact(self):
        subject.validate_prediction(self.with_peak(36 * self.GIB), expected_identity=self.identity, positions_per_step=4)
        for value in (36 * self.GIB + 1, 40 * self.GIB, 41 * self.GIB):
            with self.subTest(value=value), self.assertRaises(ValueError):
                subject.validate_prediction(self.with_peak(value), expected_identity=self.identity, positions_per_step=4)

    def test_a_prediction_without_a_declared_peak_refuses(self):
        prediction = copy.deepcopy(self.prediction)
        del prediction['predicted_peak_job_memory_bytes']
        with self.assertRaisesRegex(ValueError, 'requires predicted_peak_job_memory_bytes'):
            subject.validate_prediction(prediction, expected_identity=self.identity, positions_per_step=4)

    def test_a_declared_peak_that_is_not_a_positive_integer_refuses(self):
        for value in (None, True, 0, -1, 35.0, '35', float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                subject.validate_prediction(self.with_peak(value), expected_identity=self.identity, positions_per_step=4)

    def test_only_a_checkpoint_probe_carries_a_declared_resident_set(self):
        with self.assertRaisesRegex(ValueError, 'fields or schema differ'):
            prediction = self.with_peak(35 * self.GIB)
            prediction['probe_verify_resident_bytes'] = 30 * self.GIB
            subject.validate_prediction(prediction, expected_identity=self.identity, positions_per_step=4)

    def test_the_margin_binds_training_hours_and_not_the_no_training_modes(self):
        check = subject.check_predicted_peak_job_memory
        limit = 40 * self.GIB
        for declared in (37 * self.GIB, 36 * self.GIB + 1, 40 * self.GIB):
            with self.subTest(declared=declared, mode='training'), self.assertRaisesRegex(ValueError, 'within 4294967296 bytes'):
                check(declared, limit)                                           # a training hour: peak measured plus the margin
        for declared in (int(36.5 * self.GIB), 38 * self.GIB, 40 * self.GIB):
            with self.subTest(declared=declared, mode='no-training'):
                check(declared, limit, training=False)                           # the tail at 36.5 against a 40 GiB cap is admitted, and so is a level equal to the cap
        for training in (True, False):
            with self.subTest(training=training), self.assertRaisesRegex(ValueError, 'above the job memory limit'):
                check(40 * self.GIB + 1, limit, training=training)               # above the cap is refused in every mode

    def test_the_modes_are_told_apart_by_their_identity(self):
        probe = {'hour': {'schema': 'checkpoint-probe-v1'}}
        training = {'hour': {'schema': 'governed-hour-v1'}}
        learning = {'hour': {'schema': 'learning-comparison-v1'}}
        self.assertTrue(subject.no_training_mode(probe))
        self.assertTrue(subject.no_training_mode(dict(training, verify_tail={})))
        self.assertTrue(subject.no_training_mode(dict(training, continuation={})))
        self.assertFalse(subject.no_training_mode(training))
        self.assertFalse(subject.no_training_mode(learning))
        self.assertFalse(subject.no_training_mode({}))

    def test_an_honest_probe_is_admitted_by_the_runner_at_a_44_gib_cap(self):
        """The body's probe arithmetic: hold 31.5 + restore 11.05 + counter under 1 = 43.6 GiB, at 44 the margin left 0.4 and refused it."""
        with patch.dict(subject.LIMITS, host_memory_bytes=44 * self.GIB):
            identity, prediction = self.probe_case(probe_verify_resident_bytes=int(31.5 * self.GIB),
                                                   predicted_peak_job_memory_bytes=int(43.6 * self.GIB))
            # the peak gate runs before the geometry gate: this fixture counts one update, so an admitted peak is proved by the NEXT gate being the one that speaks
            with self.assertRaisesRegex(ValueError, 'requires 4x1024 geometry'):
                subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)
            identity, prediction = self.probe_case(probe_verify_resident_bytes=int(31.5 * self.GIB), predicted_peak_job_memory_bytes=45 * self.GIB)
            with self.assertRaisesRegex(ValueError, 'above the job memory limit'):
                subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)

    def test_a_training_hour_at_the_same_declaration_is_still_refused(self):
        with patch.dict(subject.LIMITS, host_memory_bytes=44 * self.GIB):
            identity = copy.deepcopy(self.identity)
            identity['resources'] = subject.resource_limits(identity)
            prediction = copy.deepcopy(self.prediction)
            prediction['identity'] = copy.deepcopy(identity)
            prediction['predicted_peak_job_memory_bytes'] = int(43.6 * self.GIB)
            with self.assertRaisesRegex(ValueError, 'within 4294967296 bytes of the job memory limit'):
                subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)

    def consumer_case(self, **fields):
        identity = copy.deepcopy(self.identity)
        identity['checkpoint_probe'] = {'custody_root': 'B:/x/measurement-aaaa'}
        prediction = copy.deepcopy(self.prediction)
        prediction['identity'] = copy.deepcopy(identity)
        prediction.update(fields)
        return identity, prediction

    def test_an_hour_that_consumes_a_probe_declares_the_level_the_probe_must_have_held(self):
        identity, prediction = self.consumer_case()
        with self.assertRaisesRegex(ValueError, 'requires before_verify_resident_bytes'):
            subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)
        for bad in (0, -1, True, 30.0, 35 * self.GIB, 36 * self.GIB):
            identity, prediction = self.consumer_case(before_verify_resident_bytes=bad)
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'before_verify_resident_bytes must be'):
                subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)
        identity, prediction = self.consumer_case(before_verify_resident_bytes=int(31.5 * self.GIB))
        subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)

    def test_an_hour_without_a_probe_carries_no_such_field(self):
        prediction = self.with_peak(30 * self.GIB)
        prediction['before_verify_resident_bytes'] = 20 * self.GIB
        with self.assertRaisesRegex(ValueError, 'fields or schema differ'):
            subject.validate_prediction(prediction, expected_identity=self.identity, positions_per_step=4)

    def probe_case(self, **fields):
        identity = copy.deepcopy(self.identity)
        identity['hour'] = dict(schema='checkpoint-probe-v1', arm='control', minimum_wall_seconds=0, minimum_measured_steps=2)
        identity['resources'] = subject.resource_limits(identity)
        prediction = copy.deepcopy(self.prediction)
        prediction['identity'] = copy.deepcopy(identity)
        prediction['predicted_peak_job_memory_bytes'] = 35 * self.GIB
        prediction.update(fields)
        return identity, prediction

    def test_a_probe_prediction_declares_the_resident_set_it_must_hold(self):
        identity, prediction = self.probe_case(probe_verify_resident_bytes=30 * self.GIB)
        # the geometry of this fixture counts one update; only the new field is under test, so any refusal must not be about it
        try:
            subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)
        except ValueError as error:
            self.assertNotIn('probe_verify_resident_bytes', str(error))
        identity, prediction = self.probe_case()
        with self.assertRaisesRegex(ValueError, 'requires probe_verify_resident_bytes'):
            subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)
        for bad in (0, -1, True, 30.0, 35 * self.GIB, 36 * self.GIB):
            identity, prediction = self.probe_case(probe_verify_resident_bytes=bad)
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'probe_verify_resident_bytes must be'):
                subject.validate_prediction(prediction, expected_identity=identity, positions_per_step=4)


if __name__ == '__main__':
    unittest.main()
