"""Issue #2119 row 7: claim-eligible advancement accounting bound to the approved predicate (sha256 3a2b1300...).

The eight analytical examples of the frozen predicate are executed here, plus: the predicate pin, ancestry derived from the head
(never a flag), refused branches kept separate, eligibility derived from condition evidence (never a caller Boolean), the origin
buckets partitioning the total, and null (not zero, not physical positions) when evidence is missing. One deliberate red: a counter
that reports applied physical positions as the eligible total (what master's only available number invites) is wrong on exactly the
case the predicate names.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import claim_accounting as ca  # noqa: E402

PIN = ca.PREDICATE_SHA256
HUMAN, AI, MIXED, UNKNOWN = ca.BUCKETS


def target(item, ordinal=0, *, loss=True, bucket=HUMAN, **conditions):
    cond = {name: True for name in ca.CONDITIONS}
    cond.update(conditions)
    return {'key': [item, 'text', ordinal], 'positive_loss': loss, 'conditions': cond, 'origin_bucket': bucket}


def segment(sid, parent, targets, *, positions=1000, published=True, advanced=True, unit='unit-v1', missing=None):
    return {'segment_id': sid, 'parent_segment_id': parent, 'published': published, 'advanced_head': advanced,
            'applied_positions': positions, 'budget_unit_id': unit, 'targets': targets, 'missing_evidence': missing}


def run(segments, head):
    return ca.account(segments, head_segment_id=head, predicate_sha256=PIN)


class PredicateExamplesTests(unittest.TestCase):
    def test_example_1_trained_a_b_and_masked_c_counts_two(self):
        report = run([segment('s1', None, [target('A'), target('B'), target('C', loss=False)])], 's1')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('DETERMINED', 2))

    def test_example_2_repeat_of_b_adds_nothing_and_formerly_masked_c_counts_once(self):
        report = run([segment('s1', None, [target('A'), target('B'), target('C', loss=False)]),
                      segment('s2', 's1', [target('B'), target('C')])], 's2')
        self.assertEqual(report['eligible_unique_total'], 3)
        self.assertEqual([row['eligible_increment'] for row in report['per_segment']], [2, 1])
        self.assertEqual(report['applied_loss_target_exposure'], 4)   # exposure counts the B repeat; unique credit does not

    def test_example_3_a_replayed_segment_adds_zero(self):
        report = run([segment('s1', None, [target('A'), target('B')]), segment('s2', 's1', [target('A'), target('B')])], 's2')
        self.assertEqual(report['eligible_unique_total'], 2)

    def test_example_4_a_discarded_branch_contributes_nothing_and_is_not_prior_consumption(self):
        base = segment('s1', None, [target('A')])
        discarded = segment('x1', 's1', [target('B')])
        selected = segment('s2', 's1', [target('B')])   # the same target first trained on the selected ancestry counts once there
        report = run([base, discarded, selected], 's2')
        self.assertEqual(report['eligible_unique_total'], 2)
        self.assertEqual([r['segment_id'] for r in report['refused_branches']], ['x1'])
        only_discarded = run([base, discarded], 's1')
        self.assertEqual(only_discarded['eligible_unique_total'], 1)   # B existed only on the discarded branch: zero

    def test_example_5_a_protected_item_is_excluded(self):
        report = run([segment('s1', None, [target('A'), target('P', protected_clear=False)])], 's1')
        self.assertEqual(report['eligible_unique_total'], 1)
        self.assertEqual(report['excluded'][0]['key'], ['P', 'text', 0])

    def test_example_6_buckets_report_three_two_zero_one_and_sum_to_the_total(self):
        targets = [target(f'h{i}', bucket=HUMAN) for i in range(3)] + [target(f'a{i}', bucket=AI) for i in range(2)] + [
            target('u0', bucket=UNKNOWN)]
        report = run([segment('s1', None, targets)], 's1')
        self.assertEqual(report['bucket_counts'], {HUMAN: 3, AI: 2, MIXED: 0, UNKNOWN: 1})
        self.assertEqual((report['eligible_unique_total'], sum(report['bucket_counts'].values())), (6, 6))

    def test_example_7_only_physical_positions_known_is_undetermined_not_that_number_and_not_zero(self):
        report = run([segment('s1', None, None, positions=206184448,
                              missing=['text loss masks', 'canonical target keys'])], 's1')
        self.assertEqual((report['status'], report['eligible_unique_total'], report['bucket_counts']), ('UNDETERMINED', None, None))
        self.assertEqual(report['physical_positions'], 206184448)
        self.assertTrue(any('text loss masks' in note for note in report['missing_evidence']))

    def test_example_8_unresolved_rights_is_undetermined_and_a_later_replay_cannot_mint_credit(self):
        original = segment('s1', None, [target('R', rights_provenance_ok=None)])
        replay = segment('s2', 's1', [target('R')])   # the replay's own conditions are fine, but the ORIGINAL was unresolved
        report = run([original, replay], 's2')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('UNDETERMINED', None))
        self.assertEqual(report['proved_true_unique'], {'count': 0, 'buckets': {HUMAN: 0, AI: 0, MIXED: 0, UNKNOWN: 0}, 'complete': False})

    def test_a_known_false_original_gains_nothing_from_a_later_replay_that_meets_the_conditions(self):
        report = run([segment('s1', None, [target('R', caps_ok=False)]), segment('s2', 's1', [target('R')])], 's2')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('DETERMINED', 0))


class BindingAndHonestyTests(unittest.TestCase):
    def test_a_different_predicate_digest_is_refused(self):
        with self.assertRaisesRegex(ca.AccountingRefusal, 'predicate digest'):
            ca.account([segment('s1', None, [target('A')])], head_segment_id='s1', predicate_sha256='0' * 64)

    def test_an_unpublished_or_non_advancing_segment_is_excluded_with_a_reason(self):
        report = run([segment('s1', None, [target('A')]), segment('s2', 's1', [target('B')], published=False)], 's2')
        self.assertEqual(report['eligible_unique_total'], 1)
        self.assertEqual(report['excluded'][0]['segment_id'], 's2')

    def test_a_missing_ancestry_link_is_undetermined_and_named(self):
        report = run([segment('s2', 's1', [target('B')])], 's2')   # s1 was never supplied
        self.assertEqual((report['status'], report['eligible_unique_total']), ('UNDETERMINED', None))
        self.assertTrue(any("'s1'" in note for note in report['missing_evidence']))

    def test_a_cyclic_ancestry_is_refused(self):
        with self.assertRaisesRegex(ca.AccountingRefusal, 'cyclic'):
            run([segment('a', 'b', []), segment('b', 'a', [])], 'a')

    def test_budget_unit_revisions_are_never_silently_summed(self):
        with self.assertRaisesRegex(ca.AccountingRefusal, 'budget unit'):
            run([segment('s1', None, [target('A')], unit='u1'), segment('s2', 's1', [target('B')], unit='u2')], 's2')

    def test_eligibility_is_derived_from_condition_evidence_not_a_caller_boolean(self):
        forged = target('A')
        forged['eligible'] = True          # a caller-supplied flag is ignored
        forged['conditions'] = {}          # no evidence
        report = run([segment('s1', None, [forged])], 's1')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('UNDETERMINED', None))

    def test_a_missing_origin_is_never_counted_as_human(self):
        t = target('A')
        t['origin_bucket'] = None
        report = run([segment('s1', None, [t])], 's1')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('UNDETERMINED', None))

    def test_a_malformed_target_key_is_refused(self):
        bad = target('A')
        bad['key'] = ['A', 'text']
        with self.assertRaisesRegex(ca.AccountingRefusal, 'target key'):
            run([segment('s1', None, [bad])], 's1')

    def test_the_head_must_be_supplied(self):
        report = run([segment('s1', None, [target('A')])], 'nope')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('UNDETERMINED', None))

    def test_deliberate_red_physical_positions_as_the_eligible_total_is_wrong_where_the_predicate_says_undetermined(self):
        def master_counter(segments):   # the only number master carries: summed applied positions
            return sum(s['applied_positions'] for s in segments)

        segments = [segment('s1', None, None, positions=206184448, missing=['text loss masks'])]
        report = run(segments, 's1')
        self.assertEqual(master_counter(segments), 206184448)       # the naive counter presents this as the answer
        self.assertIsNone(report['eligible_unique_total'])          # the predicate: UNDETERMINED, null
        self.assertNotEqual(report['eligible_unique_total'], master_counter(segments))
        self.assertNotEqual(report['eligible_unique_total'], 0)


if __name__ == '__main__':
    unittest.main()
