# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Synthetic native receipts test admission only; no training result is inferred."""
import hour_test_support
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cia_hour


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/('measurement-' + 'a'*32)
        self.root.mkdir()
        (self.root.parent/'operator').mkdir()
        self.runner = SimpleNamespace(GIB=1024**3,
            checked_sha=lambda value: value,
            file_sha256=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())
        self.prior = dict(run_id='a'*32, source_commit='old-head',
            geometry=dict(warm_steps=1, sequence_length=3, documents_per_step=2),
            optimizer={'fused': True}, hour=dict(schema='governed-hour-v1'))
        prediction_sha = self.write('prediction.json', {'identity': self.prior})
        rows = [dict(phase='warm' if i == 0 else 'measured', run_id=self.prior['run_id'],
            prediction_sha256=prediction_sha, applied_positions=6) for i in range(1025)]
        (self.root/'rows.jsonl').write_bytes(b'\n'.join(json.dumps(row).encode() for row in rows))
        self.hour = dict(run_id=self.prior['run_id'], prediction_sha256=prediction_sha,
            hour=self.prior['hour'], measured_updates=1024, pre_checkpoint_wall_seconds=3600,
            restored_state_matches=True, rows_sha256=self.runner.file_sha256(self.root/'rows.jsonl'),
            applied_positions=6150, continuation=None)
        self.write('owned.json', dict(status='completed', returncode=0, cleanup_verified=True,
                                      supervisor_failure=None))
        self.write('disk.json', dict(outcome='COMPLETED', stop_reason=None, runner_exit_code=0,
            child_exit_code=0, operating_reserve_breaches=[]))
        self.write('worker-terminal.json', dict(status='completed', applied_positions=6150))
        self.identity = copy.deepcopy(self.prior)
        self.identity['run_id'] = 'b'*32
        self.bind()

    def write(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value))
        return self.runner.file_sha256(path)

    def bind(self):
        digest = self.write('hour-result.json', self.hour)
        self.identity['continuation'] = dict(source_hour_result_path=str(self.root/'hour-result.json'),
                                           source_hour_result_sha256=digest)
        outcome = dict(run_id=self.prior['run_id'], success=True, daemon_cleanup_verified=True,
            measurement_files={name: self.runner.file_sha256(self.root/name) for name in
                ('hour-result.json', 'owned.json', 'disk.json', 'worker-terminal.json', 'rows.jsonl')})
        (self.root.parent/'operator/operator-outcome.json').write_text(json.dumps(outcome))

    def test_completed_hour_without_reference_is_not_a_continuation(self):
        with self.assertRaisesRegex(ValueError, 'independently bound next-update reference'):
            cia_hour.validate_continuation(self.runner, self.identity)

    def test_rehashed_resource_failure_refuses_before_reference(self):
        disk = json.loads((self.root/'disk.json').read_bytes())
        disk['operating_reserve_breaches'] = [{'root': 'B:/'}]
        self.write('disk.json', disk)
        self.bind()
        with self.assertRaisesRegex(ValueError, 'resource envelope'):
            cia_hour.validate_continuation(self.runner, self.identity)

    def test_short_hour_or_different_optimizer_cannot_supply_continuation(self):
        self.hour['pre_checkpoint_wall_seconds'] = 3599
        self.bind()
        with self.assertRaisesRegex(ValueError, 'completed separate governed hour'):
            cia_hour.validate_continuation(self.runner, self.identity)
        self.hour['pre_checkpoint_wall_seconds'] = 3600
        self.bind()
        self.identity['optimizer']['fused'] = False
        with self.assertRaisesRegex(ValueError, 'identity differs: optimizer'):
            cia_hour.validate_continuation(self.runner, self.identity)

    def test_rehashed_row_surplus_is_not_governed_credit(self):
        with (self.root/'rows.jsonl').open('ab') as stream:
            stream.write(b'\n' + json.dumps(dict(phase='measured', run_id=self.prior['run_id'],
                prediction_sha256=self.hour['prediction_sha256'], applied_positions=6)).encode())
        self.hour['rows_sha256'] = self.runner.file_sha256(self.root/'rows.jsonl')
        self.bind()
        with self.assertRaisesRegex(ValueError, 'source hour rows differ'):
            cia_hour.validate_continuation(self.runner, self.identity)


if __name__ == '__main__':
    unittest.main()
