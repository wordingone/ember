"""Issue #2119 row 8: the continuity page renders the committed continuity snapshot, and the snapshot producer reports staleness.

Each test names a requirement of the closing artifact: a page whose block differs from the render of the snapshot is stale; an
unknown key, a non-hex digest or a negative count refuses at load; an undefined claim budget renders its missing-predicate text and
never a number; the lineage-wide retained positions are not the last hour's (deliberate red: the master bug of printing the last hour
as the retained total); a snapshot whose head is not the live head is reported stale; the snapshot and the page block exist together
or not at all.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
SCRIPTS = ROOT / 'src/ember/governance/scripts'
for entry in (str(TOOLS), str(SCRIPTS), str(ROOT / 'src')):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import continuity_snapshot as producer  # noqa: E402
import training_continuity_status as status_module  # noqa: E402

_spec = importlib.util.spec_from_file_location('bound_gen_readme_status', SCRIPTS / 'gen_readme_status.py')
page = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = page
_spec.loader.exec_module(page)

H1, H2, H3 = 'a' * 64, 'b' * 64, 'c' * 64
NO_CANDIDATE_AUDIT = {'schema': 'ember-lineage-candidate-audit-v1', 'status': 'NO_CANDIDATE', 'candidate': None, 'retained': None,
                      'refusal_ruling': None, 'duplicate_credit': {'hops_checked': 2, 'distinct_manifests': 3, 'each_hour_counted_once': True,
                                                                   'summed_token_delta': 3000, 'summed_step_delta': 30}}


def status_dict(*, retained=3000, last_hour=1000, head=H3):
    """Built from the real section functions of the status producer, so a key change there fails the loader here."""
    lineage_record = {'schema': status_module.LINEAGE_SCHEMA, 'depth': 3, 'genesis_manifest_sha256': H1, 'head_manifest_sha256': head,
                      'cumulative_applied_token_delta': retained, 'cumulative_step_delta': 30}
    hour_result = {'child_manifest_sha256': head, 'parent_manifest_sha256': H2, 'applied_positions': last_hour}
    return {
        'schema': status_module.STATUS_SCHEMA,
        'lineage_checkpoint_manifest_sha256': head,
        'lineage': status_module.lineage_status(lineage_record),
        'claim_budget_eligible': status_module.claim_budget_eligible_status(None),
        'gpu_owner': status_module.gpu_owner_status({'owner': 'seat-a', 'run_id': 'r9', 'training_job_purpose': 'DIAGNOSTIC'}),
        'checkpoint': status_module.selected_checkpoint_status(hour_result),
        'learning_measurement': status_module.last_learning_measurement_status(None),
        'purpose': status_module.current_purpose_status({'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'r9'}),
        'diagnostic_allowance': {'diagnostic_occupancy_seconds': 600, 'max_diagnostic_occupancy_seconds': 3600,
                                 'postponement_seconds': 0, 'max_postponement_seconds': 7200, 'at_occupancy_limit': False,
                                 'at_postponement_limit': False},
        'next_segment': status_module.next_segment_status(blocker='no pending-continuation record'),
    }


def snapshot_dict(**kw):
    return producer.build_snapshot(status_dict(**kw), candidate_audit=NO_CANDIDATE_AUDIT, captured_at='2026-10-06T20:00:00Z')


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, snapshot, name='snapshot.json'):
        path = self.dir / name
        path.write_text(json.dumps(snapshot), encoding='utf-8')
        return path


class LoaderTests(Base):
    def test_a_valid_snapshot_loads_and_the_two_schema_constants_agree(self):
        self.assertEqual(page.load_continuity_status(self.write(snapshot_dict()))['head_manifest_sha256'], H3)
        self.assertEqual(page.CONTINUITY_STATUS_SCHEMA, status_module.STATUS_SCHEMA)
        self.assertEqual(page.CONTINUITY_SNAPSHOT_SCHEMA, producer.SNAPSHOT_SCHEMA)
        self.assertEqual(producer.STATUS_SCHEMA, status_module.STATUS_SCHEMA)

    def test_an_unknown_key_refuses_at_every_level(self):
        for mutate in (lambda s: s.update(extra=1), lambda s: s['status'].update(extra=1),
                       lambda s: s['status']['lineage'].update(extra=1), lambda s: s['status']['checkpoint'].update(extra=1),
                       lambda s: s['status']['next_segment'].update(extra=1)):
            snap = snapshot_dict()
            mutate(snap)
            with self.assertRaises(ValueError):
                page.load_continuity_status(self.write(snap))

    def test_a_non_hex_digest_refuses(self):
        for path in (('head_manifest_sha256',), ('status', 'lineage_checkpoint_manifest_sha256'), ('status', 'checkpoint', 'child_manifest_sha256'),
                     ('status', 'checkpoint', 'parent_manifest_sha256'), ('status', 'lineage', 'genesis_manifest_sha256')):
            snap = snapshot_dict()
            target = snap
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = 'NOT-HEX'
            with self.assertRaises(ValueError, msg=str(path)):
                page.load_continuity_status(self.write(snap))

    def test_a_negative_or_non_integer_count_refuses(self):
        for name in ('retained_applied_positions', 'retained_global_steps', 'depth'):
            for bad in (-1, 1.5, True, '3'):
                snap = snapshot_dict()
                snap['status']['lineage'][name] = bad
                with self.assertRaises(ValueError, msg=f'{name}={bad!r}'):
                    page.load_continuity_status(self.write(snap))
        snap = snapshot_dict()
        snap['status']['checkpoint']['last_hour_applied_positions'] = -5
        with self.assertRaises(ValueError):
            page.load_continuity_status(self.write(snap))

    def test_a_head_that_differs_from_the_status_lineage_refuses(self):
        snap = snapshot_dict()
        snap['head_manifest_sha256'] = H1
        with self.assertRaises(ValueError):
            page.load_continuity_status(self.write(snap))

    def test_a_checkpoint_child_that_differs_from_the_wrapper_and_lineage_head_refuses(self):
        # review finding on the renderer PR: the loader bound the wrapper head to the lineage head but not to checkpoint.child_manifest_sha256
        snap = snapshot_dict()
        snap['status']['checkpoint']['child_manifest_sha256'] = H1
        with self.assertRaisesRegex(ValueError, 'status checkpoint child'):
            page.load_continuity_status(self.write(snap))

    def test_non_finite_numbers_refuse_anywhere_in_the_snapshot(self):
        # json.load accepts NaN / Infinity by default; both the diagnostic seconds and a measurement payload must refuse them
        for token in ('NaN', 'Infinity', '-Infinity'):
            text = json.dumps(snapshot_dict()).replace('"diagnostic_occupancy_seconds": 600', f'"diagnostic_occupancy_seconds": {token}')
            self.assertIn(token, text)
            path = self.dir / 'nonfinite.json'
            path.write_text(text, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'non-finite'):
                page.load_continuity_status(path)
        measured = snapshot_dict()
        measured['status']['learning_measurement'] = {'status': 'measured', 'measurement': {'nll': 'PLACEHOLDER'}}
        path = self.dir / 'measured-nan.json'
        path.write_text(json.dumps(measured).replace('"PLACEHOLDER"', 'NaN'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            page.load_continuity_status(path)

    def test_ordinary_overflow_literals_refuse_in_the_measurement_and_the_allowance(self):
        # 1e999 is plain JSON, not a NaN/Infinity token: json.load turns it into float('inf') without calling parse_constant,
        # so without parse_float the measurement block would render Infinity
        for literal in ('1e999', '-1e999', '1E+400'):
            measured = snapshot_dict()
            measured['status']['learning_measurement'] = {'status': 'measured', 'measurement': {'nll': 'PLACEHOLDER'}}
            path = self.dir / 'measured-overflow.json'
            path.write_text(json.dumps(measured).replace('"PLACEHOLDER"', literal), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'non-finite'):
                page.load_continuity_status(path)
            text = json.dumps(snapshot_dict()).replace('"diagnostic_occupancy_seconds": 600', f'"diagnostic_occupancy_seconds": {literal}')
            self.assertIn(literal, text)
            path.write_text(text, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'non-finite'):
                page.load_continuity_status(path)
        # control: a large but finite literal still loads
        finite = snapshot_dict()
        finite['status']['learning_measurement'] = {'status': 'measured', 'measurement': {'nll': 'PLACEHOLDER'}}
        path = self.dir / 'measured-finite.json'
        path.write_text(json.dumps(finite).replace('"PLACEHOLDER"', '1e300'), encoding='utf-8')
        self.assertEqual(page.load_continuity_status(path)['status']['learning_measurement']['measurement']['nll'], 1e300)

    def test_a_malformed_captured_at_or_schema_refuses(self):
        for field, value in (('captured_at', 'yesterday'), ('schema_version', 'x')):
            snap = snapshot_dict()
            snap[field] = value
            with self.assertRaises(ValueError):
                page.load_continuity_status(self.write(snap))


class RenderTests(Base):
    def render(self, **kw):
        return page.render_continuity_status_block(page.load_continuity_status(self.write(snapshot_dict(**kw))))

    def test_an_undefined_claim_budget_renders_its_missing_text_and_never_a_number(self):
        block = self.render()
        self.assertIn('**UNDEFINED**', block)
        self.assertIn(status_module.CLAIM_PREDICATE_MISSING, block)
        claim_line = [line for line in block.splitlines() if line.startswith('- Claim-budget-eligible')][0]
        self.assertNotRegex(claim_line.split('missing:')[0], r'`\d')

    def test_an_undetermined_claim_budget_never_shows_a_number_and_a_measured_one_shows_its_total(self):
        snap = snapshot_dict()
        snap['status']['claim_budget_eligible'] = {'status': 'UNDETERMINED', 'missing': 'per-target identities and loss masks'}
        block = page.render_continuity_status_block(page.load_continuity_status(self.write(snap)))
        self.assertIn('**UNDETERMINED**', block)
        snap['status']['claim_budget_eligible'] = {'status': 'MEASURED', 'eligible_unique_total': 17}
        block = page.render_continuity_status_block(page.load_continuity_status(self.write(snap)))
        self.assertIn('`17`', block)

    def test_the_lineage_total_and_the_last_hour_are_printed_separately_and_the_snapshot_time_and_head_are_stated(self):
        block = self.render(retained=3000, last_hour=1000)
        self.assertIn('`3000` positions', block)
        self.assertIn('- Last hour only: `1000` applied positions.', block)
        self.assertIn('2026-10-06T20:00:00Z', block)
        self.assertIn(H3, block)
        self.assertIn('does not claim to be current', block)

    def test_deliberate_red_the_master_bug_prints_the_last_hour_as_the_lineage_total(self):
        def master_renderer(payload):   # the master behaviour: retained positions read from checkpoint.last_hour_applied_positions
            return f"retained `{payload['status']['checkpoint']['last_hour_applied_positions']}` positions"

        payload = page.load_continuity_status(self.write(snapshot_dict(retained=3000, last_hour=1000)))
        self.assertIn('`1000`', master_renderer(payload))                                  # the bug presents the last hour
        self.assertNotIn('`1000` positions', page.render_continuity_status_block(payload))  # the page prints the walk's total
        self.assertIn('`3000` positions', page.render_continuity_status_block(payload))

    def test_a_blocked_next_segment_and_a_pending_measurement_render_their_text(self):
        block = self.render()
        self.assertIn('Next segment: blocked: no pending-continuation record', block)
        self.assertIn('Last learning measurement: pending.', block)


REAL_CLAIM_SECTION = ROOT / 'tests/fixtures/issue2119_claim_undetermined_step2_9ce44ee9.json'   # claim_budget_eligible of the step-2 readout


class ClaimSectionAndCandidateTests(Base):
    """The loader admits the real UNDETERMINED claim readout under an exact key set, and the candidate audit is closed."""

    def real_claim(self):
        return json.loads(REAL_CLAIM_SECTION.read_text(encoding='utf-8'))

    def snapshot_with(self, claim, head=H3):
        snap = snapshot_dict(head=head)
        claim = copy.deepcopy(claim)
        claim['accounting']['head_segment_id'] = head   # the fixture was minted for the real head; the snapshot here has a synthetic one
        snap['status']['claim_budget_eligible'] = claim
        return snap

    def test_green_the_real_step_2_undetermined_readout_loads_and_renders_without_a_number(self):
        claim = self.real_claim()
        self.assertEqual(claim['status'], 'UNDETERMINED')
        self.assertEqual(claim['predicate_sha256'], '3a2b13004730c3391e136024b2a063bcd1bed2406c18fee44440f04f28841b87')
        self.assertEqual(len(claim['accounting']['missing_evidence']), 97)
        block = page.render_continuity_status_block(page.load_continuity_status(self.write(self.snapshot_with(claim))))
        line = [row for row in block.splitlines() if row.startswith('- Claim-budget-eligible')][0]
        self.assertIn('**UNDETERMINED**', line)
        self.assertIn('`97` missing-evidence items in `3` kinds', line)
        self.assertIn(claim['predicate_sha256'], line)
        self.assertIn('no number is shown', line)

    def test_red_an_unknown_key_in_the_claim_section_still_refuses(self):
        for mutate in (lambda c: c.update(extra=1), lambda c: c.pop('predicate_sha256')):
            claim = self.real_claim()
            mutate(claim)
            with self.assertRaises(ValueError):
                page.load_continuity_status(self.write(self.snapshot_with(claim)))

    def test_an_undetermined_claim_with_a_total_or_without_named_evidence_refuses(self):
        for mutate in (lambda c: c['accounting'].update(eligible_unique_total=5),
                       lambda c: c['accounting'].update(missing_evidence=[]),
                       lambda c: c.update(status='MEASURED')):
            claim = self.real_claim()
            mutate(claim)
            with self.assertRaises(ValueError):
                page.load_continuity_status(self.write(self.snapshot_with(claim)))

    def test_a_claim_accounting_for_another_head_refuses(self):
        snap = self.snapshot_with(self.real_claim())
        snap['status']['claim_budget_eligible']['accounting']['head_segment_id'] = H1
        with self.assertRaises(ValueError):
            page.load_continuity_status(self.write(snap))

    def test_green_a_measured_accounting_claim_loads_and_renders_its_nested_total(self):
        # review of b22b65c9: the loader admitted this shape but the renderer read a top-level total and raised KeyError
        claim = {'status': 'MEASURED', 'predicate_sha256': self.real_claim()['predicate_sha256'],
                 'accounting': {'head_segment_id': H3, 'eligible_unique_total': 12345}}
        block = page.render_continuity_status_block(page.load_continuity_status(self.write(self.snapshot_with(claim))))
        line = [row for row in block.splitlines() if row.startswith('- Claim-budget-eligible')][0]
        self.assertIn('`12345`', line)
        self.assertIn('frozen predicate evaluated', line)

    def refused_audit(self):
        audit = copy.deepcopy(NO_CANDIDATE_AUDIT)
        audit.update(status='REFUSED_NOT_RETAINED',
                     candidate={'manifest_sha256': H1, 'parent_manifest_sha256': H3, 'parent_is_selected_head': True},
                     retained={'candidate_in_retained_chain': False, 'positions_credited_to_lineage': 0},
                     refusal_ruling={'verdict': 'REFUTED', 'row_sha256': H2, 'receipt_sha256': H2})
        return audit

    def test_a_refused_candidate_renders_its_ruling_and_zero_credit_and_the_duplicate_check(self):
        snap = snapshot_dict()
        snap['candidate_audit'] = self.refused_audit()
        block = page.render_continuity_status_block(page.load_continuity_status(self.write(snap)))
        self.assertIn('`REFUSED_NOT_RETAINED`', block)
        self.assertIn('positions credited to the lineage `0`', block)
        self.assertIn('each hour counted once: `true`', block)

    def test_a_candidate_audit_that_contradicts_itself_or_leaks_a_path_refuses(self):
        def credited(a):
            a['retained']['positions_credited_to_lineage'] = 5
        def retained_mismatch(a):
            a['retained']['candidate_in_retained_chain'] = True
        def no_ruling(a):
            a['refusal_ruling'] = None
        def duplicate_failed(a):
            a['duplicate_credit']['each_hour_counted_once'] = False
        def leaks_path(a):
            a['candidate']['record_path'] = 'B:' + chr(92) + 'x' + chr(92) + 'y.json'
        for mutate in (credited, retained_mismatch, no_ruling, duplicate_failed, leaks_path):
            snap = snapshot_dict()
            snap['candidate_audit'] = self.refused_audit()
            mutate(snap['candidate_audit'])
            with self.assertRaises(ValueError, msg=mutate.__name__):
                page.load_continuity_status(self.write(snap))

    def test_deliberate_red_a_truthy_string_flag_or_a_non_integer_credit_refuses(self):
        # review of b22b65c9: 'false' is truthy, so `in_chain is True` and `if not in_chain` both passed a refused candidate with credit 1
        cases = (('false', 1), ('false', 0), (0, 0), (None, 0), (False, True), (False, 1), (False, -1), (False, 0.0), (False, '0'))
        for flag, credit in cases:
            snap = snapshot_dict()
            snap['candidate_audit'] = self.refused_audit()
            snap['candidate_audit']['retained'] = {'candidate_in_retained_chain': flag, 'positions_credited_to_lineage': credit}
            with self.assertRaises(ValueError, msg=repr((flag, credit))):
                page.load_continuity_status(self.write(snap))

    def test_green_strict_flag_and_credit_still_load_for_refused_and_retained_candidates(self):
        snap = snapshot_dict()
        snap['candidate_audit'] = self.refused_audit()
        page.load_continuity_status(self.write(snap))                                   # False / 0 with a REFUTED ruling
        retained = self.refused_audit()
        retained.update(status='RETAINED_IN_CHAIN', retained={'candidate_in_retained_chain': True, 'positions_credited_to_lineage': 150},
                        refusal_ruling=None)
        snap['candidate_audit'] = retained
        block = page.render_continuity_status_block(page.load_continuity_status(self.write(snap)))
        self.assertIn('positions credited to the lineage `150`', block)

    def test_deliberate_red_an_audit_tuple_that_disagrees_with_the_selected_lineage_refuses(self):
        # review of b22b65c9: each_hour_counted_once=true was accepted beside counts that did not reconcile with the selected lineage
        def distinct(a):
            a['duplicate_credit']['distinct_manifests'] = 1
        def hops(a):
            a['duplicate_credit']['hops_checked'] = 0
        def steps(a):
            a['duplicate_credit']['summed_step_delta'] = 29
        def tokens(a):
            a['duplicate_credit']['summed_token_delta'] = 1
        def boolean(a):
            a['duplicate_credit']['distinct_manifests'] = True
        def text(a):
            a['duplicate_credit']['hops_checked'] = '2'
        def parent_flag_lies(a):
            a.update(self.refused_audit())
            a['candidate']['parent_is_selected_head'] = False
        def parent_flag_string(a):
            a.update(self.refused_audit())
            a['candidate']['parent_is_selected_head'] = 'true'
        for mutate in (distinct, hops, steps, tokens, boolean, text, parent_flag_lies, parent_flag_string):
            snap = snapshot_dict()
            snap['candidate_audit'] = copy.deepcopy(NO_CANDIDATE_AUDIT)
            mutate(snap['candidate_audit'])
            with self.assertRaises(ValueError, msg=mutate.__name__):
                page.load_continuity_status(self.write(snap))

    def test_green_an_audit_tuple_that_reconciles_with_the_lineage_loads(self):
        snap = snapshot_dict()
        payload = page.load_continuity_status(self.write(snap))
        duplicate = snap['candidate_audit']['duplicate_credit']
        lineage = snap['status']['lineage']
        self.assertEqual((duplicate['distinct_manifests'], duplicate['hops_checked']), (lineage['depth'], lineage['depth'] - 1))
        self.assertEqual((duplicate['summed_step_delta'], duplicate['summed_token_delta']),
                         (lineage['retained_global_steps'], lineage['retained_applied_positions']))
        self.assertIsNotNone(payload)

    def test_the_audit_schema_constants_agree(self):
        import lineage_candidate_audit
        self.assertEqual(page.CONTINUITY_CANDIDATE_AUDIT_SCHEMA, lineage_candidate_audit.SCHEMA)
        self.assertEqual(page.CONTINUITY_CANDIDATE_AUDIT_STATUSES, set(lineage_candidate_audit.STATUSES))


class PageTests(Base):
    def page_text(self, block='old'):
        return f'intro\n{page.CONTINUITY_BEGIN_MARKER}\n{block}\n{page.CONTINUITY_END_MARKER}\noutro\n'

    def test_a_page_whose_block_differs_from_the_render_of_the_snapshot_is_stale_and_a_regenerated_one_is_current(self):
        path = self.write(snapshot_dict())
        stale = self.page_text('hand edited block')
        regenerated = page.apply_continuity_status(stale, path)
        self.assertNotEqual(regenerated, stale)
        self.assertEqual(page.apply_continuity_status(regenerated, path), regenerated)   # idempotent: current

    def test_a_page_with_neither_snapshot_nor_block_is_untouched(self):
        self.assertEqual(page.apply_continuity_status('plain page\n', self.dir / 'absent.json'), 'plain page\n')

    def test_a_block_without_a_snapshot_and_a_snapshot_without_a_block_both_refuse(self):
        with self.assertRaisesRegex(ValueError, 'snapshot is absent'):
            page.apply_continuity_status(self.page_text(), self.dir / 'absent.json')
        with self.assertRaisesRegex(ValueError, 'no continuity-status block'):
            page.apply_continuity_status('plain page\n', self.write(snapshot_dict()))

    def test_an_invalid_snapshot_refuses_instead_of_rendering(self):
        snap = snapshot_dict()
        snap['status']['lineage']['depth'] = -1
        with self.assertRaisesRegex(ValueError, 'continuity snapshot is invalid'):
            page.apply_continuity_status(self.page_text(), self.write(snap))


class ProducerTests(Base):
    def test_build_and_write_are_deterministic_and_atomic(self):
        out = producer.write_snapshot(self.dir / 'out' / 'snapshot.json', snapshot_dict())
        first = out.read_bytes()
        producer.write_snapshot(out, snapshot_dict())
        self.assertEqual(out.read_bytes(), first)
        self.assertFalse((self.dir / 'out' / 'snapshot.json.tmp').exists())
        self.assertTrue(first.endswith(b'\n') and b'\r' not in first)
        self.assertEqual(json.loads(first)['head_manifest_sha256'], H3)

    def test_a_status_of_another_schema_is_refused(self):
        bad = status_dict()
        bad['schema'] = 'something-else'
        with self.assertRaises(ValueError):
            producer.build_snapshot(bad, candidate_audit=NO_CANDIDATE_AUDIT)

    def test_check_live_reports_a_snapshot_older_than_the_live_head_as_stale(self):
        path = producer.write_snapshot(self.dir / 'snapshot.json', snapshot_dict(head=H3))
        fresh = producer.check_live(path, current_head=lambda: H3)
        stale = producer.check_live(path, current_head=lambda: H2)
        self.assertEqual((fresh['stale'], stale['stale']), (False, True))
        self.assertEqual((stale['snapshot_head'], stale['live_head']), (H3, H2))

    def test_check_live_needs_a_head_source(self):
        path = producer.write_snapshot(self.dir / 'snapshot.json', snapshot_dict())
        with self.assertRaises(ValueError):
            producer.check_live(path)


if __name__ == '__main__':
    unittest.main()
