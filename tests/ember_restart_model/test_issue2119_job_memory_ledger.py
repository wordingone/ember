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
HOUR_MARKS = ('startup', 'before_verify', 'verified', 'energy_end', 'fp32_evidence', 'continuation')    # strict: a failed reading refuses the hour at once
DEFERRED_MARKS = ('training', 'published', 'terminal_state')           # between the end of training and the terminal witness: recorded, refused at the hour result


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
        counter._CIA_READER_STATS.update(digest_passes=1, digest_pass_max_read_bytes=counter._CIA_READ_CHUNK, chunk_reads=3, chunk_read_max_bytes=1024)
        report = ledger.fields(self.PREDICTION)['counter_io']
        self.assertEqual(report['counter_io_mechanism'], 'streaming')
        self.assertEqual(report['counter_sha256'], hashlib.sha256(Path(counter.__file__).read_bytes()).hexdigest())
        self.assertIn(kept, report['history_bound_sha256'])
        self.assertEqual(report['history_bound_sha256'], sorted(report['history_bound_sha256']))
        module = counter._counter_for(kept)
        self.assertEqual((module.COUNTER_IO_MECHANISM, module.COUNTER_IO_BOUND_ONTO), ('streaming', kept))

    def test_the_mechanism_is_read_back_from_the_reader_that_did_the_work(self):
        """Review r1 note 6: `counter_io_mechanism` was the literal 'streaming'. It is now derived from what the component reader did in this process."""
        import tempfile
        import parameter_counter as counter
        saved = dict(counter._CIA_READER_STATS)
        try:
            counter._CIA_READER_STATS.update(digest_passes=0, digest_pass_max_read_bytes=0, chunk_reads=0, chunk_read_max_bytes=0)
            self.assertEqual(counter.counter_io_report()['counter_io_mechanism'], 'unobserved')     # nothing was read: nothing is claimed
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'component.bin'
                path.write_bytes(b'x' * 5000)
                digest, table, whole = counter._cia_counter_digest_pass(path, 5000)
            self.assertTrue(whole)
            report = counter.counter_io_report()
            self.assertEqual(report['counter_io_mechanism'], 'streaming')
            self.assertEqual(report['reader_observed']['digest_passes'], 1)
            self.assertEqual(report['reader_observed']['digest_pass_max_read_bytes'], 5000)
            counter._CIA_READER_STATS['chunk_read_max_bytes'] = counter._CIA_READ_CHUNK + 1         # a read above one chunk is a whole read: not streaming
            self.assertEqual(counter.counter_io_report()['counter_io_mechanism'], 'unobserved')
        finally:
            counter._CIA_READER_STATS.update(saved)

    def test_the_counter_subprocess_gives_its_own_account_and_the_hour_carries_it(self):
        raw = b'warning\nCOUNTER_IO {"counter_io_mechanism": "streaming", "reader_observed": {"digest_passes": 2}}\n'
        self.assertEqual(cia_hour.counter_io_from_stderr(raw)['reader_observed'], {'digest_passes': 2})
        self.assertIsNone(cia_hour.counter_io_from_stderr(b'no account here\n'))
        self.assertIsNone(cia_hour.counter_io_from_stderr(b'COUNTER_IO {broken\n'))
        fields = cia_hour.JobMemoryLedger(FakeRunner([(34 * GIB, 30 * GIB)]), {'run_id': 'r'})
        fields.mark('verified')
        self.assertIn('pre_publish_counter_io', fields.fields(self.PREDICTION))
        self.assertIn('pre_publish_counter_walls', fields.fields(self.PREDICTION))
        import parameter_counter
        self.assertIn("'COUNTER_IO ' + json.dumps(counter_io_report()", inspect.getsource(parameter_counter.main))

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

    def test_a_deferred_reading_that_fails_is_recorded_and_refuses_only_at_the_hour_result(self):
        """Review r1 item 3: mark() raises by design; between the end of training and the terminal witness a raise loses the hour or the witness."""
        class FailsOnce(FakeRunner):
            def job_memory(self, identity):
                if self.reads == self.fail_at:
                    self.reads += 1
                    raise ValueError('owned numerical job is missing')
                return super().job_memory(identity)
        runner = FailsOnce([(20 * GIB, 19 * GIB), (26 * GIB, 25 * GIB)])
        runner.fail_at = 0
        ledger = cia_hour.JobMemoryLedger(runner, {'run_id': 'r'})
        self.assertIsNone(ledger.mark_deferred('training'))             # does not raise
        self.assertIn('training', ledger.failed)
        ledger.mark_deferred('published')
        with self.assertRaisesRegex(ValueError, 'could not be taken at training.*owned numerical job is missing'):
            ledger.fields(self.PREDICTION)                              # where the hour result is written
        strict = FailsOnce([(1, 1)])
        strict.fail_at = 0
        with self.assertRaises(ValueError):
            cia_hour.JobMemoryLedger(strict, {'run_id': 'r'}).mark('training')   # the strict mark still raises (strict marks are unchanged)

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


class ProbeHeld(unittest.TestCase):
    """Review r1 item 2: what the probe REALLY held, read after the hold, is compared with the level the consuming hour holds."""
    LEVEL = int(31.5 * GIB)

    def record(self, **changes):
        base = dict(declared_bytes=self.LEVEL, process_private_bytes_before_hold=int(3.2 * GIB), ballast_bytes=self.LEVEL - int(3.2 * GIB),
                    process_private_bytes_after_hold=self.LEVEL)
        base.update(changes)
        return base

    def test_a_probe_that_held_the_hours_level_is_accepted(self):
        cia_hour.require_probe_held(self.record(), self.LEVEL)
        cia_hour.require_probe_held(self.record(process_private_bytes_after_hold=self.LEVEL + 1, declared_bytes=self.LEVEL + 1), self.LEVEL)

    def test_a_one_byte_hold_is_refused(self):
        tiny = self.record(declared_bytes=1, ballast_bytes=0, process_private_bytes_after_hold=int(3.2 * GIB))
        with self.assertRaisesRegex(ValueError, 'is not a dry run of the hour'):
            cia_hour.require_probe_held(tiny, self.LEVEL)

    def test_a_requested_hold_that_was_not_reached_is_refused(self):
        """declared_bytes and ballast_bytes are what was ASKED; only the private commit read after the hold says what the process holds."""
        with self.assertRaisesRegex(ValueError, 'held .* below'):
            cia_hour.require_probe_held(self.record(process_private_bytes_after_hold=self.LEVEL - 1), self.LEVEL)
        with self.assertRaisesRegex(ValueError, 'declared .* below'):
            cia_hour.require_probe_held(self.record(declared_bytes=self.LEVEL - 1), self.LEVEL)

    def test_a_probe_that_did_not_record_its_hold_is_refused(self):
        for record in (None, {}, {k: v for k, v in self.record().items() if k != 'process_private_bytes_after_hold'}, dict(self.record(), extra=1),
                       self.record(process_private_bytes_after_hold=True), self.record(ballast_bytes=-1), self.record(declared_bytes=1.5 * GIB)):
            with self.subTest(record=record), self.assertRaisesRegex(ValueError, 'lacks the resident set it held'):
                cia_hour.require_probe_held(record, self.LEVEL)

    def test_the_hours_own_level_must_be_a_positive_integer(self):
        for level in (None, 0, -1, True, 31.5 * GIB):
            with self.subTest(level=level), self.assertRaises(ValueError):
                cia_hour.require_probe_held(self.record(), level)

    def test_the_consumer_check_is_wired_into_the_validator_and_the_preparation(self):
        self.assertIn('require_probe_held(result.get(\'probe_verify_resident\'), required_hold_bytes)', inspect.getsource(cia_hour.validate_checkpoint_probe))
        self.assertIn("required_hold_bytes=prediction.get('before_verify_resident_bytes')", inspect.getsource(cia_step_runner.prepare_execution))
        source = inspect.getsource(cia_hour.run_hour)
        order = ["held = hold_resident_set(", "process_private_bytes_after_hold=runner.process_private_bytes()", "require_probe_held(probe_hold, declared)",
                 "verify_checkpoint_restore(runner"]
        positions = [source.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))       # recorded after the hold, checked before the verify starts

    def test_a_probe_resident_result_is_read_from_a_real_probe_block(self):
        """The block the worker writes has exactly the fields the validator reads."""
        self.assertEqual(set(cia_hour.PROBE_HOLD_FIELDS), set(self.record()))
        source = inspect.getsource(cia_hour.run_hour)
        for name in cia_hour.PROBE_HOLD_FIELDS:
            self.assertIn(name, source)


class EndOfTraining(unittest.TestCase):
    """Review r1 item 3, three-point test: a reading that raises at 'training', 'published' or 'terminal_state' still leaves the child and the witness on disk.
    This runs the REAL `publish_child_with_witness` that run_hour calls, with a fake job and a fake publisher that write real files."""

    class Runner:
        def __init__(self, fail_at):
            self.fail_at, self.reads, self.stamps = fail_at, 0, []

        def job_memory(self, identity):
            self.reads += 1
            if self.reads == self.fail_at:
                raise ValueError('GetProcessMemoryInfo failed')
            return {'host_memory_bytes': 40 * GIB, 'peak_job_memory_used_bytes': 30 * GIB, 'process_private_bytes': 28 * GIB}

        def tail_stamp(self, custody, name):
            self.stamps.append(name)

    def run_point(self, fail_at):
        import tempfile
        runner = self.Runner(fail_at)
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory)
            memory = cia_hour.JobMemoryLedger(runner, {'run_id': 'r'})

            def publish():
                (custody / 'trained-child').mkdir()
                (custody / 'trained-child' / 'checkpoint-manifest.json').write_text('{}')
                return {'data_cursor': {'global_step': 1}}

            def witness(child, state, finished):
                (custody / 'terminal-witness.json').write_text('{"state": %r}' % state)

            outcome = cia_hour.publish_child_with_witness(runner, memory, custody, publish=publish,
                                                          terminal_state=lambda child: 'S', witness=witness)
            on_disk = ((custody / 'trained-child' / 'checkpoint-manifest.json').exists(), (custody / 'terminal-witness.json').exists())
            return outcome, on_disk, memory

    def test_the_clean_path_publishes_then_persists_the_witness(self):
        (child, finished, state), on_disk, memory = self.run_point(fail_at=0)
        self.assertEqual((on_disk, state), ((True, True), 'S'))
        self.assertEqual(list(memory.phases), ['training', 'published', 'terminal_state'])

    def test_a_raising_reading_at_each_of_the_three_points_leaves_child_and_witness_on_disk(self):
        for index, phase in enumerate(DEFERRED_MARKS, start=1):
            with self.subTest(phase=phase):
                _, on_disk, memory = self.run_point(fail_at=index)
                self.assertEqual(on_disk, (True, True))                         # child and witness are both on disk
                self.assertEqual(list(memory.failed), [phase])
                with self.assertRaisesRegex(ValueError, 'could not be taken at ' + phase):
                    memory.fields({'predicted_peak_job_memory_bytes': 35 * GIB})   # and the hour result is refused where it is written

    def test_run_hour_publishes_only_through_the_helper(self):
        source = inspect.getsource(cia_hour.run_hour)
        self.assertIn('publish_child_with_witness(', source)
        self.assertNotIn("memory.mark('training')", source)
        self.assertNotIn("memory.mark('published')", source)
        self.assertNotIn("memory.mark('terminal_state')", source)
        self.assertNotIn("child = publish('trained-child'", source)           # no direct publish outside the helper

    def test_the_helper_takes_only_deferred_readings_before_the_witness(self):
        tree = ast.parse(inspect.getsource(cia_hour.publish_child_with_witness))
        names = [(node.lineno, node.func.attr) for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in ('mark', 'mark_deferred')]
        self.assertEqual([name for _, name in sorted(names)], ['mark_deferred'] * 3)


class PrePublishCounter(unittest.TestCase):
    """Review r1 note 12: a slow-but-correct counter is waited for, not refused; an expired bound is a time-out, never a counter refusal."""
    SLEEP = [sys.executable, '-c', 'import time; time.sleep(1.2); print(7)']

    def setUp(self):
        self.saved = list(cia_hour.PRE_PUBLISH_COUNTER_WALLS)
        del cia_hour.PRE_PUBLISH_COUNTER_WALLS[:]

    def tearDown(self):
        cia_hour.PRE_PUBLISH_COUNTER_WALLS[:] = self.saved

    def test_a_slow_but_correct_counter_is_waited_for(self):
        result = cia_hour.run_pre_publish_counter(self.SLEEP, timeout=30)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, b'7'))
        wall = cia_hour.PRE_PUBLISH_COUNTER_WALLS[-1]
        self.assertEqual((wall['outcome'], wall['bound_seconds']), ('returned', 30))
        self.assertGreaterEqual(wall['wall_seconds'], 1.2)                      # slower than a tight bound would allow, and it was waited for

    def test_a_counter_still_running_at_the_bound_is_a_timeout_not_a_refusal(self):
        with self.assertRaisesRegex(ValueError, 'still running at its 0.3 s bound .*a time-out, not a counter refusal'):
            cia_hour.run_pre_publish_counter(self.SLEEP, timeout=0.3)
        self.assertEqual(cia_hour.PRE_PUBLISH_COUNTER_WALLS[-1]['outcome'], 'timeout')

    def test_the_publisher_waits_through_the_one_named_bound_and_records_every_wall(self):
        source = inspect.getsource(cia_hour.checkpoint_publisher)
        self.assertIn('run_pre_publish_counter(command, **runner.hidden_kwargs())', source)
        self.assertNotIn('timeout=240', source)                                  # no second, literal bound
        self.assertEqual(inspect.signature(cia_hour.run_pre_publish_counter).parameters['timeout'].default, None)
        self.assertIn('PRE_PUBLISH_COUNTER_TIMEOUT_SECONDS', inspect.getsource(cia_hour.run_pre_publish_counter))
        self.assertIn("pre_publish_counter_walls=[dict(wall) for wall in PRE_PUBLISH_COUNTER_WALLS]", inspect.getsource(cia_hour.JobMemoryLedger.fields))


class Fp32SchemaRead(unittest.TestCase):
    """Review r1 item 4: the child optimizer's schema_version is read from its data.pkl member, never by mapping the 5.3 GiB file."""

    def child(self, directory):
        import torch
        path = Path(directory) / 'optimizer-state.pt'
        torch.save({'schema_version': 'ember-cia-optimizer-v3', 'state': {'w': torch.arange(64, dtype=torch.float32)}}, path)
        return path

    def test_the_schema_is_read_without_mapping_the_file(self):
        import mmap
        import tempfile
        import torch
        import cia_fp32_evidence
        with tempfile.TemporaryDirectory() as directory:
            path = self.child(directory)
            expected = torch.load(path, map_location='cpu', weights_only=True, mmap=True).get('schema_version')
            def refuse(*args, **kwargs):
                raise AssertionError('the schema read mapped or loaded the optimizer file')
            with patch.object(torch, 'load', refuse), patch.object(mmap, 'mmap', refuse):
                self.assertEqual(cia_fp32_evidence.read_optimizer_schema_version(path), expected)
        self.assertEqual(expected, 'ember-cia-optimizer-v3')

    def test_the_finish_reads_the_schema_through_that_reader_only(self):
        import cia_fp32_evidence
        source = inspect.getsource(cia_fp32_evidence)
        self.assertNotIn('mmap=True', source.replace('torch.load(..., mmap=True)', ''))     # the docstring names the old call; no live call remains
        self.assertIn('schema = read_optimizer_schema_version(child_optimizer_state_path)', inspect.getsource(cia_fp32_evidence.Evidence.finish))

    def test_a_file_without_a_schema_reads_as_none(self):
        import tempfile
        import torch
        import cia_fp32_evidence
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'x.pt'
            torch.save({'state': {'w': torch.zeros(2)}}, path)
            self.assertIsNone(cia_fp32_evidence.read_optimizer_schema_version(path))


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
        self.assertEqual(self.marks(cia_hour.run_hour), list(HOUR_MARKS))
        helper = ast.parse(inspect.getsource(cia_hour.publish_child_with_witness))
        deferred = sorted((n.lineno, n.args[0].value) for n in ast.walk(helper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                          and n.func.attr == 'mark_deferred' and n.args and isinstance(n.args[0], ast.Constant))
        self.assertEqual([phase for _, phase in deferred], list(DEFERRED_MARKS))

    def test_the_marks_surround_the_phases_they_name(self):
        text = inspect.getsource(cia_hour.run_hour)
        order = ["memory.mark('startup')", "publish_child_with_witness(", "write_terminal_witness(runner, custody, published", "release_training_buffers()",
                 "memory.mark('before_verify')", "verify_checkpoint_restore(runner", "memory.mark('verified')",
                 "energy_binding = energy.end()", "memory.mark('energy_end')", "fp32_evidence.finish(", "memory.mark('fp32_evidence')",
                 "publish_continuation_reference(", "memory.mark('continuation')", "runner._write_new(custody / 'hour-result.json'"]
        positions = [text.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))
        helper = inspect.getsource(cia_hour.publish_child_with_witness)
        order = ["memory.mark_deferred('training')", "child = publish()", "memory.mark_deferred('published')", "state = terminal_state(child)",
                 "memory.mark_deferred('terminal_state')", "witness(child, state, checkpoint_finished)"]
        positions = [helper.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))                       # the witness is written after the three deferred readings and nothing else raises before it

    def test_the_capture_bind_and_the_update_are_attributed_separately(self):
        """Review r1 item 4: energy end, the fp32 evidence, the capture bind and the S+1 update each end in their own reading."""
        text = inspect.getsource(cia_hour.next_update_reference)
        order = ["bind_hour_capture(runner", "mark('capture_bound')", "runner.measure_step("]
        positions = [text.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('terminal_state, device, applied, mark=None)', text)
        self.assertIn('device, applied, mark=mark)', inspect.getsource(cia_hour.publish_continuation_reference))
        self.assertNotIn('mark=', inspect.getsource(cia_hour.run_continuation).split('next_update_reference(')[1].split(')')[0])   # the continuation worker is unchanged

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
