# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Keep continuation selection distinct from an ordinary hour or checkpoint probe."""
import hour_test_support
import importlib.util
from pathlib import Path
import unittest
import cia_hour

import cia_step_runner as runner


class ContinuationModeTests(unittest.TestCase):
    def test_orphan_and_probe_continuation_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'bound governed hour'):
            runner.hour_mode({'continuation': {}})
        probe = dict(hour=dict(schema='checkpoint-probe-v1', arm='control',
            minimum_wall_seconds=0, minimum_measured_steps=2), continuation={})
        with self.assertRaisesRegex(ValueError, 'completed governed hour'):
            runner.hour_mode(probe)

    def test_explicit_reproduction_preserves_device_and_memory_limits(self):
        hour = dict(hour=dict(schema='governed-hour-v1', arm='treatment',
            minimum_wall_seconds=3600, minimum_measured_steps=1024))
        ordinary = runner.resource_limits(hour)
        reproduced = runner.resource_limits(dict(hour, continuation={}))
        self.assertEqual((ordinary['wall_seconds'], ordinary['max_b_write_gib']), (4500, 24))
        self.assertEqual((reproduced['wall_seconds'], reproduced['max_b_write_gib']), (900, 1))
        for key in ordinary.keys() - {'wall_seconds', 'max_b_write_gib'}:
            self.assertEqual(ordinary[key], reproduced[key])
        self.assertEqual(hour['hour']['minimum_wall_seconds'], 3600)

    def test_native_disk_projection_uses_the_selected_worker_envelope(self):
        identity = dict(hour=dict(schema='governed-hour-v1', arm='control',
            minimum_wall_seconds=3600, minimum_measured_steps=1024),
            geometry=dict(measured_steps=1024), production_mixture={}, data={})
        for continuation, gib in ((False, 24), (True, 1)):
            current = dict(identity)
            if continuation:
                current['continuation'] = {}
            current['dispatch_resources'] = dict(disk_write_walls=[dict(volume_root='B:/',
                maximum_write_bytes=gib * runner.GIB)])
            # Both legitimate envelopes reach the next admission predicate.
            with self.assertRaisesRegex(ValueError, 'complete frozen production-mixture'):
                cia_hour.validate_identity(runner=runner, identity=current)
            current['dispatch_resources']['disk_write_walls'][0]['maximum_write_bytes'] = (25-gib) * runner.GIB
            with self.assertRaisesRegex(ValueError, 'native disk wall differs'):
                cia_hour.validate_identity(runner=runner, identity=current)

    def test_reproduction_prediction_counts_one_update_and_preserves_hour_minimum(self):
        identity = dict(hour=dict(schema='governed-hour-v1', arm='control',
            minimum_wall_seconds=3600, minimum_measured_steps=1024), continuation={},
            geometry=dict(sequence_length=1024, documents_per_step=4, warm_steps=1, measured_steps=1024))
        identity['resources'] = runner.resource_limits(identity)
        prediction = dict(schema='ember-cia-step-prediction-v1', identity=identity,
            expected_step_seconds=1.5, expected_positions_per_second=4096/1.5, basis='single reproduced update')
        runner.validate_prediction(prediction, expected_identity=identity, positions_per_step=4096)
        self.assertEqual(identity['hour']['minimum_measured_steps'], 1024)
        prediction.update(expected_step_seconds=900, expected_positions_per_second=4096/900)
        with self.assertRaisesRegex(ValueError, 'fixed wall bound'):
            runner.validate_prediction(prediction, expected_identity=identity, positions_per_step=4096)


if __name__ == '__main__':
    unittest.main()
