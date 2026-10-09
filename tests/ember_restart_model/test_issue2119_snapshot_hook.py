"""Issue #2119 row 8 (hook half): the continuity snapshot is written at the publication boundary, and a failure there is loud.

`continuity_snapshot` had a producer and nothing that called it. These tests pin the call: the hook walks the real ancestry from the
published head and writes a snapshot whose head equals that head; a head or genesis that does not match writes nothing and leaves the
older snapshot in place (the deliberate red: the page then reads stale through `check_live`, it never describes the wrong head); and
`promote_with_pending_v1` writes the snapshot only after a clean move, refuses a malformed snapshot spec before the move, and returns
code 8 (head moved, snapshot not written) instead of hiding the failure.
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
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import claim_accounting as ca  # noqa: E402
import continuity_snapshot as snap  # noqa: E402
import continuity_snapshot_hook as hook  # noqa: E402
import post_hour_promotion_gate as cadence  # noqa: E402
import promote_with_pending_v1 as promote_module  # noqa: E402
import scored_pair_entry as entry_mod  # noqa: E402
import training_continuity_ledger as ledger  # noqa: E402
import training_lineage_ancestry as ancestry  # noqa: E402


def write_manifest(root: Path, name: str, *, tokens: int, step: int, parent: Path | None = None, parent_sha: str | None = None,
                   token_delta: int | None = None, step_delta: int | None = None) -> tuple[Path, str]:
    directory = root / name
    directory.mkdir()
    lineage = {} if parent is None else {'parent_checkpoint': str(parent).replace('/', '\\'), 'parent_manifest_sha256': parent_sha,
                                         'token_delta': token_delta, 'step_delta': step_delta}
    raw = json.dumps({'schema_version': 'ember-cia-checkpoint-v1', 'lineage': lineage,
                      'data_cursor': {'tokens_seen': tokens, 'global_step': step}}, sort_keys=True).encode()
    (directory / ancestry.MANIFEST_NAME).write_bytes(raw)
    return directory, hashlib.sha256(raw).hexdigest()



def bad_score_rows():
    """Scorer-v12 arms.fresh shapes that carry no usable scored rows. Each is refused by name (review finding 1; the first is the reviewer's pinned counterexample)."""
    row = {'loss_sum': 4608.0, 'targets': 1024}
    good = {'episodes': 2, 'total_nll': 9216.0, 'targets': 2048, 'mean_nll': 4.5, 'per_episode': [dict(row), dict(row)]}
    def with_rows(first, **over):
        return dict(good, per_episode=[first, dict(row)], **over)
    return {
        'rows with no scored values': {'episodes': 2, 'mean_nll': 4.5, 'per_episode': [{}, {}]},
        'rows with no scored values and consistent totals': dict(good, per_episode=[{}, {}]),
        'nan loss_sum': with_rows(dict(row, loss_sum=float('nan'))),
        'infinite loss_sum': with_rows(dict(row, loss_sum=float('inf'))),
        'negative loss_sum': with_rows(dict(row, loss_sum=-1.0)),
        'string loss_sum': with_rows(dict(row, loss_sum='4608.0')),
        'target count 0': with_rows(dict(row, targets=0), targets=1024),
        'fractional target count': with_rows(dict(row, targets=1024.5)),
        'boolean target count': with_rows(dict(row, targets=True)),
        'row is not an object': dict(good, per_episode=[4.5, 4.5]),
        'mean disagrees with the rows': dict(good, mean_nll=9.0),
        'total_nll disagrees with the rows': dict(good, total_nll=100.0),
        'arm targets disagree with the rows': dict(good, targets=2049),
        'no total_nll': {key: value for key, value in good.items() if key != 'total_nll'},
        'no arm targets': {key: value for key, value in good.items() if key != 'targets'},
    }


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.g, self.g_sha = write_manifest(self.root, 'g', tokens=0, step=0)
        self.b, self.b_sha = write_manifest(self.root, 'b', tokens=100, step=10, parent=self.g, parent_sha=self.g_sha, token_delta=100, step_delta=10)
        self.c, self.c_sha = write_manifest(self.root, 'c', tokens=150, step=15, parent=self.b, parent_sha=self.b_sha, token_delta=50, step_delta=5)
        self.hour_result = self.root / 'hour-result.json'
        self.hour_result.write_text(json.dumps({'child_manifest_sha256': self.c_sha, 'parent_manifest_sha256': self.b_sha, 'applied_positions': 50}))
        self.custody = self.root / 'custody'
        self.custody.mkdir()
        self.out = self.root / 'manifests' / 'status.json'
        self.env = patch.dict(os.environ, {ledger.LEDGER_ROOT_ENV: str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def score_fields(self, *, child=None, plan=None, scores=True, name='score-receipt.json', fresh_override=None):
        """A scorer-v12 receipt for `child` (default the fixture child) on the cadence plan, written and cited by digest, the way the head mover re-checks it."""
        fresh = {'episodes': 2, 'total_nll': 7168.0, 'targets': 2048, 'mean_nll': 3.5, 'per_episode': [{'loss_sum': 3481.6, 'targets': 1024}, {'loss_sum': 3686.4, 'targets': 1024}]}
        body = {'schema': cadence.CADENCE_SCORE_SCHEMA, 'label': 'child-episode-nll scorer v12 fixture',
                'bindings': {'episode_plan_sha256': plan or cadence.CADENCE_PLAN_SHA256, 'checkpoint_manifest_sha256': child or self.c_sha},
                'arms': {'fresh': fresh_override if fresh_override is not None else fresh if scores else {'mean_nll': 3.5}}}
        path = self.root / name
        raw = json.dumps(body, sort_keys=True).encode()
        path.write_bytes(raw)
        return {'score_receipt': str(path), 'score_receipt_sha256': hashlib.sha256(raw).hexdigest()}

    def publish(self, **overrides):
        args = dict(head_directory=self.c, hour_result_path=self.hour_result, expected_genesis_manifest_sha256=self.g_sha,
                    custody_parent=self.custody, snapshot_path=self.out, next_blocker='no admitted mixture bound yet')
        args.update(overrides)
        return hook.publish_snapshot(**args)


class CandidateAuditHookTests(Fixture):
    """The hook derives the refused child and the duplicate-credit check from files; the caller's blocker text cannot feed them."""

    def setUp(self):
        super().setUp()
        self.receipts = self.root / 'receipts'
        self.receipts.mkdir()
        self.cand = 'd' * 64
        self.cand_hour = self.root / 'candidate-hour-result.json'
        self.cand_hour_bytes = json.dumps({'child_manifest_sha256': self.cand, 'parent_manifest_sha256': self.c_sha, 'applied_positions': 77}, sort_keys=True).encode()
        self.cand_hour.write_bytes(self.cand_hour_bytes)
        self.write_candidate(self.cand, self.c_sha)
        self.receipt = self.root / 'episode-nll.json'
        receipt_bytes = json.dumps({'bindings': {'checkpoint_manifest_sha256': self.cand}}, sort_keys=True).encode()
        self.receipt.write_bytes(receipt_bytes)
        self.receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
        self.log = self.root / 'loop.jsonl'
        self.write_log(self.receipt_sha[:8])

    def write_candidate(self, cand, parent):
        (self.receipts / 'candidate-continuation-head.json').write_text(json.dumps({
            'candidate_checkpoint_manifest_sha256': cand, 'hour_result_path': str(self.cand_hour), 'hour_result_sha256': hashlib.sha256(self.cand_hour_bytes).hexdigest(),
            'parent_checkpoint_manifest_sha256': parent, 'published_at': 1.0, 'schema': 'ember-candidate-continuation-head-v1'}), encoding='utf-8')

    def write_log(self, cited):
        self.log.write_text(json.dumps({'id': 'ep-1', 'stage': 'RULED', 'verdict': 'REFUTED',
                                        'because': f'limit exceeded; receipt episode-nll.json sha256 {cited}; pointer unchanged'}) + '\n', encoding='utf-8')

    def test_refused_candidate_is_derived_from_files_and_the_blocker_text_does_not_feed_it(self):
        private = self.root / 'private.json'
        outcome = self.publish(receipts_root=self.receipts, ruling_log=self.log, ruling_id='ep-1', refusal_receipt=self.receipt, private_path=private,
                               next_blocker='the child 0000 was refused')
        self.assertEqual(outcome['status'], 'WRITTEN')
        audit = json.loads(self.out.read_text(encoding='utf-8'))['candidate_audit']
        self.assertEqual((audit['status'], audit['candidate']['manifest_sha256']), ('REFUSED_NOT_RETAINED', self.cand))
        self.assertEqual(audit['retained']['positions_credited_to_lineage'], 0)
        self.assertEqual(audit['refusal_ruling']['receipt_sha256'], self.receipt_sha)
        self.assertNotIn(self.root.name, self.out.read_text(encoding='utf-8'))            # the committed view carries no path
        self.assertIn(self.root.name, json.dumps(json.loads(private.read_text(encoding='utf-8'))['candidate_audit']))   # the private view does

    def test_a_candidate_equal_to_the_head_reads_retained_in_chain_deliberate_control(self):
        self.write_candidate(self.c_sha, self.b_sha)
        self.cand_hour_bytes = json.dumps({'child_manifest_sha256': self.c_sha, 'parent_manifest_sha256': self.b_sha, 'applied_positions': 50}, sort_keys=True).encode()
        self.cand_hour.write_bytes(self.cand_hour_bytes)
        self.write_candidate(self.c_sha, self.b_sha)
        self.assertEqual(self.publish(receipts_root=self.receipts)['status'], 'WRITTEN')
        audit = json.loads(self.out.read_text(encoding='utf-8'))['candidate_audit']
        self.assertEqual((audit['status'], audit['retained']['positions_credited_to_lineage']), ('RETAINED_IN_CHAIN', 50))

    def test_a_ruling_that_cites_another_receipt_writes_nothing_deliberate_red(self):
        self.write_log('0' * 8)
        outcome = self.publish(receipts_root=self.receipts, ruling_log=self.log, ruling_id='ep-1', refusal_receipt=self.receipt)
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertIn('not a prefix', outcome['why'])
        self.assertFalse(self.out.exists())

    def test_no_candidate_record_reads_no_candidate(self):
        self.assertEqual(self.publish()['status'], 'WRITTEN')
        self.assertEqual(json.loads(self.out.read_text(encoding='utf-8'))['candidate_audit']['status'], 'NO_CANDIDATE')

    def test_spec_keys_for_the_audit_are_admitted_and_unknown_keys_still_refuse(self):
        base = {'published_checkpoint_root': str(self.c), 'hour_result_path': str(self.hour_result), 'expected_genesis': self.g_sha,
                'custody_parent': str(self.custody), 'snapshot_path': str(self.out), 'blocker': 'x', 'receipts_root': str(self.receipts)}
        self.assertEqual(hook.publish_from_spec({**base, 'surprise': 1})['status'], 'FAILED')
        self.assertEqual(hook.publish_from_spec({**base, 'ruling_id': 'ep-1', 'ruling_log': str(self.log), 'refusal_receipt': str(self.receipt)})['status'], 'WRITTEN')


class HookTests(Fixture):
    def test_writes_a_snapshot_whose_head_is_the_published_head_and_check_live_agrees(self):
        outcome = self.publish()
        self.assertEqual(outcome['status'], 'WRITTEN')
        written = json.loads(self.out.read_text(encoding='utf-8'))
        self.assertEqual((written['head_manifest_sha256'], outcome['head']), (self.c_sha, self.c_sha))
        self.assertEqual(written['status']['lineage']['retained_applied_positions'], 150)
        self.assertFalse(snap.check_live(self.out, current_head=lambda: self.c_sha)['stale'])

    def test_deliberate_red_a_failed_hook_leaves_the_old_snapshot_and_the_page_reads_stale(self):
        self.assertEqual(self.publish()['status'], 'WRITTEN')
        before = self.out.read_bytes()
        # the next hour's head moves on, but the hook is handed a genesis that is not this lineage's: nothing is written
        outcome = self.publish(expected_genesis_manifest_sha256='f' * 64)
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertIn('AncestryRefusal', outcome['why'])
        self.assertEqual(self.out.read_bytes(), before)
        self.assertTrue(snap.check_live(self.out, current_head=lambda: 'e' * 64)['stale'])

    def test_the_repair_cli_exits_8_when_the_snapshot_is_written_but_the_page_is_not(self):
        # review of 82481add: main() returned 0 for WRITTEN even when the requested live page FAILED, so a repair rerun read as success
        spec_file = self.root / 'spec.json'
        spec_file.write_text('{}', encoding='utf-8')
        cases = (({'status': 'WRITTEN', 'page': {'status': 'FAILED', 'why': 'OSError: disk full'}}, 8),
                 ({'status': 'WRITTEN', 'page': {'status': 'WRITTEN', 'state': 'CURRENT', 'reasons': []}}, 0),
                 ({'status': 'WRITTEN'}, 0), ({'status': 'FAILED', 'why': 'x'}, 8))
        for result, expected in cases:
            with patch.object(hook, 'publish_from_spec', return_value=result), patch('builtins.print'):
                self.assertEqual(hook.main([str(spec_file)]), expected, result)

    def test_a_hour_result_for_another_head_writes_nothing(self):
        other = json.loads(self.hour_result.read_text())
        other['child_manifest_sha256'] = self.b_sha
        self.hour_result.write_text(json.dumps(other))
        outcome = self.publish()
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertFalse(self.out.exists())

    def test_publish_from_spec_never_raises_on_a_none_or_wrong_typed_path_value(self):
        base = {'published_checkpoint_root': str(self.c), 'hour_result_path': str(self.hour_result), 'expected_genesis': self.g_sha,
                'custody_parent': str(self.custody), 'blocker': 'x', 'snapshot_path': str(self.out)}
        for field in ('custody_parent', 'published_checkpoint_root', 'hour_result_path', 'snapshot_path', 'expected_genesis'):
            for bad in (None, 5, ['a']):
                result = hook.publish_from_spec({**base, field: bad})
                self.assertEqual(result['status'], 'FAILED', (field, bad))
        self.assertFalse(self.out.exists())

    def test_the_hook_never_raises_on_a_missing_head_directory(self):
        outcome = self.publish(head_directory=self.root / 'absent')
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertFalse(self.out.exists())

    def test_spec_must_be_closed_and_name_a_next_segment_source(self):
        base = {'published_checkpoint_root': str(self.c), 'hour_result_path': str(self.hour_result), 'expected_genesis': self.g_sha,
                'custody_parent': str(self.custody), 'snapshot_path': str(self.out)}
        self.assertEqual(hook.publish_from_spec({**base, 'surprise': 1, 'blocker': 'x'})['status'], 'FAILED')
        self.assertEqual(hook.publish_from_spec(base)['status'], 'FAILED')            # no receipts_root, next or blocker
        self.assertFalse(self.out.exists())
        self.assertEqual(hook.publish_from_spec({**base, 'blocker': 'no admitted mixture bound yet'})['status'], 'WRITTEN')


class FakePending:
    def __init__(self, *, fail_advance=False):
        self.calls = []
        self.fail_advance = fail_advance
        self.record = None

    def advance_and_record_pending(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_advance:
            raise RuntimeError('advance refused')
        self.record = {'blocker': kwargs['blocker']}

    def read_pending_continuation(self, receipts_root, *, current_head_sha256):
        return self.record or {}


class FakeHeads:
    def __init__(self, root: Path, head: str):
        self.path = root / 'selected-head.json'
        self.path.write_text('{}')
        self.head = head

    def pointer_path(self, receipts_root):
        return self.path

    def current_head_sha256(self, receipts_root):
        return self.head


class PromoteIntegrationTests(Fixture):
    def spec(self, **snapshot_overrides):
        shot = {'expected_genesis': self.g_sha, 'custody_parent': str(self.custody), 'snapshot_path': str(self.out), **snapshot_overrides}
        return {'repo_root': str(self.root), 'receipts_root': str(self.root), 'published_checkpoint_root': str(self.c),
                'hour_result_path': str(self.hour_result), 'expected_parent': self.b_sha, 'expected_child': self.c_sha,
                'ledger': str(self.root / 'promote-ledger.jsonl'), 'blocker': 'no admitted mixture bound yet', 'snapshot': shot, **self.score_fields()}

    def run_promote(self, spec, *, pending=None, writer=hook.publish_from_spec):
        rows = []
        pending = pending or FakePending()
        out = promote_module.promote(spec, pending=pending, sch=FakeHeads(self.root, self.c_sha), row=lambda **fields: rows.append(fields),
                                     ruling='66882', snapshot=writer)
        return out, pending, rows

    def refused_before_any_move(self, spec, needle):
        out, pending, rows = self.run_promote(spec)
        self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'), out)
        self.assertIn(needle, out['why'])
        self.assertEqual(pending.calls, [])                                 # the head mover was never reached: the selected head and the pending record are as they were
        self.assertFalse(any(row['kind'] in ('intent', 'promote_outcome') for row in rows), rows)
        self.assertFalse(self.out.exists())                                 # and no snapshot was written
        return rows

    def test_a_missing_score_receipt_means_no_advance_deliberate_red(self):
        for fields in (('score_receipt',), ('score_receipt_sha256',), ('score_receipt', 'score_receipt_sha256')):
            spec = self.spec()
            for name in fields:
                del spec[name]
            self.refused_before_any_move(spec, 'spec not closed')
        spec = self.spec()
        spec['score_receipt'] = ''
        self.refused_before_any_move(spec, 'non-empty strings')
        spec = self.spec()
        spec['score_receipt'] = str(self.root / 'no-such-receipt.json')
        self.refused_before_any_move(spec, 'unreadable')

    def test_a_header_only_score_receipt_is_refused_before_any_move_deliberate_red(self):
        spec = {**self.spec(), **self.score_fields(scores=False, name='header-only.json')}
        self.refused_before_any_move(spec, 'carries no scores')

    def test_a_receipt_whose_rows_carry_no_valid_scored_values_is_refused_before_any_move_deliberate_red(self):
        for name, fresh in bad_score_rows().items():
            with self.subTest(name):
                spec = {**self.spec(), **self.score_fields(fresh_override=fresh, name='bad-rows.json')}
                self.refused_before_any_move(spec, 'carries no scores')

    def test_a_receipt_that_does_not_hash_to_the_cited_digest_is_refused_deliberate_red(self):
        spec = self.spec()
        spec['score_receipt_sha256'] = '0' * 64
        self.refused_before_any_move(spec, 'do not hash')

    def test_a_receipt_scored_on_another_plan_or_for_another_head_is_refused_deliberate_red(self):
        self.refused_before_any_move({**self.spec(), **self.score_fields(plan='a' * 64, name='other-plan.json')}, 'frozen plan')
        self.refused_before_any_move({**self.spec(), **self.score_fields(child=self.b_sha, name='other-head.json')}, 'different checkpoint')

    def write_run_identity(self, digest, *, purpose='RETENTION_ELIGIBLE_EXPERIMENT', bind_hour_result=True):
        """The run's frozen identity as the child custody holds it: <hour result dir>/prediction.json carries `identity`, and the hour result names the file's sha256."""
        identity = {'training_job_purpose': purpose}
        if digest is not None:
            identity['scored_pair_binding_sha256'] = digest
        raw = json.dumps({'identity': identity}, sort_keys=True).encode()
        (self.hour_result.parent / 'prediction.json').write_bytes(raw)
        hour = json.loads(self.hour_result.read_text(encoding='utf-8'))
        hour['prediction_sha256'] = hashlib.sha256(raw).hexdigest() if bind_hour_result else '0' * 64
        self.hour_result.write_text(json.dumps(hour))

    def frozen_entry(self, plan='a' * 64, *, parent=None, mutate=None, name='plan-entry.json'):
        """A closed prelaunch scored-pair entry for `plan` written to disk; returns (path, sha256 of its bytes)."""
        entry = {'schema': entry_mod.ENTRY_SCHEMA, 'run_id': 'r1',
                 'bindings': {key: (plan if key == 'episode_plan_sha256' else 'c' * 64) for key in entry_mod.COMMON_BINDING_KEYS},
                 'metric': {'name': 'heldout_loss', 'path': 'arms.fresh.mean_nll'}, 'parent_manifest_sha256': parent or self.b_sha,
                 'promote': {'repo_root': str(self.root), 'receipts_root': str(self.root), 'ledger': str(self.root / 'promote-ledger.jsonl'), 'blocker': 'x'}}
        if mutate is not None:
            mutate(entry)
        path = self.root / name
        raw = json.dumps(entry, sort_keys=True).encode()
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def frozen_plan_binding(self, plan='a' * 64, *, parent=None, mutate=None, digest=None, name='plan-entry.json'):
        """A prelaunch entry for `plan` on disk AND the run identity that froze its digest (`digest` overrides what the run froze); returns the spec binding {entry}."""
        path, entry_digest = self.frozen_entry(plan, parent=parent, mutate=mutate, name=name)
        self.write_run_identity(digest or entry_digest)
        return {'entry': str(path)}

    def test_the_one_declared_plan_override_admits_exactly_that_plan_control(self):
        self.refused_before_any_move({**self.spec(), **self.score_fields(plan='b' * 64, name='not-the-declared.json'), 'score_plan_sha256': 'a' * 64,
                                      'score_plan_binding': self.frozen_plan_binding('a' * 64)}, 'frozen plan')
        self.refused_before_any_move({**self.spec(), 'score_plan_sha256': 'not-a-sha', 'score_plan_binding': self.frozen_plan_binding('a' * 64)}, 'not the frozen plan')
        spec = {**self.spec(), **self.score_fields(plan='a' * 64, name='declared-plan.json'), 'score_plan_sha256': 'a' * 64,
                'score_plan_binding': self.frozen_plan_binding('a' * 64)}
        out, pending, _ = self.run_promote(spec)
        self.assertEqual((out['code'], len(pending.calls)), (0, 1))

    def test_a_declared_plan_with_no_frozen_entry_provenance_is_refused_before_any_move_deliberate_red(self):
        """Ash (a): a caller-supplied score_plan_sha256 other than the cadence plan, with no frozen-entry provenance, used to be accepted on the standalone path."""
        spec = {**self.spec(), **self.score_fields(plan='a' * 64, name='declared-plan.json'), 'score_plan_sha256': 'a' * 64}
        rows = self.refused_before_any_move(spec, 'no frozen-entry provenance')
        self.assertEqual([row['kind'] for row in rows], ['refuse_before_move'])
        # the cadence plan itself needs no binding (no override is being declared)
        out, pending, _ = self.run_promote({**self.spec(), 'score_plan_sha256': cadence.CADENCE_PLAN_SHA256})
        self.assertEqual((out['code'], len(pending.calls)), (0, 1))

    def test_a_plan_binding_that_does_not_match_its_frozen_entry_is_refused_before_any_move_deliberate_red(self):
        declared = {**self.spec(), **self.score_fields(plan='a' * 64, name='declared-plan.json'), 'score_plan_sha256': 'a' * 64}
        cases = {
            'entry bytes differ from the digest the run froze': lambda: self.frozen_plan_binding('a' * 64, digest='0' * 64),
            'entry is for another plan': lambda: self.frozen_plan_binding('d' * 64),
            'entry parent is not the head being advanced from': lambda: self.frozen_plan_binding('a' * 64, parent='e' * 64),
            'entry is not the closed prelaunch schema': lambda: self.frozen_plan_binding('a' * 64, mutate=lambda entry: entry.update(per_arm={'x': 1})),
        }
        for name, make in cases.items():
            with self.subTest(name):
                self.refused_before_any_move({**declared, 'score_plan_binding': make()}, 'no frozen-entry provenance')
        self.write_run_identity('a' * 64)
        for name, binding in {'not an object': 'x', 'extra key': {'entry': 'y', 'x': 1}, 'missing entry': {'entry_sha256': 'a' * 64}, 'entry not a path': {'entry': 7},
                              'digest not hex': {'entry': 'y', 'entry_sha256': 'z' * 64}, 'entry unreadable': {'entry': str(self.root / 'none.json')}}.items():
            with self.subTest(name):
                self.refused_before_any_move({**declared, 'score_plan_binding': binding}, 'no frozen-entry provenance')
        self.refused_before_any_move({**self.spec(), 'score_plan_binding': self.frozen_plan_binding('a' * 64)}, 'no score_plan_sha256')

    def test_a_self_consistent_foreign_entry_is_refused_before_any_move_and_the_genuine_entry_is_accepted_deliberate_red(self):
        """The digest must come from the RUN's frozen identity. A valid foreign entry B (same parent, same plan, its own correct digest) must not pass for run A."""
        declared = {**self.spec(), **self.score_fields(plan='a' * 64, name='declared-plan.json'), 'score_plan_sha256': 'a' * 64}
        genuine, genuine_digest = self.frozen_entry('a' * 64, name='entry-A.json')
        foreign, foreign_digest = self.frozen_entry('a' * 64, mutate=lambda entry: entry.update(run_id='someone-else'), name='entry-B.json')
        self.assertNotEqual(genuine_digest, foreign_digest)
        self.write_run_identity(genuine_digest)                                    # the run froze entry A
        # B named with its own matching digest: the old self-consistency check passed this
        rows = self.refused_before_any_move({**declared, 'score_plan_binding': {'entry': str(foreign), 'entry_sha256': foreign_digest}}, 'not the scored_pair_binding_sha256')
        self.assertEqual([row['kind'] for row in rows], ['refuse_before_move'])
        # B named alone: its bytes do not hash to the digest the run froze
        self.refused_before_any_move({**declared, 'score_plan_binding': {'entry': str(foreign)}}, 'no frozen-entry provenance')
        # genuine A: accepted, with or without the optional caller digest
        for binding in ({'entry': str(genuine)}, {'entry': str(genuine), 'entry_sha256': genuine_digest}):
            out, pending, _ = self.run_promote({**declared, 'score_plan_binding': binding})
            self.assertEqual((out['code'], len(pending.calls)), (0, 1), out)
            self.assertFalse(self.out.exists() and False)
            if self.out.exists():
                self.out.unlink()

    def foreign_receipt_group(self, *, claimed_child=None, name='foreign'):
        """A whole self-consistent group for the SAME parent and plan elsewhere: its own entry B, prediction.json carrying B's digest, and an hour result that
        hashes that prediction. Returns (hour_result_path, binding)."""
        folder = self.root / name
        folder.mkdir()
        entry_path, digest = self.frozen_entry('a' * 64, mutate=lambda entry: entry.update(run_id='someone-else'), name=f'{name}-entry.json')
        raw = json.dumps({'identity': {'training_job_purpose': 'RETENTION_ELIGIBLE_EXPERIMENT', 'scored_pair_binding_sha256': digest}}, sort_keys=True).encode()
        (folder / 'prediction.json').write_bytes(raw)
        hour = folder / 'hour-result.json'
        hour.write_text(json.dumps({'child_manifest_sha256': claimed_child or self.c_sha, 'parent_manifest_sha256': self.b_sha, 'applied_positions': 50,
                                    'prediction_sha256': hashlib.sha256(raw).hexdigest()}))
        return hour, {'entry': str(entry_path), 'entry_sha256': digest}

    def test_a_foreign_receipt_group_for_the_same_child_is_refused_before_any_move_and_the_genuine_group_is_accepted_deliberate_red(self):
        """The hour result path is caller-supplied, so the identity must be anchored to the published child's own custody, not to whatever self-consistent
        hour-result + prediction + entry group the caller names (same parent, declared plan, a valid score receipt for the genuine child)."""
        declared = {**self.spec(), **self.score_fields(plan='a' * 64, name='declared-plan.json'), 'score_plan_sha256': 'a' * 64}
        genuine = self.frozen_plan_binding('a' * 64)                                  # the child's own custody: <root>/hour-result.json beside the published root
        hour, binding = self.foreign_receipt_group()
        rows = self.refused_before_any_move({**declared, 'hour_result_path': str(hour), 'score_plan_binding': binding}, 'foreign receipt group')
        self.assertEqual([row['kind'] for row in rows], ['refuse_before_move'])
        hour, binding = self.foreign_receipt_group(claimed_child='f' * 64, name='foreign-other-child')
        self.refused_before_any_move({**declared, 'hour_result_path': str(hour), 'score_plan_binding': binding}, 'foreign receipt group')
        # an hour result in the child's own directory that names another child is another child's receipt
        genuine_hour = json.loads(self.hour_result.read_text(encoding='utf-8'))
        self.hour_result.write_text(json.dumps({**genuine_hour, 'child_manifest_sha256': 'f' * 64}))
        self.refused_before_any_move({**declared, 'score_plan_binding': genuine}, 'another child')
        self.hour_result.write_text(json.dumps(genuine_hour))
        out, pending, _ = self.run_promote({**declared, 'score_plan_binding': genuine})                      # control: the genuine group
        self.assertEqual((out['code'], len(pending.calls)), (0, 1), out)

    def test_no_readable_run_identity_refuses_any_non_cadence_plan_before_any_move_deliberate_red(self):
        declared = {**self.spec(), **self.score_fields(plan='a' * 64, name='declared-plan.json'), 'score_plan_sha256': 'a' * 64}
        path, digest = self.frozen_entry('a' * 64)
        binding = {'entry': str(path), 'entry_sha256': digest}
        prediction = self.hour_result.parent / 'prediction.json'
        if prediction.exists():
            prediction.unlink()
        self.refused_before_any_move({**declared, 'score_plan_binding': binding}, 'no run identity can be read')         # no identity file in the custody
        self.write_run_identity(digest, bind_hour_result=False)
        self.refused_before_any_move({**declared, 'score_plan_binding': binding}, 'does not hash to the hour result')   # file not bound by the hour result
        self.write_run_identity(digest, purpose='CONTINUE_TRAINING')
        self.refused_before_any_move({**declared, 'score_plan_binding': binding}, 'froze no scored-pair entry')          # a lineage identity froze none
        self.write_run_identity(None)
        self.refused_before_any_move({**declared, 'score_plan_binding': binding}, 'no sha256 scored_pair_binding_sha256')
        self.write_run_identity(digest)
        out, pending, _ = self.run_promote({**declared, 'score_plan_binding': binding})                                   # control: the same inputs with the identity restored
        self.assertEqual((out['code'], len(pending.calls)), (0, 1), out)

    def test_a_refusal_is_recorded_in_the_ledger_with_its_reason(self):
        spec = {**self.spec(), **self.score_fields(scores=False, name='header-only.json')}
        rows = self.refused_before_any_move(spec, 'carries no scores')
        self.assertEqual([row['kind'] for row in rows], ['refuse_before_move'])
        self.assertIn('carries no scores', rows[0]['why'])

    def test_a_clean_move_writes_the_snapshot_and_records_it(self):
        out, pending, rows = self.run_promote(self.spec())
        self.assertEqual((out['code'], out['snapshot']['status']), (0, 'WRITTEN'))
        self.assertEqual(json.loads(self.out.read_text(encoding='utf-8'))['head_manifest_sha256'], self.c_sha)
        self.assertEqual([row['kind'] for row in rows][-2:], ['promote_outcome', 'snapshot_outcome'])
        self.assertEqual(len(pending.calls), 1)

    def test_the_hour_end_move_regenerates_the_live_page_and_an_unreadable_pointer_reads_stale_deliberate_red(self):
        page = self.root / 'live-page.md'
        out, _, rows = self.run_promote(self.spec(page_path=str(page)))
        self.assertEqual((out['code'], out['snapshot']['status']), (0, 'WRITTEN'))
        self.assertEqual((out['snapshot']['page']['status'], out['snapshot']['page']['state']), ('WRITTEN', 'STALE'))   # the test pointer is not a real one
        first = page.read_text(encoding='utf-8').splitlines()[0]
        self.assertTrue(first.startswith('> **[RED] STALE'), first)
        self.assertIn('live selected head is GENESIS', first)                  # no pointer file: the reader reports the genesis head, which is not the snapshot head
        self.assertIn('receipt missing: selected-continuation-head.json', first)
        self.assertEqual(rows[-1]['kind'], 'snapshot_outcome')

    def test_a_page_write_failure_after_the_move_is_code_8(self):
        def writer(spec):
            return {'status': 'WRITTEN', 'page': {'status': 'FAILED', 'why': 'OSError: disk full'}}
        out, pending, _ = self.run_promote(self.spec(page_path=str(self.root / 'p.md')), writer=writer)
        self.assertEqual((out['code'], out['status']), (8, 'PROMOTED_SNAPSHOT_FAILED'))
        self.assertEqual(len(pending.calls), 1)

    def test_a_bad_page_path_refuses_before_any_move(self):
        for bad in (None, '', 5):
            out, pending, rows = self.run_promote(self.spec(page_path=bad))
            self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'), bad)
            self.assertEqual((pending.calls, rows), ([], []), bad)

    def test_a_move_without_a_snapshot_key_behaves_exactly_as_before(self):
        spec = self.spec()
        del spec['snapshot']
        out, _, rows = self.run_promote(spec)
        self.assertEqual(out['code'], 0)
        self.assertNotIn('snapshot', out)
        self.assertFalse(self.out.exists())
        self.assertEqual([row['kind'] for row in rows][-1], 'promote_outcome')

    def test_a_snapshot_failure_after_the_move_is_code_8_and_does_not_undo_the_move(self):
        out, pending, rows = self.run_promote(self.spec(expected_genesis='f' * 64))
        self.assertEqual((out['code'], out['status']), (8, 'PROMOTED_SNAPSHOT_FAILED'))
        self.assertEqual(out['snapshot']['status'], 'FAILED')
        self.assertEqual(out['head'], self.c_sha)
        self.assertEqual(len(pending.calls), 1)
        self.assertEqual(rows[-1]['kind'], 'snapshot_outcome')

    def test_a_malformed_snapshot_spec_refuses_before_any_move(self):
        for bad in ({'expected_genesis': self.g_sha}, {'expected_genesis': self.g_sha, 'custody_parent': 'x', 'surprise': 1}):
            spec = self.spec()
            spec['snapshot'] = bad
            out, pending, _ = self.run_promote(spec)
            self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'))
            self.assertEqual(pending.calls, [])

    def test_a_snapshot_spec_with_a_non_string_or_malformed_value_refuses_before_any_move(self):
        # static review finding: custody_parent=None passed the key-only check and reached Path(None) after the move
        for field, bad in (('custody_parent', None), ('custody_parent', ''), ('custody_parent', 5), ('expected_genesis', None),
                           ('expected_genesis', 'not-hex'), ('expected_genesis', 'F' * 64), ('snapshot_path', 7), ('snapshot_path', '')):
            out, pending, rows = self.run_promote(self.spec(**{field: bad}))
            self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'), (field, bad))
            self.assertEqual((pending.calls, rows), ([], []), (field, bad))

    def test_the_row_7_producer_keys_pass_the_production_caller_to_the_writer(self):
        # the hook accepts these three; the caller's whitelist once refused them, so no real hour could bind a live source
        keys = {'gpu_window_marker': str(self.root / 'gpu-window-open'), 'measurement_receipt': str(self.root / 'episode-nll.json'),
                'hold_record': str(self.root / 'training-hold.json')}
        seen = []

        def writer(spec):
            seen.append(spec)
            return {'status': 'WRITTEN'}
        out, pending, _ = self.run_promote(self.spec(**keys), writer=writer)
        self.assertEqual(out['code'], 0)
        self.assertEqual(len(pending.calls), 1)
        self.assertEqual({name: seen[0][name] for name in keys}, keys)

    def test_the_live_page_tracks_every_existing_producer_input_not_only_the_hour_result_deliberate_red(self):
        import continuity_page_live
        from unittest import mock
        sources = {name: self.root / f'{name}.src' for name in ('gpu_window_marker', 'measurement_receipt', 'hold_record')}
        for path in sources.values():
            path.write_text('x', encoding='utf-8')
        absent = str(self.root / 'absent-hold.json')
        captured = {}

        def fake_page(**kwargs):
            captured.update(kwargs)
            return {'state': 'CURRENT', 'reasons': []}
        with mock.patch.object(continuity_page_live, 'generate_live_page', fake_page):
            self.run_promote(self.spec(page_path=str(self.root / 'p.md'), **{name: str(path) for name, path in sources.items()}))
            tracked = {Path(path) for path in captured['receipt_paths']}
            self.assertEqual(tracked, {self.hour_result, *sources.values()})           # a changed hold, measurement or marker makes the page STALE
            captured.clear()
            self.run_promote(self.spec(page_path=str(self.root / 'p.md'), hold_record=absent))
            # an absent named source stays a named dependency with its captured absence (review finding 2): UNKNOWN in the status now, STALE once it appears
            self.assertEqual({Path(path) for path in captured['receipt_paths']}, {self.hour_result})
            self.assertEqual({Path(path) for path in captured['absent_paths']}, {Path(absent)})

    def test_every_absent_named_source_is_passed_with_its_captured_absence_and_none_when_all_exist_deliberate_red(self):
        import continuity_page_live
        from unittest import mock
        names = ('gpu_window_marker', 'measurement_receipt', 'hold_record')
        captured = {}

        def fake_page(**kwargs):
            captured.update(kwargs)
            return {'state': 'CURRENT', 'reasons': []}
        with mock.patch.object(continuity_page_live, 'generate_live_page', fake_page):
            absent = {name: self.root / f'{name}.absent' for name in names}
            self.run_promote(self.spec(page_path=str(self.root / 'p.md'), **{name: str(path) for name, path in absent.items()}))
            self.assertEqual({Path(path) for path in captured['absent_paths']}, set(absent.values()))
            self.assertEqual({Path(path) for path in captured['receipt_paths']}, {self.hour_result})
            captured.clear()
            for path in absent.values():
                path.write_text('x', encoding='utf-8')
            self.run_promote(self.spec(page_path=str(self.root / 'p.md'), **{name: str(path) for name, path in absent.items()}))
            self.assertEqual(list(captured['absent_paths']), [])

    def test_a_non_string_or_empty_producer_key_refuses_before_any_move_deliberate_red(self):
        for field in ('gpu_window_marker', 'measurement_receipt', 'hold_record'):
            for bad in (None, '', 7):
                out, pending, rows = self.run_promote(self.spec(**{field: bad}))
                self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'), (field, bad))
                self.assertEqual((pending.calls, rows), ([], []), (field, bad))

    def test_a_writer_that_raises_after_the_move_still_records_the_outcome_and_is_code_8(self):
        def raising_writer(spec):
            raise TypeError('expected str, bytes or os.PathLike object, not NoneType')
        out, pending, rows = self.run_promote(self.spec(), writer=raising_writer)
        self.assertEqual((out['code'], out['status']), (8, 'PROMOTED_SNAPSHOT_FAILED'))
        self.assertEqual(out['snapshot']['status'], 'FAILED')
        self.assertIn('TypeError', out['snapshot']['why'])
        self.assertEqual(out['head'], self.c_sha)
        self.assertEqual(len(pending.calls), 1)
        self.assertEqual([row['kind'] for row in rows][-2:], ['promote_outcome', 'snapshot_outcome'])

    def test_the_chain_promote_to_hook_to_file_to_the_page_renderer(self):
        # the smallest real-consumer chain: promote's boundary calls the real hook, the hook writes the file, the page renderer reads that file
        renderer_path = ROOT / 'src/ember/governance/scripts/gen_readme_status.py'
        sys.path.insert(0, str(renderer_path.parent))
        try:
            spec = importlib.util.spec_from_file_location('chain_gen_readme_status', renderer_path)
            renderer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(renderer)
        finally:
            sys.path.remove(str(renderer_path.parent))
        if not hasattr(renderer, 'apply_continuity_status'):
            self.skipTest('the page renderer (#2339) is not in this tree yet; the chain runs once it merges')
        out, _, rows = self.run_promote(self.spec())
        self.assertEqual((out['code'], out['snapshot']['status']), (0, 'WRITTEN'))
        page_text = 'before\n' + renderer.CONTINUITY_BEGIN_MARKER + '\nold\n' + renderer.CONTINUITY_END_MARKER + '\nafter\n'
        rendered = renderer.apply_continuity_status(page_text, str(self.out))
        self.assertIn(self.c_sha, rendered)
        self.assertIn('`150` positions', rendered)
        self.assertNotIn('\nold\n', rendered)
        self.assertEqual(renderer.apply_continuity_status(rendered, str(self.out)), rendered)     # idempotent: the page is current
        self.assertEqual(rows[-1]['kind'], 'snapshot_outcome')

    def test_a_snapshot_key_without_a_writer_refuses_before_any_move(self):
        out, pending, _ = self.run_promote(self.spec(), writer=None)
        self.assertEqual((out['code'], pending.calls), (4, []))

    def test_a_refused_move_writes_no_snapshot(self):
        out, _, _ = self.run_promote(self.spec(), pending=FakePending(fail_advance=True))
        self.assertNotEqual(out['code'], 0)
        self.assertNotIn('snapshot', out)
        self.assertFalse(self.out.exists())


class PromoteBindingTests(Fixture):
    """The production caller (promote) must forward the frozen claim predicate and the ruling/receipt the hook already accepts."""

    def setUp(self):
        super().setUp()
        self.receipts = self.root / 'receipts'
        self.receipts.mkdir()
        self.cand = 'd' * 64
        cand_hour = self.root / 'candidate-hour-result.json'
        cand_bytes = json.dumps({'child_manifest_sha256': self.cand, 'parent_manifest_sha256': self.c_sha, 'applied_positions': 77}, sort_keys=True).encode()
        cand_hour.write_bytes(cand_bytes)
        (self.receipts / 'candidate-continuation-head.json').write_text(json.dumps({
            'candidate_checkpoint_manifest_sha256': self.cand, 'hour_result_path': str(cand_hour), 'hour_result_sha256': hashlib.sha256(cand_bytes).hexdigest(),
            'parent_checkpoint_manifest_sha256': self.c_sha, 'published_at': 1.0, 'schema': 'ember-candidate-continuation-head-v1'}), encoding='utf-8')
        self.receipt = self.root / 'episode-nll.json'
        receipt_bytes = json.dumps({'bindings': {'checkpoint_manifest_sha256': self.cand}}, sort_keys=True).encode()
        self.receipt.write_bytes(receipt_bytes)
        self.receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
        self.log = self.root / 'loop.jsonl'
        self.write_log(self.receipt_sha[:8])
        self.predicate = self.root / 'predicate.json'
        self.predicate.write_bytes(b'{"schema": "ember-claim-budget-predicate-v1", "fixture": true}')
        self.predicate_sha = hashlib.sha256(self.predicate.read_bytes()).hexdigest()
        self.pinned = patch.object(ca, 'PREDICATE_SHA256', self.predicate_sha)

    def write_log(self, cited):
        self.log.write_text(json.dumps({'id': 'ep-1', 'stage': 'RULED', 'verdict': 'REFUTED',
                                        'because': f'limit exceeded; receipt episode-nll.json sha256 {cited}; pointer unchanged'}) + '\n', encoding='utf-8')

    def spec(self, **bindings):
        shot = {'expected_genesis': self.g_sha, 'custody_parent': str(self.custody), 'snapshot_path': str(self.out),
                'claim_predicate': str(self.predicate), 'ruling_log': str(self.log), 'ruling_id': 'ep-1', 'refusal_receipt': str(self.receipt), **bindings}
        return {'repo_root': str(self.root), 'receipts_root': str(self.receipts), 'published_checkpoint_root': str(self.c),
                'hour_result_path': str(self.hour_result), 'expected_parent': self.b_sha, 'expected_child': self.c_sha,
                'ledger': str(self.root / 'promote-ledger.jsonl'), 'blocker': 'no admitted mixture bound yet', 'snapshot': shot, **self.score_fields()}

    def run_promote(self, spec):
        rows = []
        pending = FakePending()
        with self.pinned:
            out = promote_module.promote(spec, pending=pending, sch=FakeHeads(self.root, self.c_sha), row=lambda **fields: rows.append(fields),
                                         ruling='66882', snapshot=hook.publish_from_spec)
        return out, pending, rows

    def test_the_production_promote_forwards_the_claim_predicate_and_the_known_refusal_to_the_snapshot(self):
        out, pending, _ = self.run_promote(self.spec())
        self.assertEqual((out['code'], out['snapshot']['status']), (0, 'WRITTEN'))
        shot = json.loads(self.out.read_text(encoding='utf-8'))
        self.assertEqual(shot['status']['claim_budget_eligible']['status'], 'UNDETERMINED')            # not UNDEFINED: the predicate reached the status
        self.assertEqual(shot['status']['claim_budget_eligible']['predicate_sha256'], self.predicate_sha)
        audit = shot['candidate_audit']
        self.assertEqual((audit['status'], audit['retained']['positions_credited_to_lineage']), ('REFUSED_NOT_RETAINED', 0))
        self.assertEqual(audit['refusal_ruling']['receipt_sha256'], self.receipt_sha)
        self.assertEqual(len(pending.calls), 1)

    def test_without_the_bindings_the_same_candidate_is_unruled_and_the_claim_is_undefined_control(self):
        spec = self.spec()
        for name in ('claim_predicate', 'ruling_log', 'ruling_id', 'refusal_receipt'):
            del spec['snapshot'][name]
        out, _, _ = self.run_promote(spec)
        self.assertEqual(out['code'], 0)
        shot = json.loads(self.out.read_text(encoding='utf-8'))
        self.assertEqual((shot['candidate_audit']['status'], shot['status']['claim_budget_eligible']['status']), ('UNRULED_NOT_RETAINED', 'UNDEFINED'))

    def test_a_ruling_that_cites_another_receipt_is_code_8_after_the_move_and_writes_no_snapshot_deliberate_red(self):
        self.write_log('0' * 8)
        out, pending, _ = self.run_promote(self.spec())
        self.assertEqual((out['code'], out['status']), (8, 'PROMOTED_SNAPSHOT_FAILED'))
        self.assertIn('not a prefix', out['snapshot']['why'])
        self.assertFalse(self.out.exists())
        self.assertEqual(len(pending.calls), 1)                  # the move stands; the failure is loud, not a rollback

    def test_a_malformed_or_incomplete_binding_refuses_before_any_move_deliberate_red(self):
        for name, bad in (('claim_predicate', 5), ('claim_predicate', ''), ('ruling_id', None), ('ruling_log', 3), ('refusal_receipt', ''), ('candidate_record', 7)):
            out, pending, rows = self.run_promote(self.spec(**{name: bad}))
            self.assertEqual((out['code'], out['status']), (4, 'REFUSED_BEFORE_MOVE'), (name, bad))
            self.assertEqual((pending.calls, rows), ([], []), (name, bad))
        spec = self.spec()
        del spec['snapshot']['refusal_receipt']                  # a ruling id with no receipt it cites
        out, pending, _ = self.run_promote(spec)
        self.assertEqual((out['code'], pending.calls), (4, []))

    def test_an_unknown_snapshot_key_still_refuses_before_any_move(self):
        out, pending, _ = self.run_promote(self.spec(surprise='x'))
        self.assertEqual((out['code'], pending.calls), (4, []))


if __name__ == '__main__':
    unittest.main()
