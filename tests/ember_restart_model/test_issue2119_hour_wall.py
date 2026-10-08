"""CPU checks of the optional declared governed-hour wall: one identity value, bound by prediction, plan, worker and supervisor."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
from pathlib import Path
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'
spec = importlib.util.spec_from_file_location('tested_hour_wall_runner', SOURCE)
runner = importlib.util.module_from_spec(spec)
sys.modules['tested_hour_wall_runner'] = runner
spec.loader.exec_module(runner)


def hour(**extra):
    return dict(hour=dict(schema='governed-hour-v1', arm='control', minimum_wall_seconds=3600, minimum_measured_steps=1024, **extra))


class HourWallTests(unittest.TestCase):
    def test_absent_wall_keeps_the_default(self):
        self.assertEqual(runner.resource_limits(hour())['wall_seconds'], 5656)
        self.assertEqual(runner.HOUR_WALL_SECONDS, 5656)

    def test_declared_wall_up_to_the_cap_is_the_limit(self):
        for value in (5657, 6033, 7200, 7500):
            self.assertEqual(runner.resource_limits(hour(wall_seconds=value))['wall_seconds'], value)
            self.assertEqual(runner.resource_limits(hour(wall_seconds=value))['max_b_write_gib'], 24)

    def test_above_the_cap_refuses(self):
        with self.assertRaises(ValueError):
            runner.resource_limits(hour(wall_seconds=7501))

    def test_default_given_explicitly_or_below_it_refuses(self):
        for value in (5656, 5655, 3600, 0, -1):
            with self.assertRaises(ValueError):
                runner.hour_mode(hour(wall_seconds=value))

    def test_non_int_wall_refuses(self):
        for value in (6000.0, '6000', True, None):
            with self.assertRaises(ValueError):
                runner.hour_mode(hour(wall_seconds=value))

    def test_other_schemas_refuse_a_declared_wall(self):
        for schema, steps, minimum in (('checkpoint-probe-v1', 2, 0), ('learning-comparison-v1', 16383, 0)):
            identity = dict(hour=dict(schema=schema, arm='control', minimum_wall_seconds=minimum, minimum_measured_steps=steps,
                                      wall_seconds=6000))
            with self.assertRaises(ValueError):
                runner.hour_mode(identity)

    def test_continuation_keeps_its_own_short_wall(self):
        identity = dict(hour(wall_seconds=6033), continuation={})
        self.assertEqual(runner.resource_limits(identity)['wall_seconds'], 900)

    def test_a_supervisor_or_worker_value_that_differs_from_the_identity_is_a_mismatch(self):
        # verify_worker and the prediction check both compare a recorded envelope to resource_limits(prediction identity):
        # an envelope carrying the default wall does not equal the declared 6033 one, and the reverse.
        declared = hour(wall_seconds=6033)
        default = hour()
        self.assertNotEqual(runner.canonical(runner.resource_limits(declared)), runner.canonical(runner.resource_limits(default)))
        recorded_by_supervisor = dict(runner.resource_limits(default))
        self.assertNotEqual(runner.canonical(recorded_by_supervisor), runner.canonical(runner.resource_limits(declared)))

    def test_prediction_resource_envelope_must_equal_the_declared_wall(self):
        declared = dict(hour(wall_seconds=6033), resources=runner.resource_limits(hour()))
        self.assertNotEqual(runner.canonical(declared['resources']), runner.canonical(runner.resource_limits(declared)))

    def test_no_supervisor_side_override_exists(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertEqual(source.count('HOUR_WALL_SECONDS_CAP'), 3)
        self.assertNotIn('EMBER_HOUR_WALL', source)


if __name__ == '__main__':
    unittest.main()
