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

    def test_chained_arm_parent_checkpoint_counts_as_a_verified_resume(self):
        """#2119: the arm chains a governed hour to its lineage parent via the arm-only
        parent_checkpoint identity key ({'root', 'manifest_sha256'}), reopened by run_hour in
        cia_hour.py against the parent's published receipt (manifest digest re-verified, every
        object restored) before an hour trains from it. Master's shared predicate never learned
        that key, so every arm continuation read as having no resume. With parent_checkpoint and
        an hour's production_mixture both present, CONTINUE_TRAINING is admitted; the same
        identity with parent_checkpoint removed refuses with the shared predicate's own
        resume_checkpoint message (the deliberate red -- proves the key is load-bearing here,
        not merely tolerated by the closed-set schema check)."""
        parent_checkpoint = {'root': 'A:/ember-wt/fixture/trained-child',
                              'manifest_sha256': hashlib.sha256(b'fixture-parent-manifest').hexdigest()}
        identity = _bare_identity(training_job_purpose='CONTINUE_TRAINING',
                                   parent_checkpoint=parent_checkpoint,
                                   production_mixture={'shards': ['fixture-shard-0']})
        self.assertEqual(runner.validate_training_job_purpose(identity, hour=True), 'CONTINUE_TRAINING')
        del identity['parent_checkpoint']
        with self.assertRaisesRegex(ValueError, r'CONTINUE_TRAINING requires a verified parent state '
                                                  r'\(resume_checkpoint\)'):
            runner.validate_training_job_purpose(identity, hour=True)

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
            'retained_applied_positions': 0,
        })

    def test_published_checkpoint_reports_parent_and_retained_applied_positions(self):
        hour_result = {'child_manifest_sha256': 'c' * 64, 'parent_manifest_sha256': 'p' * 64,
                        'applied_positions': 12288}
        self.assertEqual(status.selected_checkpoint_status(hour_result), {
            'child_manifest_sha256': 'c' * 64, 'parent_manifest_sha256': 'p' * 64,
            'retained_applied_positions': 12288,
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
        record = status.training_continuity_status(
            custody_parent=self.root, hour_result=hour_result,
            current_identity={'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'd2'},
            measurement=None, next_blocker='readiness blocker: image evaluator unbound')
        self.assertEqual(record['schema'], status.STATUS_SCHEMA)
        self.assertEqual(record['lineage_checkpoint_manifest_sha256'], hour_result['child_manifest_sha256'])
        self.assertEqual(record['checkpoint']['retained_applied_positions'], 4096)
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


if __name__ == '__main__':
    unittest.main()
