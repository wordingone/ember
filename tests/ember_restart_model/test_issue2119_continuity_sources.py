"""Issue #2119 row 7 (producer side): the GPU owner, last measurement and training-hold sources behind the continuity status.

Ruling 71916: the GPU owner is the window marker's line 2 when the marker exists, else the process census; 'free' only when BOTH show nothing; UNKNOWN when the
census fails. A missing source reads UNKNOWN with its reason, never blank, never a value carried from another head. Deliberate reds: an unreadable census must
not read free, a receipt for another head must not read measured, and an absent hold record must not read 'not postponed'.
The census is injected; no test starts a process or touches a GPU.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import continuity_sources as sources  # noqa: E402
import training_continuity_status as status  # noqa: E402

HEAD, OTHER = 'a' * 64, 'b' * 64
HOLD_REASON = ('training hold since 2026-10-08 8:00 AM LA: no card run unless a named deliverable needs it (operator Discord 1557407154787328085)')


def census_empty():
    return []


def census_holder():
    return [{'pid': 4242, 'entry_point': 'cia_hour.py'}]


def census_fails():
    raise RuntimeError('powershell not reachable')


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text if isinstance(text, str) else json.dumps(text), encoding='utf-8')
        return path


class GpuOwnerTests(SourceFixture):
    def test_marker_line_two_names_the_owner_and_purpose(self):
        marker = self.write('gpu-window-open', '2026-10-08T19:00:00Z\nseat-a: governed probe hour\n')
        out = sources.gpu_owner(marker, census_empty)
        self.assertEqual((out['status'], out['owner'], out['training_job_purpose']), ('held', 'seat-a', 'governed probe hour'))

    def test_marker_wins_over_the_census(self):
        marker = self.write('gpu-window-open', '2026-10-08T19:00:00Z\nseat-a: governed probe hour\n')
        self.assertEqual(sources.gpu_owner(marker, census_fails)['owner'], 'seat-a')    # the census is not even needed

    def test_free_only_when_both_the_marker_and_the_census_show_nothing(self):
        self.assertEqual(sources.gpu_owner(self.root / 'absent', census_empty), {'status': 'free'})

    def test_no_marker_but_a_trainer_process_is_held_by_the_census(self):
        out = sources.gpu_owner(self.root / 'absent', census_holder)
        self.assertEqual((out['status'], out['owner']), ('held', 'process census'))
        self.assertIn('4242', out['training_job_purpose'])

    def test_a_failing_census_is_unknown_never_free_DELIBERATE_RED(self):
        out = sources.gpu_owner(self.root / 'absent', census_fails)
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertIn('census failed', out['reason'])

    def test_a_marker_without_an_owner_line_is_unknown_not_free(self):
        marker = self.write('gpu-window-open', '2026-10-08T19:00:00Z\n')
        self.assertEqual(sources.gpu_owner(marker, census_empty)['status'], 'UNKNOWN')

    def test_a_blank_line_two_is_unknown_never_the_third_line_owner_DELIBERATE_RED(self):
        for text in ('2026-10-08T19:00:00Z\n\nseat-b: not the owner\n', '2026-10-08T19:00:00Z\n   \nseat-b: not the owner\n'):
            out = sources.gpu_owner(self.write('gpu-window-open', text), census_empty)
            self.assertEqual(out['status'], 'UNKNOWN', text)
            self.assertIn('line 2', out['reason'])

    def test_no_marker_path_at_all_is_unknown(self):
        self.assertEqual(sources.gpu_owner(None, census_empty)['status'], 'UNKNOWN')

    def test_an_unreadable_python_command_line_is_unknown_never_free_DELIBERATE_RED(self):
        for rows in ([{'ProcessId': 7, 'CommandLine': None}], {'ProcessId': 7, 'CommandLine': ''}, [{'ProcessId': 7}, {'ProcessId': 8, 'CommandLine': 'python other.py'}]):
            out = sources.gpu_owner(self.root / 'absent', lambda rows=rows: sources.trainers_in_rows(rows))
            self.assertEqual(out['status'], 'UNKNOWN', rows)
            self.assertIn('could not read the command line', out['reason'])

    def test_readable_command_lines_still_read_free_or_held(self):
        free = [{'ProcessId': 7, 'CommandLine': 'python other.py'}]
        self.assertEqual(sources.gpu_owner(self.root / 'absent', lambda: sources.trainers_in_rows(free)), {'status': 'free'})
        held = free + [{'ProcessId': 9, 'CommandLine': 'python -B cia_hour.py --x'}, {'ProcessId': 11, 'CommandLine': None}]   # a known holder wins over an unreadable row
        out = sources.gpu_owner(self.root / 'absent', lambda: sources.trainers_in_rows(held))
        self.assertEqual((out['status'], out['owner']), ('held', 'process census'))
        self.assertIn('9', out['training_job_purpose'])

    def test_a_census_that_returns_no_list_is_unknown(self):
        self.assertEqual(sources.gpu_owner(self.root / 'absent', lambda: sources.trainers_in_rows('garbage'))['status'], 'UNKNOWN')


class MeasurementTests(SourceFixture):
    def receipt(self, head=HEAD, **over):
        body = {'schema': sources.SCORE_SCHEMA, 'label': 'scorer-v12', 'finished_utc': '2026-10-08T18:00:00Z',
                'bindings': {'checkpoint_manifest_sha256': head, 'episode_plan_sha256': '9' * 64},
                'arms': {'fresh': {'episodes': 2, 'mean_nll': 4.5, 'per_episode': [{'loss_sum': 4608.0, 'targets': 1024}, {'loss_sum': 4608.0, 'targets': 1024}]}}}
        body.update(over)
        return self.write('episode-nll-H34.json', body)

    def test_a_receipt_for_exactly_this_head_is_measured_with_its_time_and_hash(self):
        out = sources.last_measurement_from_receipt(self.receipt(), HEAD)
        self.assertEqual(out['status'], 'measured')
        self.assertEqual((out['measurement']['measured_at'], out['measurement']['receipt']), ('2026-10-08T18:00:00Z', 'episode-nll-H34.json'))
        self.assertEqual(len(out['measurement']['receipt_sha256']), 64)

    def test_a_receipt_for_another_head_is_unknown_never_carried_forward_DELIBERATE_RED(self):
        out = sources.last_measurement_from_receipt(self.receipt(head=OTHER), HEAD)
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertIn('different checkpoint', out['reason'])

    def test_missing_unreadable_or_wrong_schema_is_unknown_with_a_reason(self):
        for receipt in (None, self.root / 'absent.json', self.write('bad.json', 'not json'), self.receipt(schema='other')):
            out = sources.last_measurement_from_receipt(receipt, HEAD)
            self.assertEqual(out['status'], 'UNKNOWN', receipt)
            self.assertTrue(out['reason'])

    def test_a_header_with_the_right_head_but_no_scores_is_unknown_never_measured_DELIBERATE_RED(self):
        fresh = {'episodes': 2, 'mean_nll': 4.5, 'per_episode': [{}, {}]}
        for name, arms in (('no arms', None), ('no fresh arm', {}), ('zero episodes', {'fresh': dict(fresh, episodes=0)}), ('no mean', {'fresh': dict(fresh, mean_nll=None)}),
                           ('nan mean', {'fresh': dict(fresh, mean_nll=float('nan'))}), ('bool episodes', {'fresh': dict(fresh, episodes=True)}),
                           ('rows differ from episodes', {'fresh': dict(fresh, per_episode=[{}])})):
            body = {'schema': sources.SCORE_SCHEMA, 'label': 'scorer-v12', 'finished_utc': '2026-10-08T18:00:00Z',
                    'bindings': {'checkpoint_manifest_sha256': HEAD, 'episode_plan_sha256': '9' * 64}}
            if arms is not None:
                body['arms'] = arms
            out = sources.last_measurement_from_receipt(self.write('headeronly.json', json.dumps(body, allow_nan=True)), HEAD)
            self.assertEqual(out['status'], 'UNKNOWN', name)
            self.assertIn('carries no scores', out['reason'], name)

    def test_no_finish_time_is_unknown(self):
        self.assertEqual(sources.last_measurement_from_receipt(self.receipt(finished_utc='yesterday'), HEAD)['status'], 'UNKNOWN')


class HoldTests(SourceFixture):
    def hold(self, **over):
        body = {'schema': sources.HOLD_SCHEMA, 'since': '2026-10-08T15:00:00Z', 'reason': HOLD_REASON, 'source': 'Discord 1557407154787328085'}
        body.update(over)
        return self.write('training-hold.json', body)

    def test_a_hold_record_renders_the_reason_since_and_its_source(self):
        out = sources.postponement_from_hold(self.hold())
        self.assertIs(out['postponed'], True)
        for part in (HOLD_REASON, '2026-10-08T15:00:00Z', '1557407154787328085'):
            self.assertIn(part, out['postponement_reason'])

    def test_an_absent_hold_record_is_unknown_not_unpostponed_DELIBERATE_RED(self):
        out = sources.postponement_from_hold(self.root / 'absent.json')
        self.assertEqual(out['postponed'], 'UNKNOWN')
        self.assertTrue(out['postponement_reason'])

    def test_no_path_unreadable_or_open_schema_is_unknown(self):
        for hold in (None, self.write('bad.json', '{'), self.hold(schema='x'), self.hold(source=''), self.hold(since='soon'), self.hold(reason=' ')):
            self.assertEqual(sources.postponement_from_hold(hold)['postponed'], 'UNKNOWN', hold)


class StatusWiringTests(SourceFixture):
    def call(self, **extra):
        hour_result = {'child_manifest_sha256': HEAD, 'parent_manifest_sha256': 'p' * 64, 'applied_positions': 8}
        lineage = {'schema': status.LINEAGE_SCHEMA, 'head_manifest_sha256': HEAD, 'genesis_manifest_sha256': 'g' * 64, 'depth': 1,
                   'cumulative_applied_token_delta': 8, 'cumulative_step_delta': 1}
        return status.training_continuity_status(custody_parent=self.root, hour_result=hour_result, lineage_record=lineage, current_identity=None,
                                                 measurement=None, next_blocker='training hold', **extra)

    def test_without_producer_sections_the_older_vocabulary_is_unchanged(self):
        record = self.call()
        self.assertEqual(record['gpu_owner'], {'status': 'not_reported'})
        self.assertEqual(record['learning_measurement'], {'status': 'pending'})
        self.assertNotIn('postponed', record['diagnostic_allowance'])

    def test_producer_sections_replace_the_older_ones(self):
        record = self.call(gpu_owner={'status': 'free'}, measurement_section=sources.unknown('no receipt'),
                           postponement={'postponed': True, 'postponement_reason': HOLD_REASON})
        self.assertEqual(record['gpu_owner'], {'status': 'free'})
        self.assertEqual(record['learning_measurement']['status'], 'UNKNOWN')
        self.assertEqual(record['diagnostic_allowance']['postponement_reason'], HOLD_REASON)
        self.assertIn('postponement_seconds', record['diagnostic_allowance'])      # the ledger-derived numbers are still there

    def test_a_producer_section_and_its_older_input_together_are_refused(self):
        with self.assertRaises(ValueError):
            self.call(gpu_owner={'status': 'free'}, gpu_lease={'owner': 'x'})


if __name__ == '__main__':
    unittest.main()
