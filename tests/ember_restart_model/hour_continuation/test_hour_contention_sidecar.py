# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The hour binds co-tenant attribution (A) and a waiting headroom gate (lead rulings 81910 / 81914 / 81915).

Evidence only: the sampler and its sidecar never change a row, a pin or the hour's outcome, and a shortage of host reserve
waits with a bounded logged backoff before it refuses."""
import hour_test_support
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cia_hour
import cia_step_runner as runner


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class SourceClosure(unittest.TestCase):
    def test_contention_module_is_in_the_hour_source_set(self):
        entry = 'src/ember/infrastructure/tools/ember-restart-3b/cia_contention.py'
        self.assertIn(entry, runner.HOUR_SOURCES)
        self.assertTrue((runner.ROOT / entry).is_file())
        self.assertEqual(runner.CONTENTION_ENTRY, entry)


class WaitingHeadroom(unittest.TestCase):
    def test_short_reserve_waits_with_a_logged_backoff_then_proceeds(self):
        contention = runner.load_contention_module()
        clock, calls, events = FakeClock(), [], []
        answers = [contention.ReserveUnavailable('measurement operating reserve is unavailable')] * 3 + [{'free_commit_bytes': 1}]

        def headroom():
            calls.append(clock.now)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        with mock.patch.object(runner, 'headroom', headroom):
            value = runner.wait_headroom(sleep=clock.sleep, clock=clock, log=events.append)
        self.assertEqual(value, {'free_commit_bytes': 1})
        self.assertEqual(clock.sleeps, [1, 2, 4])
        self.assertEqual([e['attempt'] for e in events], [1, 2, 3])

    def test_a_shortage_that_never_clears_ends_in_a_named_refusal(self):
        contention = runner.load_contention_module()
        clock = FakeClock()

        def headroom():
            raise contention.ReserveUnavailable('measurement operating reserve is unavailable')
        with mock.patch.object(runner, 'headroom', headroom):
            with self.assertRaises(ValueError) as caught:
                runner.wait_headroom(sleep=clock.sleep, clock=clock, max_wait=60)
        self.assertIn('still short after', str(caught.exception))
        self.assertIn('measurement operating reserve is unavailable', str(caught.exception))

    def test_any_other_failure_is_not_waited_on(self):
        clock = FakeClock()

        def headroom():
            raise ValueError('cannot read system commit headroom')
        with mock.patch.object(runner, 'headroom', headroom):
            with self.assertRaisesRegex(ValueError, 'cannot read system commit headroom'):
                runner.wait_headroom(sleep=clock.sleep, clock=clock)
        self.assertEqual(clock.sleeps, [])

    @unittest.skipUnless(os.name == 'nt', 'headroom reads the Windows commit counters')
    def test_the_real_gate_raises_a_waitable_error_when_the_reserve_is_short(self):
        contention = runner.load_contention_module()
        with mock.patch.dict(runner.LIMITS, {'min_free_commit_bytes': 1 << 62}):
            with self.assertRaises(contention.ReserveUnavailable):
                runner.headroom()
        self.assertTrue(issubclass(contention.ReserveUnavailable, ValueError))

    def test_all_three_call_sites_wait(self):
        text = (runner.ROOT / runner.ENTRY).read_text(encoding='utf-8')
        self.assertEqual(text.count('wait_headroom()'), 3)
        # the only bare call left is the definition's own use inside wait_for_reserve
        bare = [line for line in text.splitlines() if line.strip() in ('headroom()', 'preflight = headroom()')]
        self.assertEqual(bare, [])


class AttributionSidecar(unittest.TestCase):
    def test_sampler_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {'EMBER_CONTENTION_SAMPLER': '0'}):
            self.assertIsNone(cia_hour.start_contention_sampler('cpu'))

    def test_receipt_splits_raw_and_uncontended_and_names_its_calibration(self):
        contention = runner.load_contention_module()
        written = {}
        fake_runner = mock.Mock(_write_new=lambda path, value: written.update(path=path, value=value))
        sampler = contention.ContentionSampler(lambda: {'foreign_gpu_bytes': 0, 'cpu_other_percent': 1.0})
        read = mock.Mock(overhead_bytes=lambda: 123)
        rows = [dict(update=2, positions_per_second=100.0, contention={'known': True, 'contended': False, 'reasons': []}),
                dict(update=3, positions_per_second=50.0, contention={'known': True, 'contended': True, 'reasons': ['foreign_gpu_bytes']}),
                dict(update=4, positions_per_second=80.0, contention={'known': False, 'contended': False, 'reasons': []})]
        cia_hour.file_contention_attribution(fake_runner, Path('custody'), (sampler, read), rows)
        value = written['value']
        self.assertEqual(written['path'], Path('custody') / 'contention-attribution.json')
        self.assertEqual(value['schema'], 'ember-contention-attribution-v1')
        self.assertAlmostEqual(value['raw_positions_per_second_mean'], 230 / 3)
        self.assertEqual((value['uncontended_positions_per_second_mean'], value['contended_positions_per_second_mean']), (100.0, 50.0))
        self.assertEqual((value['unknown_updates'], value['overhead_bytes_final']), (1, 123))
        self.assertEqual(value['overhead_calibration'], 'running_minimum_outside_this_allocator')

    def test_no_sampler_writes_nothing(self):
        fake_runner = mock.Mock()
        cia_hour.file_contention_attribution(fake_runner, Path('custody'), None, [])
        fake_runner._write_new.assert_not_called()

    def test_a_failing_sidecar_write_is_named_and_never_raised(self):
        contention = runner.load_contention_module()
        fake_runner = mock.Mock(_write_new=mock.Mock(side_effect=FileExistsError('already there')))
        sampler = contention.ContentionSampler(lambda: {'foreign_gpu_bytes': 0, 'cpu_other_percent': None})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            cia_hour.file_contention_attribution(fake_runner, Path('custody'), (sampler, mock.Mock(overhead_bytes=lambda: 0)), [])
        self.assertIn('CONTENTION_ATTRIBUTION_DEGRADED FileExistsError', err.getvalue())

    def test_unreadable_card_makes_every_update_unknown_and_never_contended(self):
        import torch
        contention = runner.load_contention_module()
        if torch.cuda.is_available():
            self.skipTest('this red needs a card that cannot be queried')
        started = cia_hour.start_contention_sampler(torch.device('cpu'))
        self.assertIsNotNone(started)
        sampler, read = started
        sampler.stop()
        self.assertGreaterEqual(sampler.errors, 1)
        verdict = sampler.classify(0.0, 1e9)
        self.assertEqual(verdict, {'known': False, 'contended': False, 'reasons': [], 'samples': 0})

    def test_classification_stays_correct_over_a_long_history(self):
        contention = runner.load_contention_module()
        clock = FakeClock()
        gpu = {'bytes': 0}
        sampler = contention.ContentionSampler(lambda: {'foreign_gpu_bytes': gpu['bytes'], 'cpu_other_percent': 0.0},
                                               clock=clock, keep=7200)
        for second in range(5000):
            clock.now = float(second)
            gpu['bytes'] = contention.FOREIGN_GPU_BYTES if 4000 <= second < 4010 else 0
            sampler.sample_once()
        self.assertFalse(sampler.classify(4500.0, 4501.0)['contended'])
        window = sampler.classify(4005.5, 4006.5)
        self.assertTrue(window['contended'] and window['reasons'] == ['foreign_gpu_bytes'])
        self.assertEqual(window['samples'], 2)                   # the one just before t0 plus the one inside
        self.assertTrue(sampler.classify(4009.5, 4010.5)['contended'])    # the sample just before t0 (4009) counts
        self.assertFalse(sampler.classify(4010.5, 4011.5)['contended'])   # before = 4010, already clear
        self.assertEqual(sampler.classify(1.5, 2.5)['samples'], 2)
        self.assertFalse(sampler.classify(1.5, 2.5)['contended'])
        # a window past the newest sample still sees the newest as 'just before'; nothing is invented for t > newest
        self.assertEqual(sampler.classify(9000.0, 9001.0)['samples'], 1)


if __name__ == '__main__':
    unittest.main()
