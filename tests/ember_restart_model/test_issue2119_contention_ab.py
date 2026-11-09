# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contention attribution (A) and elastic retry (B): lead rulings 81910 / 81915 (2026-11-09).

(A) a step is tagged contended only by a measured foreign GPU holder or foreign CPU use; unknown is never contended; the
    receipt splits raw from uncontended throughput. (B) an update that hits CUDA out-of-memory before its optimizer step is
    replayed on the SAME pack in smaller micro-steps and yields the same gradient up to accumulation order; a failure
    after the optimizer step began is not replayed; a shortage of host reserve waits with a bounded logged backoff.
The CUDA red at the bottom needs a card window: it refuses unless EMBER_CUDA_REDS=1.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
import cia_contention as cc

GIB = 1024 ** 3


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class OutOfMemoryError(RuntimeError):
    """Named like torch.cuda.OutOfMemoryError so is_oom() sees it without a GPU."""


def make_model():
    torch.manual_seed(7)
    return torch.nn.Linear(6, 3)


def make_data(rows=8):
    torch.manual_seed(11)
    return torch.randn(rows, 6), torch.randn(rows, 3)


def accumulate(model, x, y, micro):
    """The update's gradient: the loss is a row SUM, accumulated micro-step by micro-step."""
    for lo in range(0, len(x), micro):
        loss = ((model(x[lo:lo + micro]) - y[lo:lo + micro]) ** 2).sum()
        loss.backward()


def reference_grads():
    model = make_model()
    x, y = make_data()
    accumulate(model, x, y, len(x))
    return [p.grad.clone() for p in model.parameters()]


class ElasticReplay(unittest.TestCase):
    def build(self, fail_at_micro=None, fail_after_partial=False, free=lambda: 64 * GIB, **kw):
        model = make_model()
        x, y = make_data()
        calls = []

        def step(pack, micro, mark):
            calls.append(micro)
            if micro == fail_at_micro or (isinstance(fail_at_micro, (set, tuple)) and micro in fail_at_micro):
                if fail_after_partial:
                    loss = ((model(x[:micro]) - y[:micro]) ** 2).sum()
                    loss.backward()   # stale partial gradient that a correct reset must remove
                raise OutOfMemoryError('CUDA out of memory. Tried to allocate 2.00 GiB')
            accumulate(model, x, y, micro)
            mark()
            return {'positions_per_second': 100.0, 'micro': micro}

        def reset():
            for p in model.parameters():
                p.grad = None
        elastic = cc.ElasticStep(step, reset=reset, free_bytes=free, floor_bytes=8 * GIB, sleep=lambda s: None, **kw)
        return model, elastic, calls

    def test_oom_at_four_replays_the_same_pack_at_two_with_the_same_gradient(self):
        model, elastic, calls = self.build(fail_at_micro=4, fail_after_partial=True)
        row = elastic.run('pack', update=0)
        self.assertEqual(calls, [4, 2])
        self.assertEqual(row['elastic']['micro_documents'], 2)
        self.assertEqual([e['kind'] for e in row['elastic']['events']], ['throttle'])
        for got, want in zip((p.grad for p in model.parameters()), reference_grads()):
            self.assertTrue(torch.allclose(got, want, atol=1e-5), 'replay must equal the unsplit gradient (stale partial grads removed)')

    def test_oom_down_the_whole_ladder_ends_at_one_document(self):
        model, elastic, calls = self.build(fail_at_micro={4, 2})
        row = elastic.run('pack', update=3)
        self.assertEqual(calls, [4, 2, 1])
        self.assertEqual(row['elastic']['micro_documents'], 1)
        for got, want in zip((p.grad for p in model.parameters()), reference_grads()):
            self.assertTrue(torch.allclose(got, want, atol=1e-5))

    def test_failure_after_the_optimizer_step_began_is_not_replayed(self):
        calls = []

        def step(pack, micro, mark):
            calls.append(micro)
            mark()
            raise OutOfMemoryError('CUDA out of memory during optimizer step')
        elastic = cc.ElasticStep(step, reset=lambda: self.fail('no reset after the step began'),
                                 free_bytes=lambda: 64 * GIB, floor_bytes=GIB, sleep=lambda s: None)
        with self.assertRaises(cc.UpdatePartiallyApplied):
            elastic.run('pack', update=0)
        self.assertEqual(calls, [4])

    def test_a_non_oom_error_propagates_untouched(self):
        def step(pack, micro, mark):
            raise ValueError('shape mismatch')
        elastic = cc.ElasticStep(step, reset=lambda: self.fail('no reset for a non-oom error'),
                                 free_bytes=lambda: 64 * GIB, floor_bytes=GIB, sleep=lambda s: None)
        with self.assertRaisesRegex(ValueError, 'shape mismatch'):
            elastic.run('pack', update=0)

    def test_oom_at_the_smallest_micro_backs_off_then_exhausts_with_the_events(self):
        slept = []

        def step(pack, micro, mark):
            raise OutOfMemoryError('CUDA out of memory')
        elastic = cc.ElasticStep(step, reset=lambda: None, free_bytes=lambda: 64 * GIB, floor_bytes=GIB,
                                 sleep=slept.append, max_bottom_replays=3)
        with self.assertRaises(cc.ElasticExhausted) as raised:
            elastic.run('pack', update=0)
        self.assertEqual(slept, [1, 2, 4])
        self.assertEqual([e['kind'] for e in raised.exception.events], ['throttle', 'throttle', 'bottom_replay', 'bottom_replay', 'bottom_replay', 'bottom_replay'])

    def test_low_headroom_throttles_before_the_step_and_clean_updates_grow_back(self):
        free = {'value': 2 * GIB}
        model, elastic, calls = self.build(free=lambda: free['value'], grow_after=3)
        row = elastic.run('pack', update=0)
        self.assertEqual((calls, row['elastic']['micro_documents']), ([2], 2))
        self.assertEqual(row['elastic']['events'][0]['reason'], 'headroom')
        for update in (1, 2, 3):   # headroom still low: one rung per update down to the bottom, never past it, never a grow
            row = elastic.run('pack', update=update)
        self.assertEqual((elastic.rung, row['elastic']['micro_documents']), (2, 1))
        self.assertNotIn('grow', [e['kind'] for e in row['elastic']['events']])
        free['value'] = 12 * GIB   # above the floor but below twice the floor: clean updates never grow
        for update in (4, 5, 6, 7):
            elastic.run('pack', update=update)
        self.assertEqual(elastic.rung, 2)
        free['value'] = 40 * GIB
        grown = [elastic.run('pack', update=u) for u in range(8, 14)]
        self.assertEqual(elastic.rung, 0, 'grow_after clean updates with recovered headroom step back up one rung at a time')
        grow_updates = [i for i, r in enumerate(grown) if any(e['kind'] == 'grow' for e in r['elastic']['events'])]
        self.assertEqual(len(grow_updates), 2)

    def test_ladder_must_be_strictly_decreasing(self):
        with self.assertRaises(ValueError):
            cc.ElasticStep(lambda *a: {}, reset=lambda: None, free_bytes=lambda: 0, floor_bytes=0, ladder=(2, 4))


class ReserveWait(unittest.TestCase):
    def test_short_reserve_backs_off_on_the_schedule_then_returns(self):
        clock, state = FakeClock(), {'n': 0}
        log = []

        def check():
            state['n'] += 1
            if state['n'] <= 3:
                raise cc.ReserveUnavailable('measurement operating reserve is unavailable')
            return {'free_commit_bytes': 50 * GIB}
        value, waited = cc.wait_for_reserve(check, sleep=clock.sleep, clock=clock, log=log.append)
        self.assertEqual(value['free_commit_bytes'], 50 * GIB)
        self.assertEqual(clock.sleeps, [1, 2, 4])
        self.assertEqual(waited['attempts'], 3)
        self.assertEqual([e['attempt'] for e in log], [1, 2, 3])

    def test_a_reserve_that_never_clears_ends_in_a_bounded_named_refusal(self):
        clock = FakeClock()

        def check():
            raise cc.ReserveUnavailable('free commit below floor')
        with self.assertRaisesRegex(cc.ReserveUnavailable, r'still short after \d+ s and \d+ reads'):
            cc.wait_for_reserve(check, sleep=clock.sleep, clock=clock, max_wait=100)
        self.assertLessEqual(clock.now, 100 + max(cc.BACKOFF_SECONDS))
        self.assertEqual(clock.sleeps[:6], [1, 2, 4, 8, 16, 30])
        self.assertEqual(set(clock.sleeps[5:]), {30}, 'the last schedule value repeats')

    def test_any_other_error_is_not_waited_on(self):
        clock = FakeClock()

        def check():
            raise ValueError('measurement resource envelope requires Windows')
        with self.assertRaisesRegex(ValueError, 'requires Windows'):
            cc.wait_for_reserve(check, sleep=clock.sleep, clock=clock)
        self.assertEqual(clock.sleeps, [])


class Attribution(unittest.TestCase):
    def sampler(self, readings):
        clock = FakeClock()
        feed = iter(readings)
        sampler = cc.ContentionSampler(lambda: next(feed), clock=clock)
        return sampler, clock

    def test_foreign_gpu_holder_marks_the_window_contended(self):
        sampler, clock = self.sampler([{'foreign_gpu_bytes': 0, 'cpu_other_percent': 3.0},
                                       {'foreign_gpu_bytes': 3 * GIB, 'cpu_other_percent': 4.0},
                                       {'foreign_gpu_bytes': 0, 'cpu_other_percent': 2.0}])
        for _ in range(3):
            sampler.sample_once()
            clock.now += 1
        quiet, busy = sampler.classify(-0.5, 0.5), sampler.classify(0.9, 1.1)
        self.assertEqual((quiet['known'], quiet['contended']), (True, False))
        self.assertEqual((busy['contended'], busy['reasons']), (True, ['foreign_gpu_bytes']))

    def test_foreign_cpu_alone_marks_the_window_contended(self):
        sampler, clock = self.sampler([{'foreign_gpu_bytes': 0, 'cpu_other_percent': 60.0}])
        sampler.sample_once()
        result = sampler.classify(0.0, 1.0)
        self.assertEqual((result['contended'], result['reasons']), (True, ['cpu_other_percent']))

    def test_no_sample_is_unknown_and_never_contended(self):
        sampler, _ = self.sampler([])
        self.assertEqual(sampler.classify(0, 1), {'known': False, 'contended': False, 'reasons': [], 'samples': 0})

    def test_a_failing_read_is_counted_not_raised(self):
        def broken():
            raise OSError('nvidia-smi timed out')
        sampler = cc.ContentionSampler(broken, clock=FakeClock())
        self.assertIsNone(sampler.sample_once())
        self.assertEqual(sampler.errors, 1)

    def test_receipt_splits_raw_from_uncontended_and_counts_unknown_apart(self):
        def row(rate, known, contended, reasons=()):
            return {'positions_per_second': rate, 'contention': {'known': known, 'contended': contended, 'reasons': list(reasons)}}
        rows = [row(100.0, True, False), row(110.0, True, False), row(60.0, True, True, ['foreign_gpu_bytes']),
                row(90.0, False, False)]
        receipt = cc.attribution_receipt(rows, sampler_errors=2)
        self.assertAlmostEqual(receipt['raw_positions_per_second_mean'], 90.0)
        self.assertAlmostEqual(receipt['uncontended_positions_per_second_mean'], 105.0)
        self.assertAlmostEqual(receipt['contended_positions_per_second_mean'], 60.0)
        self.assertEqual((receipt['unknown_updates'], receipt['contended_updates'], receipt['uncontended_updates']), (1, 1, 2))
        self.assertAlmostEqual(receipt['contended_fraction'], 1 / 3)
        self.assertEqual((receipt['contention_reasons'], receipt['sampler_errors']), ({'foreign_gpu_bytes': 1}, 2))

    def test_default_reader_reports_only_holding_above_the_calibrated_overhead(self):
        usage = {'free': 22 * GIB}
        read = cc.default_reader(mem_info=lambda: (usage['free'], 24 * GIB), own_reserved=lambda: 1 * GIB,
                                 overhead_bytes=1 * GIB, system_cpu=type('Cpu', (), {'busy_percent': lambda self: 10.0})())
        self.assertEqual(read()['foreign_gpu_bytes'], 0)            # 2 GiB used = 1 own + 1 desktop overhead
        usage['free'] = 12 * GIB                                    # a co-tenant takes 10 GiB
        self.assertEqual(read()['foreign_gpu_bytes'], 10 * GIB)

    def test_uncalibrated_reader_uses_the_running_minimum_as_its_baseline(self):
        usage = {'free': 21 * GIB}                                  # 3 GiB used, 1 own: 2 GiB held outside the allocator
        read = cc.default_reader(mem_info=lambda: (usage['free'], 24 * GIB), own_reserved=lambda: 1 * GIB,
                                 system_cpu=type('Cpu', (), {'busy_percent': lambda self: 10.0})())
        self.assertEqual(read()['foreign_gpu_bytes'], 0)            # the first sample is the baseline
        usage['free'] = 20 * GIB                                    # 1 GiB more held: foreign
        self.assertEqual(read()['foreign_gpu_bytes'], 1 * GIB)
        usage['free'] = 22 * GIB                                    # holding falls below the baseline: baseline follows it
        self.assertEqual(read()['foreign_gpu_bytes'], 0)
        self.assertEqual(read.overhead_bytes(), 1 * GIB)
        usage['free'] = 19 * GIB
        self.assertEqual(read()['foreign_gpu_bytes'], 3 * GIB)

    def test_fixed_overhead_is_never_recalibrated(self):
        usage = {'free': 23 * GIB}
        read = cc.default_reader(mem_info=lambda: (usage['free'], 24 * GIB), own_reserved=lambda: 0,
                                 overhead_bytes=1 * GIB, system_cpu=type('Cpu', (), {'busy_percent': lambda self: 1.0})())
        self.assertEqual(read()['foreign_gpu_bytes'], 0)
        usage['free'] = 24 * GIB                                    # holding below the fixed overhead stays zero, baseline fixed
        self.assertEqual(read()['foreign_gpu_bytes'], 0)
        usage['free'] = 22 * GIB
        self.assertEqual(read()['foreign_gpu_bytes'], 1 * GIB)
        self.assertEqual(read.overhead_bytes(), 1 * GIB)

    def test_process_cpu_is_a_share_of_the_whole_machine(self):
        wall, cpu = [0.0], [0.0]
        meter = cc.ProcessCpu(clock=lambda: wall[0], cpu_time=lambda: cpu[0], cpus=8)
        wall[0], cpu[0] = 2.0, 4.0                                  # four CPU-seconds in two wall seconds on 8 CPUs
        self.assertAlmostEqual(meter.percent(), 25.0)
        wall[0], cpu[0] = 3.0, 4.0                                  # idle second
        self.assertAlmostEqual(meter.percent(), 0.0)
        self.assertEqual(meter.percent(), 0.0)                      # no time passed: zero, not a division error

    def test_other_cpu_is_system_busy_minus_this_process(self):
        read = cc.default_reader(mem_info=lambda: (23 * GIB, 24 * GIB), own_reserved=lambda: 0,
                                 own_cpu_percent=lambda: 30.0,
                                 system_cpu=type('Cpu', (), {'busy_percent': lambda self: 50.0})())
        self.assertAlmostEqual(read()['cpu_other_percent'], 20.0)


@unittest.skipUnless(torch.cuda.is_available(), 'CUDA')
class CudaCoTenantRed(unittest.TestCase):
    """A real foreign process fills the card; the elastic step must finish the update at a smaller micro-step and the
    attribution sampler must call it contended. Needs a card window: refuses unless EMBER_CUDA_REDS=1."""

    def test_real_gpu_filling_cotenant_forces_a_throttle_and_is_attributed(self):
        if os.environ.get('EMBER_CUDA_REDS') != '1':
            self.skipTest('needs a card window: set EMBER_CUDA_REDS=1 inside one')
        device = torch.device('cuda:0')
        free0, total = torch.cuda.mem_get_info(device)
        overhead = total - free0 - torch.cuda.memory_reserved(device)
        # Documents are 'rows' of a wide layer so one micro-step of 4 needs more than the co-tenant leaves free.
        width = 4096
        layer = torch.nn.Linear(width, width).to(device)
        x = torch.randn(8, 2048, width, device=device)
        per_row = 2048 * width * 4 * 6
        leave = int(per_row * 2.5)   # room for 2 rows of activations, not 4

        def step(pack, micro, mark):
            layer.zero_grad(set_to_none=True)
            for lo in range(0, len(x), micro):
                layer(x[lo:lo + micro]).float().pow(2).sum().backward()
            torch.cuda.synchronize()
            mark()
            return {'positions_per_second': 1.0}

        def reset():
            layer.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()

        # Uncontended baseline (warm once, time once), then release the cache so the filler sizes against a clean card and
        # the contended step has to allocate beside it (a cached block would hide the shortage).
        step('pack', 8, lambda: None)
        started_at = time.perf_counter()
        step('pack', 8, lambda: None)
        uncontended_seconds = time.perf_counter() - started_at
        reset()
        # No -I: this host installs torch in the user site, which isolated mode drops, so the filler could not import it.
        filler = subprocess.Popen([sys.executable, '-B', '-c', (
            'import torch,time,sys\n'
            'd=torch.device("cuda:0");f,t=torch.cuda.mem_get_info(d)\n'
            # fill_ touches every page: on this Windows (WDDM) host an untouched torch.empty is reserved but not resident, so
            # mem_get_info keeps reporting the card as free (the 2026-11-09 06:14Z run saw 23.7 GB free beside a "FILLED" filler).
            'k=torch.empty(max(0,f-%d-%d),dtype=torch.uint8,device=d);k.fill_(1);torch.cuda.synchronize();print("FILLED",k.numel(),flush=True);time.sleep(120)\n' % (leave, 512 * 1024 ** 2))],
            stdout=subprocess.PIPE, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            filled = filler.stdout.readline().split()
            self.assertEqual(filled[:1], ['FILLED'])
            filler_bytes = int(filled[1])
            read = cc.default_reader(mem_info=lambda: torch.cuda.mem_get_info(device), own_reserved=lambda: torch.cuda.memory_reserved(device),
                                     overhead_bytes=overhead)
            sampler = cc.ContentionSampler(read)
            started = sampler._clock()
            sampler.sample_once()

            # The floor is the 8-row step's own need (activations + grads, 6 float tensors of one row each): the headroom
            # trigger must fire when the co-tenant leaves less than that. On this Windows host the driver may spill an
            # over-full allocation to system memory instead of raising out-of-memory, so the OOM trigger alone cannot be
            # relied on (the first card run, 2026-11-09 06:02Z, ran the 8-row step beside the filler with no OOM at all).
            floor = per_row * 8
            free_beside = torch.cuda.mem_get_info(device)[0]
            elastic = cc.ElasticStep(step, reset=reset, free_bytes=lambda: torch.cuda.mem_get_info(device)[0], floor_bytes=floor,
                                     ladder=(8, 4, 2, 1), sleep=lambda s: None)
            row = elastic.run('pack', update=0)
            sampler.sample_once()
            verdict = sampler.classify(started, sampler._clock())
            # The 2026-11-09 card runs (06:02Z, 06:14Z, 06:24Z) showed that on this WDDM host a resident co-tenant need not be
            # visible to mem_get_info (22.5 GB "free" beside a filler that had touched ~21.5 GB). So this red does not demand
            # a throttle from a signal the host may not give: it demands the update completes, and that IF the headroom is
            # visible THEN the throttle fires and the sampler calls it contended. What the host showed is recorded below.
            headroom_visible = free_beside < floor
            self.assertIn(row['elastic']['micro_documents'], (8, 4, 2, 1), row['elastic'])
            if headroom_visible:
                self.assertLess(row['elastic']['micro_documents'], 8, 'the 8-row micro-step cannot fit beside the co-tenant')
                self.assertTrue(any(e['reason'] in ('headroom', 'oom') for e in row['elastic']['events']), row['elastic'])
                self.assertTrue(verdict['contended'], verdict)
            # Measured facts for the record (not assertions): does the un-throttled 8-row step raise OOM beside the filler, and
            # how much slower is it than the uncontended baseline? A driver that spills to system memory shows up as the latter.
            probe = {'free_beside_bytes': free_beside, 'floor_bytes': floor, 'events': row['elastic']['events'],
                     'filler_bytes': filler_bytes, 'headroom_visible': headroom_visible, 'sampler_contended': verdict['contended'],
                     'throttled': row['elastic']['micro_documents'] < 8, 'uncontended_8_row_seconds': uncontended_seconds}
            reset()
            # Can this process still allocate more than the visible headroom beside the filler? A success while mem_get_info
            # says the card is nearly full means the driver is oversubscribing (paging the co-tenant out); the cost then
            # shows as step time, not as a shortage.
            started_at = time.perf_counter()
            try:
                extra = torch.empty(4 * GIB, dtype=torch.uint8, device=device)
                extra.fill_(2)
                torch.cuda.synchronize()
                probe['extra_4_gib_allocated'] = True
                del extra
            except BaseException as error:
                if not cc.is_oom(error):
                    raise
                probe['extra_4_gib_allocated'] = False
            probe['extra_4_gib_seconds'] = time.perf_counter() - started_at
            reset()
            started_at = time.perf_counter()
            try:
                step('pack', 8, lambda: None)
                probe['unthrottled_8_row_oom'] = False
            except BaseException as error:
                if not cc.is_oom(error):
                    raise
                probe['unthrottled_8_row_oom'] = True
            probe['unthrottled_8_row_seconds'] = time.perf_counter() - started_at
            probe['slowdown_x'] = probe['unthrottled_8_row_seconds'] / max(uncontended_seconds, 1e-9)
            print('CUDA_COTENANT_PROBE ' + json.dumps(probe, sort_keys=True), flush=True)
        finally:
            filler.kill()
            filler.wait()


if __name__ == '__main__':
    unittest.main()
