# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contention attribution (A) and elastic retry (B) for the governed step loop (lead rulings 81910 / 81915, 2026-11-09).

A training hour shares the host with other lanes (a browser, a data job, a second tenant). Two things follow:

(A) Attribution. Every update row can be tagged with what else was using the machine while it ran, so the throughput
    receipt reports raw positions per second AND the uncontended rate, and the difference is measured instead of guessed.
(B) Elasticity. A shortage the run did not cause (a co-tenant took GPU memory, commit ran low) must slow the run, never
    kill it. An update that hits CUDA out-of-memory before its optimizer step is replayed on the SAME pack in smaller
    micro-steps (documents per micro-step 4 -> 2 -> 1); the effective batch, and so the loss sum, is unchanged up to
    accumulation order. A shortage of host commit or disk waits with a bounded, logged backoff instead of raising.

This module holds only the policy. It imports no torch at import time and opens no checkpoint, so it is testable on a
tiny model and on the CPU. The step loop binds it by passing a ``step(pack, micro_documents, mark_update)`` callable.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from collections import deque

FOREIGN_GPU_BYTES = 256 * 1024 ** 2      # a foreign GPU holder at or above this marks a step contended
FOREIGN_CPU_PERCENT = 25.0               # non-run CPU use at or above this marks a step contended
SAMPLE_SECONDS = 1.0
LADDER = (4, 2, 1)                       # documents per micro-step; documents per update never changes
GROW_AFTER_CLEAN = 8                     # clean updates before a throttled run steps back up one rung
MAX_BOTTOM_REPLAYS = 3                   # out-of-memory replays at the smallest micro-step before giving up
BACKOFF_SECONDS = (1, 2, 4, 8, 16, 30)   # then the last value repeats
BACKOFF_MAX_SECONDS = 1800               # a wait for host reserve is bounded; it ends in a named refusal


class ReserveUnavailable(ValueError):
    """A host reserve (commit, disk) is short right now. Waitable: the caller backs off and re-reads."""


class ElasticExhausted(RuntimeError):
    """Out-of-memory persisted at the smallest micro-step through every bounded replay."""

    def __init__(self, message, events):
        super().__init__(message)
        self.events = events


class UpdatePartiallyApplied(RuntimeError):
    """The failure came after the optimizer step began, so the update cannot be replayed."""


def is_oom(error):
    """True for a CUDA out-of-memory error without importing torch."""
    if type(error).__name__ == 'OutOfMemoryError':
        return True
    return isinstance(error, RuntimeError) and 'out of memory' in str(error).lower()


# ---------------------------------------------------------------- (A) attribution

class SystemCpu:
    """Whole-machine busy percent from GetSystemTimes deltas; None off Windows or on a failed read."""

    def __init__(self):
        self._previous = None

    @staticmethod
    def _read():
        if os.name != 'nt':
            return None
        idle, kernel, user = (ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong())
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return idle.value, kernel.value + user.value   # kernel time includes idle

    def busy_percent(self):
        now = self._read()
        previous, self._previous = self._previous, now
        if now is None or previous is None:
            return None
        idle, total = now[0] - previous[0], now[1] - previous[1]
        return None if total <= 0 else max(0.0, min(100.0, 100.0 * (total - idle) / total))


class ProcessCpu:
    """This process's CPU use as a percent of the whole machine (all threads, children not included), between calls."""

    def __init__(self, *, clock=time.perf_counter, cpu_time=time.process_time, cpus=None):
        self._clock, self._cpu_time = clock, cpu_time
        self._cpus = cpus or os.cpu_count() or 1
        self._previous = (clock(), cpu_time())

    def percent(self):
        now = (self._clock(), self._cpu_time())
        wall, cpu = now[0] - self._previous[0], now[1] - self._previous[1]
        self._previous = now
        return 0.0 if wall <= 0 else max(0.0, 100.0 * cpu / wall / self._cpus)


def default_reader(*, mem_info, own_reserved, overhead_bytes=None, own_cpu_percent=lambda: 0.0, system_cpu=None):
    """Build the sample function. ``mem_info() -> (free, total)`` device bytes, ``own_reserved() -> bytes`` held by this
    process's allocator. ``overhead_bytes`` is what the machine holds on the device with no foreign tenant (the desktop,
    the CUDA context); foreign holding is what appears ABOVE it. Pass a number to fix it, or None to calibrate it as the
    running minimum of what was held outside this process's allocator (a tenant present from the very first sample is then
    folded into the baseline and under-counted; the receipt says how it was calibrated)."""
    cpu = system_cpu or SystemCpu()
    floor = [overhead_bytes]

    def read():
        free, total = mem_info()
        held = total - free - own_reserved()
        if overhead_bytes is None and (floor[0] is None or held < floor[0]):
            floor[0] = max(0, held)
        busy = cpu.busy_percent()
        other = None if busy is None else max(0.0, busy - own_cpu_percent())
        return {'foreign_gpu_bytes': max(0, held - floor[0]), 'cpu_other_percent': other}
    read.overhead_bytes = lambda: floor[0]
    return read


class ContentionSampler:
    """Samples ``read()`` on a background thread (or by calling ``sample_once``) and classifies a time window.

    A failed read is counted, never raised: attribution is evidence, and losing it must not fail a training hour."""

    def __init__(self, read, *, interval=SAMPLE_SECONDS, clock=time.monotonic, keep=7200,
                 gpu_bytes=FOREIGN_GPU_BYTES, cpu_percent=FOREIGN_CPU_PERCENT):
        self._read, self._interval, self._clock = read, interval, clock
        self._gpu_bytes, self._cpu_percent = gpu_bytes, cpu_percent
        self._samples = deque(maxlen=keep)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.errors = 0

    def sample_once(self):
        try:
            value = self._read()
        except Exception:   # noqa: BLE001 - evidence only; see class doc
            self.errors += 1
            return None
        value = dict(value, t=self._clock())
        with self._lock:
            self._samples.append(value)
        return value

    def start(self):
        if self._thread is not None:
            raise RuntimeError('sampler already started')
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                self.sample_once()
                self._stop.wait(self._interval)
        self._thread = threading.Thread(target=loop, name='contention-sampler', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
        self._thread = None

    def classify(self, t0, t1):
        """Tag the window [t0, t1] (the sampler clock). One sample taken just before t0 counts, so a step shorter than
        the interval still gets the state it ran in. No sample at all means ``known: False`` and never ``contended``."""
        # Samples are appended in time order and the asked window is recent, so walk back from the newest sample and stop
        # at the first one before t0 (per-update cost stays flat however long the hour has run).
        inside, before = [], None
        with self._lock:
            for sample in reversed(self._samples):
                if sample['t'] > t1:
                    continue
                if sample['t'] >= t0:
                    inside.append(sample)
                else:
                    before = sample
                    break
        window = ([before] if before is not None else []) + inside[::-1]
        if not window:
            return {'known': False, 'contended': False, 'reasons': [], 'samples': 0}
        gpu = max(s['foreign_gpu_bytes'] for s in window)
        cpus = [s['cpu_other_percent'] for s in window if s.get('cpu_other_percent') is not None]
        cpu = max(cpus) if cpus else None
        reasons = []
        if gpu >= self._gpu_bytes:
            reasons.append('foreign_gpu_bytes')
        if cpu is not None and cpu >= self._cpu_percent:
            reasons.append('cpu_other_percent')
        return {'known': True, 'contended': bool(reasons), 'reasons': reasons, 'samples': len(window),
                'foreign_gpu_bytes_max': gpu, 'cpu_other_percent_max': cpu}


def attribution_receipt(rows, *, sampler_errors=0, events=()):
    """Summarise per-update rows. Each row needs ``positions_per_second`` and ``contention`` (a classify() result).
    Raw is the plain mean. Uncontended is the mean over rows whose contention is known and false; unknown rows are
    counted separately and are in neither group. Nothing here changes a throughput claim: it adds the split."""
    def mean(values):
        values = list(values)
        return sum(values) / len(values) if values else None

    def median(values):
        values = sorted(values)
        if not values:
            return None
        mid = len(values) // 2
        return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    rates = [r['positions_per_second'] for r in rows]
    contended = [r['positions_per_second'] for r in rows if r['contention']['known'] and r['contention']['contended']]
    clear = [r['positions_per_second'] for r in rows if r['contention']['known'] and not r['contention']['contended']]
    unknown = sum(1 for r in rows if not r['contention']['known'])
    reasons = {}
    for r in rows:
        for reason in r['contention']['reasons']:
            reasons[reason] = reasons.get(reason, 0) + 1
    return {'updates': len(rows), 'raw_positions_per_second_mean': mean(rates),
            'raw_positions_per_second_median': median(rates),
            'uncontended_positions_per_second_mean': mean(clear), 'uncontended_updates': len(clear),
            'contended_positions_per_second_mean': mean(contended), 'contended_updates': len(contended),
            'unknown_updates': unknown, 'contended_fraction': (len(contended) / (len(contended) + len(clear))
                                                               if contended or clear else None),
            'contention_reasons': reasons, 'sampler_errors': sampler_errors, 'throttle_events': list(events)}


# ---------------------------------------------------------------- (B) elasticity

def wait_for_reserve(check, *, sleep=time.sleep, clock=time.monotonic, schedule=BACKOFF_SECONDS,
                     max_wait=BACKOFF_MAX_SECONDS, log=None):
    """Call ``check()`` until it returns. A ReserveUnavailable backs off per ``schedule`` (last value repeats) and re-reads;
    any other exception propagates at once. After ``max_wait`` seconds the last ReserveUnavailable is raised with the wait
    named, so a shortage that never clears ends in a refusal with evidence rather than an unbounded hang.
    Returns (check_value, {'waited_seconds', 'attempts'})."""
    started, attempts = clock(), 0
    while True:
        try:
            return check(), {'waited_seconds': clock() - started, 'attempts': attempts}
        except ReserveUnavailable as error:
            attempts += 1
            waited = clock() - started
            if log is not None:
                log({'event': 'reserve_wait', 'attempt': attempts, 'waited_seconds': waited, 'reason': str(error)})
            if waited >= max_wait:
                raise ReserveUnavailable('%s (still short after %.0f s and %d reads)' % (error, waited, attempts)) from error
            sleep(schedule[min(attempts - 1, len(schedule) - 1)])


class ElasticStep:
    """Run one update, shrinking the micro-step on out-of-memory and growing it back when the machine recovers.

    ``step(pack, micro_documents, mark_update)`` runs the whole update and returns its row; it MUST call
    ``mark_update()`` immediately before its optimizer step. ``reset()`` zeroes accumulated gradients and releases cached
    device memory. ``free_bytes()`` reads current device headroom."""

    def __init__(self, step, *, reset, free_bytes, floor_bytes, ladder=LADDER, grow_after=GROW_AFTER_CLEAN,
                 max_bottom_replays=MAX_BOTTOM_REPLAYS, sleep=time.sleep, schedule=BACKOFF_SECONDS, log=None):
        if list(ladder) != sorted(ladder, reverse=True) or len(set(ladder)) != len(ladder):
            raise ValueError('ladder must be strictly decreasing documents per micro-step')
        self._step, self._reset, self._free, self._floor = step, reset, free_bytes, floor_bytes
        self._ladder, self._grow_after, self._bottom = tuple(ladder), grow_after, max_bottom_replays
        self._sleep, self._schedule, self._log = sleep, schedule, log
        self.rung, self._clean, self.events = 0, 0, []

    def _event(self, update, kind, **fields):
        event = dict(update=update, kind=kind, micro_documents=self._ladder[self.rung], **fields)
        self.events.append(event)
        if self._log is not None:
            self._log(event)
        return event

    def run(self, pack, *, update):
        updates_events = []
        if self._free() < self._floor and self.rung + 1 < len(self._ladder):
            self.rung += 1
            updates_events.append(self._event(update, 'throttle', reason='headroom', free_bytes=self._free()))
        bottom_replays = 0
        while True:
            applied, used = [], self._ladder[self.rung]
            try:
                row = self._step(pack, used, lambda: applied.append(True))
                break
            except BaseException as error:
                if not is_oom(error):
                    raise
                if applied:
                    raise UpdatePartiallyApplied('out of memory after the optimizer step began; the update cannot be replayed') from error
                self._reset()
                if self.rung + 1 < len(self._ladder):
                    self.rung += 1
                    updates_events.append(self._event(update, 'throttle', reason='oom'))
                else:
                    bottom_replays += 1
                    updates_events.append(self._event(update, 'bottom_replay', reason='oom', replay=bottom_replays))
                    if bottom_replays > self._bottom:
                        raise ElasticExhausted('out of memory persisted at %d document(s) per micro-step through %d replays'
                                               % (self._ladder[-1], self._bottom), list(self.events)) from error
                    self._sleep(self._schedule[min(bottom_replays - 1, len(self._schedule) - 1)])
        if updates_events:
            self._clean = 0
        else:
            self._clean += 1
            if self.rung > 0 and self._clean >= self._grow_after and self._free() >= 2 * self._floor:
                self.rung -= 1
                self._clean = 0
                updates_events.append(self._event(update, 'grow', reason='recovered'))
        row = dict(row)
        row['elastic'] = {'micro_documents': used, 'events': updates_events}
        return row
