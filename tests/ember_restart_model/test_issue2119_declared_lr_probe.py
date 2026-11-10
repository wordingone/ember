# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Declared-lr probe consumption (#2119 H43 attempt 3): a governed hour that declares an lr consumes only a probe whose
hour declared the same lr and whose optimizer equals the hour's; an undeclared hour keeps today's exact probe shape."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(ROOT / 'src'))
_spec = importlib.util.spec_from_file_location('cia_hour_lr_probe', TOOL / 'cia_hour.py')
subject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(subject)

REF = dict(custody_root='x', result_sha256='r', prediction_sha256='p', owned_sha256='o', disk_sha256='d',
           worker_terminal_sha256='t')


class Root:
    drive, name = 'B:', 'measurement-0'
    def resolve(self, strict=False): return self
    def __truediv__(self, other): return other


class Reached(Exception):
    pass


def check(hour_declared, probe_declared, probe_lr=0.0003, hour_lr=0.0003):
    governed = dict(schema='governed-hour-v1', arm='treatment', minimum_wall_seconds=3600, minimum_measured_steps=1024)
    probe = dict(schema='checkpoint-probe-v1', arm='treatment', minimum_wall_seconds=0, minimum_measured_steps=2)
    if hour_declared is not None: governed['declared_lr'] = hour_declared
    if probe_declared is not None: probe['declared_lr'] = probe_declared
    prior = dict(hour=probe, optimizer=dict(lr=probe_lr))
    docs = {'hour-result.json': dict(hour=probe, measured_updates=2, applied_positions=3*4096, restored_state_matches=True),
            'prediction.json': dict(identity=prior),
            'owned.json': dict(status='completed', returncode=0, cleanup_verified=True, supervisor_failure=None),
            'disk.json': dict(outcome='COMPLETED', runner_exit_code=0, child_exit_code=0, stop_reason=None,
                              operating_reserve_breaches=[]),
            'worker-terminal.json': dict(status='completed', applied_positions=3*4096)}
    identity = dict(hour=governed, checkpoint_probe=REF, optimizer=dict(lr=hour_lr))
    def reached(*a): raise Reached()
    with mock.patch.object(subject, 'Path', lambda p: Root()), \
         mock.patch.object(subject, 'bound_json', lambda runner, path, sha: docs[path]), \
         mock.patch.object(subject, 'validate_probe_inputs', reached):
        subject.validate_checkpoint_probe(None, identity)


class DeclaredLrProbe(unittest.TestCase):
    def test_matching_declared_probe_is_consumed(self):
        with self.assertRaises(Reached):
            check(0.0003, 0.0003)

    def test_undeclared_shape_passes_as_before(self):
        with self.assertRaises(Reached):
            check(None, None, probe_lr=0.001, hour_lr=0.001)

    def test_probe_declaring_another_lr_refuses(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            check(0.0003, 0.001)

    def test_declared_probe_for_undeclared_hour_refuses(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            check(None, 0.0003)

    def test_undeclared_probe_for_declared_hour_refuses(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            check(0.0003, None)

    def test_probe_optimizer_differing_from_hour_refuses(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            check(0.0003, 0.0003, probe_lr=0.001)


if __name__ == '__main__':
    unittest.main()
