"""Tests for training_lineage_ancestry (issue #2119 sections 3 and 5). Non-learning fixtures: synthetic
manifests in a temp directory; no GPU, no repository tree. Each leg carries a deliberate red."""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import training_lineage_ancestry as ancestry  # noqa: E402


def _write(root: Path, name: str, *, tokens_seen: int, global_step: int, parent: Path | None = None,
           parent_sha: str | None = None, token_delta: int | None = None, step_delta: int | None = None) -> tuple[Path, str]:
    directory = root / name
    directory.mkdir()
    lineage = {} if parent is None else {
        'parent_checkpoint': str(parent).replace('/', '\\'), 'parent_manifest_sha256': parent_sha,
        'token_delta': token_delta, 'step_delta': step_delta}
    raw = json.dumps({'schema_version': 'ember-cia-checkpoint-v1', 'lineage': lineage,
                      'data_cursor': {'tokens_seen': tokens_seen, 'global_step': global_step}},
                     sort_keys=True).encode()
    (directory / ancestry.MANIFEST_NAME).write_bytes(raw)
    return directory, hashlib.sha256(raw).hexdigest()


def _rewrite(directory: Path, mutate) -> str:
    """Rewrite a manifest in place with `mutate(dict)`, returning the new file-bytes digest."""
    path = directory / ancestry.MANIFEST_NAME
    manifest = json.loads(path.read_bytes())
    mutate(manifest)
    raw = json.dumps(manifest, sort_keys=True).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class Chain:
    """genesis (0 tokens) -> a (+100/10) -> b (+250/25) -> c (+50/5); head c = 400 tokens, step 40."""

    def __init__(self, root: Path):
        self.g, self.g_sha = _write(root, 'g', tokens_seen=0, global_step=0)
        self.a, self.a_sha = _write(root, 'a', tokens_seen=100, global_step=10, parent=self.g,
                                    parent_sha=self.g_sha, token_delta=100, step_delta=10)
        self.b, self.b_sha = _write(root, 'b', tokens_seen=350, global_step=35, parent=self.a,
                                    parent_sha=self.a_sha, token_delta=250, step_delta=25)
        self.c, self.c_sha = _write(root, 'c', tokens_seen=400, global_step=40, parent=self.b,
                                    parent_sha=self.b_sha, token_delta=50, step_delta=5)


def _naive_walk_ending_at_any_parentless_manifest(head: Path) -> int:
    """The pre-fix shape, expressed here as the deliberate-red control: follow parent links and stop at the
    first manifest with no parent, whichever it is. Returns the depth it reports as 'complete'."""
    depth = 0
    directory = head
    while True:
        manifest = json.loads((directory / ancestry.MANIFEST_NAME).read_bytes())
        depth += 1
        parent = (manifest.get('lineage') or {}).get('parent_checkpoint')
        if not parent:
            return depth
        directory = Path(parent.replace('\\', '/'))


class LineageWalkTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def walk(self, head: Path, genesis_sha: str, **kwargs):
        return ancestry.walk_lineage(head, expected_genesis_manifest_sha256=genesis_sha, **kwargs)

    def test_three_hours_count_once_and_both_derivations_agree(self):
        chain = Chain(self.root)
        record = self.walk(chain.c, chain.g_sha)
        self.assertEqual(record['depth'], 4)
        self.assertEqual(record['cumulative_applied_token_delta'], 400)
        self.assertEqual(record['head_tokens_seen'], 400)
        self.assertEqual(record['cumulative_step_delta'], 40)
        self.assertEqual(record['head_manifest_sha256'], chain.c_sha)
        self.assertEqual(record['genesis_manifest_sha256'], chain.g_sha)
        self.assertEqual([e['token_delta'] for e in record['chain']], [None, 100, 250, 50])

    def test_walking_a_middle_hour_reports_only_its_own_ancestry(self):
        chain = Chain(self.root)
        self.assertEqual(self.walk(chain.b, chain.g_sha)['cumulative_applied_token_delta'], 350)

    def test_a_missing_ancestor_refuses_and_names_it(self):
        chain = Chain(self.root)
        (chain.a / ancestry.MANIFEST_NAME).unlink()
        with self.assertRaisesRegex(ancestry.AncestryRefusal, r'ancestor .*a: checkpoint-manifest.json absent'):
            self.walk(chain.c, chain.g_sha)

    def test_a_swapped_parent_refuses_on_digest(self):
        chain = Chain(self.root)
        _rewrite(chain.a, lambda m: m['data_cursor'].__setitem__('tokens_seen', 101))  # a different manifest under the same directory
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'differs from the'):
            self.walk(chain.c, chain.g_sha)

    def test_a_replayed_hour_double_credit_refuses(self):
        # c claims +50 tokens but its cursor moved by 100: the hour was credited twice
        g, g_sha = _write(self.root, 'g', tokens_seen=0, global_step=0)
        a, a_sha = _write(self.root, 'a', tokens_seen=100, global_step=10, parent=g, parent_sha=g_sha,
                          token_delta=100, step_delta=10)
        c, _ = _write(self.root, 'c', tokens_seen=200, global_step=15, parent=a, parent_sha=a_sha,
                      token_delta=50, step_delta=5)
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'duplicate or missing credit'):
            self.walk(c, g_sha)

    def test_a_step_gap_refuses(self):
        g, g_sha = _write(self.root, 'g', tokens_seen=0, global_step=0)
        a, _ = _write(self.root, 'a', tokens_seen=100, global_step=11, parent=g, parent_sha=g_sha,
                      token_delta=100, step_delta=10)
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'global_step'):
            self.walk(a, g_sha)

    def test_a_cycle_refuses(self):
        a = self.root / 'a'
        b = self.root / 'b'
        a.mkdir()
        b.mkdir()
        for here, there in ((a, b), (b, a)):
            (here / ancestry.MANIFEST_NAME).write_bytes(json.dumps({'lineage': {
                'parent_checkpoint': str(there), 'parent_manifest_sha256': '0' * 64, 'token_delta': 1, 'step_delta': 1},
                'data_cursor': {'tokens_seen': 1, 'global_step': 1}}).encode())
        with self.assertRaises(ancestry.AncestryRefusal):
            self.walk(a, '1' * 64)

    def test_depth_cap_refuses(self):
        chain = Chain(self.root)
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'deeper than 2'):
            self.walk(chain.c, chain.g_sha, max_depth=2)

    def test_a_nonzero_genesis_is_reported_not_assumed(self):
        g, g_sha = _write(self.root, 'g', tokens_seen=7, global_step=3)
        a, _ = _write(self.root, 'a', tokens_seen=107, global_step=13, parent=g, parent_sha=g_sha,
                      token_delta=100, step_delta=10)
        record = self.walk(a, g_sha)
        self.assertEqual(record['genesis_tokens_seen'], 7)
        self.assertEqual(record['cumulative_applied_token_delta'], 100)

    def test_malformed_delta_refuses(self):
        g, g_sha = _write(self.root, 'g', tokens_seen=0, global_step=0)
        a, _ = _write(self.root, 'a', tokens_seen=100, global_step=10, parent=g, parent_sha=g_sha,
                      token_delta=-5, step_delta=10)
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'token_delta must be a nonnegative integer'):
            self.walk(a, g_sha)

    def test_deliberate_red_a_sum_of_deltas_without_the_hop_check_lets_double_credit_through(self):
        """Control: summing deltas alone (the shape the old status producer had) reports the replayed
        chain as 150 tokens and raises nothing; the real walk refuses the same fixture."""
        g, g_sha = _write(self.root, 'g', tokens_seen=0, global_step=0)
        a, a_sha = _write(self.root, 'a', tokens_seen=100, global_step=10, parent=g, parent_sha=g_sha,
                          token_delta=100, step_delta=10)
        c, _ = _write(self.root, 'c', tokens_seen=200, global_step=15, parent=a, parent_sha=a_sha,
                      token_delta=50, step_delta=5)
        naive = sum(json.loads((d / ancestry.MANIFEST_NAME).read_bytes())['lineage'].get('token_delta', 0) or 0
                    for d in (g, a, c))
        self.assertEqual(naive, 150)  # the naive total is silent about the 50 tokens of unexplained cursor motion
        with self.assertRaises(ancestry.AncestryRefusal):
            self.walk(c, g_sha)


class GenesisIdentityTests(unittest.TestCase):
    """The walk ends only on the expected genesis (Vera, genesis ancestry, issue row 4)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_child_with_its_parent_link_removed_is_refused(self):
        chain = Chain(self.root)
        # b loses lineage.parent_checkpoint (tokens_seen stays 350): it now reads as a parentless manifest
        b_sha = _rewrite(chain.b, lambda m: m['lineage'].pop('parent_checkpoint'))
        _rewrite(chain.c, lambda m: m['lineage'].__setitem__('parent_manifest_sha256', b_sha))
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'not the expected genesis'):
            ancestry.walk_lineage(chain.c, expected_genesis_manifest_sha256=chain.g_sha)

    def test_a_child_with_its_whole_lineage_block_removed_is_refused(self):
        chain = Chain(self.root)
        b_sha = _rewrite(chain.b, lambda m: m.pop('lineage'))
        _rewrite(chain.c, lambda m: m['lineage'].__setitem__('parent_manifest_sha256', b_sha))
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'not the expected genesis'):
            ancestry.walk_lineage(chain.c, expected_genesis_manifest_sha256=chain.g_sha)

    def test_a_foreign_genesis_is_refused(self):
        chain = Chain(self.root)
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'not the expected genesis'):
            ancestry.walk_lineage(chain.c, expected_genesis_manifest_sha256='f' * 64)

    def test_the_expected_genesis_that_declares_a_parent_is_refused(self):
        chain = Chain(self.root)
        with self.assertRaisesRegex(ancestry.AncestryRefusal, 'declares a parent'):
            ancestry.walk_lineage(chain.c, expected_genesis_manifest_sha256=chain.b_sha)

    def test_a_malformed_expected_genesis_is_refused_before_any_read(self):
        chain = Chain(self.root)
        for bad in ('', 'abc', 'G' * 64, 'A' * 64, None):
            with self.assertRaisesRegex(ancestry.AncestryRefusal, 'expected genesis manifest sha256'):
                ancestry.walk_lineage(chain.c, expected_genesis_manifest_sha256=bad)

    def test_deliberate_red_a_walk_that_stops_at_any_parentless_manifest_calls_a_truncated_lineage_complete(self):
        """Control: the pre-fix shape follows parent links and stops at the first parentless manifest, so the
        parent-removed child above reads as a complete lineage of depth 2. The real walk refuses the same fixture."""
        chain = Chain(self.root)
        b_sha = _rewrite(chain.b, lambda m: m['lineage'].pop('parent_checkpoint'))
        _rewrite(chain.c, lambda m: m['lineage'].__setitem__('parent_manifest_sha256', b_sha))
        self.assertEqual(_naive_walk_ending_at_any_parentless_manifest(chain.c), 2)  # c -> b, b "is genesis": 350 tokens never explained
        with self.assertRaises(ancestry.AncestryRefusal):
            ancestry.walk_lineage(chain.c, expected_genesis_manifest_sha256=chain.g_sha)


class ReceiptTests(unittest.TestCase):
    """The CLI receipt preserves the exact command, the exit status and the per-hop chain."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _run(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = ancestry.main(argv)
        return code, json.loads(out.getvalue())

    def test_success_receipt_carries_command_exit_status_and_every_hop(self):
        chain = Chain(self.root)
        receipt_path = self.root / 'receipt.json'
        argv = ['--head', str(chain.c), '--genesis', chain.g_sha, '--receipt', str(receipt_path)]
        code, printed = self._run(argv)
        self.assertEqual(code, 0)
        written = json.loads(receipt_path.read_bytes())
        self.assertEqual(written, printed)
        self.assertEqual(written['command'], ['training_lineage_ancestry.py', *argv])
        self.assertEqual(written['exit_status'], 0)
        self.assertEqual([hop['manifest_sha256'] for hop in written['chain']],
                         [chain.g_sha, chain.a_sha, chain.b_sha, chain.c_sha])
        self.assertEqual(written['record']['cumulative_applied_token_delta'], 400)

    def test_refusal_receipt_carries_exit_status_two_and_the_refusal_text(self):
        chain = Chain(self.root)
        argv = ['--head', str(chain.c), '--genesis', 'f' * 64]
        code, printed = self._run(argv)
        self.assertEqual(code, 2)
        self.assertEqual(printed['exit_status'], 2)
        self.assertEqual(printed['command'], ['training_lineage_ancestry.py', *argv])
        self.assertIn('not the expected genesis', printed['refusal'])
        self.assertNotIn('chain', printed)

    def test_deliberate_red_a_receipt_without_the_exit_status_cannot_distinguish_a_refusal_from_a_count(self):
        chain = Chain(self.root)
        _, ok = self._run(['--head', str(chain.c), '--genesis', chain.g_sha])
        _, refused = self._run(['--head', str(chain.c), '--genesis', 'f' * 64])
        stripped = [{k: v for k, v in receipt.items() if k not in ('exit_status', 'refusal', 'record', 'chain')} for receipt in (ok, refused)]
        self.assertNotEqual(stripped[0]['expected_genesis_manifest_sha256'], stripped[1]['expected_genesis_manifest_sha256'])
        self.assertIn('exit_status', ok)
        self.assertNotEqual(ok['exit_status'], refused['exit_status'])


if __name__ == '__main__':
    unittest.main()
