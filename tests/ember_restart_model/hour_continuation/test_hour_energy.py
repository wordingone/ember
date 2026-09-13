# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Exercise actual worker boundary ordering and fail-closed energy receipts."""
import hour_test_support
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace


class BoundaryTests(unittest.TestCase):
    def test_real_collector_contract_with_boundary_samples(self):
        from cia_hour_energy import HourEnergy
        source=__import__('hour_test_support').source/'boundary_energy_collector.py'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
            'a276a8b2a3798fffbb7ccde4bc92e7d92f084d9c2ad74d303b98af0717ed50ff')
        spec=importlib.util.spec_from_file_location('tested_boundary_collector',source)
        collector=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        def sample(seconds,energy):
            return dict(device_uuid='GPU-fixture',device_name='fixture',driver_version='fixture',
                nvml_version='fixture',enforced_power_limit_mw=450000,energy_mj=energy,
                read_monotonic_ns_before=int(seconds*1e9),read_monotonic_ns_after=int(seconds*1e9)+100,
                read_wall_unix=seconds,read_cost_ns=100,instantaneous_power_mw=100000)
        samples=iter([sample(100.,100000),sample(3700.2,360120000)])
        def sample_device(index):
            self.assertEqual(index,0)
            return next(samples)
        sample_device.last_shutdown_code=0
        collector.sample_device=sample_device
        clock=iter([100.1,3700.1])
        with tempfile.TemporaryDirectory() as folder:
            telemetry=HourEnergy(collector=collector,source=source,
                expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),custody=Path(folder),
                run_id='a'*32,device_index=0,clock=lambda:next(clock))
            telemetry.begin()
            binding=telemetry.end()
            result=json.loads(telemetry.end_path.read_bytes())
            self.assertEqual(result['verdict'],'MEASURED')
            self.assertEqual(binding['hour_end_unix']-binding['hour_start_unix'],3600.)
            self.assertEqual(binding['result_sha256'],hashlib.sha256(telemetry.end_path.read_bytes()).hexdigest())

    def test_boundary_sequence_covers_checkpoint_cost(self):
        from cia_hour_energy import HourEnergy
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'boundary_energy_collector.py'
            source.write_text('fixture collector source')
            samples = iter([100., 3605.])
            events = []
            def begin(args):
                events.append('begin')
                Path(args.out).write_text(json.dumps({'verdict': 'SAMPLED'}))
                return 0
            def end(args):
                events.append(('end', args.hour_start_unix, args.hour_end_unix))
                self.assertEqual(args.boundary_source if hasattr(args, 'boundary_source') else None, None)
                Path(args.out).write_text(json.dumps({'verdict': 'MEASURED'}))
                return 0
            collector = SimpleNamespace(cmd_begin=begin, cmd_end=end)
            telemetry = HourEnergy(collector=collector, source=source,
                expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                custody=root, run_id='a'*32, device_index=0, clock=lambda:next(samples))
            telemetry.begin()
            events.extend(['updates', 'checkpoint', 'restore'])
            telemetry.end()
            self.assertEqual(events, ['begin', 'updates', 'checkpoint', 'restore', ('end',100.,3605.)])

    def test_changed_source_at_close_refuses(self):
        from cia_hour_energy import HourEnergy
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'collector.py'
            source.write_bytes(b'collector')
            def begin(args):
                Path(args.out).write_text(json.dumps({'verdict':'SAMPLED'}))
                return 0
            telemetry=HourEnergy(collector=SimpleNamespace(cmd_begin=begin), source=source,
                expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), custody=root,
                run_id='a'*32, device_index=0, clock=lambda:100.)
            telemetry.begin()
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'source changed'):
                telemetry.end()

    def test_refused_begin_prevents_window(self):
        from cia_hour_energy import HourEnergy
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'collector.py'
            source.write_bytes(b'collector')
            telemetry=HourEnergy(collector=SimpleNamespace(cmd_begin=lambda args:3), source=source,
                expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), custody=root,
                run_id='a'*32, device_index=0, clock=lambda:100.)
            with self.assertRaisesRegex(ValueError,'begin refused'):
                telemetry.begin()
            with self.assertRaisesRegex(ValueError,'not begun'):
                telemetry.end()

    def test_changed_collector_refuses_before_sampling(self):
        from cia_hour_energy import HourEnergy
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'collector.py'
            source.write_bytes(b'changed')
            telemetry=HourEnergy(collector=SimpleNamespace(), source=source,
                expected_sha256='0'*64, custody=root, run_id='a'*32, device_index=0)
            with self.assertRaisesRegex(ValueError,'source changed'):
                telemetry.begin()


if __name__=='__main__':
    unittest.main()
