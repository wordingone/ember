"""Tests for checkpoint_prune_closure_gate: a prune must never delete a file the selected head's chain reopen needs.

Non-learning fixtures: a synthetic receipts tree (zero-step root -> parent -> head) with tiny fake payload files in a temp
directory; no GPU, no real checkpoints. The deliberate red shows the refusal clause is load-bearing."""
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

import checkpoint_prune_closure_gate as gate  # noqa: E402


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checkpoint(directory: Path, *, tag: str, step: int, parent: tuple[Path, str] | None) -> str:
    """Write a fake CIA checkpoint (two experts) and return its manifest file-bytes digest."""
    (directory / 'objects').mkdir(parents=True)
    core = _sha(f'core-{tag}'.encode())
    experts = [_sha(f'expert-{tag}-{i}'.encode()) for i in range(2)]
    for name in [core, *experts]:
        (directory / 'objects' / f'{name}.pt').write_bytes(b'x')
    index_raw = json.dumps({'schema_version': 'ember-cia-expert-index-v1', 'candidate_revision': 'CIA3-R1-N61',
                            'experts': [{'expert_id': i, 'sha256': s, 'bytes': 1} for i, s in enumerate(experts)]}).encode()
    index_sha = _sha(index_raw)
    index_name = f'expert-index-{index_sha}.json'
    (directory / index_name).write_bytes(index_raw)
    for name in ('optimizer-state.pt', 'replay-state.pt', 'parameter-counter-receipt.json'):
        (directory / name).write_bytes(b'x')
    (directory / 'stdout.log').write_bytes(b'not in the closure')
    manifest = {
        'schema_version': 'ember-cia-checkpoint-v1',
        'core': {'sha256': core, 'bytes': 1, 'architecture_sha256': '0' * 64},
        'expert_index': {'path': index_name, 'sha256': index_sha, 'bytes': len(index_raw), 'expert_object_bytes': 2},
        'optimizer': {'path': 'optimizer-state.pt', 'sha256': '1' * 64, 'bytes': 1},
        'replay': {'path': 'replay-state.pt', 'sha256': '2' * 64, 'bytes': 1},
        'data_cursor': {'global_step': step, 'tokens_seen': step * 10},
    }
    if parent is None:
        manifest['genesis_provenance'] = {'kind': 'ZERO_STEP_OBJECT_BINDING', 'independently_qualified': False}
    else:
        manifest['genesis_provenance'] = {'kind': 'VERIFIED_DESCENDANT_PARENT', 'independently_qualified': False}
        # Windows spelling, as the real manifests carry it
        manifest['lineage'] = {'parent_checkpoint': str(parent[0]).replace('/', '\\'), 'parent_manifest_sha256': parent[1]}
    raw = json.dumps(manifest, sort_keys=True).encode()
    (directory / 'checkpoint-manifest.json').write_bytes(raw)
    return _sha(raw)


class Tree:
    """receipts root with a selected pointer at head; chain head -> parent -> zero-step root; plus an unrelated checkpoint."""

    def __init__(self, base: Path):
        self.root_dir = base / 'cia-learning-candidate-a' / 'measurement-0' / 'zero-parent'
        self.parent_dir = base / 'cia-hour-b' / 'measurement-1' / 'trained-child'
        self.head_hour = base / 'cia-hour-c' / 'measurement-2'
        self.head_dir = self.head_hour / 'trained-child'
        self.other_dir = base / 'cia-hour-x' / 'measurement-9' / 'trained-child'
        root_sha = _checkpoint(self.root_dir, tag='root', step=0, parent=None)
        self.parent_sha = _checkpoint(self.parent_dir, tag='parent', step=5, parent=(self.root_dir, root_sha))
        head_sha = _checkpoint(self.head_dir, tag='head', step=9, parent=(self.parent_dir, self.parent_sha))
        _checkpoint(self.other_dir, tag='other', step=0, parent=None)
        hour_raw = json.dumps({'child_manifest_sha256': head_sha}).encode()
        (self.head_hour / 'hour-result.json').write_bytes(hour_raw)
        pointer = {'schema': 'ember-selected-continuation-head-v1', 'lineage_checkpoint_manifest_sha256': head_sha,
                   'hour_result_path': str(self.head_hour / 'hour-result.json').replace('/', '\\'),
                   'hour_result_sha256': _sha(hour_raw), 'published_at': 1.0, 'seeded_reason': ''}
        (base / 'selected-continuation-head.json').write_text(json.dumps(pointer), encoding='utf-8')
        self.base = base

    @staticmethod
    def objects(directory: Path) -> list[str]:
        return sorted(str(p) for p in (directory / 'objects').iterdir())


def _assert_refuses(test: unittest.TestCase, result: dict, clause: str = gate.CLAUSE_PROTECTED) -> None:
    test.assertEqual(result['verdict'], 'REFUSED')
    test.assertEqual(result['clause'], clause)


class ClosureGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Tree(Path(self._tmp.name))
        self.closure = gate.protected_closure(self.tree.base)

    def tearDown(self):
        self._tmp.cleanup()

    def test_walk_reaches_the_zero_step_root(self):
        self.assertEqual(self.closure['depth'], 3)
        self.assertEqual(self.closure['nodes'][1]['manifest_sha256'], self.tree.parent_sha)
        # per node: manifest, expert index, optimizer, replay, counter receipt, core + 2 experts
        self.assertTrue(all(len(n['files']) == 8 for n in self.closure['nodes']))

    def test_refuses_when_a_parent_object_is_a_candidate(self):
        candidates = Tree.objects(self.tree.other_dir) + Tree.objects(self.tree.parent_dir)[:1]
        result = gate.evaluate(candidates, self.closure)
        _assert_refuses(self, result)
        self.assertEqual([h['protected_by_node'] for h in result['protected_hits']], [self.tree.parent_sha])

    def test_refuses_on_the_zero_step_root_and_the_parent_optimizer(self):
        candidates = [Tree.objects(self.tree.root_dir)[0], str(self.tree.parent_dir / 'optimizer-state.pt')]
        result = gate.evaluate(candidates, self.closure)
        _assert_refuses(self, result)
        self.assertEqual(len(result['protected_hits']), 2)

    def test_passes_when_no_candidate_is_in_the_chain_closure(self):
        candidates = Tree.objects(self.tree.other_dir) + [str(self.tree.parent_dir / 'stdout.log')]
        result = gate.evaluate(candidates, self.closure)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['protected_hits'], [])

    def test_separator_and_case_spelling_does_not_slip_past(self):
        candidate = Tree.objects(self.tree.parent_dir)[0].replace('/', '\\').upper()
        _assert_refuses(self, gate.evaluate([candidate], self.closure))

    def test_deliberate_red_gate_disabled_lets_the_parent_deletion_through(self):
        """With the refusal clause suppressed, the same candidate set reads PASS and the refusal assertion fails."""
        candidates = Tree.objects(self.tree.parent_dir)
        disabled = gate.evaluate(candidates, self.closure, enforce=False)
        self.assertEqual(disabled['verdict'], 'PASS')
        self.assertTrue(disabled['protected_hits'])  # the hits are still computed; only the clause is gone
        with self.assertRaises(AssertionError):
            _assert_refuses(self, disabled)

    def test_cli_refuses_with_exit_3_and_writes_a_receipt_row(self):
        listing = self.tree.base / 'candidates.txt'
        listing.write_text('# fake prune\n' + '\n'.join(Tree.objects(self.tree.parent_dir)) + '\n', encoding='utf-8')
        receipt = self.tree.base / 'gate-receipts.jsonl'
        with redirect_stdout(io.StringIO()):
            code = gate.main(['--receipts-root', str(self.tree.base), '--candidates', str(listing), '--receipt', str(receipt)])
        self.assertEqual(code, gate.EXIT_REFUSED)
        row = json.loads(receipt.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual(row['clause'], gate.CLAUSE_PROTECTED)
        self.assertEqual(len(row['protected_hits']), 3)
        self.assertIn('ts', row)

    def test_dry_run_prints_the_protected_set(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = gate.main(['--receipts-root', str(self.tree.base), '--dry-run'])
        self.assertEqual(code, gate.EXIT_PASS)
        printed = json.loads(out.getvalue())
        self.assertEqual(printed['depth'], 3)

    def test_broken_parent_digest_refuses_the_whole_prune(self):
        manifest = self.tree.parent_dir / 'checkpoint-manifest.json'
        manifest.write_bytes(manifest.read_bytes() + b' ')
        with self.assertRaises(gate.ClosureUnresolvable):
            gate.protected_closure(self.tree.base)
        listing = self.tree.base / 'candidates.txt'
        listing.write_text('\n'.join(Tree.objects(self.tree.other_dir)), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            code = gate.main(['--receipts-root', str(self.tree.base), '--candidates', str(listing)])
        self.assertEqual(code, gate.EXIT_REFUSED)

    def test_parentless_node_that_is_not_zero_step_refuses(self):
        manifest = self.tree.root_dir / 'checkpoint-manifest.json'
        payload = json.loads(manifest.read_bytes())
        payload['data_cursor']['global_step'] = 3
        raw = json.dumps(payload, sort_keys=True).encode()
        manifest.write_bytes(raw)
        # rebind the parent's declared digest so only the root rule is exercised (this changes the parent and head digests)
        parent_manifest = self.tree.parent_dir / 'checkpoint-manifest.json'
        parent = json.loads(parent_manifest.read_bytes())
        parent['lineage']['parent_manifest_sha256'] = _sha(raw)
        parent_raw = json.dumps(parent, sort_keys=True).encode()
        parent_manifest.write_bytes(parent_raw)
        head_manifest = self.tree.head_dir / 'checkpoint-manifest.json'
        head = json.loads(head_manifest.read_bytes())
        head['lineage']['parent_manifest_sha256'] = _sha(parent_raw)
        head_raw = json.dumps(head, sort_keys=True).encode()
        head_manifest.write_bytes(head_raw)
        hour_raw = json.dumps({'child_manifest_sha256': _sha(head_raw)}).encode()
        (self.tree.head_hour / 'hour-result.json').write_bytes(hour_raw)
        pointer_file = self.tree.base / 'selected-continuation-head.json'
        pointer = json.loads(pointer_file.read_text(encoding='utf-8'))
        pointer.update(lineage_checkpoint_manifest_sha256=_sha(head_raw), hour_result_sha256=_sha(hour_raw))
        pointer_file.write_text(json.dumps(pointer), encoding='utf-8')
        with self.assertRaisesRegex(gate.ClosureUnresolvable, 'not a zero-step root'):
            gate.protected_closure(self.tree.base)

    def test_unreadable_expert_index_protects_objects_and_refuses(self):
        for item in self.tree.parent_dir.glob('expert-index-*.json'):
            item.unlink()
        closure = gate.protected_closure(self.tree.base)
        result = gate.evaluate(Tree.objects(self.tree.other_dir), closure)
        _assert_refuses(self, result, gate.CLAUSE_UNRESOLVABLE)
        stray = str(self.tree.parent_dir / 'objects' / ('f' * 64 + '.pt'))
        _assert_refuses(self, gate.evaluate([stray], closure))

    def test_replay_rebuilds_candidates_from_receipts_and_index(self):
        index = {'checkpoints': {
            'checkpoints/lineage-2119/step5-parent': {'original_root': str(self.tree.parent_dir), 'files': [
                {'path': 'objects/a.pt', 'bytes': 2 << 20}, {'path': 'checkpoint-manifest.json', 'bytes': 100}]},
            'checkpoints/lineage-2119/step0-other': {'original_root': str(self.tree.other_dir), 'files': [
                {'path': 'objects/b.pt', 'bytes': 2 << 20}]}}}
        index_file = self.tree.base / 'INDEX.json'
        index_file.write_text(json.dumps(index), encoding='utf-8')
        rows = [{'kind': 'intent', 'klass': 4, 'checkpoint': 'checkpoints/lineage-2119/step5-parent',
                 'root': str(self.tree.parent_dir).replace('/', '\\'), 'verdict': gate.REPLAY_VERDICT, 'files': 1},
                {'kind': 'intent', 'klass': 4, 'checkpoint': 'checkpoints/lineage-2119/step0-other',
                 'verdict': 'KEEP_SELECTED_OR_S4'}]
        receipts = self.tree.base / 'closeout.jsonl'
        receipts.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
        candidates = gate.replay_candidates(receipts, index_file)
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].endswith('trained-child/objects/a.pt'))


if __name__ == '__main__':
    unittest.main()
