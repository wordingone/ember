"""Issue #2119 (review 63986 R2, ruling 63996; repaired after review 64088/64090): the INTEGRATED chain through the real entry point, in the REAL ORDER.

    1. freeze the PRELAUNCH entry, put its digest in the identity            (no receipt exists yet; asserted)
    2. (the run) score both arms, then the scoring chain writes arm-publication.json (digests derived from the files)
    3. finalize_scored_pair: entry + publication -> producer -> finalizer (REAL ledger file + lock) -> verdict -> promote_with_pending_v1.promote
       (REAL selected_continuation_head + pending_continuation)

Nothing in the chain is mocked except the one lineage derivation (pinned to the frozen start, as in RealLedgerFinalizerTests) and, in the resume
cases, a single raise injected into the finalizer or the promotion. The refusal cases assert the whole write set: no arm-results.json, no ledger
row, no outcome marker, and the selected-head pointer byte-identical.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
NIKO_DIR = Path(os.environ.get('EMBER_NIKO_MODULE_DIR', 'A:/niko-staging/issue2119-dispatch-policy-20261006T2027Z/src/ember/infrastructure/tools/ember-restart-3b'))
CALLER_DIR = Path(os.environ.get('EMBER_PROMOTE_CALLER_DIR', 'A:/eli-staging/h33-repair-tests'))
REPO = NIKO_DIR.parents[3]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
for directory in (NIKO_DIR, CALLER_DIR):      # appended: this tree's modules always win a name clash
    if str(directory) not in sys.path:
        sys.path.append(str(directory))

import arm_results_producer as producer  # noqa: E402
import retention_eligibility as elig  # noqa: E402
import scored_pair_entry as entry_mod  # noqa: E402
import scored_pair_cli as scorer_cli  # noqa: E402
import pending_continuation as pending  # noqa: E402
import selected_continuation_head as sch  # noqa: E402
import promote_with_pending_v1 as caller  # noqa: E402

PLAN, LEDGER, MIXTURE, DECL, SCORER, TOKENIZER = ('1' * 64, '2' * 64, '3' * 64, '4' * 64, '5' * 64, '6' * 64)
METRIC_PATH = 'arms.fresh.mean_nll'
ROLES = ('control', 'treatment')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ScoredPairChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('scored_pair_cia_step_runner', MODULE_DIR / 'cia_step_runner.py')
        cls.runner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.runner
        sys.path.insert(0, str(ROOT / 'src'))
        spec.loader.exec_module(cls.runner)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.rr = self.root / 'receipts'
        self.rows = []
        self.start = self._checkpoint('start', 0)
        self.ctl = self._checkpoint('ctl', 1)
        self.trt = self._checkpoint('trt', 2)
        sch.advance_selected_continuation_head(repo_root=REPO, receipts_root=self.rr, published_checkpoint_root=Path(self.start['root']),
                                               hour_result_path=Path(self.start['hr']), hour_result_sha256=self.start['hr_sha'],
                                               expected_parent_checkpoint_manifest_sha256=sch.GENESIS_SENTINEL, now=1000.0)
        self.ledger = self.runner.load_ledger_module()
        self.ledger.lineage_checkpoint_manifest_sha256 = lambda identity, **kwargs: self.start['manifest']
        for patcher in (unittest.mock.patch.object(self.runner, 'load_ledger_module', lambda: self.ledger),
                        unittest.mock.patch.dict(os.environ, {self.ledger.LEDGER_ROOT_ENV: str(self.root / 'ledger-root')})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.custody = self.rr / 'measurement-r1'
        self.custody.mkdir(parents=True)
        rule = {'schema': elig.RULE_SCHEMA, 'frozen_start_manifest_sha256': self.start['manifest'], 'control_arm_id': 'control',
                'treatment_arm_id': 'treatment',
                'selection': {'metric': 'heldout_loss', 'direction': 'lower', 'min_delta': 0.01, 'evaluation_set_class': 'developmental'}}
        self.identity = {'training_experiment_continuation_rule': json.dumps(rule), 'run_id': 'r1',
                         'parent_checkpoint': {'root': 'r', 'manifest_sha256': self.start['manifest']}}
        (self.custody / 'run-complete.json').write_text(json.dumps({
            'status': 'run_complete_not_yet_scored', 'succeeded': True, 'run_id': 'r1', 'custody_name': 'measurement-r1',
            'dispatch_started': 100.0, 'run_complete_at': 200.0}), encoding='utf-8')
        self.ledger_file = self.ledger.ledger_path(self.custody.parent)
        self.pointer_before = self.ptr_sha()
        self.scored_dir = self.root / 'scored'      # the run's outputs: they do not exist when the entry is frozen
        self.entry_path = self.root / 'scored-pair-entry.json'

    # ---- fixtures ----
    def _checkpoint(self, name, index):
        hour = self.root / name
        child = hour / 'trained-child'
        child.mkdir(parents=True)
        manifest = json.dumps({'data_cursor': {'shard': 0, 'record_index': index}}).encode()
        (child / 'checkpoint-manifest.json').write_bytes(manifest)
        hr = json.dumps({'name': name}).encode()
        (hour / 'hour-result.json').write_bytes(hr)
        return {'root': str(child), 'hr': str(hour / 'hour-result.json'), 'hr_sha': sha(hr), 'manifest': sha(manifest)}

    def freeze_entry(self, *, mutate=None, identity_digest=True):
        """STEP 1: the prelaunch entry and its digest in the identity. No scored receipt exists yet."""
        entry = {'schema': entry_mod.ENTRY_SCHEMA, 'run_id': 'r1',
                 'bindings': {'episode_plan_sha256': PLAN, 'shard_ledger_sha256': LEDGER, 'mixture_identity_sha256': MIXTURE,
                              'frozen_declaration_sha256': DECL, 'scorer_sha256': SCORER, 'tokenizer_sha256': TOKENIZER},
                 'metric': {'name': 'heldout_loss', 'path': METRIC_PATH}, 'parent_manifest_sha256': self.start['manifest'],
                 'promote': {'repo_root': str(REPO), 'receipts_root': str(self.rr), 'ledger': str(self.root / 'ledger.jsonl'),
                             'next': {'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'next-r9'}}}
        if mutate is not None:
            mutate(entry)
        self.entry_path.write_bytes(json.dumps(entry, sort_keys=True).encode())
        if identity_digest:
            self.identity['scored_pair_binding_sha256'] = sha(self.entry_path.read_bytes())
        return self.entry_path

    def scored(self, role, loss, **binding_overrides):
        self.scored_dir.mkdir(exist_ok=True)
        ck = self.ctl if role == 'control' else self.trt
        ckpt_receipt = self.scored_dir / f'{role}-checkpoint-receipt.json'
        ckpt_receipt.write_bytes(f'checkpoint receipt for {role}'.encode())
        bindings = {'checkpoint_manifest_sha256': ck['manifest'], 'checkpoint_receipt_sha256': sha(ckpt_receipt.read_bytes()),
                    'episode_plan_sha256': PLAN, 'shard_ledger_sha256': LEDGER, 'mixture_identity_sha256': MIXTURE,
                    'frozen_declaration_sha256': DECL, 'scorer_sha256': SCORER, 'tokenizer_sha256': TOKENIZER}
        bindings.update(binding_overrides)
        path = self.scored_dir / f'{role}-scored.json'
        path.write_text(json.dumps({'schema': 'ember-2119-child-episode-nll-v1', 'bindings': bindings, 'arms': {'fresh': {'mean_nll': loss}}}), encoding='utf-8')
        return path, ckpt_receipt

    def publish(self, *, control_loss=2.0, treatment_loss=1.5, unpublished=(), scored_overrides=None, tweak=None):
        """STEP 2: the run scored both arms; the scoring chain publishes them (digests derived by hashing the files)."""
        scored_overrides = scored_overrides or {}
        arms = {}
        for role, loss in (('control', control_loss), ('treatment', treatment_loss)):
            if role in unpublished:
                arms[role] = None
                continue
            ck = self.ctl if role == 'control' else self.trt
            receipt, ckpt_receipt = self.scored(role, loss, **scored_overrides.get(role, {}))
            arms[role] = {'published_checkpoint_root': ck['root'], 'hour_result_path': ck['hr'], 'applied_positions': 1000,
                          'receipt': str(receipt), 'checkpoint_receipt': str(ckpt_receipt)}
        if tweak is not None:
            tweak(arms)
        return entry_mod.write_arm_publication(self.custody, arms=arms)

    def real_order(self, **publish_kwargs):
        """Freeze, then (the run), then publish; returns the frozen entry path."""
        path = self.freeze_entry()
        self.publish(**publish_kwargs)
        return path

    def promote_fn(self, spec, *, ruling):
        return caller.promote(spec, pending=pending, sch=sch, row=lambda **fields: self.rows.append(fields), ruling=ruling)

    def run_chain(self, entry_path=None, ruling='63996'):
        return entry_mod.finalize_scored_pair(self.identity, entry_path=entry_path or self.entry_path, custody=self.custody, parent=self.rr,
                                              runner=self.runner, promote_fn=self.promote_fn, ruling=ruling)

    def ptr_sha(self):
        return sha(sch.pointer_path(self.rr).read_bytes())

    def outcome_rows(self):
        return [r for r in self.ledger.read_rows(self.ledger_file) if r.get('row_kind') == 'retention_experiment_outcome']

    def assert_nothing_written(self):
        self.assertFalse((self.custody / elig.ARM_RESULTS_FILENAME).exists())
        self.assertFalse((self.custody / self.runner.OUTCOME_RECORDED_FILENAME).exists())
        self.assertEqual(self.outcome_rows() if self.ledger_file.exists() else [], [])
        self.assertEqual(self.ptr_sha(), self.pointer_before)
        self.assertEqual(sch.current_head_sha256(self.rr), self.start['manifest'])

    # ---- the real order (review 64088) ----
    def test_the_identity_digest_is_frozen_before_any_scored_receipt_exists(self):
        path = self.freeze_entry()
        self.assertFalse(self.scored_dir.exists())                 # no receipt, no checkpoint receipt, nothing the run produces
        self.assertFalse((self.custody / entry_mod.PUBLICATION_FILENAME).exists())
        self.assertEqual(self.identity['scored_pair_binding_sha256'], sha(path.read_bytes()))
        self.runner.validate_scored_pair_binding(dict(self.identity, training_job_purpose='RETENTION_ELIGIBLE_EXPERIMENT'))
        self.publish()                                             # the run happens AFTER the declaration; the identity is not touched again
        digest = self.identity['scored_pair_binding_sha256']
        self.assertEqual(self.run_chain()['verdict']['eligible_arm'], 'treatment')
        self.assertEqual(self.identity['scored_pair_binding_sha256'], digest)

    def test_a_prelaunch_entry_carrying_per_arm_post_run_fields_is_refused(self):
        path = self.freeze_entry(mutate=lambda entry: entry.update(arms={'control': {'receipt_sha256': 'a' * 64}}))
        self.publish()
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'closed prelaunch scored-pair schema'):
            self.run_chain(path)
        self.assert_nothing_written()

    def test_finalize_refuses_when_the_scoring_chain_has_not_published_the_arms(self):
        path = self.freeze_entry()
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'no arm-publication.json'):
            self.run_chain(path)
        self.assert_nothing_written()

    # ---- the chain, accepted ----
    def test_a_treatment_win_runs_the_whole_chain_and_moves_the_head_to_the_treatment_child(self):
        self.real_order(control_loss=2.0, treatment_loss=1.5)
        out = self.run_chain()
        self.assertTrue(out['eligible'])
        self.assertEqual((out['verdict']['verdict'], out['verdict']['eligible_arm']), (elig.TREATMENT_ELIGIBLE, 'treatment'))
        self.assertEqual((out['promotion']['code'], out['promotion']['head']), (0, self.trt['manifest']))
        self.assertEqual(sch.current_head_sha256(self.rr), self.trt['manifest'])
        self.assertEqual(out['promotion']['next_segment_read'], {'next_identity': {'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'next-r9'}})
        arms = json.loads((self.custody / elig.ARM_RESULTS_FILENAME).read_text(encoding='utf-8'))
        self.assertEqual([arms[r]['measurement_set_class'] for r in ROLES], ['developmental', 'developmental'])
        self.assertEqual(arms['treatment']['source_receipt_sha256'], sha((self.scored_dir / 'treatment-scored.json').read_bytes()))
        self.assertEqual(self.outcome_rows(), [])      # an eligible descendant charges no occupancy (the pointer advance is its record)
        self.assertTrue((self.custody / self.runner.OUTCOME_RECORDED_FILENAME).is_file())

    def test_a_control_win_promotes_the_control_child_not_the_treatment(self):
        self.real_order(control_loss=1.5, treatment_loss=2.0)
        out = self.run_chain()
        self.assertEqual(out['verdict']['eligible_arm'], 'control')
        self.assertEqual(out['promotion']['head'], self.ctl['manifest'])
        self.assertEqual(sch.current_head_sha256(self.rr), self.ctl['manifest'])

    def test_a_treatment_that_did_not_publish_leaves_the_control_eligible(self):
        self.real_order(unpublished=('treatment',))
        out = self.run_chain()
        self.assertEqual((out['verdict']['eligible_arm'], out['promotion']['head']), ('control', self.ctl['manifest']))

    def test_no_eligible_arm_means_no_promotion_and_charges_the_run_duration(self):
        self.real_order(unpublished=ROLES)
        out = self.run_chain()
        self.assertFalse(out['eligible'])
        self.assertEqual(out['promotion'], 'NOT_ATTEMPTED_NO_ELIGIBLE_ARM')
        self.assertEqual(self.ptr_sha(), self.pointer_before)
        self.assertEqual([r['occupancy_seconds'] for r in self.outcome_rows()], [100])    # R1 through the whole chain: run duration, not finalize time
        self.assertEqual(self.ledger.diagnostic_occupancy_seconds(self.ledger.read_rows(self.ledger_file), self.start['manifest']), 100)

    # ---- a ruling that arrives later (review 64090) ----
    def test_a_delayed_ruling_reuses_the_completed_outcome_and_promotes_without_deleting_the_marker(self):
        self.real_order()
        first = self.run_chain(ruling=None)
        self.assertEqual((first['eligible'], first['promotion'], first['resumed_completed_outcome']), (True, 'NOT_ATTEMPTED_NO_RULING', False))
        marker = self.custody / self.runner.OUTCOME_RECORDED_FILENAME
        marker_bytes = marker.read_bytes()
        self.assertEqual(self.ptr_sha(), self.pointer_before)
        second = self.run_chain(ruling='64100')                    # the ruling is granted later; the finalizer's one-writer marker is untouched
        self.assertTrue(second['resumed_completed_outcome'])
        self.assertEqual((second['promotion']['code'], second['promotion']['head']), (0, self.trt['manifest']))
        self.assertEqual(marker.read_bytes(), marker_bytes)
        self.assertEqual(self.outcome_rows(), [])

    def test_a_crash_after_finalization_and_before_promotion_resumes_the_same_way(self):
        self.real_order()
        with unittest.mock.patch.object(self, 'promote_fn', side_effect=OSError('simulated crash before the head move')):
            with self.assertRaises(OSError):
                self.run_chain()
        self.assertTrue((self.custody / self.runner.OUTCOME_RECORDED_FILENAME).is_file())
        self.assertEqual(self.ptr_sha(), self.pointer_before)
        out = self.run_chain()
        self.assertEqual((out['resumed_completed_outcome'], out['promotion']['head']), (True, self.trt['manifest']))

    def test_a_second_promotion_after_success_is_refused_by_the_promoter_and_moves_nothing(self):
        self.real_order()
        self.run_chain()
        after = self.ptr_sha()
        again = self.run_chain()
        self.assertTrue(again['resumed_completed_outcome'])
        self.assertNotEqual(again['promotion']['code'], 0)        # expected_parent is no longer the head: the promoter refuses, nothing moves
        self.assertEqual(self.ptr_sha(), after)

    def test_a_recorded_outcome_that_is_not_this_runs_is_not_reused(self):
        self.real_order()
        self.run_chain(ruling=None)
        marker = self.custody / self.runner.OUTCOME_RECORDED_FILENAME
        marker.write_text(json.dumps({'eligible_descendant_published': True, 'run_id': 'some-other-run'}), encoding='utf-8')
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'not this run'):
            self.run_chain()
        marker.write_text(json.dumps({'eligible_descendant_published': False, 'run_id': 'r1'}), encoding='utf-8')   # disagrees with the verdict on disk
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'disagrees with the eligibility verdict'):
            self.run_chain()
        self.assertEqual(self.ptr_sha(), self.pointer_before)

    # ---- the real entry point refuses a pair that is the same class but a different population ----
    def test_a_same_class_pair_scored_on_a_different_population_is_refused_and_nothing_is_written(self):
        for key, other in (('episode_plan_sha256', 'a' * 64), ('shard_ledger_sha256', 'b' * 64), ('mixture_identity_sha256', 'c' * 64)):
            for drifted in (('treatment',), ROLES):     # one drifted arm, and a pair consistent with itself but not with the frozen entry
                with self.subTest(binding=key, drifted=drifted):
                    self.setUp()
                    path = self.freeze_entry()
                    self.publish(scored_overrides={role: {key: other} for role in drifted})
                    with self.assertRaisesRegex(producer.ArmProducerRefusal, key):
                        self.run_chain(path)
                    self.assert_nothing_written()

    def test_a_scored_receipt_edited_after_publication_is_refused(self):
        path = self.real_order()
        receipt = self.scored_dir / 'treatment-scored.json'
        data = json.loads(receipt.read_text(encoding='utf-8'))
        data['arms']['fresh']['mean_nll'] = 0.5          # a better number after the scoring chain published the digest
        receipt.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'edited since publication'):
            self.run_chain(path)
        self.assert_nothing_written()

    def test_a_hand_edited_publication_digest_is_refused(self):
        path = self.real_order()
        publication = self.custody / entry_mod.PUBLICATION_FILENAME
        record = json.loads(publication.read_text(encoding='utf-8'))
        record['treatment']['receipt_sha256'] = 'f' * 64
        publication.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'edited since publication'):
            self.run_chain(path)
        self.assert_nothing_written()

    def test_a_receipt_scored_on_a_different_child_than_the_published_root_is_refused(self):
        def swap_root(arms):
            arms['treatment']['published_checkpoint_root'] = self.ctl['root']      # the published root is not the scored child
        path = self.freeze_entry()
        self.publish(tweak=swap_root)
        with self.assertRaises(producer.ArmProducerRefusal):
            self.run_chain(path)
        self.assert_nothing_written()

    def test_a_receipt_whose_checkpoint_receipt_binding_differs_from_the_derived_digest_is_refused(self):
        path = self.freeze_entry()
        self.publish(scored_overrides={'treatment': {'checkpoint_receipt_sha256': 'e' * 64}})
        with self.assertRaisesRegex(producer.ArmProducerRefusal, 'checkpoint_receipt_sha256'):
            self.run_chain(path)
        self.assert_nothing_written()

    def test_the_publication_is_created_exclusively_and_closed(self):
        self.real_order()
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'already exists'):
            self.publish()
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'exactly a control and a treatment'):
            entry_mod.write_arm_publication(self.root, arms={'control': None})
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'needs exactly'):
            entry_mod.write_arm_publication(self.root, arms={'control': None, 'treatment': {'receipt': 'x'}})

    # ---- the frozen entry itself ----
    def test_the_identity_must_carry_the_digest_and_the_entry_bytes_must_match_it(self):
        path = self.freeze_entry(identity_digest=False)
        self.publish()
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'carries no frozen'):
            self.run_chain(path)
        self.identity['scored_pair_binding_sha256'] = '0' * 64
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'differ from the digest frozen'):
            self.run_chain(path)
        self.assert_nothing_written()

    def test_every_mandatory_binding_must_be_in_the_entry_and_is_never_defaulted(self):
        for key in entry_mod.COMMON_BINDING_KEYS:
            with self.subTest(missing=key):
                path = self.freeze_entry(mutate=lambda entry, key=key: entry['bindings'].pop(key))
                with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'bindings must be exactly'):
                    self.run_chain(path)
        self.assert_nothing_written()

    def test_the_entry_run_id_and_parent_must_match_the_identity(self):
        self.publish()
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'run_id'):
            self.run_chain(self.freeze_entry(mutate=lambda entry: entry.update(run_id='r2')))
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'parent'):
            self.run_chain(self.freeze_entry(mutate=lambda entry: entry.update(parent_manifest_sha256='9' * 64)))
        self.assert_nothing_written()

    def test_the_caller_has_no_way_to_supply_a_binding(self):
        names = set(inspect.signature(entry_mod.finalize_scored_pair).parameters)
        self.assertEqual(names, {'identity', 'entry_path', 'custody', 'parent', 'runner', 'promote_fn', 'ruling'})

    # ---- the launch identity freezes the entry digest (ruling 64046: emission ships in this successor) ----
    def test_a_retention_identity_must_freeze_the_scored_pair_digest_and_no_other_purpose_may_carry_it(self):
        ok = {'training_job_purpose': 'RETENTION_ELIGIBLE_EXPERIMENT', 'scored_pair_binding_sha256': 'a' * 64}
        self.runner.validate_scored_pair_binding(ok)
        for bad in (None, 'abc', 'A' * 64, 7):
            with self.subTest(frozen=bad):
                identity = {'training_job_purpose': 'RETENTION_ELIGIBLE_EXPERIMENT'}
                if bad is not None:
                    identity['scored_pair_binding_sha256'] = bad
                with self.assertRaisesRegex(ValueError, 'freezes the scored-pair entry digest'):
                    self.runner.validate_scored_pair_binding(identity)
        self.runner.validate_scored_pair_binding({'training_job_purpose': 'DIAGNOSTIC'})
        with self.assertRaisesRegex(ValueError, 'belongs to a RETENTION_ELIGIBLE_EXPERIMENT identity only'):
            self.runner.validate_scored_pair_binding({'training_job_purpose': 'DIAGNOSTIC', 'scored_pair_binding_sha256': 'a' * 64})

    def test_the_runner_calls_the_check_in_prepare_execution_and_allows_the_identity_key(self):
        source = inspect.getsource(self.runner.prepare_execution)
        self.assertIn('validate_scored_pair_binding(identity)', source)
        self.assertIn("'scored_pair_binding_sha256'", source)
        self.assertEqual(entry_mod.IDENTITY_DIGEST_FIELD, 'scored_pair_binding_sha256')

    # ---- the actual scorer caller (review 64093) ----
    def cli(self, *extra, entry=None):
        identity_file = self.root / 'identity.json'
        identity_file.write_text(json.dumps({'identity': self.identity}), encoding='utf-8')
        argv = ['--identity', str(identity_file), '--entry', str(entry or self.entry_path), '--custody', str(self.custody),
                '--parent', str(self.rr), *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = scorer_cli.main(argv, runner=self.runner, promote_caller=caller, pending=pending, sch=sch)
        return rc, json.loads(buffer.getvalue().strip().splitlines()[-1])

    def arms_file(self, *, unpublished=()):
        arms = {}
        for role, loss in (('control', 2.0), ('treatment', 1.5)):
            if role in unpublished:
                arms[role] = None
                continue
            ck = self.ctl if role == 'control' else self.trt
            receipt, ckpt_receipt = self.scored(role, loss)
            arms[role] = {'published_checkpoint_root': ck['root'], 'hour_result_path': ck['hr'], 'applied_positions': 1000,
                          'receipt': str(receipt), 'checkpoint_receipt': str(ckpt_receipt)}
        path = self.root / 'arms.json'
        path.write_text(json.dumps(arms), encoding='utf-8')
        return path

    def test_the_scorer_caller_publishes_then_finalizes_then_promotes_in_one_command(self):
        self.freeze_entry()
        arms = self.arms_file()
        rc, out = self.cli('--arms', str(arms), '--ruling', '64100')
        self.assertEqual(rc, 0)
        self.assertEqual((out['verdict']['eligible_arm'], out['promotion']['head']), ('treatment', self.trt['manifest']))
        self.assertTrue((self.custody / entry_mod.PUBLICATION_FILENAME).is_file())
        self.assertEqual(sch.current_head_sha256(self.rr), self.trt['manifest'])
        self.assertTrue((self.custody / 'promotion-rows.jsonl').is_file())

    def test_the_scorer_caller_with_no_ruling_finalizes_and_a_later_call_with_the_ruling_promotes(self):
        self.freeze_entry()
        arms = self.arms_file()
        rc, out = self.cli('--arms', str(arms))
        self.assertEqual((rc, out['promotion']), (0, 'NOT_ATTEMPTED_NO_RULING'))
        rc, out = self.cli('--ruling', '64100')          # no --arms: the publication already exists
        self.assertEqual((rc, out['resumed_completed_outcome'], out['promotion']['head']), (0, True, self.trt['manifest']))

    def test_the_scorer_caller_refuses_a_foreign_entry_before_any_write_and_exits_3(self):
        self.freeze_entry()
        arms = self.arms_file()
        foreign = self.root / 'foreign-entry.json'
        foreign.write_bytes(self.entry_path.read_bytes() + b' ')      # not the bytes the identity froze
        rc, out = self.cli('--arms', str(arms), '--ruling', '64100', entry=foreign)
        self.assertEqual((rc, out['status']), (3, 'REFUSED'))
        self.assertFalse((self.custody / entry_mod.PUBLICATION_FILENAME).exists())
        self.assertFalse((self.custody / elig.ARM_RESULTS_FILENAME).exists())
        self.assertEqual(self.ptr_sha(), self.pointer_before)

    def test_the_scorer_caller_has_no_flag_that_supplies_a_binding(self):
        source = inspect.getsource(scorer_cli.main)
        flags = {part for part in source.split("'") if part.startswith('--')}
        self.assertEqual(flags, {'--identity', '--entry', '--custody', '--parent', '--arms', '--ruling', '--rows-out', '--promote-caller',
                                 '--niko-module-dir'})

    # ---- idempotence across an interrupted chain ----
    def test_an_interrupted_finalize_resumes_without_a_second_arm_record_or_a_second_ledger_row(self):
        self.real_order()
        with unittest.mock.patch.object(self.runner, 'finalize_retention_outcome', side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError):
                self.run_chain()
        written = (self.custody / elig.ARM_RESULTS_FILENAME).read_bytes()
        self.assertEqual(self.ptr_sha(), self.pointer_before)
        out = self.run_chain()                      # resumes: arm-results.json equals the rebuilt pair, so it is kept
        self.assertEqual((self.custody / elig.ARM_RESULTS_FILENAME).read_bytes(), written)
        self.assertEqual(self.outcome_rows(), [])
        self.assertTrue((self.custody / self.runner.OUTCOME_RECORDED_FILENAME).is_file())
        self.assertEqual(out['promotion']['head'], self.trt['manifest'])

    def test_an_existing_arm_record_that_differs_from_the_frozen_entry_and_publication_is_refused(self):
        self.real_order()
        self.run_chain(ruling=None)
        (self.custody / self.runner.OUTCOME_RECORDED_FILENAME).unlink()
        arms = json.loads((self.custody / elig.ARM_RESULTS_FILENAME).read_text(encoding='utf-8'))
        arms['treatment']['metric']['heldout_loss'] = 0.1
        (self.custody / elig.ARM_RESULTS_FILENAME).write_text(json.dumps(arms), encoding='utf-8')
        with self.assertRaisesRegex(entry_mod.ScoredPairRefusal, 'differs from the pair rebuilt'):
            self.run_chain()
        self.assertEqual(self.ptr_sha(), self.pointer_before)


if __name__ == '__main__':
    unittest.main()
