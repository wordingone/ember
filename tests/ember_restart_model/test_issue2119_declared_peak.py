# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The hour declares its job memory peak and a peak near the cap refuses at preflight (#2119, H50).

H50 died in the restore verify at a job peak of 43,271,577,600 B (40.30 GiB) against the 40 GiB limit; nothing had declared a peak. The
prediction now carries `predicted_peak_job_memory_bytes`, a prediction within 4 GiB of the cap refuses, an absent one refuses, and only a
checkpoint probe carries `probe_verify_resident_bytes`, which must sit under the declared peak. These reds were first written beside the
other prediction tests (test_cia_step_runner.py, which no CI job collects); they live here so the issue 2119 wiring job runs them.
"""
import copy
import unittest

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
