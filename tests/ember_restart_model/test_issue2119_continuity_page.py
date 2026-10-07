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
        'gpu_owner': status_module.gpu_owner_status({'owner': 'eli', 'run_id': 'r9', 'training_job_purpose': 'DIAGNOSTIC'}),
        'checkpoint': status_module.selected_checkpoint_status(hour_result),
        'learning_measurement': status_module.last_learning_measurement_status(None),
        'purpose': status_module.current_purpose_status({'training_job_purpose': 'DIAGNOSTIC', 'run_id': 'r9'}),
        'diagnostic_allowance': {'diagnostic_occupancy_seconds': 600, 'max_diagnostic_occupancy_seconds': 3600,
                                 'postponement_seconds': 0, 'max_postponement_seconds': 7200, 'at_occupancy_limit': False,
                                 'at_postponement_limit': False},
        'next_segment': status_module.next_segment_status(blocker='no pending-continuation record'),
    }


def snapshot_dict(**kw):
    return producer.build_snapshot(status_dict(**kw), captured_at='2026-10-06T20:00:00Z')


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
            producer.build_snapshot(bad)

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
