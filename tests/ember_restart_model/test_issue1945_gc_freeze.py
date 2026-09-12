# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Governed-hour p10 tail: cyclic-GC attribution sidecar and the resident-graph freeze (issue 1945).

Receipt behind the change: governed hour 256270a2 (2026-09-12) carried a +139 ms host pause inside the forward wall on
5.1% of measured rows at strictly step-periodic gaps with every CUDA phase unchanged; terminal p10 19,789 against a
20,000 bar. Whether those pauses are collections is what the sidecar's in-step rows will show on the next run; nothing
here asserts it. These tests establish callback ownership, event classification and loop wiring -- not throughput.
"""
import gc
import importlib.util
from pathlib import Path
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
SUBJECT_PATH = TOOLS / 'cia_step_runner.py'
SPEC = importlib.util.spec_from_file_location('bound_checkout_cia_step_runner_gc', SUBJECT_PATH)
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)
assert Path(subject.__file__).resolve(strict=True) == SUBJECT_PATH.resolve(strict=True)
HOUR_PATH = TOOLS / 'cia_hour.py'


def _cyclic_population(count):
    """count self-referencing containers: tracked by the cyclic collector, alive while the list is."""
    population = []
    for _ in range(count):
        node = {}
        node['self'] = node
        population.append(node)
    return population


class GcPauseMeterOwnershipTests(unittest.TestCase):
    def test_meter_files_each_collection_with_generation_duration_and_instant(self):
        with subject.GcPauseMeter() as meter:
            self.assertIn(meter, gc.callbacks)
            before = time.perf_counter()
            gc.collect(2)
            after = time.perf_counter()
            events = meter.drain()
        self.assertNotIn(meter, gc.callbacks)
        full = [event for event in events if event['generation'] == 2]
        self.assertEqual(len(full), 1, events)
        event = full[0]
        self.assertGreaterEqual(event['seconds'], 0.0)
        self.assertLessEqual(event['seconds'], after - before)
        self.assertGreaterEqual(event['at'], before)
        self.assertLessEqual(event['at'], after)
        self.assertEqual(set(event), {'generation', 'seconds', 'collected', 'uncollectable', 'at'})
        self.assertEqual(meter.drain(), [], 'drain hands back each collection exactly once')
        self.assertEqual(meter.total, len(events))

    def test_install_is_idempotent_and_removal_is_exact(self):
        meter = subject.GcPauseMeter()
        try:
            meter.install(); meter.install()
            self.assertEqual(gc.callbacks.count(meter), 1)
        finally:
            meter.remove(); meter.remove()
        self.assertNotIn(meter, gc.callbacks)

    def test_an_exception_inside_the_scope_still_removes_exactly_this_callback(self):
        """Regression for the ownership defect: a loop, open or write failure must not leave the callback behind."""
        sentinel = lambda phase, info: None
        gc.callbacks.append(sentinel)
        try:
            meter = subject.GcPauseMeter()
            with self.assertRaises(RuntimeError):
                with meter:
                    self.assertIn(meter, gc.callbacks)
                    raise RuntimeError('rows.jsonl write failed')
            self.assertNotIn(meter, gc.callbacks)
            self.assertIn(sentinel, gc.callbacks, 'other callbacks are untouched')
        finally:
            gc.callbacks.remove(sentinel)


class CollectionClassificationTests(unittest.TestCase):
    """Deterministic: synthetic events against a declared step window; no collector state involved."""

    def _meter_with(self, instants):
        meter = subject.GcPauseMeter()
        for generation, at in instants:
            meter.events.append({'generation': generation, 'seconds': 0.001, 'collected': 0, 'uncollectable': 0, 'at': at})
        return meter

    def test_only_collections_that_began_inside_the_call_window_are_in_step(self):
        meter = self._meter_with([(2, 9.5), (0, 10.0), (1, 10.7), (2, 11.0), (2, 11.2)])
        row = meter.file(7, 'measured', call_started=10.0, call_finished=11.0)
        self.assertEqual(row['index'], 7)
        self.assertEqual(row['phase'], 'measured')
        self.assertEqual((row['call_started'], row['call_finished']), (10.0, 11.0))
        self.assertEqual([event['at'] for event in row['in_step']], [10.0, 10.7, 11.0], 'window is closed on both ends')
        self.assertEqual([event['at'] for event in row['outside_step']], [9.5, 11.2])
        self.assertEqual(meter.drain(), [], 'file() consumes every queued event')

    def test_setup_collections_before_the_first_measured_step_are_outside_step_not_pauses_of_it(self):
        """The explicit collect+freeze (and any capture-time collections) happen before the measured step's window
        opens; they must land in outside_step of that step's row, never in in_step."""
        meter = self._meter_with([(2, 4.0), (2, 4.5)])   # e.g. freeze_resident_object_graph()'s own full collection
        row = meter.file(1, 'measured', call_started=5.0, call_finished=6.0)
        self.assertEqual(row['in_step'], [])
        self.assertEqual(len(row['outside_step']), 2)

    def test_rows_and_freeze_receipt_carry_the_run_identity_they_belong_to(self):
        meter = subject.GcPauseMeter().bind(run_id='a' * 32, prediction_sha256='b' * 64)
        row = meter.file(0, 'warm', call_started=1.0, call_finished=2.0)
        self.assertEqual((row['run_id'], row['prediction_sha256']), ('a' * 32, 'b' * 64))
        try:
            receipt = subject.freeze_resident_object_graph(run_id='a' * 32, prediction_sha256='b' * 64)
        finally:
            gc.unfreeze()
        self.assertEqual((receipt['run_id'], receipt['prediction_sha256'], receipt['schema']),
                         ('a' * 32, 'b' * 64, 'gc-freeze-v1'))

    def test_terminal_row_with_an_empty_window_files_everything_outside_step(self):
        meter = self._meter_with([(0, 20.0), (2, 20.5)])
        row = meter.file(None, 'after-last-step', call_started=21.0, call_finished=21.0)
        self.assertIsNone(row['index'])
        self.assertEqual(row['in_step'], [])
        self.assertEqual(len(row['outside_step']), 2)


class FreezeResidentObjectGraphTests(unittest.TestCase):
    def test_freeze_keeps_the_collector_enabled_and_moves_the_live_graph_into_the_permanent_generation(self):
        population = _cyclic_population(50_000)
        frozen_before = gc.get_freeze_count()
        try:
            receipt = subject.freeze_resident_object_graph()
            self.assertEqual(receipt['schema'], 'gc-freeze-v1')
            self.assertTrue(receipt['enabled'])
            self.assertTrue(gc.isenabled())
            self.assertEqual(receipt['threshold'], list(gc.get_threshold()))
            self.assertIsInstance(receipt['collected'], int)
            self.assertGreaterEqual(receipt['frozen'] - frozen_before, 50_000)
        finally:
            del population
            gc.unfreeze()
            gc.collect()

    def test_full_collection_cost_before_and_after_the_freeze_is_recorded_as_diagnostic_evidence(self):
        """Diagnostic, not a CI timing gate: the unfrozen/frozen generation-2 pass timings over a large live graph are
        printed for the record; the only assertions are structural (both measured, frozen pass touched fewer objects)."""
        population = _cyclic_population(400_000)
        try:
            gc.collect()
            unfrozen = min(_timed_full_collection() for _ in range(3))
            receipt = subject.freeze_resident_object_graph()
            frozen = min(_timed_full_collection() for _ in range(3))
        finally:
            del population
            gc.unfreeze()
            gc.collect()
        print(f'gc-freeze diagnostic: gen2 pass unfrozen {unfrozen * 1e3:.2f} ms, frozen {frozen * 1e3:.2f} ms, '
              f'frozen objects {receipt["frozen"]}')
        self.assertGreater(unfrozen, 0.0)
        self.assertGreaterEqual(frozen, 0.0)


def _timed_full_collection():
    started = time.perf_counter()
    gc.collect(2)
    return time.perf_counter() - started


class LoopWiringTests(unittest.TestCase):
    """Both governed loops own the callback for exactly the loop's scope, file one classified sidecar row per step
    plus a terminal row, and freeze once at the declared warm-to-measured boundary."""

    def test_measurement_loop_freezes_before_the_first_measured_step_for_any_declared_warm_count(self):
        source = SUBJECT_PATH.read_text(encoding='utf-8')
        loop = source[source.index("with GcPauseMeter().bind(**gc_identity) as gc_meter, (custody / 'rows.jsonl').open('xb') as rows"):]
        loop = loop[:loop.index('\n        if measurement:')]
        self.assertEqual(loop.count('freeze_resident_object_graph('), 1)
        self.assertIn("if pack['phase'] == 'measured' and not frozen:", loop)
        self.assertIn("gc_events_sha256=file_sha256(custody / 'gc-events.jsonl')", source)
        self.assertIn("gc_freeze_sha256=file_sha256(custody / 'gc-freeze.json') if frozen else None", source)
        self.assertNotIn('if index == 0:\n                    # Warm-to-measured', loop, 'index 0 is not the boundary when warm_steps != 1')
        # Freeze precedes the step call's clock; the step call's window brackets measure_step and nothing else.
        self.assertLess(loop.index('freeze_resident_object_graph('), loop.index('call_started = time.perf_counter()'))
        self.assertLess(loop.index('call_started = time.perf_counter()'), loop.index('row = measure_step('))
        self.assertLess(loop.index('row = measure_step('), loop.index('call_finished = time.perf_counter()'))
        self.assertIn('gc_meter.file(index, pack[\'phase\'], call_started=call_started', loop)
        self.assertIn("gc_meter.file(None, 'after-last-step'", loop)
        self.assertNotIn('gc_meter.remove()', loop, 'ownership is the context manager, not a trailing call')
        self.assertNotIn('gc', subject.measure_step.__code__.co_names, 'the timed step itself never collects or freezes')

    def test_hour_loop_keeps_warm1_freezes_before_the_governed_clock_and_files_classified_rows(self):
        source = HOUR_PATH.read_text(encoding='utf-8')
        loop = source[source.index('with runner.GcPauseMeter().bind(**gc_identity) as gc_meter'):source.index('elapsed_before_checkpoint')]
        self.assertEqual(loop.count('runner.freeze_resident_object_graph('), 1)
        self.assertIn('if total_steps == 1:', loop)
        self.assertLess(loop.index('if total_steps == 1:'), loop.index('runner.freeze_resident_object_graph('))
        self.assertIn("gc_freeze_sha256=runner.file_sha256(custody / 'gc-freeze.json')", source)
        self.assertIn("gc_events_sha256=runner.file_sha256(custody / 'gc-events.jsonl')", source)
        self.assertLess(loop.index('runner.freeze_resident_object_graph('), loop.index('\n                started = time.perf_counter()'))
        self.assertLess(loop.index('call_started = time.perf_counter()'), loop.index('row = runner.measure_step('))
        self.assertLess(loop.index('row = runner.measure_step('), loop.index('call_finished = time.perf_counter()'))
        self.assertIn("gc_meter.file(total_steps, row['phase'], call_started=call_started", loop)
        self.assertIn("gc_meter.file(None, 'after-last-step'", loop)
        self.assertNotIn('gc_meter.remove()', loop)


if __name__ == '__main__':
    unittest.main()
