# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression for the H26 pointer switch (Issue #2119): an hour run from a tree without the candidate-only change must be refused.

REPRODUCTION (red on the pre-fix shape): the legacy hour source below calls advance_selected_continuation_head after the hour result, exactly as
the master 00edcc / H26 dispatch tree b8f2ff29 cia_hour.py did; hour_source_advances_selected_head reports it, so a dispatcher refuses the tree.
GREEN: the live cia_hour.py publishes a candidate only and reports no pointer mover. Ancestry: a throwaway repository proves the tree HEAD must
contain the required commit (green), a tree branched before it (red), an unknown id (red) and a non-repository (red).
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
import dispatch_tree_check as dtc  # noqa: E402

# HOUR_SOURCE overrides the hour source under test (the deliberate red points it at the pre-c13998ac cia_hour.py of the H26 dispatch tree).
HOUR_SOURCE = Path(os.environ.get('HOUR_SOURCE') or TOOLS / 'cia_hour.py')

LEGACY_HOUR_SOURCE = '''
def run_hour(runner, custody, chain, selected_continuation_head, training_continuity_ledger):
    runner.tail_stamp(custody, 'hour_result')
    selected_continuation_head.advance_selected_continuation_head(
        repo_root=runner.ROOT, receipts_root=training_continuity_ledger.ledger_root(custody.parent),
        published_checkpoint_root=custody / 'trained-child', hour_result_path=custody / 'hour-result.json',
        hour_result_sha256=runner.file_sha256(custody / 'hour-result.json'),
        expected_parent_checkpoint_manifest_sha256=chain['manifest_sha256'])
    runner.tail_stamp(custody, 'pointer_cas')
'''
CANDIDATE_ONLY_SOURCE = LEGACY_HOUR_SOURCE.replace('advance_selected_continuation_head', 'publish_candidate_continuation_head')


def git(tree, *args):
    subprocess.run(['git', '-C', str(tree), *args], check=True, capture_output=True, text=True, shell=False)


class HourSourceTests(unittest.TestCase):
    def test_the_legacy_hour_shape_that_moved_the_h26_head_is_detected(self):
        self.assertEqual(len(dtc.hour_source_advances_selected_head(LEGACY_HOUR_SOURCE)), 1)

    def test_a_candidate_only_hour_reports_no_pointer_mover(self):
        self.assertEqual(dtc.hour_source_advances_selected_head(CANDIDATE_ONLY_SOURCE), [])

    def test_the_live_hour_source_never_moves_the_selected_head(self):
        self.assertEqual(dtc.hour_source_advances_selected_head(HOUR_SOURCE.read_text(encoding='utf-8')), [])


class AncestryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = Path(self._tmp.name)
        git(self.tree, 'init', '-q', '.')
        git(self.tree, 'config', 'user.email', 't@t')
        git(self.tree, 'config', 'user.name', 't')
        (self.tree / 'f').write_text('a')
        git(self.tree, 'add', 'f')
        git(self.tree, 'commit', '-q', '-m', 'base')
        self.base = self._head()
        git(self.tree, 'checkout', '-q', '-b', 'feature')
        (self.tree / 'f').write_text('b')
        git(self.tree, 'commit', '-qam', 'want')
        self.want = self._head()

    def _head(self):
        return subprocess.run(['git', '-C', str(self.tree), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()

    def test_a_tree_containing_the_commit_passes(self):
        self.assertEqual(dtc.require_commit_in_head(self.tree, self.want), self.want)

    def test_a_tree_branched_before_the_commit_is_refused(self):
        git(self.tree, 'checkout', '-q', '-b', 'before', self.base)
        (self.tree / 'g').write_text('c')
        git(self.tree, 'add', 'g')
        git(self.tree, 'commit', '-q', '-m', 'other')
        with self.assertRaises(dtc.DispatchTreeRefusal):
            dtc.require_commit_in_head(self.tree, self.want)

    def test_a_cherry_picked_equivalent_passes_but_the_old_tree_does_not(self):
        git(self.tree, 'checkout', '-q', '-b', 'picked', self.base)
        time.sleep(1.1)  # a pick inside the same second reproduces the same id (then it is an ancestor, not a pick)
        git(self.tree, 'cherry-pick', self.want)
        self.assertEqual(dtc.require_commit_in_head(self.tree, self.want), self.want)
        git(self.tree, 'checkout', '-q', '-b', 'old', self.base)
        (self.tree / 'g').write_text('z')
        git(self.tree, 'add', 'g')
        git(self.tree, 'commit', '-q', '-m', 'unrelated')
        with self.assertRaises(dtc.DispatchTreeRefusal):
            dtc.require_commit_in_head(self.tree, self.want)

    def test_an_unknown_commit_is_refused_not_read_as_present(self):
        with self.assertRaises(dtc.DispatchTreeRefusal):
            dtc.require_commit_in_head(self.tree, 'deadbeefdeadbeef')

    def test_a_directory_that_is_not_a_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as plain:
            with self.assertRaises(dtc.DispatchTreeRefusal):
                dtc.require_commit_in_head(plain, self.want)


if __name__ == '__main__':
    unittest.main()
