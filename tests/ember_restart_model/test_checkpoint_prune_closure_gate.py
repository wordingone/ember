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


BS = chr(92)  # the backslash


def _mixed(path: str) -> str:
    """Alternate separators segment by segment, the way the hub INDEX and receipts spell paths."""
    parts = path.replace(BS, '/').split('/')
    return ''.join(part + ('/' if i % 2 else BS) for i, part in enumerate(parts[:-1])) + parts[-1]


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
        original = Tree.objects(self.tree.parent_dir)[0]
        for candidate in (original.replace(BS, '/').upper(), original.replace('/', BS).upper(),
                          _mixed(original).upper()):
            with self.subTest(candidate=candidate):
                _assert_refuses(self, gate.evaluate([candidate], self.closure))

    def test_dot_dot_spelling_does_not_slip_past(self):
        objects = self.tree.parent_dir / 'objects'
        name = Tree.objects(self.tree.parent_dir)[0].replace(BS, '/').rsplit('/', 1)[1]
        candidate = str(objects).replace(BS, '/') + '/../objects/./' + name
        _assert_refuses(self, gate.evaluate([candidate], self.closure))

    def test_a_directory_candidate_above_a_protected_file_is_a_hit(self):
        for directory in (self.tree.parent_dir / 'objects', self.tree.parent_dir, self.tree.parent_dir.parent,
                          self.tree.parent_dir.parent.parent, self.tree.head_hour, self.tree.base):
            with self.subTest(directory=directory):
                _assert_refuses(self, gate.evaluate([str(directory)], self.closure))
        # an unrelated checkpoint's directory still passes
        self.assertEqual(gate.evaluate([str(self.tree.other_dir.parent.parent)], self.closure)['verdict'], 'PASS')

    def test_pointer_and_head_hour_result_are_protected(self):
        for name in (self.tree.base / 'selected-continuation-head.json', self.tree.head_hour / 'hour-result.json'):
            with self.subTest(name=name):
                _assert_refuses(self, gate.evaluate([str(name)], self.closure))

    def test_a_relative_candidate_refuses(self):
        result = gate.evaluate(['objects/x.pt'], self.closure)
        _assert_refuses(self, result, gate.CLAUSE_CANDIDATE)

    def test_deliberate_red_an_empty_protected_index_lets_the_parent_deletion_through(self):
        """The red removes what the refusal rests on (the protected index), with no switch in the shipped code: the same
        candidates then read PASS and the refusal assertion fails."""
        candidates = Tree.objects(self.tree.parent_dir)
        original = gate._protected_index
        try:
            gate._protected_index = lambda closure: ({}, [])
            red = gate.evaluate(candidates, self.closure)
        finally:
            gate._protected_index = original
        self.assertEqual(red['verdict'], 'PASS')
        with self.assertRaises(AssertionError):
            _assert_refuses(self, red)

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

    def _real_shaped_replay_inputs(self) -> tuple[Path, Path]:
        """A receipts file and a hub INDEX in the shapes of the 2026-10-10 class-4 receipts and the lineage-2119 INDEX
        (field names and value spellings copied; every path and digest synthetic): the root and the parent are marked
        DELETE (one dry and one wet intent plus an outcome each), the head is KEEP."""
        checkpoints = {}
        rows = []
        gate_block = {'restore_pass_mail': 1, 'package_verified_mail': 2, 'note': 'synthetic'}
        nodes = list(reversed(self.closure['nodes']))  # root -> head
        for lineage_index, node in enumerate(nodes):
            directory = Path(node['directory'])
            hub_dir = f'checkpoints/lineage-2119/step{lineage_index * 5}-{node["manifest_sha256"][:12]}'
            parent = nodes[lineage_index - 1] if lineage_index else None
            files = []
            for name in node['files']:
                big = name.startswith('objects/') or name in gate.STATE_FILES
                files.append({'path': name, 'bytes': (3 << 20) if big else 512, 'sha256': _sha(name.encode())})
            checkpoints[hub_dir] = {
                'step': str(lineage_index * 5), 'manifest_sha256': node['manifest_sha256'],
                'parent_manifest_sha256': parent['manifest_sha256'] if parent else None, 'lineage_index': str(lineage_index),
                'original_root': str(directory).replace('/', BS),
                'parent_checkpoint_path': str(parent['directory']).replace('/', BS) if parent else None, 'files': files}
            root = str(directory).replace('/', BS)
            if node is nodes[-1]:
                rows.append({'kind': 'intent', 'klass': 4, 'checkpoint': hub_dir, 'verdict': 'KEEP_SELECTED_OR_S4',
                             'ts': '2026-10-10T22:00:00+00:00'})
                continue
            payload = [f for f in files if f['bytes'] >= gate.REPLAY_MIN_BYTES]
            for dry in (True, False):
                rows.append({'bytes': sum(f['bytes'] for f in payload), 'checkpoint': hub_dir, 'dry': dry,
                             'files': len(payload), 'gate': gate_block, 'kind': 'intent', 'klass': 4, 'root': root,
                             'skipped': [], 'ts': '2026-10-10T22:13:12+00:00', 'verdict': gate.REPLAY_VERDICT})
            rows.append({'bytes_deleted': sum(f['bytes'] for f in payload), 'checkpoint': hub_dir, 'errors': [],
                         'files_deleted': len(payload), 'kind': 'outcome', 'klass': 4, 'root': root,
                         'ts': '2026-10-10T22:13:32+00:00'})
        index_file = self.tree.base / 'INDEX.json'
        index_file.write_text(json.dumps({'schema': 'synthetic-index', 'checkpoints': checkpoints}), encoding='utf-8')
        receipts = self.tree.base / 'closeout-delete-receipts.jsonl'
        receipts.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows), encoding='utf-8')
        return receipts, index_file

    def test_replay_of_a_real_shaped_prune_refuses_end_to_end(self):
        receipts, index_file = self._real_shaped_replay_inputs()
        candidates = gate.replay_candidates(receipts, index_file)
        self.assertEqual(len(candidates), 2 * 5)  # root and parent: optimizer, replay, core, two experts each
        result = gate.evaluate(candidates, self.closure)
        _assert_refuses(self, result)
        hit_nodes = {h['protected_by_node'] for h in result['protected_hits']}
        self.assertEqual(hit_nodes, {self.closure['nodes'][1]['manifest_sha256'], self.closure['nodes'][2]['manifest_sha256']})
        self.assertEqual(len(result['protected_hits']), len(candidates))
        out = io.StringIO()
        with redirect_stdout(out):
            code = gate.main(['--receipts-root', str(self.tree.base), '--replay-receipts', str(receipts),
                              '--replay-index', str(index_file)])
        self.assertEqual(code, gate.EXIT_REFUSED)
        self.assertEqual(json.loads(out.getvalue())['clause'], gate.CLAUSE_PROTECTED)

    def test_unreadable_replay_input_refuses_without_a_traceback(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = gate.main(['--receipts-root', str(self.tree.base), '--replay-receipts', str(self.tree.base / 'absent.jsonl'),
                              '--replay-index', str(self.tree.base / 'absent.json')])
        self.assertEqual(code, gate.EXIT_REFUSED)
        self.assertEqual(json.loads(out.getvalue())['clause'], gate.CLAUSE_INPUT)
        broken = self.tree.base / 'broken.json'
        broken.write_text('{not json', encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            code = gate.main(['--receipts-root', str(self.tree.base), '--replay-receipts', str(broken),
                              '--replay-index', str(broken)])
        self.assertEqual(code, gate.EXIT_REFUSED)

    def test_dry_run_exits_3_when_a_node_has_a_problem(self):
        for item in self.tree.parent_dir.glob('expert-index-*.json'):
            item.unlink()
        with redirect_stdout(io.StringIO()):
            code = gate.main(['--receipts-root', str(self.tree.base), '--dry-run'])
        self.assertEqual(code, gate.EXIT_REFUSED)

    def test_lineage_null_is_malformed_not_a_root(self):
        manifest = self.tree.head_dir / 'checkpoint-manifest.json'
        payload = json.loads(manifest.read_bytes())
        payload['lineage'] = None
        raw = json.dumps(payload, sort_keys=True).encode()
        manifest.write_bytes(raw)
        hour_raw = json.dumps({'child_manifest_sha256': _sha(raw)}).encode()
        (self.tree.head_hour / 'hour-result.json').write_bytes(hour_raw)
        pointer_file = self.tree.base / 'selected-continuation-head.json'
        pointer = json.loads(pointer_file.read_text(encoding='utf-8'))
        pointer.update(lineage_checkpoint_manifest_sha256=_sha(raw), hour_result_sha256=_sha(hour_raw))
        pointer_file.write_text(json.dumps(pointer), encoding='utf-8')
        with self.assertRaisesRegex(gate.ClosureUnresolvable, 'lineage is not an object'):
            gate.protected_closure(self.tree.base)


if __name__ == '__main__':
    unittest.main()
