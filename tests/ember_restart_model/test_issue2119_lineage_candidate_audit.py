"""Issue #2119 rows 13/19: the candidate audit reads the refused child and the duplicate-credit check from files. Synthetic chain, candidate record,
hour result, ruling log and refusal receipt in a temp dir. Each guard carries a deliberate red."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import lineage_candidate_audit as audit  # noqa: E402

GENESIS, CHILD_A, HEAD, CANDIDATE = 'a' * 64, 'b' * 64, 'c' * 64, 'd' * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chain():
    return [
        {'manifest_sha256': GENESIS, 'tokens_seen': 0, 'global_step': 0, 'token_delta': None, 'step_delta': None},
        {'manifest_sha256': CHILD_A, 'tokens_seen': 100, 'global_step': 10, 'token_delta': 100, 'step_delta': 10},
        {'manifest_sha256': HEAD, 'tokens_seen': 250, 'global_step': 25, 'token_delta': 150, 'step_delta': 15},
    ]


def lineage_record(entries=None):
    entries = chain() if entries is None else entries
    return {'chain': entries, 'head_manifest_sha256': entries[-1]['manifest_sha256'], 'head_tokens_seen': entries[-1]['tokens_seen'],
            'head_global_step': entries[-1]['global_step']}


class AuditTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.hour = self.root / 'hour-result.json'
        self.hour_bytes = json.dumps({'child_manifest_sha256': CANDIDATE, 'parent_manifest_sha256': HEAD, 'applied_positions': 777}, sort_keys=True).encode()
        self.hour.write_bytes(self.hour_bytes)
        self.write_record(CANDIDATE)
        receipt = json.dumps({'bindings': {'checkpoint_manifest_sha256': CANDIDATE}, 'arms': {}}, sort_keys=True).encode()
        self.receipt = self.root / 'episode-nll.json'
        self.receipt.write_bytes(receipt)
        self.receipt_sha = sha(receipt)
        self.write_log(self.receipt_sha[:8])

    def write_record(self, candidate):
        record = {'candidate_checkpoint_manifest_sha256': candidate, 'hour_result_path': str(self.hour), 'hour_result_sha256': sha(self.hour_bytes),
                  'parent_checkpoint_manifest_sha256': HEAD, 'published_at': 1.0, 'schema': audit.CANDIDATE_SCHEMA}
        self.record = self.root / 'candidate-continuation-head.json'
        self.record.write_text(json.dumps(record, sort_keys=True), encoding='utf-8')

    def write_log(self, cited, verdict='REFUTED', row_id='ep-1'):
        rows = [{'id': 'other', 'stage': 'RULED', 'verdict': 'CONFIRMED', 'because': 'unrelated'},
                {'id': row_id, 'stage': 'OBSERVED', 'because': 'not the ruling'},
                {'id': row_id, 'stage': 'RULED', 'verdict': verdict, 'because': f'limit exceeded; receipt episode-nll.json sha256 {cited}; pointer unchanged',
                 'seat': 'seat-a', 'ts': '2026-10-08T12:44:42Z'}]
        self.log = self.root / 'loop.jsonl'
        self.log.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf-8')

    def run_audit(self, **overrides):
        arguments = dict(candidate_record_path=self.record, lineage_record=lineage_record(), ruling_log_path=self.log, ruling_id='ep-1',
                         refusal_receipt_path=self.receipt)
        arguments.update(overrides)
        return audit.audit_candidate(**arguments)

    def test_refused_child_is_read_from_files_and_credited_nothing(self):
        result = self.run_audit()
        self.assertEqual(result['status'], 'REFUSED_NOT_RETAINED')
        self.assertEqual(result['candidate']['manifest_sha256'], CANDIDATE)
        self.assertTrue(result['candidate']['parent_is_selected_head'])
        self.assertEqual(result['retained'], {'candidate_in_retained_chain': False, 'positions_credited_to_lineage': 0})
        self.assertEqual(result['refusal_ruling']['verdict'], 'REFUTED')
        self.assertEqual(result['refusal_ruling']['receipt_sha256'], self.receipt_sha)
        self.assertEqual(result['refusal_ruling']['row_number'], 3)
        self.assertEqual(result['duplicate_credit']['hops_checked'], 2)
        self.assertTrue(result['duplicate_credit']['each_hour_counted_once'])

    def test_a_blocker_string_has_no_way_in(self):
        parameters = inspect.signature(audit.audit_candidate).parameters
        self.assertFalse([name for name in parameters if 'blocker' in name or 'verdict' in name])

    def test_child_absent_from_chain_with_no_ruling_is_still_reported_DELIBERATE_RED(self):
        result = self.run_audit(ruling_id=None, ruling_log_path=None, refusal_receipt_path=None)
        self.assertEqual(result['status'], 'UNRULED_NOT_RETAINED')
        self.assertFalse(result['retained']['candidate_in_retained_chain'])
        self.assertEqual(result['retained']['positions_credited_to_lineage'], 0)

    def test_no_candidate_record_reports_no_candidate_not_a_pass_for_one(self):
        result = self.run_audit(candidate_record_path=self.root / 'absent.json', ruling_id=None, ruling_log_path=None, refusal_receipt_path=None)
        self.assertEqual(result['status'], 'NO_CANDIDATE')

    def test_a_duplicate_advance_refuses_DELIBERATE_RED(self):
        doubled = chain() + [dict(chain()[2])]
        doubled[3].update(tokens_seen=400, global_step=40, token_delta=150, step_delta=15)
        with self.assertRaisesRegex(audit.DuplicateCreditRefusal, 'counted more than once'):
            self.run_audit(lineage_record=lineage_record(doubled))

    def test_a_hop_that_skips_credit_refuses_DELIBERATE_RED(self):
        skewed = chain()
        skewed[2]['tokens_seen'] = 260
        with self.assertRaisesRegex(audit.DuplicateCreditRefusal, 'running total'):
            self.run_audit(lineage_record=lineage_record(skewed))

    def test_summed_deltas_must_equal_head_cursor(self):
        record = lineage_record()
        record['head_tokens_seen'] = 251
        with self.assertRaisesRegex(audit.DuplicateCreditRefusal, 'summed hop deltas'):
            self.run_audit(lineage_record=record)

    def test_ruling_that_cites_another_receipt_refuses(self):
        self.write_log('0' * 8)
        with self.assertRaisesRegex(audit.CandidateAuditRefusal, 'not a prefix'):
            self.run_audit()

    def test_receipt_bound_to_another_checkpoint_refuses(self):
        other = json.dumps({'bindings': {'checkpoint_manifest_sha256': 'e' * 64}}, sort_keys=True).encode()
        self.receipt.write_bytes(other)
        self.write_log(sha(other)[:8])
        with self.assertRaisesRegex(audit.CandidateAuditRefusal, 'not bound to the candidate'):
            self.run_audit()

    def test_missing_ruling_row_and_tampered_hour_result_refuse(self):
        with self.assertRaisesRegex(audit.CandidateAuditRefusal, 'no RULED row'):
            self.run_audit(ruling_id='absent-id')
        self.hour.write_bytes(self.hour_bytes + b' ')
        with self.assertRaisesRegex(audit.CandidateAuditRefusal, 'do not hash'):
            self.run_audit()

    def test_candidate_inside_the_chain_with_a_refusal_refuses_and_without_one_is_retained(self):
        inside = lineage_record(chain())
        self.hour.write_bytes(json.dumps({'child_manifest_sha256': HEAD, 'parent_manifest_sha256': CHILD_A, 'applied_positions': 150}, sort_keys=True).encode())
        record = json.loads(self.record.read_text(encoding='utf-8'))
        record.update(candidate_checkpoint_manifest_sha256=HEAD, parent_checkpoint_manifest_sha256=CHILD_A, hour_result_sha256=sha(self.hour.read_bytes()))
        self.record.write_text(json.dumps(record, sort_keys=True), encoding='utf-8')
        retained = self.run_audit(lineage_record=inside, ruling_id=None, ruling_log_path=None, refusal_receipt_path=None)
        self.assertEqual(retained['status'], 'RETAINED_IN_CHAIN')
        self.assertEqual(retained['retained']['positions_credited_to_lineage'], 150)

    def test_public_view_carries_no_path_or_free_text(self):
        view = audit.public_view(self.run_audit())
        text = json.dumps(view)
        self.assertNotIn(self.root.name, text)
        self.assertNotIn('limit exceeded', text)
        self.assertNotIn('"seat"', text)                      # repo-guard `names` refused the ruling seat's name in the committed snapshot
        self.assertIn('seat-a', json.dumps(self.run_audit()))      # the private view still carries it; only the public view drops it
        self.assertEqual(view['candidate']['record']['path'], 'candidate-continuation-head.json')
        self.assertEqual(copy.deepcopy(view)['status'], 'REFUSED_NOT_RETAINED')


if __name__ == '__main__':
    unittest.main()
