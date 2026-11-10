# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The hour states its job memory peak and the probe holds the hour's resident set at the verify (#2119, H50).

H50 published its child and died in the verify that restores its terminal state (job peak 43,271,577,600 B = 40.30 GiB at the refusal, against
the 40 GiB limit). Nothing had declared a peak, the hour
result carried none, and the probe that was meant to rehearse the end of the hour held far less than the hour does. These tests pin the
platform independent half: the ledger the worker keeps (`JobMemoryLedger`, read from the job object through `runner.job_memory`), where
run_hour, run_verify_tail and run_continuation mark it and what they write, the probe's hold (`hold_resident_set`), and the preparer flags.
The real-kernel half (a named job, a committed ballast, the old counter under the hour's resident set) is
test_issue2119_post_train_memory_job.py, Windows only."""
import ast
import hashlib
import inspect
import sys
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'))
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', message='`torch.jit.script_method` is deprecated', category=DeprecationWarning)
    import cia_hour  # noqa: E402
    import cia_step_runner  # noqa: E402

GIB = 1024 ** 3
PHASES = ('startup', 'training', 'published', 'terminal_state', 'before_verify', 'verified', 'continuation')


class FakeRunner:
    """A runner whose job object has a scripted ledger: each read returns the next (peak, private) pair."""
    def __init__(self, readings, limit=40 * GIB):
        self.readings, self.limit, self.reads = list(readings), limit, 0

    def job_memory(self, identity):
        peak, private = self.readings[self.reads]
        self.reads += 1
        return {'host_memory_bytes': self.limit, 'peak_job_memory_used_bytes': peak, 'process_private_bytes': private}


class Ledger(unittest.TestCase):
    PREDICTION = {'predicted_peak_job_memory_bytes': 35 * GIB}

    def test_each_phase_records_its_peak_and_its_private_level_and_the_last_peak_is_the_hours(self):
        runner = FakeRunner([(20 * GIB, 19 * GIB), (26 * GIB, 25 * GIB), (37 * GIB, 26 * GIB), (37 * GIB, 30 * GIB)])
        ledger = cia_hour.JobMemoryLedger(runner, {'run_id': 'r'})
        for phase in ('training', 'published', 'before_verify', 'verified'):
            ledger.mark(phase)
        fields = ledger.fields(self.PREDICTION)
        self.assertEqual(fields['peak_job_memory_used_bytes'], 37 * GIB)
        self.assertEqual(fields['host_memory_bytes'], 40 * GIB)
        self.assertEqual(fields['peak_headroom_bytes'], 3 * GIB)
        self.assertEqual(fields['job_memory_phase_peaks_bytes'],
                         {'training': 20 * GIB, 'published': 26 * GIB, 'before_verify': 37 * GIB, 'verified': 37 * GIB})
        self.assertEqual(fields['job_memory_phase_private_bytes']['before_verify'], 26 * GIB)
        self.assertEqual(fields['predicted_peak_job_memory_bytes'], 35 * GIB)
        self.assertIs(fields['peak_within_predicted'], False)     # 37 used against 35 declared: stated, never hidden

    def test_the_result_names_the_counter_io_mechanism_and_the_history_it_was_bound_onto(self):
        import parameter_counter as counter
        ledger = cia_hour.JobMemoryLedger(FakeRunner([(34 * GIB, 30 * GIB)]), {'run_id': 'r'})
        ledger.mark('verified')
        kept = '7d46fc9db80c30427ade481cda5feefa473869a0bfbe12c5aa068a7426176e47'
        counter._counter_for(kept)
        report = ledger.fields(self.PREDICTION)['counter_io']
        self.assertEqual(report['counter_io_mechanism'], 'streaming')
        self.assertEqual(report['counter_sha256'], hashlib.sha256(Path(counter.__file__).read_bytes()).hexdigest())
        self.assertIn(kept, report['history_bound_sha256'])
        self.assertEqual(report['history_bound_sha256'], sorted(report['history_bound_sha256']))
        module = counter._counter_for(kept)
        self.assertEqual((module.COUNTER_IO_MECHANISM, module.COUNTER_IO_BOUND_ONTO), ('streaming', kept))

    def test_a_peak_within_the_declaration_says_so(self):
        ledger = cia_hour.JobMemoryLedger(FakeRunner([(34 * GIB, 30 * GIB)]), {'run_id': 'r'})
        ledger.mark('verified')
        self.assertIs(ledger.fields(self.PREDICTION)['peak_within_predicted'], True)

    def test_a_reading_that_cannot_be_taken_refuses_and_is_not_swallowed(self):
        class Broken:
            def job_memory(self, identity):
                raise ValueError('owned numerical job is missing')
        with self.assertRaisesRegex(ValueError, 'owned numerical job is missing'):
            cia_hour.JobMemoryLedger(Broken(), {'run_id': 'r'}).mark('training')

    def test_no_reading_no_fields(self):
        with self.assertRaises(ValueError):
            cia_hour.JobMemoryLedger(FakeRunner([]), {'run_id': 'r'}).fields(self.PREDICTION)


class Runner(unittest.TestCase):
    def test_job_memory_reads_the_runs_own_job_against_the_bound_limit(self):
        seen = {}

        def owned(run_id, *, namespace, host_memory_bytes):
            seen.update(run_id=run_id, namespace=namespace, host_memory_bytes=host_memory_bytes)
            return {'host_memory_bytes': host_memory_bytes, 'peak_job_memory_used_bytes': 1, 'process_private_bytes': 2}
        with patch.object(cia_step_runner, 'owned_job_memory', owned):
            reading = cia_step_runner.job_memory({'run_id': 'a' * 32})
        self.assertEqual(seen, {'run_id': 'a' * 32, 'namespace': 'EmberCIAMeasurement', 'host_memory_bytes': 40 * GIB})
        self.assertEqual(reading['peak_job_memory_used_bytes'], 1)


class ProbeHold(unittest.TestCase):
    class Resources:
        def __init__(self):
            self.made = []

        class CommittedBallast:
            def __init__(self, nbytes):
                self.nbytes = nbytes

    def test_the_probe_commits_exactly_the_missing_resident_bytes(self):
        resources = self.Resources()
        resources.CommittedBallast = lambda n: SimpleNamespace(nbytes=n)
        held = cia_hour.hold_resident_set(resources, 34 * GIB, 22 * GIB)
        self.assertEqual(held.nbytes, 12 * GIB)

    def test_a_probe_that_already_holds_the_declared_level_commits_nothing(self):
        resources = self.Resources()
        resources.CommittedBallast = lambda n: self.fail('no ballast is needed')
        self.assertIsNone(cia_hour.hold_resident_set(resources, 34 * GIB, 34 * GIB))
        self.assertIsNone(cia_hour.hold_resident_set(resources, 34 * GIB, 36 * GIB))

    def test_sizes_must_be_integers(self):
        for declared, private in ((0, 1), (-1, 1), (True, 1), (34.0, 1), (34 * GIB, -1), (34 * GIB, 1.5)):
            with self.subTest(declared=declared, private=private), self.assertRaises(ValueError):
                cia_hour.hold_resident_set(self.Resources(), declared, private)


class Wiring(unittest.TestCase):
    """run_hour is not executed on CPU; these pin where it marks the ledger and what it writes, from its own source."""

    @staticmethod
    def calls(function, name):
        tree = ast.parse(inspect.getsource(function))
        return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == name]

    def marks(self, function):
        out = []
        for call in self.calls(function, 'mark'):
            if call.args and isinstance(call.args[0], ast.Constant):
                out.append((call.lineno, call.args[0].value))
        return [phase for _, phase in sorted(out)]

    def test_run_hour_marks_every_phase_in_order(self):
        self.assertEqual(self.marks(cia_hour.run_hour), list(PHASES))

    def test_the_marks_surround_the_phases_they_name(self):
        text = inspect.getsource(cia_hour.run_hour)
        order = ["memory.mark('startup')", "memory.mark('training')", "child = publish('trained-child'", "memory.mark('published')",
                 "terminal_state = continuation_state(", "memory.mark('terminal_state')", "release_training_buffers()",
                 "memory.mark('before_verify')", "verify_checkpoint_restore(runner", "memory.mark('verified')",
                 "publish_continuation_reference(", "memory.mark('continuation')", "runner._write_new(custody / 'hour-result.json'"]
        positions = [text.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))

    def test_the_continuation_reads_the_ledger_after_its_update_and_its_second_verify(self):
        """H50 died in the verify that restores S after the S+1 update, not in the first verify: that update has its own peak (the sampler
        saw 39.1 GiB there) and the level the second verify starts from, so the continuation reads the ledger twice itself."""
        self.assertEqual(self.marks(cia_hour.publish_continuation_reference), [])     # the reads are plain calls of the local `mark`
        tree = ast.parse(inspect.getsource(cia_hour.publish_continuation_reference))
        reads = sorted((node.lineno, node.args[0].value) for node in ast.walk(tree) if isinstance(node, ast.Call)
                       and getattr(node.func, 'id', None) == 'mark' and node.args and isinstance(node.args[0], ast.Constant))
        self.assertEqual([phase for _, phase in reads], ['reference_update', 'restored'])
        self.assertIn('device, applied, governed_wall, energy_binding, memory=memory)', inspect.getsource(cia_hour.run_hour))
        text = inspect.getsource(cia_hour.publish_continuation_reference)
        order = ["next_update_reference(runner", "mark('reference_update')", "verify_checkpoint_restore(runner", "mark('restored')"]
        positions = [text.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))

    def test_the_hour_result_carries_the_ledger_and_the_probe_its_hold(self):
        text = inspect.getsource(cia_hour.run_hour)
        self.assertIn('**memory.fields(prediction)', text)
        self.assertIn("{'probe_verify_resident': probe_hold} if probe else {}", text)

    def test_the_probe_holds_across_the_verify_and_releases_it_even_when_the_verify_refuses(self):
        tree = ast.parse(inspect.getsource(cia_hour.run_hour))
        tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try) and any(
            isinstance(c, ast.Call) and getattr(c.func, 'id', None) == 'verify_checkpoint_restore' for b in n.body for c in ast.walk(b))]
        self.assertEqual(len(tries), 1)
        released = [c for b in tries[0].finalbody for c in ast.walk(b) if isinstance(c, ast.Call) and getattr(c.func, 'attr', None) == 'release']
        self.assertEqual(len(released), 1)

    def test_the_tail_and_the_continuation_worker_keep_the_ledger_too(self):
        self.assertEqual(self.marks(cia_hour.run_verify_tail), ['built', 'verified'])
        self.assertEqual(self.marks(cia_hour.run_continuation), ['built', 'verified', 'reproduced'])
        self.assertIn('dict(result, **memory.fields(prediction))', inspect.getsource(cia_hour.run_verify_tail))
        self.assertIn('reproduced.update(job_memory=memory.fields(prediction))', inspect.getsource(cia_hour.run_continuation))

    def test_run_verify_tail_returns_the_tail_result_with_the_ledger(self):
        identity = {'run_id': 'r', 'verify_tail': {'lost_custody': 'L'}}
        runner = FakeRunner([(30 * GIB, 28 * GIB), (33 * GIB, 28 * GIB)])
        with patch.object(cia_hour, 'build_hour_model', lambda **kw: ('m', {'i': 1}, 'o')), \
                patch.object(cia_hour, 'verify_tail', lambda *a: {'status': 'RESTORE_VERIFIED_FROM_WITNESS'}):
            result = cia_hour.run_verify_tail(runner=runner, config=None, prepared=None,
                prediction={'identity': identity, 'predicted_peak_job_memory_bytes': 35 * GIB}, binding=None, custody=None,
                device=None, compiler=None, applied=None)
        self.assertEqual(result['status'], 'RESTORE_VERIFIED_FROM_WITNESS')
        self.assertEqual(result['peak_job_memory_used_bytes'], 33 * GIB)
        self.assertEqual(result['job_memory_phase_peaks_bytes'], {'built': 30 * GIB, 'verified': 33 * GIB})
        self.assertIs(result['peak_within_predicted'], True)

    def test_the_preparer_requires_the_declared_peak_and_a_probe_its_resident_set(self):
        import prepare_hour
        source = inspect.getsource(prepare_hour.main)
        self.assertRegex(source, r"add_argument\('--predicted-peak-job-memory-bytes', type=int, required=True")
        self.assertIn("add_argument('--probe-verify-resident-bytes', type=int,", source)
        self.assertIn('predicted_peak_job_memory_bytes=args.predicted_peak_job_memory_bytes', source)
        self.assertIn("{'probe_verify_resident_bytes': args.probe_verify_resident_bytes} if args.probe else {}", source)
        self.assertIn('args.probe != (args.probe_verify_resident_bytes is not None)', source)


if __name__ == '__main__':
    unittest.main()
