"""Issue #2119 row 7: the status caller for claim accounting.

`training_continuity_status.claim_budget_eligible_status` used to raise 'no evaluator exists' for any present predicate file, so the
accounting module (claim_accounting.account, #2335) had no production caller. These tests pin the caller: the absent-file contract is
unchanged, a foreign predicate file refuses, the approved file runs the accounting over the ancestry-derived segments (totals None with the
missing evidence named, never a guess), and caller-supplied per-target segments produce a DETERMINED total.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
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
import training_continuity_ledger as ledger  # noqa: E402
import training_continuity_status as status  # noqa: E402

GENESIS, MID, HEAD = 'a' * 64, 'b' * 64, 'c' * 64


def lineage_record():
    chain = [
        {'directory': 'g', 'manifest_sha256': GENESIS, 'tokens_seen': 100, 'global_step': 10, 'token_delta': None, 'step_delta': None},
        {'directory': 'm', 'manifest_sha256': MID, 'tokens_seen': 1100, 'global_step': 20, 'token_delta': 1000, 'step_delta': 10},
        {'directory': 'h', 'manifest_sha256': HEAD, 'tokens_seen': 3100, 'global_step': 40, 'token_delta': 2000, 'step_delta': 20},
    ]
    return {'schema': status.LINEAGE_SCHEMA, 'head_manifest_sha256': HEAD, 'genesis_manifest_sha256': GENESIS, 'depth': 3,
            'genesis_tokens_seen': 100, 'cumulative_applied_token_delta': 3000, 'cumulative_step_delta': 30,
            'head_tokens_seen': 3100, 'head_global_step': 40, 'chain': chain}


def target(item, *, loss=True):
    return {'key': [item, 'text', 0], 'positive_loss': loss, 'conditions': {name: True for name in ca.CONDITIONS},
            'origin_bucket': ca.BUCKETS[0]}


class ClaimStatusCallerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        # The approved predicate file is not committed; a fixture file stands in for it by pinning the approved digest to the fixture bytes.
        self.predicate = self.dir / 'predicate.json'
        self.predicate.write_bytes(b'{"schema": "ember-claim-budget-predicate-v1", "fixture": true}')
        self.digest = hashlib.sha256(self.predicate.read_bytes()).hexdigest()

    def pinned(self):
        return patch.object(ca, 'PREDICATE_SHA256', self.digest)

    def test_absent_predicate_file_is_undefined_exactly_as_before(self):
        self.assertEqual(status.claim_budget_eligible_status(None), {'status': status.UNDEFINED, 'missing': status.CLAIM_PREDICATE_MISSING})
        self.assertEqual(status.claim_budget_eligible_status(self.dir / 'absent.json', lineage_record=lineage_record()),
                         {'status': status.UNDEFINED, 'missing': status.CLAIM_PREDICATE_MISSING})

    def test_a_predicate_file_that_is_not_the_approved_one_refuses(self):
        # RED before the caller existed: any present file raised 'no evaluator exists'; now only a digest mismatch refuses.
        with self.assertRaisesRegex(ValueError, 'differs from the approved frozen predicate'):
            status.claim_budget_eligible_status(self.predicate, lineage_record=lineage_record())

    def test_approved_file_runs_the_accounting_over_the_ancestry_and_names_the_missing_evidence(self):
        with self.pinned():
            result = status.claim_budget_eligible_status(self.predicate, lineage_record=lineage_record())
        report = result['accounting']
        self.assertEqual((result['status'], result['predicate_sha256']), ('UNDETERMINED', self.digest))
        self.assertIsNone(report['eligible_unique_total'])            # no per-target evidence on the walk: None, not 0 and not positions
        self.assertEqual(report['selected_segment_ids'], [GENESIS, MID, HEAD])
        self.assertTrue(report['missing_evidence'])
        self.assertTrue(any('per-target identities' in note for note in report['missing_evidence']))

    def test_genesis_is_excluded_and_counts_zero_positions(self):
        with self.pinned():
            report = status.claim_budget_eligible_status(self.predicate, lineage_record=lineage_record())['accounting']
        by_id = {row['segment_id']: row for row in report['per_segment']}
        self.assertEqual(by_id[GENESIS]['status'], 'EXCLUDED')
        self.assertEqual(by_id[GENESIS]['applied_positions'], 0)
        self.assertEqual([by_id[MID]['applied_positions'], by_id[HEAD]['applied_positions']], [1000, 2000])
        self.assertEqual(report['physical_positions_known_subtotal']['count'], 3000)

    def test_caller_supplied_segments_with_target_evidence_give_a_determined_total(self):
        segments = [
            {'segment_id': GENESIS, 'parent_segment_id': None, 'published': False, 'advanced_head': False, 'applied_positions': 0,
             'budget_unit_id': 'unit-v1', 'targets': [], 'missing_evidence': None},
            {'segment_id': MID, 'parent_segment_id': GENESIS, 'published': True, 'advanced_head': True, 'applied_positions': 1000,
             'budget_unit_id': 'unit-v1', 'targets': [target('A'), target('B')], 'missing_evidence': None},
            {'segment_id': HEAD, 'parent_segment_id': MID, 'published': True, 'advanced_head': True, 'applied_positions': 2000,
             'budget_unit_id': 'unit-v1', 'targets': [target('B'), target('C')], 'missing_evidence': None},
        ]
        with self.pinned():
            result = status.claim_budget_eligible_status(self.predicate, lineage_record=lineage_record(), claim_segments=segments)
        self.assertEqual((result['status'], result['accounting']['eligible_unique_total']), ('DETERMINED', 3))   # B repeats: counted once

    def full_segments(self):
        return [
            {'segment_id': GENESIS, 'parent_segment_id': None, 'published': False, 'advanced_head': False, 'applied_positions': 0,
             'budget_unit_id': 'unit-v1', 'targets': [], 'missing_evidence': None},
            {'segment_id': MID, 'parent_segment_id': GENESIS, 'published': True, 'advanced_head': True, 'applied_positions': 1000,
             'budget_unit_id': 'unit-v1', 'targets': [target('A'), target('B')], 'missing_evidence': None},
            {'segment_id': HEAD, 'parent_segment_id': MID, 'published': True, 'advanced_head': True, 'applied_positions': 2000,
             'budget_unit_id': 'unit-v1', 'targets': [target('B'), target('C')], 'missing_evidence': None},
        ]

    def refused(self, segments, pattern):
        with self.pinned(), self.assertRaisesRegex(ValueError, pattern):
            status.claim_budget_eligible_status(self.predicate, lineage_record=lineage_record(), claim_segments=segments)

    def test_deliberate_red_a_head_only_segment_with_no_parent_does_not_return_determined(self):
        # Review finding on #2337: without the coverage check this exact input returned DETERMINED over a one-hop lineage that omits the
        # ancestry the pointer selects; it must refuse.
        head_only = [dict(self.full_segments()[2], parent_segment_id=None)]
        with self.pinned():
            self.assertEqual(ca.account(head_only, head_segment_id=HEAD, predicate_sha256=self.digest)['status'], 'DETERMINED')   # the hole
        self.refused(head_only, 'do not cover the lineage ancestry chain')

    def test_an_omitted_hop_a_replayed_hop_and_a_reordered_chain_refuse(self):
        full = self.full_segments()
        self.refused([full[0], full[2]], 'do not cover')                  # mid omitted
        self.refused([full[0], full[1], full[1], full[2]], 'do not cover')  # mid replayed
        self.refused([full[0], full[2], full[1]], 'do not cover')         # reordered
        self.refused([], 'do not cover')

    def test_a_reparented_segment_refuses_even_when_the_ids_match(self):
        full = self.full_segments()
        full[2] = dict(full[2], parent_segment_id=GENESIS)
        self.refused(full, 'is not the ancestry parent')
        full = self.full_segments()
        full[0] = dict(full[0], parent_segment_id=HEAD)
        self.refused(full, 'is not the ancestry parent')

    def test_caller_supplied_segments_without_the_lineage_record_refuse(self):
        with self.pinned(), self.assertRaisesRegex(ValueError, 'need the lineage ancestry record'):
            status.claim_budget_eligible_status(self.predicate, claim_segments=self.full_segments())

    def test_present_file_without_a_lineage_record_or_segments_refuses(self):
        with self.pinned(), self.assertRaisesRegex(ValueError, 'needs the lineage ancestry record'):
            status.claim_budget_eligible_status(self.predicate)

    def test_the_full_status_record_carries_the_accounting(self):
        hour_result = {'child_manifest_sha256': HEAD, 'parent_manifest_sha256': MID, 'applied_positions': 2000}
        with self.pinned(), tempfile.TemporaryDirectory() as custody, patch.dict(
                'os.environ', {ledger.LEDGER_ROOT_ENV: self._tmp.name}):
            record = status.training_continuity_status(
                custody_parent=Path(custody), hour_result=hour_result, current_identity=None, measurement=None,
                next_blocker='no admitted mixture bound yet', lineage_record=lineage_record(), claim_predicate_path=self.predicate)
        self.assertEqual(record['claim_budget_eligible']['status'], 'UNDETERMINED')
        self.assertIn('accounting', record['claim_budget_eligible'])


if __name__ == '__main__':
    unittest.main()
