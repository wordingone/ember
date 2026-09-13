# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Place the existing energy collector around the worker's governed interval."""
import hashlib
import json
from pathlib import Path
import time
from types import ModuleType, SimpleNamespace


def load(*, runner, identity, custody, device):
    relative = 'src/ember/infrastructure/tools/ember-restart-3b/boundary_energy_collector.py'
    source = runner.ROOT / relative
    raw = source.read_bytes()
    expected = identity['source_sha256'][relative]
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('energy collector source changed before loading')
    collector = ModuleType('cia_bound_hour_energy_collector')
    collector.__file__ = str(source)
    exec(compile(raw, str(source), 'exec'), collector.__dict__)
    return HourEnergy(collector=collector, source=source, expected_sha256=expected,
        custody=custody, run_id=identity['run_id'],
        device_index=0 if device.index is None else device.index)


class HourEnergy:
    def __init__(self, *, collector, source, expected_sha256, custody, run_id,
                 device_index, clock=time.time):
        self.collector = collector
        self.source = Path(source)
        self.expected_sha256 = expected_sha256
        self.custody = Path(custody)
        self.run_id = run_id
        self.device_index = device_index
        self.clock = clock
        self.start = None
        self.closed = False
        self.begin_path = self.custody / 'energy-boundary-begin.json'
        self.end_path = self.custody / 'energy-boundary-result.json'

    def verify_source(self):
        if hashlib.sha256(self.source.read_bytes()).hexdigest() != self.expected_sha256:
            raise ValueError('energy collector source changed')

    def begin(self):
        if self.start is not None:
            raise ValueError('energy interval already begun')
        self.verify_source()
        args = SimpleNamespace(run_id=self.run_id, custody=str(self.custody),
            device_index=self.device_index, boundary_source='external', out=str(self.begin_path))
        if self.collector.cmd_begin(args) != 0:
            raise ValueError('energy begin refused')
        if json.loads(self.begin_path.read_bytes()).get('verdict') != 'SAMPLED':
            raise ValueError('energy begin receipt not sampled')
        self.start = self.clock()

    def end(self):
        if self.start is None:
            raise ValueError('energy interval not begun')
        if self.closed:
            raise ValueError('energy interval already closed')
        finished = self.clock()
        self.verify_source()
        args = SimpleNamespace(begin=str(self.begin_path), out=str(self.end_path),
            hour_start_unix=self.start, hour_end_unix=finished,
            max_slack_seconds=60., placement_evidence=None)
        if self.collector.cmd_end(args) != 0:
            raise ValueError('energy end refused')
        if json.loads(self.end_path.read_bytes()).get('verdict') != 'MEASURED':
            raise ValueError('energy end receipt not measured')
        self.closed = True
        return dict(begin_sha256=hashlib.sha256(self.begin_path.read_bytes()).hexdigest(),
            result_sha256=hashlib.sha256(self.end_path.read_bytes()).hexdigest(),
            hour_start_unix=self.start, hour_end_unix=finished,
            collector_sha256=self.expected_sha256)
