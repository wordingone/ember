"""Issue #2119 rows 7 and 8: the continuity page accepts and renders the producer's UNKNOWN / free / postponed vocabulary, and a stale page FAILS the check.

Row 7: a gpu_owner of free or UNKNOWN, a learning_measurement of UNKNOWN and a diagnostic_allowance carrying postponed + postponement_reason load and render, each with its
reason on the page; an open or malformed value still refuses (deliberate reds: a non-pair postponement key, an UNKNOWN without a reason, a gpu status the loader never named).
Row 8: `gen_readme_status.py --check --generated-status` run as the CI step runs it, against a COPY of the page, exits 0 for the page as committed and exits 1 with STALE when
the page's status block is older than its source snapshot (deliberate red). Child interpreters are owned, hidden processes (owned_children); no checkpoint, no GPU.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from owned_children import python_argv, run_one  # noqa: E402
import test_issue2119_continuity_page as base  # noqa: E402

page = base.page
SCRIPT = ROOT / 'src/ember/governance/scripts/gen_readme_status.py'
PAGE = ROOT / 'docs/domains/governance/authority/CONTINUITY.md'
SNAPSHOT = ROOT / 'manifests/ember-training-continuity-status-v1.json'
HOLD = ('training hold since 2026-10-08 8:00 AM LA: no card run unless a named deliverable needs it (operator Discord 1557407154787328085)')


def with_sections(**sections):
    snap = base.snapshot_dict()
    for key, value in sections.items():
        if key == 'postponement':
            snap['status']['diagnostic_allowance'].update(value)
        else:
            snap['status'][key] = value
    return snap


class VocabularyTests(base.Base):
    def load(self, snap):
        return page.load_continuity_status(self.write(snap))

    def render(self, snap):
        return page.render_continuity_status_block(self.load(snap))

    def test_gpu_owner_free_and_unknown_load_and_render(self):
        self.assertIn('GPU owner: free', self.render(with_sections(gpu_owner={'status': 'free'})))
        text = self.render(with_sections(gpu_owner={'status': 'UNKNOWN', 'reason': 'the process census failed (RuntimeError); no marker is present'}))
        self.assertIn('GPU owner: **UNKNOWN** (the process census failed (RuntimeError); no marker is present)', text)

    def test_measurement_unknown_renders_its_reason(self):
        text = self.render(with_sections(learning_measurement={'status': 'UNKNOWN', 'reason': 'no measurement receipt was named'}))
        self.assertIn('Last learning measurement: **UNKNOWN** (no measurement receipt was named)', text)

    def test_the_training_hold_reason_is_rendered_verbatim(self):
        text = self.render(with_sections(postponement={'postponed': True, 'postponement_reason': HOLD}))
        self.assertIn(f'Training postponed: yes ({HOLD}).', text)

    def test_an_unreadable_hold_source_renders_unknown_never_blank(self):
        text = self.render(with_sections(postponement={'postponed': 'UNKNOWN', 'postponement_reason': 'the hold record does not exist'}))
        self.assertIn('Training postponed: **UNKNOWN** (the hold record does not exist).', text)

    def test_the_older_vocabulary_still_renders_without_a_postponement_line(self):
        self.assertNotIn('Training postponed', self.render(base.snapshot_dict()))

    def test_open_or_malformed_values_still_refuse_DELIBERATE_RED(self):
        bad = [
            with_sections(gpu_owner={'status': 'UNKNOWN'}),                                              # no reason
            with_sections(gpu_owner={'status': 'idle'}),                                                 # a status the loader never named
            with_sections(learning_measurement={'status': 'UNKNOWN', 'reason': ''}),
            with_sections(postponement={'postponed': True}),                                             # keys come as a pair
            with_sections(postponement={'postponed': False, 'postponement_reason': 'x'}),
            with_sections(postponement={'postponed': True, 'postponement_reason': HOLD, 'extra': 1}),
        ]
        for snap in bad:
            with self.assertRaises(ValueError, msg=json.dumps(snap['status'])[:200]):
                self.load(snap)


class StalePageFailsTheCheckTests(unittest.TestCase):
    """The CI step: python -B gen_readme_status.py --check --generated-status, with the page and snapshot passed as copies."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.page = self.dir / 'CONTINUITY.md'
        self.snapshot = self.dir / 'snapshot.json'
        shutil.copyfile(PAGE, self.page)
        shutil.copyfile(SNAPSHOT, self.snapshot)

    def check(self):
        result = run_one(python_argv(SCRIPT, '--check', '--generated-status', '--continuity', self.page, '--continuity-snapshot', self.snapshot), timeout_s=300)
        return result.returncode, result.stdout + result.stderr

    def test_the_page_as_committed_is_current(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn('is current', out)

    def test_a_page_older_than_its_source_snapshot_FAILS_the_check_DELIBERATE_RED(self):
        snap = json.loads(self.snapshot.read_text(encoding='utf-8'))
        snap['captured_at'] = '2099-01-01T00:00:00Z'                  # the source now says something the page block does not
        self.snapshot.write_text(json.dumps(snap), encoding='utf-8')
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn('STALE', out)

    def test_regenerating_the_block_from_the_new_source_makes_the_check_pass_again(self):
        snap = json.loads(self.snapshot.read_text(encoding='utf-8'))
        snap['captured_at'] = '2099-01-01T00:00:00Z'
        self.snapshot.write_text(json.dumps(snap), encoding='utf-8')
        self.page.write_text(page.apply_continuity_status(self.page.read_text(encoding='utf-8'), self.snapshot), encoding='utf-8', newline='\n')
        code, out = self.check()
        self.assertEqual(code, 0, out)


if __name__ == '__main__':
    unittest.main()
