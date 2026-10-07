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
        # Kai 62062: unknown prior ancestry means no known segment above it can earn proved credit
        self.assertEqual(report['proved_true_unique']['count'], 0)
        self.assertEqual([row['eligible_increment'] for row in report['per_segment']], [None])
        self.assertEqual(report['unresolved_after_coverage_gap'], [['B', 'text', 0]])

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


class MissingEvidenceIsNeverDeterminedTests(unittest.TestCase):
    """Kai 62008 R1-R3: absent evidence is UNDETERMINED, never a known exclusion, a genesis or a unit; and an unknown-coverage
    segment makes every later first occurrence unresolved."""

    def undetermined(self, report):
        self.assertEqual((report['status'], report['eligible_unique_total'], report['bucket_counts']), ('UNDETERMINED', None, None))

    def test_r1_missing_publication_or_advancement_flags_are_undetermined_not_excluded(self):
        for field in ('published', 'advanced_head'):
            seg = segment('s1', None, [target('A')])
            del seg[field]
            report = run([seg], 's1')
            self.undetermined(report)
            self.assertTrue(any(field in note for note in report['missing_evidence']), field)
            seg[field] = 'yes'   # not a boolean either
            self.undetermined(run([seg], 's1'))

    def test_r1_an_absent_loss_mask_is_undetermined_and_a_later_positive_replay_cannot_mint_credit(self):
        unknown = target('A')
        del unknown['positive_loss']
        report = run([segment('s1', None, [unknown]), segment('s2', 's1', [target('A')])], 's2')
        self.undetermined(report)
        self.assertEqual(report['proved_true_unique']['count'], 0)
        self.assertEqual([row['eligible_increment'] for row in report['per_segment']], [0, 0])

    def test_r1_a_known_false_loss_mask_is_still_masked_input_not_unresolved(self):
        report = run([segment('s1', None, [target('A', loss=False)]), segment('s2', 's1', [target('A')])], 's2')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('DETERMINED', 1))

    def test_r2_an_absent_parent_link_is_not_a_genesis(self):
        seg = segment('s2', None, [target('B')])
        del seg['parent_segment_id']
        report = run([seg], 's2')
        self.undetermined(report)
        self.assertTrue(any('parent_segment_id is absent' in note for note in report['missing_evidence']))
        self.assertEqual(report['proved_true_unique']['count'], 0)                       # the unknown parent may have consumed B
        self.assertEqual([row['eligible_increment'] for row in report['per_segment']], [None])
        self.assertEqual(report['unresolved_after_coverage_gap'], [['B', 'text', 0]])
        self.assertEqual(run([segment('s2', None, [target('B')])], 's2')['eligible_unique_total'], 1)   # an explicit null is a genesis

    def test_r2_an_absent_budget_unit_is_undetermined(self):
        for unit in (None, '', '  '):
            report = run([segment('s1', None, [target('A')], unit=unit)], 's1')
            self.undetermined(report)
            self.assertTrue(any('budget_unit_id' in note for note in report['missing_evidence']), repr(unit))
        seg = segment('s1', None, [target('A')])
        del seg['budget_unit_id']
        self.undetermined(run([seg], 's1'))

    def test_r3_an_earlier_unknown_coverage_segment_leaves_later_first_occurrences_unresolved(self):
        unknown_first = segment('s1', None, None, missing=['text loss masks'])
        later = segment('s2', 's1', [target('A'), target('B')])
        report = run([unknown_first, later], 's2')
        self.undetermined(report)
        self.assertEqual(report['proved_true_unique']['count'], 0)
        self.assertEqual([row['eligible_increment'] for row in report['per_segment']], [None, None])
        self.assertEqual(report['unresolved_after_coverage_gap'], [['A', 'text', 0], ['B', 'text', 0]])

    def test_r3_coverage_known_before_the_gap_keeps_its_proved_credit_under_its_own_name(self):
        report = run([segment('s1', None, [target('A')]), segment('s2', 's1', None, missing=['masks']),
                      segment('s3', 's2', [target('A'), target('B')])], 's3')
        self.undetermined(report)
        self.assertEqual(report['proved_true_unique'], {'count': 1, 'buckets': {HUMAN: 1, AI: 0, MIXED: 0, UNKNOWN: 0}, 'complete': False})
        self.assertEqual([row['eligible_increment'] for row in report['per_segment']], [1, None, None])

    def test_r4_condition_evidence_must_be_the_boolean_true_or_the_string_true(self):
        for unsupported in (1, 1.0, 'true', 'yes', [], {}, 'TRUE '):
            report = run([segment('s1', None, [target('A', rights_provenance_ok=unsupported)])], 's1')
            self.undetermined(report)
            self.assertTrue(any('rights_provenance_ok' in note for note in report['missing_evidence']), repr(unsupported))
        self.assertEqual(run([segment('s1', None, [target('A', rights_provenance_ok='TRUE')])], 's1')['eligible_unique_total'], 1)
        self.assertEqual(run([segment('s1', None, [target('A', protected_clear='FALSE')])], 's1')['eligible_unique_total'], 0)

    def test_r4_the_origin_bucket_must_be_one_of_the_four_names(self):
        for bad in ('human', 1, True, ['HUMAN_SOURCE_EVIDENCED']):
            t = target('A')
            t['origin_bucket'] = bad
            self.undetermined(run([segment('s1', None, [t])], 's1'))

    def test_deliberate_red_treating_absent_evidence_as_a_known_exclusion_gives_a_determined_zero(self):
        def pre_repair_counter(segments):   # absent mask -> "masked input"; absent flag -> "excluded"; absent parent -> genesis
            seen, total = set(), 0
            for seg in segments:
                if seg.get('published') is not True or seg.get('advanced_head') is not True:
                    continue
                for t in seg['targets']:
                    if t.get('positive_loss') is not True or tuple(t['key']) in seen:
                        continue
                    seen.add(tuple(t['key']))
                    total += 1
            return ('DETERMINED', total)

        unknown = target('A')
        del unknown['positive_loss']
        segments = [segment('s1', None, [unknown]), segment('s2', 's1', [target('A')])]
        self.assertEqual(pre_repair_counter(segments), ('DETERMINED', 1))   # the defect: a replay mints fresh credit after an unknown original
        report = run(segments, 's2')
        self.undetermined(report)                                          # the repaired accounting: UNDETERMINED, no credit
        self.assertEqual(report['proved_true_unique']['count'], 0)


class ExposureAndPhysicalTotalsAreKnownOrNullTests(unittest.TestCase):
    """Kai 64227 S2/S3: a total is a number only when every contributing piece of evidence is known. Otherwise it is None and the known
    part is an explicitly incomplete subtotal; an already-seen target with an unknown mask never leaves the status determined; a
    missing position count is unknown (never int(x or 0)) and a non-integer one is refused."""

    def test_complete_evidence_keeps_the_numbers_and_marks_them_complete(self):
        report = run([segment('s1', None, [target('A'), target('B')], positions=700),
                      segment('s2', 's1', [target('B')], positions=300)], 's2')
        self.assertEqual((report['status'], report['eligible_unique_total']), ('DETERMINED', 2))
        self.assertEqual((report['applied_loss_target_exposure'], report['physical_positions']), (3, 1000))
        self.assertEqual(report['applied_loss_target_exposure_known_subtotal'], {'count': 3, 'complete': True})
        self.assertEqual(report['physical_positions_known_subtotal'], {'count': 1000, 'complete': True, 'missing': []})
        self.assertEqual([row['exposure'] for row in report['per_segment']], [2, 1])

    def test_s2_an_already_seen_target_with_an_unknown_mask_is_never_determined_and_has_no_numeric_exposure(self):
        unknown = target('A')
        del unknown['positive_loss']
        report = run([segment('s1', None, [target('A')]), segment('s2', 's1', [unknown])], 's2')
        self.assertEqual(report['status'], 'UNDETERMINED')
        self.assertIsNone(report['eligible_unique_total'])
        self.assertIsNone(report['applied_loss_target_exposure'])
        self.assertEqual(report['applied_loss_target_exposure_known_subtotal'], {'count': 1, 'complete': False})
        self.assertEqual(report['proved_true_unique']['count'], 1)                      # the credit proved before the gap stays visible
        self.assertFalse(report['proved_true_unique']['complete'])
        self.assertTrue(any('already-seen' in note for note in report['missing_evidence']))
        self.assertEqual([row['exposure'] for row in report['per_segment']], [1, None])
        self.assertEqual([row['exposure_known_subtotal'] for row in report['per_segment']], [1, 0])

    def test_s2_missing_target_coverage_leaves_exposure_unknown_with_an_incomplete_subtotal(self):
        report = run([segment('s1', None, [target('A')]), segment('s2', 's1', None, missing=['text loss masks'])], 's2')
        self.assertIsNone(report['applied_loss_target_exposure'])
        self.assertEqual(report['applied_loss_target_exposure_known_subtotal'], {'count': 1, 'complete': False})
        self.assertEqual([row['exposure'] for row in report['per_segment']], [1, None])

    def test_s2_a_missing_ancestor_link_leaves_exposure_unknown(self):
        report = run([segment('s2', 's1', [target('B')])], 's2')                        # s1 was never supplied
        self.assertIsNone(report['applied_loss_target_exposure'])
        self.assertEqual(report['applied_loss_target_exposure_known_subtotal'], {'count': 1, 'complete': False})

    def test_s2_absent_publication_flags_leave_exposure_unknown(self):
        seg = segment('s1', None, [target('A')])
        del seg['published']
        report = run([seg], 's1')
        self.assertIsNone(report['applied_loss_target_exposure'])
        self.assertEqual(report['applied_loss_target_exposure_known_subtotal'], {'count': 0, 'complete': False})
        self.assertEqual([row['exposure'] for row in report['per_segment']], [None])

    def test_deliberate_red_s2_the_pre_repair_accounting_reports_a_determined_numeric_exposure_for_kais_case(self):
        def pre_repair(segments):       # an already-seen target with an absent mask was skipped silently: determined, numeric
            seen, exposure, credit = set(), 0, 0
            for seg in segments:
                for t in seg['targets']:
                    key = tuple(t['key'])
                    if t.get('positive_loss') is False:
                        continue
                    if t.get('positive_loss') is not True:
                        if key not in seen:
                            seen.add(key)
                        continue
                    exposure += 1
                    if key not in seen:
                        seen.add(key)
                        credit += 1
            return ('DETERMINED', credit, exposure)

        unknown = target('A')
        del unknown['positive_loss']
        segments = [segment('s1', None, [target('A')]), segment('s2', 's1', [unknown, target('B')])]
        self.assertEqual(pre_repair(segments), ('DETERMINED', 2, 2))                    # the defect: numeric exposure, status determined
        report = run(segments, 's2')
        self.assertEqual(report['status'], 'UNDETERMINED')                              # the repaired accounting
        self.assertIsNone(report['applied_loss_target_exposure'])
        self.assertEqual(report['applied_loss_target_exposure_known_subtotal'], {'count': 2, 'complete': False})

    def test_s3_a_missing_position_count_is_unknown_not_zero_and_eligible_accounting_is_preserved(self):
        seg = segment('s1', None, [target('A')])
        del seg['applied_positions']
        report = run([seg], 's1')
        self.assertIsNone(report['physical_positions'])
        self.assertEqual(report['physical_positions_known_subtotal']['count'], 0)
        self.assertFalse(report['physical_positions_known_subtotal']['complete'])
        self.assertTrue(any("'s1'" in note or 's1:' in note for note in report['physical_positions_known_subtotal']['missing']))
        self.assertIsNone(report['per_segment'][0]['applied_positions'])
        self.assertEqual((report['status'], report['eligible_unique_total']), ('DETERMINED', 1))   # eligible-unique is untouched

    def test_s3_a_known_physical_subtotal_is_labelled_incomplete_when_a_later_segment_lacks_positions(self):
        later = segment('s2', 's1', [target('B')])
        del later['applied_positions']
        report = run([segment('s1', None, [target('A')], positions=1000), later], 's2')
        self.assertIsNone(report['physical_positions'])
        self.assertEqual({k: report['physical_positions_known_subtotal'][k] for k in ('count', 'complete')},
                         {'count': 1000, 'complete': False})

    def test_s3_a_missing_ancestor_link_makes_the_physical_total_incomplete(self):
        report = run([segment('s2', 's1', [target('B')], positions=500)], 's2')
        self.assertIsNone(report['physical_positions'])
        self.assertEqual(report['physical_positions_known_subtotal']['count'], 500)
        self.assertFalse(report['physical_positions_known_subtotal']['complete'])

    def test_s3_a_non_integer_or_negative_position_count_is_refused_and_a_known_zero_is_zero(self):
        for bad in (True, False, 1000.0, 1000.9, '1000', -1, [], {}):
            with self.assertRaisesRegex(ca.AccountingRefusal, 'nonnegative integer', msg=repr(bad)):
                run([segment('s1', None, [target('A')], positions=bad)], 's1')
        report = run([segment('s1', None, [target('A')], positions=0)], 's1')
        self.assertEqual((report['physical_positions'], report['physical_positions_known_subtotal']['complete']), (0, True))

    def test_deliberate_red_s3_the_pre_repair_coercion_turns_absent_and_fractional_counts_into_numbers(self):
        def pre_repair(value):          # int(x or 0): None -> 0, 1000.9 -> 1000, '12' -> 12, False -> 0
            return int(value or 0)

        self.assertEqual((pre_repair(None), pre_repair(1000.9), pre_repair('12'), pre_repair(False)), (0, 1000, 12, 0))
        absent = segment('s1', None, [target('A')])
        del absent['applied_positions']
        self.assertIsNone(run([absent], 's1')['physical_positions'])                    # the repaired accounting: unknown, not 0
        with self.assertRaises(ca.AccountingRefusal):
            run([segment('s1', None, [target('A')], positions=1000.9)], 's1')           # and not silently floored to 1000


if __name__ == '__main__':
    unittest.main()
