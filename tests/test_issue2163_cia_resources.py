# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ember.governance.scripts import cia_conformance_resources as resources
from ember.governance.scripts.owned_process import OwnedProcessRunner


class ResourceTests(unittest.TestCase):
    def test_measurement_resource_namespace_is_distinct_and_numerical_defaults_remain(self):
        run_id = 'a' * 32
        self.assertEqual(resources.job_name(run_id), 'Local\\EmberCIAConformance-' + run_id)
        self.assertEqual(resources.job_name(run_id, namespace='EmberCIAMeasurement'),
                         'Local\\EmberCIAMeasurement-' + run_id)
        with self.assertRaises(ValueError):
            resources.job_name(run_id, namespace='other\\job')
        self.assertEqual(resources.ALLOCATOR_BYTES, 16 * 1024 ** 3)

    def test_selected_device_ceiling_is_explicit_without_changing_default(self):
        identity = 'GPU-ab12'
        sample = 'GPU-ab12, 24564, 19456'
        self.assertEqual(resources.parse_device_sample(sample, identity)['used_bytes'], 19 * 1024 ** 3)
        with self.assertRaises(ValueError):
            resources.parse_device_sample(sample, identity, total_gpu_bytes=18 * 1024 ** 3)
        for ceiling in [0, True, -1, 25 * 1024 ** 3]:
            with self.subTest(ceiling=ceiling), self.assertRaises(ValueError):
                resources.parse_device_sample(sample, identity, total_gpu_bytes=ceiling)

    def test_total_device_limits_and_identity(self):
        identity = 'GPU-ab12'
        good = resources.parse_device_sample('GPU-ab12, 24564, 900\n', identity)
        self.assertEqual(good['used_bytes'], 900 * 1024 ** 2)
        for text in ('GPU-other, 24564, 900', 'GPU-ab12, 24564, 20480',
                     'GPU-ab12, 24564, N/A', 'GPU-ab12, 1024, 900',
                     'GPU-ab12, 24564, 900\nGPU-ab12, 24564, 900',
                     'GPU-ab12, 24564, -1'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                resources.parse_device_sample(text, identity)

    @unittest.skipUnless(os.name == 'nt', 'Windows named job enforcement')
    def test_unowned_consumer_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            resources.require_owned_job(uuid.uuid4().hex)

    @unittest.skipUnless(os.name == 'nt', 'Windows named job enforcement')
    def test_actual_child_reads_back_its_named_job_limits(self):
        run_id = uuid.uuid4().hex
        code = f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); from ember.governance.scripts.cia_conformance_resources import require_owned_job; require_owned_job({run_id!r}); print('OWNED_CAP_VERIFIED')"
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
                   str(Path.home() / '.codex/headless-python.ps1'), '--', '-B', '-c', code]
        with patch.object(resources, 'sample_device', return_value={'used_bytes': 1}):
            result = OwnedProcessRunner(windows_job_factory=lambda: resources.ConformanceJob(run_id, 'GPU-ab12')).run(command, timeout_s=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OWNED_CAP_VERIFIED', result.stdout)
        self.assertTrue(result.cleanup_verified)

    @unittest.skipUnless(os.name == 'nt', 'Windows named job enforcement')
    def test_supervisor_failure_terminates_owned_child(self):
        jobs = []
        def factory():
            job = resources.ConformanceJob(uuid.uuid4().hex, 'GPU-ab12')
            jobs.append(job)
            return job
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
                   str(Path.home() / '.codex/headless-python.ps1'), '--', '-B', '-c',
                   'import time; time.sleep(30)']
        with patch.object(resources, 'sample_device', side_effect=[{'used_bytes': 1}, ValueError('injected unreadable total device')]):
            result = OwnedProcessRunner(windows_job_factory=factory).run(command, timeout_s=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.status, 'completed')
        self.assertTrue(result.cleanup_verified)
        self.assertIn('injected unreadable', jobs[0].failure)

    @unittest.skipUnless(os.name == 'nt', 'Windows named job enforcement')
    def test_failed_termination_uses_close_and_reports_containment_failure(self):
        jobs = []
        def factory():
            job = resources.ConformanceJob(uuid.uuid4().hex, 'GPU-ab12')
            jobs.append(job)
            return job
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
                   str(Path.home() / '.codex/headless-python.ps1'), '--', '-B', '-c',
                   'import time; time.sleep(30)']
        with patch.object(resources, 'sample_device', side_effect=[{'used_bytes': 1}, ValueError('injected query failure')]), patch.object(resources.owned_process._kernel32, 'TerminateJobObject', return_value=False):
            with self.assertRaisesRegex(resources.owned_process.ProcessContainmentError, 'TerminateJobObject failed'):
                OwnedProcessRunner(windows_job_factory=factory).run(command, timeout_s=10)
        self.assertIsNone(jobs[0]._handle)
        self.assertFalse(jobs[0]._watcher.is_alive())


if __name__ == '__main__':
    unittest.main()
