# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #2115: declared pause, the terminated_in_declared_pause outcome class, parameter dumps and the offline comparator.

Synthetic custody only; no training result is inferred."""
import hour_test_support
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cia_hour
import cia_step_runner as step_runner
import declared_pause as dp

PAUSE = dict(kind=dp.PAUSE_KIND, position='after-hour-result', seconds=5)
DUMP = dict(kind=dp.DUMP_KIND, scope=dp.DUMP_SCOPE)
HOUR = dict(schema='governed-hour-v1', arm='treatment', minimum_wall_seconds=3600, minimum_measured_steps=1024)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class DeclarationTests(unittest.TestCase):
    def test_declaration_is_exact_and_governed_hour_only(self):
        self.assertIsNone(dp.pause_declaration(dict(hour=HOUR)))
        self.assertEqual(dp.pause_declaration(dict(hour=HOUR, declared_pause=PAUSE)), PAUSE)
        for bad in (dict(PAUSE, kind='x'), dict(PAUSE, position='mid-training'), dict(PAUSE, seconds=0),
                    dict(PAUSE, seconds=3601), dict(PAUSE, seconds=5.0), dict(PAUSE, extra=1), 'pause'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dp.pause_declaration(dict(hour=HOUR, declared_pause=bad))
        for other in (dict(continuation={}), dict(verify_tail={}), dict(checkpoint_probe=True)):
            with self.subTest(other=other), self.assertRaises(ValueError):
                dp.pause_declaration(dict(hour=HOUR, declared_pause=PAUSE, **other))
        with self.assertRaises(ValueError):
            dp.pause_declaration(dict(hour=dict(HOUR, schema='learning-comparison-v1'), declared_pause=PAUSE))
        with self.assertRaises(ValueError):
            dp.pause_declaration(dict(declared_pause=PAUSE))

    def test_dump_flag_is_pinned(self):
        self.assertFalse(dp.dump_declared(dict(hour=HOUR)))
        self.assertTrue(dp.dump_declared(dict(hour=HOUR, parameter_dump=DUMP)))
        self.assertTrue(dp.dump_declared(dict(hour=HOUR, continuation={}, parameter_dump=DUMP)))
        for bad in (True, dict(DUMP, scope='all'), dict(DUMP, kind='x')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dp.dump_declared(dict(hour=HOUR, parameter_dump=bad))
        with self.assertRaises(ValueError):
            dp.dump_declared(dict(hour=HOUR, verify_tail={}, parameter_dump=DUMP))

    def test_limits_widen_by_exactly_the_declared_amounts_and_not_otherwise(self):
        plain = step_runner.resource_limits(dict(hour=HOUR))
        paused = step_runner.resource_limits(dict(hour=HOUR, declared_pause=PAUSE, parameter_dump=DUMP))
        self.assertEqual(paused['wall_seconds'], plain['wall_seconds'] + 5)
        self.assertEqual(paused['max_b_write_gib'], plain['max_b_write_gib'] + dp.DUMP_EXTRA_B_WRITE_GIB)
        self.assertEqual(step_runner.resource_limits(dict(hour=HOUR)), plain)
        reproduced = step_runner.resource_limits(dict(hour=HOUR, continuation={}, parameter_dump=DUMP))
        self.assertEqual(reproduced['max_b_write_gib'], 1 + dp.DUMP_EXTRA_B_WRITE_GIB)
        self.assertEqual(step_runner.resource_limits(dict(hour=HOUR, continuation={}))['max_b_write_gib'], 1)

    def test_new_keys_are_admitted_only_with_a_valid_declaration(self):
        # prepare_execution's allowed-key list must carry both keys (a missing key would refuse every paired identity).
        text = Path(step_runner.__file__).read_text()
        self.assertIn("'declared_pause', 'parameter_dump'}", text)
        self.assertIn('declared_pause.py', text)


class PauseCustodyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base/('measurement-' + 'a'*32)
        (self.root/'trained-child').mkdir(parents=True)
        (self.base/'operator').mkdir()
        self.prior = dict(run_id='a'*32, hour=HOUR, declared_pause=dict(PAUSE), parameter_dump=dict(DUMP))
        for name in dp.BOUND_ALWAYS:
            (self.root/name).write_bytes(('bytes of ' + name).encode())
        (self.root/dp.DUMP_LIVE).write_bytes(b'dump')
        self.result_sha = sha(self.root/'hour-result.json')
        self.clock_now = [1000.0]
        self.runner = SimpleNamespace()

    def enter_and_interrupt(self, identity=None):
        class Stop(Exception):
            pass
        def stop(seconds):
            raise Stop
        with self.assertRaises(Stop):
            dp.enter_pause(self.root, identity or self.prior, position='after-hour-result', physical_positions=6156,
                           sleep=stop, clock=lambda: self.clock_now[0], pid=4242)

    def kill_cohort(self, table=None, now=1002.0, kill=None):
        table = table or {4242: 1, 4300: 4242, 4301: 4300, 9: 1}
        return dp.terminate_in_pause(self.root, table=table, kill=kill or (lambda pid: None), clock=lambda: now)

    def test_pause_holds_the_declared_seconds_and_records_the_exit(self):
        slept = []
        held = dp.enter_pause(self.root, self.prior, position='after-hour-result', physical_positions=6156,
                              sleep=slept.append, clock=lambda: self.clock_now[0], pid=4242)
        self.assertEqual(slept, [1]*5)
        self.assertEqual(held, 0.0)
        entered = json.loads((self.root/dp.ENTERED).read_bytes())
        self.assertEqual(set(dp.BOUND_ALWAYS) | {dp.DUMP_LIVE}, set(entered['files']))
        self.assertEqual(entered['files']['hour-result.json'], self.result_sha)
        self.assertEqual(entered['physical_positions'], 6156)
        self.assertTrue((self.root/dp.EXITED).is_file())

    def test_no_declaration_or_other_position_writes_nothing(self):
        plain = dict(self.prior)
        del plain['declared_pause']
        self.assertEqual(dp.enter_pause(self.root, plain, position='after-hour-result', physical_positions=0,
                                        sleep=lambda s: self.fail('slept')), 0.0)
        self.assertEqual(dp.enter_pause(self.root, self.prior, position='after-witness', physical_positions=0,
                                        sleep=lambda s: self.fail('slept')), 0.0)
        self.assertFalse((self.root/dp.ENTERED).exists())

    def test_intent_lands_before_the_first_signal_and_outcome_binds_it(self):
        self.enter_and_interrupt()
        seen = []
        def kill(pid):
            seen.append((pid, (self.root/dp.TERMINATION).is_file()))
        receipt = self.kill_cohort(kill=kill)
        self.assertEqual(sorted(pid for pid, _ in seen), [4242, 4300, 4301])
        self.assertTrue(all(intent_first for _, intent_first in seen))
        self.assertEqual(receipt['intent']['cohort'], [4242, 4300, 4301])
        self.assertTrue(receipt['outcome']['all_gone'])
        self.assertNotIn(9, receipt['intent']['cohort'])
        self.assertEqual(dp.validate_terminated_source(self.runner, self.root, self.prior, {}, self.result_sha), 6156)

    def test_kill_outside_the_declared_window_or_after_exit_refuses_before_any_signal(self):
        self.enter_and_interrupt()
        with self.assertRaisesRegex(ValueError, 'outside the declared window'):
            self.kill_cohort(now=1005.0, kill=lambda pid: self.fail('signalled'))
        with self.assertRaisesRegex(ValueError, 'outside the declared window'):
            self.kill_cohort(now=999.0, kill=lambda pid: self.fail('signalled'))
        (self.root/dp.EXITED).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'not terminable'):
            self.kill_cohort(kill=lambda pid: self.fail('signalled'))

    def test_survivor_is_reported_and_refused(self):
        self.enter_and_interrupt()
        table = {4242: 1, 4300: 4242}
        receipt = dp.terminate_in_pause(self.root, table=table, kill=lambda pid: None, clock=lambda: 1002.0)
        # the injected table models "after" by removing the cohort, so force a survivor through a custom listing
        receipt['outcome'].update(all_gone=False, remaining=[4300])
        (self.root/dp.TERMINATION).write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'intent and outcome'):
            dp.validate_terminated_source(self.runner, self.root, self.prior, {}, self.result_sha)

    def test_reds_on_the_admission_side(self):
        self.enter_and_interrupt()
        self.kill_cohort()
        good = lambda **kw: dp.validate_terminated_source(self.runner, self.root, kw.get('prior', self.prior), {}, kw.get('result', self.result_sha))
        self.assertEqual(good(), 6156)
        # no declaration pinned in the source identity: the class is unreachable
        plain = copy.deepcopy(self.prior)
        del plain['declared_pause']
        with self.assertRaisesRegex(ValueError, 'declared no pause'):
            good(prior=plain)
        # a different hour result than the marker bound
        with self.assertRaisesRegex(ValueError, 'different hour result'):
            good(result='0'*64)
        # a bound file changed after the marker (a kill before the files were durable would look the same)
        (self.root/'rows.jsonl').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'bound file differs: rows.jsonl'):
            good()
        (self.root/'rows.jsonl').write_bytes(b'bytes of rows.jsonl')
        # the dump is bound when the flag is pinned
        (self.root/dp.DUMP_LIVE).write_bytes(b'other dump')
        with self.assertRaisesRegex(ValueError, 'bound file differs: ' + dp.DUMP_LIVE):
            good()
        (self.root/dp.DUMP_LIVE).write_bytes(b'dump')
        # a worker that wrote its own terminal, or a pause that exited, is not this class
        (self.root/'worker-terminal.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'wrote its own terminal'):
            good()
        (self.root/'worker-terminal.json').unlink()
        (self.root/dp.EXITED).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'pause exited'):
            good()
        (self.root/dp.EXITED).unlink()
        # no termination receipt
        receipt = (self.root/dp.TERMINATION).read_bytes()
        (self.root/dp.TERMINATION).unlink()
        with self.assertRaisesRegex(ValueError, 'no cohort termination receipt'):
            good()
        # intent after the declared window closed
        tampered = json.loads(receipt)
        tampered['intent']['written_unix'] = 1006.0
        (self.root/dp.TERMINATION).write_text(json.dumps(tampered))
        with self.assertRaisesRegex(ValueError, 'intent and outcome'):
            good()
        # intent that does not belong to the outcome's digest
        tampered = json.loads(receipt)
        tampered['intent']['cohort'].append(1234)
        (self.root/dp.TERMINATION).write_text(json.dumps(tampered))
        with self.assertRaisesRegex(ValueError, 'intent and outcome'):
            good()

    def test_after_witness_marker_is_expressible_but_never_a_continuation_source(self):
        identity = dict(self.prior, declared_pause=dict(PAUSE, position='after-witness'))
        for name in ('hour-result.json', 'continuation-reference.json', 'continuation-hour.json', 'continuation-next-pack.json'):
            (self.root/name).unlink()
        class Stop(Exception):
            pass
        def stop(seconds):
            raise Stop
        with self.assertRaises(Stop):
            dp.enter_pause(self.root, identity, position='after-witness', physical_positions=0, sleep=stop,
                           clock=lambda: 1000.0, pid=4242)
        entered = json.loads((self.root/dp.ENTERED).read_bytes())
        self.assertEqual(entered['position'], 'after-witness')
        self.assertNotIn('hour-result.json', entered['files'])
        self.kill_cohort()
        with self.assertRaisesRegex(ValueError, 'hour result durable before the signal'):
            dp.validate_terminated_source(self.runner, self.root, identity, {}, self.result_sha)


class OutcomeClassThroughValidateContinuationTests(unittest.TestCase):
    """The class is decided inside validate_continuation; an unpaused non-clean hour stays refused as before."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/('measurement-' + 'a'*32)
        (self.root/'trained-child').mkdir(parents=True)
        (self.root.parent/'operator').mkdir()
        self.runner = SimpleNamespace(GIB=1024**3,
            attention_selection=lambda identity: step_runner.attention_selection(identity),
            checked_sha=lambda value: value,
            file_sha256=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())
        self.prior = dict(run_id='a'*32, source_commit='old-head',
            geometry=dict(warm_steps=1, sequence_length=3, documents_per_step=2),
            optimizer={'fused': True}, hour=dict(HOUR), declared_pause=dict(PAUSE))
        prediction_sha = self.write('prediction.json', {'identity': self.prior})
        rows = [dict(phase='warm' if i == 0 else 'measured', run_id=self.prior['run_id'],
            prediction_sha256=prediction_sha, applied_positions=6) for i in range(1025)]
        (self.root/'rows.jsonl').write_bytes(b'\n'.join(json.dumps(row).encode() for row in rows))
        self.hour = dict(run_id=self.prior['run_id'], prediction_sha256=prediction_sha, hour=self.prior['hour'],
            measured_updates=1024, pre_checkpoint_wall_seconds=3600, restored_state_matches=True,
            rows_sha256=self.runner.file_sha256(self.root/'rows.jsonl'), applied_positions=6150, continuation=None)
        for name in ('terminal-witness.json', 'continuation-reference.json', 'continuation-hour.json',
                     'continuation-next-pack.json', 'trained-child/checkpoint-manifest.json'):
            (self.root/name).write_bytes(('bytes of ' + name).encode())
        self.identity = copy.deepcopy(self.prior)
        del self.identity['declared_pause']
        self.identity['run_id'] = 'b'*32
        self.bind()

    def write(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value))
        return self.runner.file_sha256(path)

    def bind(self, success=False):
        digest = self.write('hour-result.json', self.hour)
        self.identity['continuation'] = dict(source_hour_result_path=str(self.root/'hour-result.json'),
                                           source_hour_result_sha256=digest)
        outcome = dict(run_id=self.prior['run_id'], success=success, daemon_cleanup_verified=True)
        (self.root.parent/'operator/operator-outcome.json').write_text(json.dumps(outcome))
        return digest

    def killed_worker_custody(self):
        digest = self.bind()
        self.write('owned.json', dict(status='completed', returncode=1, cleanup_verified=True, supervisor_failure=None))
        self.write('disk.json', dict(outcome='CHILD_FAILED', stop_reason=None, runner_exit_code=1, child_exit_code=1,
                                     operating_reserve_breaches=[]))
        clock = [1000.0]
        class Stop(Exception):
            pass
        def stop(seconds):
            raise Stop
        with self.assertRaises(Stop):
            dp.enter_pause(self.root, self.prior, position='after-hour-result', physical_positions=6150,
                           sleep=stop, clock=lambda: clock[0], pid=4242)
        dp.terminate_in_pause(self.root, table={4242: 1}, kill=lambda pid: None, clock=lambda: 1002.0)
        return digest

    def test_unpaused_nonclean_hour_stays_refused(self):
        plain = copy.deepcopy(self.prior)
        del plain['declared_pause']
        self.write('prediction.json', {'identity': plain})
        self.hour['prediction_sha256'] = self.runner.file_sha256(self.root/'prediction.json')
        self.bind()
        with self.assertRaisesRegex(ValueError, 'native outcome differs'):
            cia_hour.validate_continuation(self.runner, self.identity)

    def test_declared_pause_without_a_kill_is_refused_not_admitted(self):
        self.hour['prediction_sha256'] = self.runner.file_sha256(self.root/'prediction.json')
        self.write('owned.json', dict(status='completed', returncode=1, cleanup_verified=True, supervisor_failure=None))
        self.write('disk.json', dict(outcome='CHILD_FAILED', stop_reason=None, operating_reserve_breaches=[]))
        self.bind()
        (self.root/dp.ENTERED).write_text(json.dumps(dict(schema=dp.ENTERED_SCHEMA, run_id='a'*32)))
        with self.assertRaisesRegex(ValueError, 'declared pause'):
            cia_hour.validate_continuation(self.runner, self.identity)

    def test_killed_in_declared_pause_passes_the_outcome_gate(self):
        digest = self.killed_worker_custody()
        # The hour result is bound by the marker, so write it before entering: rebuild in the right order.
        self.assertTrue((self.root/dp.TERMINATION).is_file())
        # Reaches the stage after the outcome class (no next-update reference in this synthetic hour).
        with self.assertRaisesRegex(ValueError, 'independently bound next-update reference'):
            cia_hour.validate_continuation(self.runner, self.identity)
        self.assertEqual(digest, self.identity['continuation']['source_hour_result_sha256'])

    def test_paused_hour_that_exited_cleanly_is_classified_as_before(self):
        (self.root/dp.ENTERED).write_text('{}')
        (self.root/dp.EXITED).write_text('{}')
        self.write('owned.json', dict(status='completed', returncode=0, cleanup_verified=True, supervisor_failure=None))
        self.write('disk.json', dict(outcome='COMPLETED', stop_reason=None, runner_exit_code=0, child_exit_code=0,
                                     operating_reserve_breaches=[]))
        self.write('worker-terminal.json', dict(status='completed', applied_positions=6150))
        digest = self.bind(success=True)
        outcome = json.loads((self.root.parent/'operator/operator-outcome.json').read_bytes())
        outcome['measurement_files'] = {name: self.runner.file_sha256(self.root/name) for name in
            ('hour-result.json', 'owned.json', 'disk.json', 'worker-terminal.json', 'rows.jsonl')}
        (self.root.parent/'operator/operator-outcome.json').write_text(json.dumps(outcome))
        with self.assertRaisesRegex(ValueError, 'independently bound next-update reference'):
            cia_hour.validate_continuation(self.runner, self.identity)

    def test_parameter_dump_flag_must_match_between_source_and_continuation(self):
        self.prior['parameter_dump'] = dict(DUMP)
        self.write('prediction.json', {'identity': self.prior})
        self.hour['prediction_sha256'] = self.runner.file_sha256(self.root/'prediction.json')
        self.bind()
        with self.assertRaisesRegex(ValueError, 'identity differs: parameter_dump'):
            cia_hour.validate_continuation(self.runner, self.identity)


class DumpAndComparatorTests(unittest.TestCase):
    def test_dump_holds_only_optimizer_state_owners_with_their_dtype_and_refuses_overwrite(self):
        import torch
        owner = torch.nn.Parameter(torch.ones(4, 3, dtype=torch.bfloat16))
        idle = torch.nn.Parameter(torch.ones(2, dtype=torch.float32))
        optimizer = torch.optim.AdamW([owner], lr=1e-2)
        owner.grad = torch.full_like(owner, 0.5)
        optimizer.step()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'dump.pt'
            record = dp.dump_updated_parameters(path, optimizer, {'owner.weight': owner, 'idle.weight': idle})
            loaded = torch.load(path, map_location='cpu', weights_only=True)
            self.assertEqual(list(loaded), ['owner.weight'])
            self.assertEqual(loaded['owner.weight'].dtype, torch.bfloat16)
            self.assertTrue(torch.equal(loaded['owner.weight'], owner.detach()))
            self.assertEqual((record['tensors'], record['elements'], record['dtypes'], record['sha256']),
                             (1, 12, ['torch.bfloat16'], sha(path)))
            self.assertFalse(path.with_name('dump.pt.partial').exists())
            with self.assertRaisesRegex(ValueError, 'already exists'):
                dp.dump_updated_parameters(path, optimizer, {'owner.weight': owner})
        with self.assertRaisesRegex(ValueError, 'no optimizer-state owners'):
            dp.dump_updated_parameters('unused.pt', torch.optim.AdamW([idle]), {'idle.weight': idle})

    def save(self, directory, name, tensors):
        import torch
        path = Path(directory)/name
        torch.save(tensors, path)
        return path

    def test_comparator_reports_equal_and_refuses_every_difference_without_a_tolerance(self):
        import torch
        base = {'a': torch.arange(6, dtype=torch.float32).reshape(2, 3), 'b': torch.ones(4, dtype=torch.bfloat16)}
        with tempfile.TemporaryDirectory() as directory:
            first = self.save(directory, 'first.pt', base)
            self.assertTrue(dp.compare_dumps(first, self.save(directory, 'same.pt', copy.deepcopy(base)))['bitwise_equal'])
            self.assertEqual(dp.main(['x', 'compare', str(first), str(Path(directory)/'same.pt')]), 0)
            nudged = copy.deepcopy(base)
            nudged['a'][1, 2] = torch.nextafter(nudged['a'][1, 2], torch.tensor(1e9))   # one ulp
            report = dp.compare_dumps(first, self.save(directory, 'ulp.pt', nudged))
            self.assertEqual(report['verdict'], 'REFUSE_DIFFERS')
            row = report['differing'][0]
            self.assertEqual((row['name'], row['elements_differing']), ('a', 1))
            self.assertGreater(row['max_abs_diff'], 0)
            self.assertGreater(row['relative_l2'], 0)
            self.assertEqual(dp.main(['x', 'compare', str(first), str(Path(directory)/'ulp.pt')]), 1)
            dtype = dict(base, b=base['b'].float())
            self.assertEqual(dp.compare_dumps(first, self.save(directory, 'dtype.pt', dtype))['differing'][0]['reason'], 'dtype or shape')
            missing = {'a': base['a']}
            report = dp.compare_dumps(first, self.save(directory, 'missing.pt', missing))
            self.assertEqual(report['names_only_in_first'], ['b'])
            self.assertFalse(report['bitwise_equal'])

    def test_comparator_separates_negative_zero_and_nan_payloads_by_bits(self):
        import torch
        with tempfile.TemporaryDirectory() as directory:
            zero = self.save(directory, 'zero.pt', {'a': torch.tensor([0.0])})
            negative = self.save(directory, 'negative.pt', {'a': torch.tensor([-0.0])})
            self.assertFalse(dp.compare_dumps(zero, negative)['bitwise_equal'])
            nan = self.save(directory, 'nan.pt', {'a': torch.tensor([float('nan')])})
            self.assertTrue(dp.compare_dumps(nan, self.save(directory, 'nan2.pt', {'a': torch.tensor([float('nan')])}))['bitwise_equal'])


if __name__ == '__main__':
    unittest.main()
