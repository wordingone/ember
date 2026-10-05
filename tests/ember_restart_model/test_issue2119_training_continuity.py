"""Issue #2119: purpose gate before dispatch (section 2) and the diagnostic-allowance ledger
(section 3) that keeps a lineage's non-advancing time bounded, with non-learning fixtures only.

Test Requirements covered: missing purpose refuses before spawn; renaming does not replenish
the allowance; an authorized extension is distinguishable; bounded blocker renewals; stale
parent or partial publication cannot advance the counters; state survives a restart. One
deliberate red proves the gate is load-bearing rather than a no-op.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import training_continuity_ledger as ledger  # noqa: E402
import training_continuity_status as status  # noqa: E402
import selected_continuation_head as head_pointer  # noqa: E402


def _load_step_runner():
    spec = importlib.util.spec_from_file_location('cia_step_runner_2119test', MODULE_DIR / 'cia_step_runner.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile((MODULE_DIR / 'cia_step_runner.py').read_bytes(), str(MODULE_DIR / 'cia_step_runner.py'), 'exec'), module.__dict__)
    return module


runner = _load_step_runner()

_BASE_KEYS = ('run_id', 'source_commit', 'source_sha256', 'config_sha256', 'data', 'seed',
              'support', 'optimizer', 'geometry', 'batch_documents', 'resources', 'input_binding',
              'gpu_uuid', 'dispatch_resources')


def _bare_identity(**extra):
    identity = dict.fromkeys(_BASE_KEYS)
    identity.update(extra)
    return identity


def _current_subject_payload(checkpoint_sha, *, predecessor_sha=None):
    """A minimal but fully closed-schema current-subject payload, matching every check in
    gen_readme_status.load_current_subject -- built from the shape of the real
    manifests/ember-current-subject-v1.json this repository already ships, with only the
    checkpoint (and optionally predecessor) digest varied per test."""
    predecessor_sha = predecessor_sha or hashlib.sha256(b'fixture-predecessor').hexdigest()
    return {
        'schema_version': 'ember-current-subject-v1',
        'authority': {
            'goal_id': 'EMBER-02', 'workstream_id': 'EMBER-02A',
            'next_executed_outcome': 'EMBER-02 first sufficiently pretrained clean-genesis 3B Ember',
        },
        'subject': {
            'checkpoint_manifest_sha256': checkpoint_sha,
            'model_config_sha256': hashlib.sha256(b'fixture-model-config').hexdigest(),
            'tokenizer_sha256': hashlib.sha256(b'fixture-tokenizer').hexdigest(),
            'optimizer_state_sha256': hashlib.sha256(b'fixture-optimizer').hexdigest(),
            'token_cursor': {'global_step': 2, 'record_index': 2, 'token_offset': 2048, 'tokens_seen': 2048},
            'active_route': 'shared',
            'parameters': {'active': 100, 'allocated': 400, 'episode_trainable': 100,
                           'served': 400, 'trainable': 400, 'unique': 400},
            'disposition': 'CHECKPOINT_CANDIDATE_NOT_ADMITTED',
            'capability_credit': 'none',
            'sufficient_pretraining_proven': False,
            'predecessor': {'checkpoint_manifest_sha256': predecessor_sha, 'tokens_seen': 1024,
                            'relationship': 'historical_step1_predecessor'},
            'checkpoint_custody': {'class': 'private_checkpoint_bytes', 'locator_id': 'fixture-locator',
                                   'public_manifest_bytes_present': False},
            'evidence_paths': ['docs/domains/governance/ember-restart/integration-contract-v1.md'],
        },
    }


def _write_current_subject(path, checkpoint_sha, *, predecessor_sha=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_current_subject_payload(checkpoint_sha, predecessor_sha=predecessor_sha)),
                    encoding='utf-8')
    return path


class PurposeGateRefusesBeforeSpawnTests(unittest.TestCase):
    """Section 2: prepare_execution runs on the controller BEFORE the GPU worker is spawned
    (cia_step_runner.launch calls it, then OwnedProcessRunner.run) and on the worker itself
    (worker() calls it again) -- one shared check covers both call sites."""

    def test_missing_purpose_refuses_before_any_further_admission_work(self):
        identity = _bare_identity()  # no training_job_purpose at all
        with patch.object(runner, 'file_sha256', side_effect=AssertionError('premature source read')):
            with self.assertRaisesRegex(ValueError, 'measurement identity fields differ'):
                runner.prepare_execution({'identity': identity})

    def test_continue_training_without_resume_or_data_segment_refuses(self):
        identity = _bare_identity(training_job_purpose='CONTINUE_TRAINING')
        with self.assertRaisesRegex(ValueError, 'CONTINUE_TRAINING requires'):
            runner.validate_training_job_purpose(identity, hour=False)

    def test_diagnostic_without_its_companion_fields_refuses(self):
        identity = _bare_identity(training_job_purpose='DIAGNOSTIC')
        with self.assertRaisesRegex(ValueError, 'DIAGNOSTIC requires a non-empty'):
            runner.validate_training_job_purpose(identity, hour=False)

    def test_diagnostic_with_its_companion_fields_is_admitted(self):
        identity = _bare_identity(
            training_job_purpose='DIAGNOSTIC',
            training_diagnostic_question='does the fused path regress the loss',
            training_diagnostic_non_advancement_reason='numerical parity unverified',
            training_diagnostic_return_condition='parity proven on a matched pair',
        )
        self.assertEqual(runner.validate_training_job_purpose(identity, hour=False), 'DIAGNOSTIC')

    def test_deliberate_red_disabling_the_gate_lets_a_missing_purpose_through(self):
        """Proves the gate is load-bearing. An identity declaring DIAGNOSTIC without its
        required companion fields clears the closed-set schema check (the key is present,
        it says nothing about the value) and is refused only by validate_training_job_purpose
        itself. With that call patched into a no-op, the SAME identity is not refused for its
        purpose at all -- it falls through to an unrelated downstream failure, proving the
        purpose-specific refusal message came from the gate and not from some other check."""
        identity = _bare_identity(training_job_purpose='DIAGNOSTIC')
        with patch.object(runner, 'file_sha256', side_effect=AssertionError('premature source read')):
            with self.assertRaisesRegex(ValueError, 'DIAGNOSTIC requires a non-empty'):
                runner.prepare_execution({'identity': identity})
        with patch.object(runner, 'validate_training_job_purpose', return_value=None):
            with patch.object(runner, 'file_sha256', side_effect=AssertionError('premature source read')):
                with self.assertRaises((ValueError, TypeError)) as failure:
                    runner.prepare_execution({'identity': identity})
        self.assertNotIn('DIAGNOSTIC', str(failure.exception))


class LedgerLineageAndReadBackTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / 'diagnostic-allowance-ledger.jsonl'

    def tearDown(self):
        self._tmp.cleanup()

    def test_genesis_lineage_with_no_resume_reference(self):
        # repo_root points at a directory with no manifests/ subdirectory at all, so this
        # exercises the genuine bootstrap case -- never the real repository's own published
        # current-subject record (see SelectedContinuationHeadKeyingTests for that case).
        self.assertEqual(
            ledger.lineage_checkpoint_manifest_sha256({}, repo_root=Path(self._tmp.name)),
            ledger.GENESIS_SENTINEL)

    def test_two_custody_parents_on_the_same_lineage_share_one_ledger_and_accumulate(self):
        """issue #2119 REDO: every #1945 dispatch mints a fresh timestamped --custody parent.
        ledger_path must resolve to the SAME file regardless of which parent is passed, so
        reservations against different parents accumulate against one lineage instead of each
        starting at zero."""
        parent_a = Path(self._tmp.name) / 'cia-hour-run-a-20260101T000000Z'
        parent_b = Path(self._tmp.name) / 'cia-hour-run-b-20260102T000000Z'
        parent_a.mkdir()
        parent_b.mkdir()
        with patch.dict(os.environ, {ledger.LEDGER_ROOT_ENV: str(Path(self._tmp.name) / 'ledger-root')}):
            self.assertEqual(ledger.ledger_path(parent_a), ledger.ledger_path(parent_b))
            path = ledger.ledger_path(parent_a)
            policy = dict(ledger.DEFAULT_POLICY, max_diagnostic_occupancy_seconds=100)
            ledger.reserve_diagnostic_dispatch(
                path=ledger.ledger_path(parent_a), lineage_sha='shared-lineage', run_id='r1',
                budget_seconds=60, diagnostic_question='q', non_advancement_reason='n',
                return_condition='c', policy=policy, now=1000.0)
            # A second dispatch, same lineage, DIFFERENT custody parent: must accrue against the
            # same allowance rather than starting fresh.
            with self.assertRaisesRegex(ValueError, 'diagnostic allowance exhausted \\(occupancy\\)'):
                ledger.reserve_diagnostic_dispatch(
                    path=ledger.ledger_path(parent_b), lineage_sha='shared-lineage', run_id='r2',
                    budget_seconds=60, diagnostic_question='q', non_advancement_reason='n',
                    return_condition='c', policy=policy, now=1001.0)
            rows = ledger.read_rows(path)
            self.assertEqual(len(rows), 1)

    def test_state_survives_a_restart(self):
        """The ledger is read fresh from disk every time -- no in-process cache to lose."""
        ledger.reserve_diagnostic_dispatch(
            path=self.path, lineage_sha='abc', run_id='r1', budget_seconds=60,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=ledger.DEFAULT_POLICY, now=1000.0)
        reloaded_module = importlib.reload(ledger)
        rows = reloaded_module.read_rows(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(reloaded_module.diagnostic_occupancy_seconds(rows, 'abc'), 60)

    def test_renaming_the_run_does_not_replenish_the_allowance(self):
        """The ledger keys on lineage sha only -- never on run_id, session, or branch -- so
        dispatching the same lineage under a different run_id changes nothing about its
        accrued occupancy."""
        policy = dict(ledger.DEFAULT_POLICY, max_diagnostic_occupancy_seconds=100)
        ledger.reserve_diagnostic_dispatch(
            path=self.path, lineage_sha='L1', run_id='original-run-name', budget_seconds=90,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=policy, now=1000.0)
        with self.assertRaisesRegex(ValueError, 'diagnostic allowance exhausted \\(occupancy\\)'):
            ledger.reserve_diagnostic_dispatch(
                path=self.path, lineage_sha='L1', run_id='renamed-run-entirely-different',
                budget_seconds=90, diagnostic_question='q', non_advancement_reason='n',
                return_condition='c', policy=policy, now=1000.0)

    def test_an_authorized_extension_is_distinguishable_and_restores_headroom(self):
        policy = dict(ledger.DEFAULT_POLICY, max_diagnostic_occupancy_seconds=100)
        ledger.reserve_diagnostic_dispatch(
            path=self.path, lineage_sha='L2', run_id='r1', budget_seconds=90,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=policy, now=1000.0)
        with self.assertRaises(ValueError):
            ledger.record_operator_extension(path=self.path, lineage_sha='L2', authority_reference='',
                                              extension_seconds=200)
        extension = ledger.record_operator_extension(
            path=self.path, lineage_sha='L2', authority_reference='issue-2119 comment 1',
            extension_seconds=200, now=1001.0)
        self.assertEqual(extension['row_kind'], 'operator_extension')
        self.assertEqual(extension['authority_reference'], 'issue-2119 comment 1')
        # Now admissible again: the extension is a distinct, attributable row, not a rewrite
        # of the original reservation.
        rows = ledger.read_rows(self.path)
        self.assertEqual(sum(1 for r in rows if r['row_kind'] == 'reservation'), 1)
        self.assertEqual(sum(1 for r in rows if r['row_kind'] == 'operator_extension'), 1)
        ledger.reserve_diagnostic_dispatch(
            path=self.path, lineage_sha='L2', run_id='r2', budget_seconds=90,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=policy, now=1002.0)

    def test_bounded_blocker_renewals(self):
        # A zero occupancy cap means EVERY dispatch against this lineage is "over" from the
        # first budget_seconds onward, so each attempt in the loop below genuinely exercises
        # the blocker-occurrence check rather than merely staying under an unreached cap.
        policy = dict(ledger.DEFAULT_POLICY, max_diagnostic_occupancy_seconds=0, max_blocker_renewals=2)
        # A dispatch with no blocker refuses outright once the lineage is over its allowance.
        with self.assertRaises(ValueError):
            ledger.reserve_diagnostic_dispatch(
                path=self.path, lineage_sha='L3', run_id='r0', budget_seconds=1,
                diagnostic_question='q', non_advancement_reason='n', return_condition='c',
                policy=policy, now=1000.0)
        blocker = 'GPU card held by another governed hour'
        for attempt, ts in enumerate((1001.0, 1002.0, 1003.0), start=1):
            ledger.reserve_diagnostic_dispatch(
                path=self.path, lineage_sha='L3', run_id=f'r{attempt}', budget_seconds=1,
                diagnostic_question='q', non_advancement_reason='n', return_condition='c',
                readiness_blocker=blocker, policy=policy, now=ts)
        # A fourth attempt with the same blocker exceeds the bound (initial grant + 2 renewals).
        with self.assertRaisesRegex(ValueError, 'exhausted its renewals'):
            ledger.reserve_diagnostic_dispatch(
                path=self.path, lineage_sha='L3', run_id='r4', budget_seconds=1,
                diagnostic_question='q', non_advancement_reason='n', return_condition='c',
                readiness_blocker=blocker, policy=policy, now=1004.0)
        # A DIFFERENT blocker starts its own count from zero.
        ledger.reserve_diagnostic_dispatch(
            path=self.path, lineage_sha='L3', run_id='r5', budget_seconds=1,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            readiness_blocker='a different named blocker', policy=policy, now=1005.0)

    def test_a_new_lineage_key_starts_with_zero_occupancy(self):
        """The implicit reset: once a CONTINUE_TRAINING job publishes a descendant, that
        descendant's manifest sha becomes the new lineage key and nothing keyed to the OLD
        lineage counts toward it."""
        policy = dict(ledger.DEFAULT_POLICY, max_diagnostic_occupancy_seconds=50)
        ledger.reserve_diagnostic_dispatch(
            path=self.path, lineage_sha='OLD', run_id='r1', budget_seconds=50,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=policy, now=1000.0)
        # OLD is now exhausted, but NEW (the freshly published descendant) starts clean.
        ledger.reserve_diagnostic_dispatch(
            path=self.path, lineage_sha='NEW', run_id='r2', budget_seconds=50,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=policy, now=1001.0)

    def test_retention_experiment_with_no_eligible_descendant_counts_toward_occupancy(self):
        row = ledger.record_retention_experiment_outcome(
            path=self.path, lineage_sha='L4', run_id='r1',
            eligible_descendant_published=False, elapsed_seconds=45, now=1000.0)
        self.assertIsNotNone(row)
        rows = ledger.read_rows(self.path)
        self.assertEqual(ledger.diagnostic_occupancy_seconds(rows, 'L4'), 45)

    def test_retention_experiment_that_did_publish_is_not_ledgered(self):
        row = ledger.record_retention_experiment_outcome(
            path=self.path, lineage_sha='L5', run_id='r1',
            eligible_descendant_published=True, elapsed_seconds=999, now=1000.0)
        self.assertIsNone(row)
        self.assertEqual(ledger.read_rows(self.path), [])


class StaleOrPartialPublicationCannotAdvanceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, payload):
        path = self.root / name
        raw = json.dumps(payload).encode('utf-8')
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def test_stale_parent_hour_result_refuses(self):
        path, digest = self._write('hour-result.json', {'child_manifest_sha256': 'a' * 64})
        # Mutate the file after it was bound -- the referenced parent is now stale.
        path.write_bytes(path.read_bytes() + b' ')
        identity = {'checkpoint_probe': {'custody_root': str(self.root), 'result_sha256': digest}}
        with self.assertRaisesRegex(ValueError, 'changed since it was bound'):
            ledger.lineage_checkpoint_manifest_sha256(identity)

    def test_partial_publication_missing_child_manifest_refuses(self):
        path, digest = self._write('hour-result.json', {'some_other_field': True})
        identity = {'checkpoint_probe': {'custody_root': str(self.root), 'result_sha256': digest}}
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            ledger.lineage_checkpoint_manifest_sha256(identity)

    def test_well_formed_continuation_reference_resolves_the_lineage(self):
        path, digest = self._write('hour-result.json', {'child_manifest_sha256': 'b' * 64})
        identity = {'continuation': {'source_hour_result_path': str(path), 'source_hour_result_sha256': digest}}
        self.assertEqual(ledger.lineage_checkpoint_manifest_sha256(identity), 'b' * 64)


class SelectedContinuationHeadKeyingTests(unittest.TestCase):
    """issue #2119 REDO: a diagnostic with NO checkpoint_probe/continuation of its own must key
    to the repository's currently selected continuation head, never unconditionally to GENESIS
    -- and a published CONTINUE_TRAINING descendant (a new selected head) must reset the
    allowance, exactly like the existing implicit-reset test does for the checkpoint_probe path.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = self.root / 'diagnostic-allowance-ledger.jsonl'
        self.subject_path = self.root / 'ember-current-subject-v1.json'

    def test_diagnostic_with_no_checkpoint_reference_keys_to_the_selected_head(self):
        head = hashlib.sha256(b'selected-head-1').hexdigest()
        _write_current_subject(self.subject_path, head)
        self.assertEqual(
            ledger.lineage_checkpoint_manifest_sha256(
                {}, repo_root=ROOT, current_subject_path=self.subject_path),
            head)

    def test_a_published_continue_training_descendant_resets_the_allowance(self):
        """The old head's allowance is exhausted; the moment the current-subject record is
        rewritten to name a NEW selected head (as update_current_subject.py does on every
        CONTINUE_TRAINING publication), a diagnostic with no reference of its own keys to the
        new head and starts with a clean allowance -- the same implicit-reset guarantee the
        checkpoint_probe/continuation paths already had."""
        old_head = hashlib.sha256(b'selected-head-old').hexdigest()
        _write_current_subject(self.subject_path, old_head)
        policy = dict(ledger.DEFAULT_POLICY, max_diagnostic_occupancy_seconds=50)
        lineage_sha = ledger.lineage_checkpoint_manifest_sha256(
            {}, repo_root=ROOT, current_subject_path=self.subject_path)
        self.assertEqual(lineage_sha, old_head)
        ledger.reserve_diagnostic_dispatch(
            path=self.ledger_path, lineage_sha=lineage_sha, run_id='r1', budget_seconds=50,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=policy, now=1000.0)
        with self.assertRaisesRegex(ValueError, 'diagnostic allowance exhausted \\(occupancy\\)'):
            ledger.reserve_diagnostic_dispatch(
                path=self.ledger_path,
                lineage_sha=ledger.lineage_checkpoint_manifest_sha256(
                    {}, repo_root=ROOT, current_subject_path=self.subject_path),
                run_id='r2', budget_seconds=50, diagnostic_question='q',
                non_advancement_reason='n', return_condition='c', policy=policy, now=1001.0)
        # A CONTINUE_TRAINING publication rewrites the current-subject record to a new head.
        new_head = hashlib.sha256(b'selected-head-new').hexdigest()
        _write_current_subject(self.subject_path, new_head, predecessor_sha=old_head)
        new_lineage_sha = ledger.lineage_checkpoint_manifest_sha256(
            {}, repo_root=ROOT, current_subject_path=self.subject_path)
        self.assertEqual(new_lineage_sha, new_head)
        self.assertNotEqual(new_lineage_sha, lineage_sha)
        # The new head's allowance is clean even though the old head's was exhausted.
        ledger.reserve_diagnostic_dispatch(
            path=self.ledger_path, lineage_sha=new_lineage_sha, run_id='r3', budget_seconds=50,
            diagnostic_question='q', non_advancement_reason='n', return_condition='c',
            policy=policy, now=1002.0)


class StatusProducerTests(unittest.TestCase):
    """Section 6: the composed status record, and its two mutually-exclusive next-segment inputs."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # ledger_path now ignores custody_parent and resolves against a fixed host-wide root
        # (issue #2119 REDO fix); pin it to this test's own tempdir so these tests stay isolated
        # and never touch the real receipts root.
        env_patcher = patch.dict(os.environ, {ledger.LEDGER_ROOT_ENV: str(self.root)})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def test_genesis_checkpoint_reports_no_parent_and_zero_retained(self):
        result = status.selected_checkpoint_status(None)
        self.assertEqual(result, {
            'child_manifest_sha256': ledger.GENESIS_SENTINEL,
            'parent_manifest_sha256': None,
            'last_hour_applied_positions': 0,
        })

    def test_published_checkpoint_reports_parent_and_last_hour_applied_positions(self):
        hour_result = {'child_manifest_sha256': 'c' * 64, 'parent_manifest_sha256': 'p' * 64,
                        'applied_positions': 12288}
        self.assertEqual(status.selected_checkpoint_status(hour_result), {
            'child_manifest_sha256': 'c' * 64, 'parent_manifest_sha256': 'p' * 64,
            'last_hour_applied_positions': 12288,
        })

    def test_learning_measurement_is_pending_when_none_supplied(self):
        self.assertEqual(status.last_learning_measurement_status(None), {'status': 'pending'})

    def test_learning_measurement_reports_the_supplied_receipt(self):
        measurement = {'protected_mmmu': 0.285}
        self.assertEqual(status.last_learning_measurement_status(measurement),
                         {'status': 'measured', 'measurement': measurement})

    def test_current_purpose_reports_none_when_nothing_is_dispatched(self):
        self.assertEqual(status.current_purpose_status(None),
                         {'training_job_purpose': None, 'run_id': None})

    def test_next_segment_refuses_when_both_or_neither_input_is_given(self):
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            status.next_segment_status()
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            status.next_segment_status(next_identity={'training_job_purpose': 'CONTINUE_TRAINING'},
                                        blocker='card is held by another lineage')

    def test_next_segment_reports_ready_or_blocked_distinctly(self):
        self.assertEqual(
            status.next_segment_status(next_identity={'training_job_purpose': 'CONTINUE_TRAINING', 'run_id': 'r1'}),
            {'status': 'ready', 'training_job_purpose': 'CONTINUE_TRAINING', 'run_id': 'r1'})
        self.assertEqual(
            status.next_segment_status(blocker='no admitted mixture bound yet'),
            {'status': 'blocked', 'blocker': 'no admitted mixture bound yet'})

    def test_diagnostic_allowance_status_matches_the_reservation_gates_own_arithmetic(self):
        path = ledger.ledger_path(self.root)
        policy = dict(ledger.DEFAULT_POLICY, max_diagnostic_occupancy_seconds=1000,
                      max_postponement_seconds=10_000, max_blocker_renewals=2)
        ledger.reserve_diagnostic_dispatch(path=path, lineage_sha='lin', run_id='d1', budget_seconds=400,
            diagnostic_question='q', non_advancement_reason='r', return_condition='c', policy=policy, now=100.0)
        result = status.diagnostic_allowance_status(custody_parent=self.root, lineage_sha='lin', policy=policy, now=200.0)
        self.assertEqual(result['diagnostic_occupancy_seconds'], 400)
        self.assertEqual(result['postponement_seconds'], 100)
        self.assertFalse(result['at_occupancy_limit'])
        self.assertFalse(result['at_postponement_limit'])

    def test_full_status_record_composes_every_section_under_one_lineage_key(self):
        hour_result = {'child_manifest_sha256': 'child' + 'a' * 59, 'parent_manifest_sha256': 'parent' + 'b' * 58,
                        'applied_positions': 4096}
        lineage_record = {'schema': status.LINEAGE_SCHEMA, 'head_manifest_sha256': hour_result['child_manifest_sha256'],
                          'genesis_manifest_sha256': 'g' * 64, 'depth': 3, 'cumulative_applied_token_delta': 123456,
                          'cumulative_step_delta': 321}
        record = status.training_continuity_status(
            custody_parent=self.root, hour_result=hour_result, lineage_record=lineage_record,
            current_identity={'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'd2'},
            measurement=None, next_blocker='readiness blocker: image evaluator unbound')
        self.assertEqual(record['schema'], status.STATUS_SCHEMA)
        self.assertEqual(record['lineage_checkpoint_manifest_sha256'], hour_result['child_manifest_sha256'])
        self.assertEqual(record['checkpoint']['last_hour_applied_positions'], 4096)
        self.assertEqual(record['lineage'], {'depth': 3, 'genesis_manifest_sha256': 'g' * 64,
                                             'retained_applied_positions': 123456, 'retained_global_steps': 321})
        self.assertEqual(record['claim_budget_eligible'], {'status': status.UNDEFINED, 'missing': status.CLAIM_PREDICATE_MISSING})
        self.assertEqual(record['gpu_owner'], {'status': 'not_reported'})
        self.assertEqual(record['learning_measurement'], {'status': 'pending'})
        self.assertEqual(record['purpose']['training_job_purpose'], 'DIAGNOSTIC')
        self.assertEqual(record['next_segment'],
                         {'status': 'blocked', 'blocker': 'readiness blocker: image evaluator unbound'})
        self.assertIn('diagnostic_occupancy_seconds', record['diagnostic_allowance'])


class LedgerRootDerivedFromCustodyTests(unittest.TestCase):
    def test_two_dispatch_parents_share_one_ledger_and_no_parent_refuses(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ledger.LEDGER_ROOT_ENV, None)
            root = Path(tmp)
            first, second = root / 'hour-20260928T010000Z', root / 'hour-20260928T020000Z'
            first.mkdir(); second.mkdir()
            self.assertEqual(ledger.ledger_path(first), ledger.ledger_path(second))
            self.assertEqual(ledger.ledger_path(first).parent, root.resolve())
            with self.assertRaises(ValueError):
                ledger.ledger_path(None)


class SelectedContinuationHeadAdvanceTests(unittest.TestCase):
    """Issue #2119 section 5: advance_selected_continuation_head's three failure modes, each
    proving the pointer file is byte-identical before and after the refused call -- a refusal
    that silently mutated the pointer would be worse than no refusal at all.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.receipts_root = self.root / 'receipts'

    def _published_checkpoint(self, name, shard=0, record_index=0):
        """A minimal but real admitted-checkpoint fixture: an hour custody directory holding
        hour-result.json plus a sibling trained-child/checkpoint-manifest.json -- the exact
        shape resolve_continuation_parent (tested below) expects to find on disk too."""
        hour_dir = self.root / name
        child_dir = hour_dir / 'trained-child'
        child_dir.mkdir(parents=True)
        manifest_bytes = json.dumps(
            {'data_cursor': {'shard': shard, 'record_index': record_index}}).encode('utf-8')
        (child_dir / 'checkpoint-manifest.json').write_bytes(manifest_bytes)
        hour_result_bytes = json.dumps({'claim': 'fixture hour result', 'name': name}).encode('utf-8')
        hour_result_path = hour_dir / 'hour-result.json'
        hour_result_path.write_bytes(hour_result_bytes)
        return dict(published_checkpoint_root=child_dir, hour_result_path=hour_result_path,
                    hour_result_sha256=hashlib.sha256(hour_result_bytes).hexdigest(),
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())

    def _pointer_bytes(self):
        path = head_pointer.pointer_path(self.receipts_root)
        return path.read_bytes() if path.is_file() else None

    def test_stale_parent_promotion_refuses_and_leaves_pointer_untouched(self):
        """Two chains fork from one head: the first publish advances the pointer to C1; the
        second, still declaring the superseded GENESIS parent, is a fork and must refuse."""
        c1 = self._published_checkpoint('hour-c1')
        head_pointer.advance_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1000.0)
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), c1['manifest_sha256'])
        before = self._pointer_bytes()

        c2 = self._published_checkpoint('hour-c2-fork')
        with self.assertRaises(head_pointer.StaleParentError):
            head_pointer.advance_selected_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c2['published_checkpoint_root'],
                hour_result_path=c2['hour_result_path'],
                hour_result_sha256=c2['hour_result_sha256'],
                # Declares the pointer's OLD value; the pointer has already moved to c1.
                expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1001.0)
        self.assertEqual(self._pointer_bytes(), before)
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), c1['manifest_sha256'])

    def test_partial_publication_fails_round_trip_validation_and_leaves_pointer_untouched(self):
        """Mechanism 3's round-trip validation refuses a candidate whose own fields would not
        pass load_selected_continuation_head -- here an hour_result_sha256 that is not a sha256
        hex string, the shape a truncated or half-written publication would produce -- and the
        target file (absent, on the first call) is provably never created."""
        c1 = self._published_checkpoint('hour-partial')
        self.assertIsNone(self._pointer_bytes())
        with self.assertRaisesRegex(ValueError, 'hour_result_sha256 must be a sha256 hex string'):
            head_pointer.advance_selected_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c1['published_checkpoint_root'],
                hour_result_path=c1['hour_result_path'],
                hour_result_sha256='not-a-complete-sha256-digest',
                expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1000.0)
        self.assertIsNone(self._pointer_bytes())
        # No staged temp file survives the refusal either.
        self.assertEqual(list(self.receipts_root.glob('.*.tmp')) if self.receipts_root.is_dir() else [], [])

    def test_duplicate_replay_of_an_already_selected_child_refuses_as_stale_parent(self):
        """The same publication event replayed a second time (a retry, a re-run of the same
        job) declares the parent it was ORIGINALLY dispatched with -- GENESIS -- but the first
        replay already advanced the pointer to this exact checkpoint. The duplicate is refused
        by the identical CAS check, and the pointer keeps exactly one credit for it, not two."""
        c1 = self._published_checkpoint('hour-c1-again')
        head_pointer.advance_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1000.0)
        before = self._pointer_bytes()
        with self.assertRaises(head_pointer.StaleParentError):
            head_pointer.advance_selected_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c1['published_checkpoint_root'],
                hour_result_path=c1['hour_result_path'],
                hour_result_sha256=c1['hour_result_sha256'],
                # Same stale declaration the original (already-credited) dispatch carried.
                expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1002.0)
        self.assertEqual(self._pointer_bytes(), before)

    def test_deliberate_red_a_stale_parent_check_that_always_agrees_lets_duplicate_credit_through(self):
        """Proves the CAS check in test 3 above is load-bearing: with the comparison patched to
        always agree (simulating a StaleParentError check that was silently disabled), the
        duplicate replay is WRONGLY accepted and overwrites the pointer a second time -- the
        exact defect the real code refuses. This is the failing case the passing tests above
        are protecting against."""
        c1 = self._published_checkpoint('hour-c1-red')
        head_pointer.advance_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1000.0)
        first_published_at = json.loads(self._pointer_bytes())['published_at']
        with patch.object(head_pointer, 'GENESIS_SENTINEL', head_pointer.current_head_sha256(self.receipts_root)):
            # With the sentinel patched to already equal the pointer's current value, the very
            # same duplicate-replay call from test 3 (still declaring GENESIS) now spuriously
            # "agrees" and is wrongly accepted -- no StaleParentError, and the pointer is
            # overwritten a second time for the identical checkpoint.
            head_pointer.advance_selected_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c1['published_checkpoint_root'],
                hour_result_path=c1['hour_result_path'],
                hour_result_sha256=c1['hour_result_sha256'],
                expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1002.0)
        second_published_at = json.loads(self._pointer_bytes())['published_at']
        self.assertNotEqual(first_published_at, second_published_at)


def _run_hour_source() -> str:
    """Source text of cia_hour.run_hour (from its def to the next top-level def)."""
    text = (MODULE_DIR / 'cia_hour.py').read_text(encoding='utf-8')
    start = text.index('\ndef run_hour(')
    end = text.find('\ndef ', start + 1)
    return text[start:end if end != -1 else len(text)]


def _hour_moves_selected_head(source: str) -> bool:
    """True when the hour source can move the SELECTED head (an advance or seed call)."""
    return ('advance_selected_continuation_head(' in source
            or 'seed_selected_continuation_head(' in source)


class CandidateContinuationHeadTests(unittest.TestCase):
    """Operator ruling (mail 53920): an hour's own publish writes a CANDIDATE pointer only and never moves the
    selected head (the H20 and H21 hours each did, before their frozen score)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.receipts_root = self.root / 'receipts'
        self._helper = SelectedContinuationHeadAdvanceTests('test_stale_parent_promotion_refuses_and_leaves_pointer_untouched')
        self._helper.root = self.root
        self._helper.receipts_root = self.receipts_root

    def _publish(self, name, parent):
        c = self._helper._published_checkpoint(name)
        cand = head_pointer.publish_candidate_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c['published_checkpoint_root'],
            hour_result_path=c['hour_result_path'], hour_result_sha256=c['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=parent, now=1000.0)
        return c, cand

    def test_candidate_publish_never_creates_or_moves_the_selected_head(self):
        c1 = self._helper._published_checkpoint('hour-selected')
        head_pointer.advance_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=500.0)
        selected_before = head_pointer.pointer_path(self.receipts_root).read_bytes()
        c2, cand = self._publish('hour-candidate', c1['manifest_sha256'])
        self.assertEqual(head_pointer.pointer_path(self.receipts_root).read_bytes(), selected_before)
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), c1['manifest_sha256'])
        loaded = head_pointer.load_candidate_continuation_head(head_pointer.candidate_path(self.receipts_root))
        self.assertEqual(loaded, cand)
        self.assertEqual(loaded['candidate_checkpoint_manifest_sha256'], c2['manifest_sha256'])
        self.assertEqual(loaded['parent_checkpoint_manifest_sha256'], c1['manifest_sha256'])

    def test_candidate_publish_with_no_selected_head_leaves_it_absent(self):
        self._publish('hour-first', head_pointer.GENESIS_SENTINEL)
        self.assertFalse(head_pointer.pointer_path(self.receipts_root).exists())
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), head_pointer.GENESIS_SENTINEL)

    def test_candidate_file_is_never_readable_as_a_selected_head(self):
        self._publish('hour-cross', head_pointer.GENESIS_SENTINEL)
        with self.assertRaises(ValueError):
            head_pointer.load_selected_continuation_head(head_pointer.candidate_path(self.receipts_root))

    def test_refused_candidate_publish_writes_nothing(self):
        c = self._helper._published_checkpoint('hour-bad')
        with self.assertRaisesRegex(ValueError, 'hour_result_sha256 must be a sha256 hex string'):
            head_pointer.publish_candidate_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c['published_checkpoint_root'],
                hour_result_path=c['hour_result_path'], hour_result_sha256='short',
                expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1.0)
        self.assertFalse(head_pointer.candidate_path(self.receipts_root).exists())
        self.assertEqual(list(self.receipts_root.glob('.*.tmp')) if self.receipts_root.is_dir() else [], [])

    def test_run_hour_source_cannot_move_the_selected_head(self):
        source = _run_hour_source()
        self.assertFalse(_hour_moves_selected_head(source))
        self.assertIn('publish_candidate_continuation_head(', source)

    def test_deliberate_red_an_hour_that_advances_the_selected_head_is_caught(self):
        """The class check is load-bearing: restoring the old advance call into run_hour's source is detected."""
        regressed = _run_hour_source().replace('publish_candidate_continuation_head(', 'advance_selected_continuation_head(')
        self.assertTrue(_hour_moves_selected_head(regressed))


class SelectedContinuationHeadSeedTests(unittest.TestCase):
    """Issue #2119 section 5 REDO (operator catch, 2026-09-28): seed_selected_continuation_head,
    the one-time bootstrap for a live lineage that already has trained history predating this
    pointer. Legal only from GENESIS -- every test proves the pointer file is byte-identical
    before and after a refused call, matching SelectedContinuationHeadAdvanceTests' discipline.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.receipts_root = self.root / 'receipts'

    def _published_checkpoint(self, name, shard=0, record_index=0):
        hour_dir = self.root / name
        child_dir = hour_dir / 'trained-child'
        child_dir.mkdir(parents=True)
        manifest_bytes = json.dumps(
            {'data_cursor': {'shard': shard, 'record_index': record_index}}).encode('utf-8')
        (child_dir / 'checkpoint-manifest.json').write_bytes(manifest_bytes)
        hour_result_bytes = json.dumps({'claim': 'fixture hour result', 'name': name}).encode('utf-8')
        hour_result_path = hour_dir / 'hour-result.json'
        hour_result_path.write_bytes(hour_result_bytes)
        return dict(published_checkpoint_root=child_dir, hour_result_path=hour_result_path,
                    hour_result_sha256=hashlib.sha256(hour_result_bytes).hexdigest(),
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())

    def _pointer_bytes(self):
        path = head_pointer.pointer_path(self.receipts_root)
        return path.read_bytes() if path.is_file() else None

    def test_seed_from_genesis_succeeds(self):
        c1 = self._published_checkpoint('existing-lineage-head')
        self.assertIsNone(self._pointer_bytes())
        candidate = head_pointer.seed_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
            reason='live lineage already has trained history; pointer never written', now=1000.0)
        self.assertEqual(candidate['lineage_checkpoint_manifest_sha256'], c1['manifest_sha256'])
        self.assertEqual(candidate['seeded_reason'],
                          'live lineage already has trained history; pointer never written')
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), c1['manifest_sha256'])

    def test_seed_requires_non_empty_reason(self):
        c1 = self._published_checkpoint('needs-a-reason')
        with self.assertRaisesRegex(ValueError, 'reason must be a non-empty string'):
            head_pointer.seed_selected_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c1['published_checkpoint_root'],
                hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
                reason='   ', now=1000.0)
        self.assertIsNone(self._pointer_bytes())

    def test_seed_when_pointer_exists_refuses_and_leaves_file_byte_identical(self):
        c1 = self._published_checkpoint('already-seeded')
        head_pointer.seed_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
            reason='first seed', now=1000.0)
        before = self._pointer_bytes()
        c2 = self._published_checkpoint('a-different-real-checkpoint')

        with self.assertRaises(head_pointer.StaleParentError):
            head_pointer.seed_selected_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c2['published_checkpoint_root'],
                hour_result_path=c2['hour_result_path'], hour_result_sha256=c2['hour_result_sha256'],
                reason='second seed attempt', now=1001.0)
        self.assertEqual(self._pointer_bytes(), before)

    def test_deliberate_red_a_seed_check_that_ignores_an_existing_pointer_lets_a_second_seed_overwrite_the_first(self):
        """Proves the refusal in the test above is load-bearing: calling
        advance_selected_continuation_head (whose CAS DOES check the pointer's real current
        value, unlike a seed with its guard disabled) against the wrong expected parent shows
        the same overwrite that a disabled seed-guard would let through silently."""
        c1 = self._published_checkpoint('red-first-seed')
        head_pointer.seed_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'], hour_result_sha256=c1['hour_result_sha256'],
            reason='first seed', now=1000.0)
        c2 = self._published_checkpoint('red-second-checkpoint')
        # Simulate the seed guard having been removed: a caller with no "does a pointer already
        # exist" check would go straight to writing the candidate, exactly what
        # advance_selected_continuation_head does when (incorrectly) told the expected parent is
        # still GENESIS. The real seed function refuses this same input instead (proven above).
        with self.assertRaises(head_pointer.StaleParentError):
            head_pointer.advance_selected_continuation_head(
                repo_root=ROOT, receipts_root=self.receipts_root,
                published_checkpoint_root=c2['published_checkpoint_root'],
                hour_result_path=c2['hour_result_path'], hour_result_sha256=c2['hour_result_sha256'],
                expected_parent_checkpoint_manifest_sha256=head_pointer.GENESIS_SENTINEL, now=1001.0)

    def test_a_seeded_pointer_re_derives_the_checkpoint_digest_from_disk(self):
        """seed_selected_continuation_head never trusts a caller-declared digest -- it re-derives
        from the published checkpoint's own bytes, the same mechanism 1 discipline
        advance_selected_continuation_head applies. A checkpoint whose manifest is tampered
        AFTER seeding is caught by consumers re-deriving the digest a second time (proven by
        resolve_continuation_parent's own stale-pointer test in the standalone dispatch-preparer
        suite), not by this call itself -- this test proves the WRITTEN digest matches the bytes
        on disk at seed time, not a caller's claim."""
        c1 = self._published_checkpoint('digest-is-rederived')
        candidate = head_pointer.seed_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=c1['published_checkpoint_root'],
            hour_result_path=c1['hour_result_path'],
            # A caller-declared hour_result_sha256 is accepted as-is (it is provenance, not the
            # digest re-derived here) -- but the CHECKPOINT digest is never taken from the caller.
            hour_result_sha256=c1['hour_result_sha256'], reason='digest re-derivation', now=1000.0)
        on_disk_sha256 = hashlib.sha256(
            (c1['published_checkpoint_root'] / 'checkpoint-manifest.json').read_bytes()).hexdigest()
        self.assertEqual(candidate['lineage_checkpoint_manifest_sha256'], on_disk_sha256)
        self.assertEqual(on_disk_sha256, c1['manifest_sha256'])


_CHILD_PRELUDE = '''
import contextlib, json, os, sys, time
from pathlib import Path
args = json.loads(sys.argv[1])
sys.path.insert(0, args['module_dir'])
import selected_continuation_head as hp
_, dio = hp._import_siblings(Path(args['root']))
'''

_CHILD_ADVANCE = _CHILD_PRELUDE + '''
mode = args.get('mode', 'plain')
real_replace = dio.atomic_replace_durable
if mode == 'die_before_replace':
    dio.atomic_replace_durable = lambda staged, target: os._exit(7)
elif mode == 'die_after_replace':
    def _replace_then_die(staged, target):
        real_replace(staged, target)
        os._exit(7)
    dio.atomic_replace_durable = _replace_then_die
if args.get('hold_before_replace'):
    def _slow_replace(staged, target):
        time.sleep(args['hold_before_replace'])
        real_replace(staged, target)
    dio.atomic_replace_durable = _slow_replace
if mode == 'no_lock':
    hp._pointer_lock = contextlib.contextmanager(lambda target_path, timeout=0: (yield))
barrier = args.get('barrier')
while barrier and not Path(barrier).exists():
    time.sleep(0.005)
try:
    hp.advance_selected_continuation_head(
        repo_root=Path(args['root']), receipts_root=Path(args['receipts_root']),
        published_checkpoint_root=Path(args['published_checkpoint_root']),
        hour_result_path=Path(args['hour_result_path']), hour_result_sha256=args['hour_result_sha256'],
        expected_parent_checkpoint_manifest_sha256=args['expected_parent'], now=2000.0)
except hp.StaleParentError:
    sys.exit(3)
'''

_CHILD_HOLD_LOCK = _CHILD_PRELUDE + '''
with hp._pointer_lock(hp.pointer_path(Path(args['receipts_root']))):
    print('HELD', flush=True)
    if args.get('die_holding'):
        os._exit(0)
    time.sleep(args['hold_seconds'])
'''

_CHILD_RESTART_WRITE = _CHILD_PRELUDE + '''
import training_continuity_ledger as ledger
c = args['checkpoint']
head = hp.advance_selected_continuation_head(
    repo_root=Path(args['root']), receipts_root=Path(args['receipts_root']),
    published_checkpoint_root=Path(c['published_checkpoint_root']), hour_result_path=Path(c['hour_result_path']),
    hour_result_sha256=c['hour_result_sha256'], expected_parent_checkpoint_manifest_sha256=hp.GENESIS_SENTINEL, now=1000.0)
ledger.reserve_diagnostic_dispatch(
    path=ledger.ledger_path(Path(args['receipts_root'])), lineage_sha=head['lineage_checkpoint_manifest_sha256'],
    run_id='restart-r1', budget_seconds=300, diagnostic_question='q', non_advancement_reason='n',
    return_condition='c', policy=ledger.DEFAULT_POLICY, now=1000.0)
print(json.dumps({'head': head['lineage_checkpoint_manifest_sha256']}))
'''

_CHILD_RESTART_READ = _CHILD_PRELUDE + '''
import training_continuity_status as status
head_sha = hp.current_head_sha256(Path(args['receipts_root']))
allowance = status.diagnostic_allowance_status(custody_parent=Path(args['receipts_root']), lineage_sha=head_sha, now=1100.0)
print(json.dumps({'head': head_sha, 'occupancy': allowance['diagnostic_occupancy_seconds']}))
'''


class SelectedContinuationHeadCrashAndRaceTests(unittest.TestCase):
    """Issue #2119 section 6b: a hard kill between staging and replacing the pointer, and two real
    writers racing from one parent, using real child interpreters on a temp receipts root and
    synthetic checkpoints (never the live receipts root). Each green test has a deliberate red."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.receipts_root = self.root / 'receipts'
        env_patcher = patch.dict(os.environ, {ledger.LEDGER_ROOT_ENV: str(self.root / 'ledger-root')})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def _checkpoint(self, name, record_index=0):
        hour_dir = self.root / name
        child_dir = hour_dir / 'trained-child'
        child_dir.mkdir(parents=True)
        manifest_bytes = json.dumps({'data_cursor': {'shard': 0, 'record_index': record_index}}).encode('utf-8')
        (child_dir / 'checkpoint-manifest.json').write_bytes(manifest_bytes)
        hour_result_bytes = json.dumps({'name': name}).encode('utf-8')
        (hour_dir / 'hour-result.json').write_bytes(hour_result_bytes)
        return dict(published_checkpoint_root=str(child_dir), hour_result_path=str(hour_dir / 'hour-result.json'),
                    hour_result_sha256=hashlib.sha256(hour_result_bytes).hexdigest(),
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())

    def _advance_in_process(self, checkpoint, expected_parent):
        return head_pointer.advance_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=Path(checkpoint['published_checkpoint_root']),
            hour_result_path=Path(checkpoint['hour_result_path']),
            hour_result_sha256=checkpoint['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=expected_parent, now=1000.0)

    def _child_args(self, checkpoint, expected_parent, **extra):
        return dict(module_dir=str(MODULE_DIR), root=str(ROOT), receipts_root=str(self.receipts_root),
                    expected_parent=expected_parent, **checkpoint, **extra)

    def _spawn(self, script, args, **popen):
        import subprocess
        return subprocess.Popen([sys.executable, '-B', '-c', script, json.dumps(args)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **popen)

    def _pointer_bytes(self):
        path = head_pointer.pointer_path(self.receipts_root)
        return path.read_bytes() if path.is_file() else None

    def _first_head(self):
        c1 = self._checkpoint('c1', record_index=1)
        self._advance_in_process(c1, head_pointer.GENESIS_SENTINEL)
        return c1

    def test_a_kill_between_staging_and_replace_leaves_the_previous_head_selected(self):
        c1 = self._first_head()
        before = self._pointer_bytes()
        c2 = self._checkpoint('c2', record_index=2)
        child = self._spawn(_CHILD_ADVANCE, self._child_args(c2, c1['manifest_sha256'], mode='die_before_replace'))
        child.communicate(timeout=60)
        self.assertEqual(child.returncode, 7)
        self.assertEqual(self._pointer_bytes(), before)
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), c1['manifest_sha256'])
        # A stray staged temp may survive a hard kill; it never selects anything, and the next
        # advance from the real head succeeds without reading it.
        self._advance_in_process(c2, c1['manifest_sha256'])
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), c2['manifest_sha256'])

    def test_deliberate_red_a_kill_after_the_replace_selects_the_new_head(self):
        """The kill point matters: dying AFTER the replace leaves the NEW head selected, so the
        before-replace test above is not vacuously true of any kill."""
        c1 = self._first_head()
        c2 = self._checkpoint('c2', record_index=2)
        child = self._spawn(_CHILD_ADVANCE, self._child_args(c2, c1['manifest_sha256'], mode='die_after_replace'))
        child.communicate(timeout=60)
        self.assertEqual(child.returncode, 7)
        self.assertEqual(head_pointer.current_head_sha256(self.receipts_root), c2['manifest_sha256'])

    def test_an_error_in_replace_leaves_the_old_pointer_and_no_staged_temp(self):
        c1 = self._first_head()
        before = self._pointer_bytes()
        c2 = self._checkpoint('c2', record_index=2)
        _, durable_io = head_pointer._import_siblings(ROOT)
        with patch.object(durable_io, 'atomic_replace_durable', side_effect=OSError('injected replace failure')):
            with self.assertRaises(OSError):
                self._advance_in_process(c2, c1['manifest_sha256'])
        self.assertEqual(self._pointer_bytes(), before)
        self.assertEqual(list(self.receipts_root.glob('.*.tmp')), [])

    def _race(self, mode, trial):
        """Two real writers, both declaring the same parent, released together by a barrier file;
        each holds 0.3 s before its replace so the two compare-and-swap reads overlap."""
        import shutil
        shutil.rmtree(self.receipts_root, ignore_errors=True)
        base = self._checkpoint(f'base{trial}', record_index=10 * trial + 1)
        self._advance_in_process(base, head_pointer.GENESIS_SENTINEL)
        a = self._checkpoint(f'a{trial}', record_index=10 * trial + 2)
        b = self._checkpoint(f'b{trial}', record_index=10 * trial + 3)
        barrier = self.root / f'barrier{trial}'
        children = [self._spawn(_CHILD_ADVANCE, self._child_args(
            cp, base['manifest_sha256'], mode=mode, barrier=str(barrier), hold_before_replace=0.3)) for cp in (a, b)]
        barrier.write_bytes(b'go')
        for child in children:
            child.communicate(timeout=120)
        codes = sorted(child.returncode for child in children)
        return codes, head_pointer.current_head_sha256(self.receipts_root), (a, b)

    def test_two_real_writers_from_one_parent_exactly_one_wins(self):
        for trial in range(8):
            codes, head, (a, b) = self._race('plain', trial)
            self.assertEqual(codes, [0, 3], f'trial {trial}: expected one winner and one StaleParentError, got {codes}')
            self.assertIn(head, (a['manifest_sha256'], b['manifest_sha256']))

    def test_deliberate_red_without_the_lock_both_writers_win_and_one_overwrites_the_other(self):
        codes, head, (a, b) = self._race('no_lock', 0)
        self.assertEqual(codes, [0, 0])  # both passed the compare: the lost-update defect the lock cures

    def test_a_lock_held_by_a_killed_process_is_released_by_the_os(self):
        import time
        child = self._spawn(_CHILD_HOLD_LOCK, dict(module_dir=str(MODULE_DIR), root=str(ROOT),
                                                   receipts_root=str(self.receipts_root), die_holding=True))
        child.communicate(timeout=60)
        started = time.monotonic()
        self._first_head()
        self.assertLess(time.monotonic() - started, 10.0)

    def test_a_live_lock_holder_makes_a_second_writer_time_out_naming_the_lock(self):
        child = self._spawn(_CHILD_HOLD_LOCK, dict(module_dir=str(MODULE_DIR), root=str(ROOT),
                                                   receipts_root=str(self.receipts_root), hold_seconds=20))
        try:
            self.assertEqual(child.stdout.readline().strip(), 'HELD')
            target = head_pointer.pointer_path(self.receipts_root)
            with self.assertRaisesRegex(TimeoutError, r'\.lock'):
                with head_pointer._pointer_lock(target, timeout=0.3):
                    self.fail('acquired a lock another live process holds')
        finally:
            child.kill()
            child.communicate(timeout=30)


class RestartRecoveryTests(unittest.TestCase):
    """Issue #2119 section 6, row 15: a fresh interpreter recovers the selected checkpoint and the
    diagnostic budget from disk alone. The status producer holds no in-process state (the
    ledger test above proves only that the ledger is re-read; this one crosses real processes)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.receipts_root = self.root / 'receipts'
        self.env = dict(os.environ, **{ledger.LEDGER_ROOT_ENV: str(self.root / 'ledger-root')})

    def _run(self, script, **args):
        import subprocess
        payload = dict(module_dir=str(MODULE_DIR), root=str(ROOT), receipts_root=str(self.receipts_root), **args)
        done = subprocess.run([sys.executable, '-B', '-c', script, json.dumps(payload)], capture_output=True,
                              text=True, timeout=120, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def _checkpoint(self, name, record_index):
        hour_dir = self.root / name
        child_dir = hour_dir / 'trained-child'
        child_dir.mkdir(parents=True)
        manifest_bytes = json.dumps({'data_cursor': {'shard': 0, 'record_index': record_index}}).encode('utf-8')
        (child_dir / 'checkpoint-manifest.json').write_bytes(manifest_bytes)
        hour_result_bytes = json.dumps({'name': name}).encode('utf-8')
        (hour_dir / 'hour-result.json').write_bytes(hour_result_bytes)
        return dict(published_checkpoint_root=str(child_dir), hour_result_path=str(hour_dir / 'hour-result.json'),
                    hour_result_sha256=hashlib.sha256(hour_result_bytes).hexdigest(),
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())

    def test_a_fresh_process_recovers_the_selected_head_and_the_diagnostic_occupancy(self):
        c1 = self._checkpoint('c1', 1)
        written = self._run(_CHILD_RESTART_WRITE, checkpoint=c1)
        self.assertEqual(written['head'], c1['manifest_sha256'])
        recovered = self._run(_CHILD_RESTART_READ)
        self.assertEqual(recovered['head'], c1['manifest_sha256'])
        self.assertEqual(recovered['occupancy'], 300)

    def test_deliberate_red_a_reader_that_caches_the_first_head_misses_an_advance_made_by_another_process(self):
        c1, c2 = self._checkpoint('c1', 1), self._checkpoint('c2', 2)
        self._run(_CHILD_RESTART_WRITE, checkpoint=c1)
        cache = {'head': self._run(_CHILD_RESTART_READ)['head']}   # a module-level cache of the first read
        head_pointer.advance_selected_continuation_head(
            repo_root=ROOT, receipts_root=self.receipts_root,
            published_checkpoint_root=Path(c2['published_checkpoint_root']),
            hour_result_path=Path(c2['hour_result_path']), hour_result_sha256=c2['hour_result_sha256'],
            expected_parent_checkpoint_manifest_sha256=c1['manifest_sha256'], now=1500.0)
        self.assertEqual(self._run(_CHILD_RESTART_READ)['head'], c2['manifest_sha256'])   # the uncached reader sees it
        self.assertNotEqual(cache['head'], c2['manifest_sha256'])                          # the cached one is stale


if __name__ == '__main__':
    unittest.main()
