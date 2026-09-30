# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Executed fixtures for the GPU supervision failure branches of cia_conformance_resources.

A query that times out or exits nonzero observed nothing, so ResourceJob._watch tolerates
MAX_CONSECUTIVE_TIMEOUTS - 1 of them in a row and terminates on the next; the count resets after any valid sample.
A sample that PARSES and breaches, or is malformed or of another identity, is fatal at once: the threshold never
delays a real breach. No process is started: _watch runs against a job object built without a Windows handle.
"""
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ember.governance.scripts import cia_conformance_resources as resources

UUID = 'GPU-ab12'
MIB = 1024 ** 2
TOTAL = resources.TOTAL_GPU_BYTES


def timeout():
    return subprocess.TimeoutExpired(['nvidia-smi'], 3)


def nonzero():
    return subprocess.CalledProcessError(255, ['nvidia-smi'])


def valid_sample():
    return {'uuid': UUID, 'total_bytes': TOTAL + 1, 'used_bytes': 1}


class Script:
    """Feeds _watch one scripted outcome per second, then stops it. Each item is a sample dict or an exception."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def sample(self, uuid, *, total_gpu_bytes=None):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return dict(outcome)

    def stopped(self):
        stop = MagicMock()
        stop.wait.side_effect = lambda _seconds: self.calls >= len(self.outcomes)
        stop.is_set.return_value = False
        return stop


def watch(outcomes):
    """Run ResourceJob._watch over the scripted outcomes; return (job, terminate_mock, calls)."""
    script = Script(outcomes)
    job = object.__new__(resources.ResourceJob)
    job.samples, job.failure, job.gpu_uuid, job.total_gpu_bytes = [], None, UUID, TOTAL
    job._stop, job._handle_lock, job._handle, job._containment_error = script.stopped(), threading.RLock(), 1, None
    kernel = MagicMock()
    kernel.TerminateJobObject.return_value = True
    with patch.object(resources, 'sample_device', script.sample), patch.object(resources.owned_process, '_kernel32', kernel):
        job._watch()
    return job, kernel.TerminateJobObject, script.calls


class QueryFailureTolerance(unittest.TestCase):
    def test_the_constant_is_five_so_four_are_tolerated_and_the_fifth_terminates(self):
        self.assertEqual(resources.MAX_CONSECUTIVE_TIMEOUTS, 5)

    def test_a_four_query_failures_are_tolerated_and_the_fifth_terminates_with_code_125(self):
        job, terminate, calls = watch([timeout(), nonzero(), timeout(), nonzero(), timeout()])
        self.assertEqual(calls, 5)
        terminate.assert_called_once_with(1, 125)
        self.assertIn('5 consecutive GPU queries observed nothing', job.failure)

    def test_a2_four_failures_then_stop_do_not_terminate(self):
        job, terminate, calls = watch([timeout(), timeout(), nonzero(), timeout()])
        self.assertEqual(calls, 4)
        terminate.assert_not_called()
        self.assertIsNone(job.failure)
        self.assertEqual(job.timeouts_tolerated, 4)

    def test_b_the_count_resets_after_a_valid_sample(self):
        job, terminate, calls = watch([timeout(), timeout(), valid_sample(), timeout(), timeout(), timeout(), timeout(), valid_sample()])
        self.assertEqual(calls, 8)
        terminate.assert_not_called()
        self.assertIsNone(job.failure)
        self.assertEqual(len(job.samples), 2)

    def test_b2_without_the_reset_the_same_run_would_have_terminated_after_a_valid_sample_then_five(self):
        job, terminate, calls = watch([timeout(), valid_sample(), timeout(), timeout(), timeout(), timeout(), timeout()])
        self.assertEqual(calls, 7)
        terminate.assert_called_once_with(1, 125)


class ImmediateFailures(unittest.TestCase):
    def test_c_a_valid_over_limit_sample_refuses_immediately_with_no_retry_grace(self):
        """Deliberate red for the threshold: a real breach is never delayed by the tolerance."""
        stdout = f'{UUID}, {(TOTAL + 4096 * MIB) // MIB}, {(TOTAL + MIB) // MIB}\n'
        job = object.__new__(resources.ResourceJob)
        job.samples, job.failure, job.gpu_uuid, job.total_gpu_bytes = [], None, UUID, TOTAL
        calls = []

        def real_parse_sample(uuid, *, total_gpu_bytes=None):
            calls.append(1)
            return resources.parse_device_sample(stdout, uuid, total_gpu_bytes=TOTAL)

        stop = MagicMock()
        stop.wait.side_effect = lambda _s: len(calls) >= 10
        stop.is_set.return_value = False
        job._stop, job._handle_lock, job._handle, job._containment_error = stop, threading.RLock(), 1, None
        kernel = MagicMock()
        kernel.TerminateJobObject.return_value = True
        with patch.object(resources, 'sample_device', real_parse_sample), patch.object(resources.owned_process, '_kernel32', kernel):
            job._watch()
        self.assertEqual(len(calls), 1, 'a breaching sample must be fatal at the first observation')
        kernel.TerminateJobObject.assert_called_once_with(1, 125)
        self.assertIn('total-device memory envelope exceeded', job.failure)

    def test_d_malformed_and_identity_samples_raise_at_once(self):
        for text in (f'{UUID}, x, 1\n', f'{UUID}, 1\n', 'GPU-other, 100, 1\n', f'{UUID}, 100, 1\n{UUID}, 100, 1\n', ''):
            with self.assertRaises(ValueError, msg=text):
                resources.parse_device_sample(text, UUID, total_gpu_bytes=TOTAL)

    def test_d_a_malformed_sample_inside_the_watcher_is_fatal_at_the_first_observation(self):
        job, terminate, calls = watch([ValueError('GPU identity changed or sample malformed'), valid_sample()])
        self.assertEqual(calls, 1)
        terminate.assert_called_once_with(1, 125)
        self.assertEqual(job.failure, 'GPU identity changed or sample malformed')


class LaunchRetry(unittest.TestCase):
    def test_launch_retries_only_query_failures_up_to_five_attempts_then_raises_the_last(self):
        errors = [timeout(), nonzero(), timeout(), timeout(), nonzero()]
        with patch.object(resources, 'sample_device', side_effect=errors) as mocked:
            with self.assertRaises(subprocess.CalledProcessError):
                resources.sample_device_at_launch(UUID)
        self.assertEqual(mocked.call_count, 5)

    def test_launch_returns_the_first_valid_sample_and_does_not_retry_a_value_error(self):
        with patch.object(resources, 'sample_device', side_effect=[timeout(), valid_sample()]) as mocked:
            self.assertEqual(resources.sample_device_at_launch(UUID)['uuid'], UUID)
        self.assertEqual(mocked.call_count, 2)
        with patch.object(resources, 'sample_device', side_effect=[ValueError('breach'), valid_sample()]) as mocked:
            with self.assertRaises(ValueError):
                resources.sample_device_at_launch(UUID)
        self.assertEqual(mocked.call_count, 1)


if __name__ == '__main__':
    unittest.main()
