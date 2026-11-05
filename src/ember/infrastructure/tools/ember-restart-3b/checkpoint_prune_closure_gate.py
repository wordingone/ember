"""Refuse any checkpoint prune that would delete a file the selected continuation head needs to reopen.

Incident (2026-11-05): the governed hour H37 could not start. Its probe reopened the selected head's lineage parent, and
`parameter_counter._cia_realization_receipt` raised "CIA counter requires exact complete object closure": the parent's
`objects/` directory was empty. A closeout prune on 2026-10-10 had deleted those payload files. The prune was authorized and
every file it deleted was verified on the hub, but its keep-list named only the selected head's OWN custody. The counter
reopens the head's parent, that parent's parent, and so on to the zero-step root (`_cia_parent_snapshot_reopened`:
"its own lineage is re-validated below, recursively to genesis"), so every node of the chain must keep its full closure.

The protected set is derived from what the counter checks, not guessed:

* per node, `_cia_realization_receipt` requires the directory's file set to EQUAL
  {checkpoint-manifest.json, <expert_index.path>, optimizer-state.pt, replay-state.pt,
   objects/<core.sha256>.pt, objects/<expert.sha256>.pt for each of the 25 expert-index records}
  (plus an optional parameter-counter-receipt.json);
* per PARENT node, `_cia_parent_snapshot_reopened` additionally requires parameter-counter-receipt.json;
* depth: the whole chain, head to the zero-step root (no lineage, ZERO_STEP_OBJECT_BINDING provenance, zero cursor).

Every name is computed from the node's manifest and expert-index file, never from a directory listing, so the set is still
correct when the payload files are already gone (which is what makes the 2026-10-10 replay possible).

Fail-closed: a walk that cannot be completed (unreadable pointer or manifest, a digest that differs from the one its child
declared, a cycle, a parentless node that is not a zero-step root, an unreadable expert index) REFUSES the prune. It never
shrinks the protected set. A missing expert index protects the node's whole `objects/` directory and still refuses, because
the closure cannot be stated.

Stdlib only. Read-only on the checkpoints; the only write is the optional receipt row (JSON serializer, append).

CLI (the external deleter calls this before deleting anything; exit 0 = PASS, 3 = REFUSED, 2 = usage/unresolvable):
  python checkpoint_prune_closure_gate.py --receipts-root RECEIPTS_ROOT --candidates FILE [--receipt PATH]
  python checkpoint_prune_closure_gate.py --receipts-root RECEIPTS_ROOT --dry-run           (print the protected set)
  python checkpoint_prune_closure_gate.py --receipts-root RECEIPTS_ROOT \\
      --replay-receipts closeout-delete-receipts-20261010.jsonl --replay-index INDEX.json       (rebuild a past prune's candidates)
FILE holds one candidate path per line (blank lines and lines starting with # ignored).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR))

import selected_continuation_head as sch  # noqa: E402  (stdlib-only sibling)

SCHEMA = 'ember-checkpoint-prune-closure-gate-v1'
CLAUSE_PROTECTED = 'selected-head-closure-protected'
CLAUSE_UNRESOLVABLE = 'selected-head-closure-unresolvable'
MANIFEST_NAME = 'checkpoint-manifest.json'
COUNTER_RECEIPT_NAME = 'parameter-counter-receipt.json'
STATE_FILES = ('optimizer-state.pt', 'replay-state.pt')
MAX_DEPTH = 256
EXIT_PASS, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
REPLAY_VERDICT = 'DELETE_HUB_VERIFIED_PAYLOAD_FILES'
REPLAY_MIN_BYTES = 1 << 20  # closeout_delete_class4_v2.py MIN_BYTES: files below it were never candidates
_ZERO_STEP = {'kind': 'ZERO_STEP_OBJECT_BINDING', 'independently_qualified': False}


class ClosureUnresolvable(ValueError):
    """The selected head's chain closure cannot be stated; the prune must refuse."""


def canonical(path: str | Path) -> str:
    """One spelling per file: forward slashes, no trailing slash, casefolded (Windows paths are case-insensitive).

    Manifests write drive-letter paths with backslashes, the hub INDEX mixes separators, and the receipts file escapes backslashes; all three must
    compare equal or a candidate slips past the gate on spelling alone."""
    text = str(path).replace('\\', '/')
    while '//' in text:
        text = text.replace('//', '/')
    return text.rstrip('/').casefold()


def _read_bound(path: Path, expected_sha256: str | None, what: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ClosureUnresolvable(f'{what}: cannot read {path}: {exc}') from exc
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ClosureUnresolvable(f'{what}: {path} hashes to {digest}, not the declared {expected_sha256}')
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClosureUnresolvable(f'{what}: {path} is not JSON: {exc}') from exc
    if not isinstance(payload, dict):
        raise ClosureUnresolvable(f'{what}: {path} is not a JSON object')
    return payload, digest


def resolve_head_directory(receipts_root: Path | str) -> tuple[Path, str]:
    """Pointer -> trained-child directory, the same mapping `fresh_session_head_load` uses, every digest bound."""
    pointer_file = sch.pointer_path(Path(receipts_root))
    try:
        pointer = sch.parse_selected_continuation_head(pointer_file.read_bytes())
    except (OSError, ValueError) as exc:
        raise ClosureUnresolvable(f'selected continuation head pointer {pointer_file}: {exc}') from exc
    head = pointer['lineage_checkpoint_manifest_sha256']
    hour_result = Path(pointer['hour_result_path'].replace('\\', '/'))
    hour, _ = _read_bound(hour_result, pointer['hour_result_sha256'], 'pointer hour result')
    if hour.get('child_manifest_sha256') != head:
        raise ClosureUnresolvable('the pointer hour result names another child than the pointer lineage head')
    return hour_result.parent / 'trained-child', head


def node_closure(directory: Path, manifest: Mapping[str, Any]) -> tuple[list[str], str | None]:
    """The relative file names the counter requires in `directory`; second value is a refusal reason, or None."""
    # The counter receipt is required for a parent and optional for the head; it is protected for both, because once the
    # head advances, the head becomes a parent and its receipt becomes required.
    names = {MANIFEST_NAME, *STATE_FILES, COUNTER_RECEIPT_NAME}
    problem = None
    core = manifest.get('core') if isinstance(manifest.get('core'), Mapping) else {}
    if isinstance(core.get('sha256'), str):
        names.add('objects/' + core['sha256'] + '.pt')
    else:
        problem = f'{directory}: manifest core.sha256 absent'
    index = manifest.get('expert_index') if isinstance(manifest.get('expert_index'), Mapping) else {}
    index_name = index.get('path')
    if not isinstance(index_name, str) or '/' in index_name or '\\' in index_name or not index_name:
        return sorted(names | {'objects/'}), problem or f'{directory}: manifest expert_index.path absent or malformed'
    names.add(index_name)
    try:
        population, _ = _read_bound(directory / index_name, index.get('sha256'), 'expert index')
        experts = population.get('experts')
        if not isinstance(experts, list) or not experts:
            raise ClosureUnresolvable(f'{directory / index_name}: experts list absent')
        for record in experts:
            if not isinstance(record, Mapping) or not isinstance(record.get('sha256'), str):
                raise ClosureUnresolvable(f'{directory / index_name}: expert record without sha256')
            names.add('objects/' + record['sha256'] + '.pt')
    except ClosureUnresolvable as exc:
        # The expert names cannot be stated: protect the whole objects/ directory and refuse.
        return sorted(names | {'objects/'}), problem or str(exc)
    return sorted(names), problem


def protected_closure(receipts_root: Path | str, *, max_depth: int = MAX_DEPTH) -> dict[str, Any]:
    """Walk head -> zero-step root and return every node with the files its reopen requires.

    Raises ClosureUnresolvable when the walk cannot be completed; never returns a partial set silently. A node whose
    expert index is unreadable is returned with `problem` set (its whole objects/ directory protected); `evaluate`
    refuses on any problem."""
    directory, expected = resolve_head_directory(receipts_root)
    head_sha = expected
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    while True:
        if len(nodes) >= max_depth:
            raise ClosureUnresolvable(f'lineage deeper than {max_depth} at {directory}')
        manifest, digest = _read_bound(directory / MANIFEST_NAME, expected, 'chain manifest')
        if digest in seen:
            raise ClosureUnresolvable(f'{directory}: manifest {digest} appears twice in one walk (cycle)')
        seen.add(digest)
        files, problem = node_closure(directory, manifest)
        nodes.append({'directory': str(directory), 'manifest_sha256': digest, 'files': files, 'problem': problem})
        lineage = manifest.get('lineage')
        if lineage is None:
            cursor = manifest.get('data_cursor') if isinstance(manifest.get('data_cursor'), Mapping) else {}
            if manifest.get('genesis_provenance') != _ZERO_STEP or cursor.get('global_step') != 0 or cursor.get('tokens_seen') != 0:
                raise ClosureUnresolvable(
                    f'{directory}: no lineage link but not a zero-step root (the counter would refuse this chain)')
            break
        if not isinstance(lineage, Mapping):
            raise ClosureUnresolvable(f'{directory}: lineage is not an object')
        parent = lineage.get('parent_checkpoint')
        parent_sha = lineage.get('parent_manifest_sha256')
        if not isinstance(parent, str) or not parent or not isinstance(parent_sha, str) or len(parent_sha) != 64:
            raise ClosureUnresolvable(f'{directory}: lineage parent_checkpoint or parent_manifest_sha256 absent')
        directory, expected = Path(parent.replace('\\', '/')), parent_sha
    return {'schema': SCHEMA, 'head_manifest_sha256': head_sha, 'depth': len(nodes), 'nodes': nodes}


def _protected_index(closure: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    """canonical file path -> node manifest sha; plus canonical directory prefixes protected wholesale."""
    files: dict[str, str] = {}
    prefixes: list[str] = []
    for node in closure['nodes']:
        base = canonical(node['directory'])
        for name in node['files']:
            if name.endswith('/'):
                prefixes.append(base + '/' + name.rstrip('/').casefold() + '/')
            else:
                files[base + '/' + name.casefold()] = node['manifest_sha256']
    return files, prefixes


def evaluate(candidates: Iterable[str | Path], closure: Mapping[str, Any], *, enforce: bool = True) -> dict[str, Any]:
    """Intersect candidate deletions with the protected closure. `enforce=False` exists ONLY for the deliberate red:
    it reports PASS whatever the intersection, so a test can show the honest and flattering verdicts are one clause apart."""
    files, prefixes = _protected_index(closure)
    hits = []
    for candidate in candidates:
        key = canonical(candidate)
        node = files.get(key)
        if node is None:
            node = next((p for p in prefixes if key.startswith(p)), None)
        if node is not None:
            hits.append({'candidate': str(candidate), 'protected_by_node': node})
    problems = [n['problem'] for n in closure['nodes'] if n.get('problem')]
    refused = enforce and bool(hits or problems)
    clause = None
    if refused:
        clause = CLAUSE_PROTECTED if hits else CLAUSE_UNRESOLVABLE
    return {
        'schema': SCHEMA,
        'verdict': 'REFUSED' if refused else 'PASS',
        'clause': clause,
        'head_manifest_sha256': closure['head_manifest_sha256'],
        'chain_depth': closure['depth'],
        'protected_files': sum(len(n['files']) for n in closure['nodes']),
        'protected_hits': hits,
        'closure_problems': problems,
        'why': ('each listed file is in the exact object closure parameter_counter reopens for the selected head chain '
                '(head, its lineage parent, recursively to the zero-step root); deleting any of them stops the next hour '
                'from starting') if hits else None,
    }


def append_receipt(path: Path | str, result: Mapping[str, Any]) -> None:
    row = {'ts': datetime.now(timezone.utc).isoformat(), **result}
    with Path(path).open('a', encoding='utf-8', newline='') as handle:
        handle.write(json.dumps(row, sort_keys=True) + '\n')


def replay_candidates(receipts_file: Path | str, index_file: Path | str) -> list[str]:
    """Rebuild the candidate set a past class-4 prune acted on. Its intent rows record a file COUNT, not names, so the
    names come from the hub INDEX it read: every file >= 1 MiB of each checkpoint the receipts mark for deletion."""
    index = json.loads(Path(index_file).read_text(encoding='utf-8'))['checkpoints']
    roots: dict[str, str] = {}
    for line in Path(receipts_file).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('kind') == 'intent' and row.get('verdict') == REPLAY_VERDICT and row.get('checkpoint') in index:
            roots[row['checkpoint']] = row.get('root') or index[row['checkpoint']]['original_root']
    out = []
    for hub_dir, root in sorted(roots.items()):
        for record in index[hub_dir]['files']:
            if record['bytes'] >= REPLAY_MIN_BYTES:
                out.append(root.replace('\\', '/').rstrip('/') + '/' + record['path'])
    return out


def _read_candidates(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--receipts-root', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--candidates', type=Path)
    mode.add_argument('--dry-run', action='store_true', help='print the protected set and exit 0')
    mode.add_argument('--replay-receipts', type=Path)
    parser.add_argument('--replay-index', type=Path)
    parser.add_argument('--receipt', type=Path, help='append the verdict row here (JSON serializer)')
    args = parser.parse_args(argv)
    try:
        closure = protected_closure(args.receipts_root)
    except ClosureUnresolvable as exc:
        result = {'schema': SCHEMA, 'verdict': 'REFUSED', 'clause': CLAUSE_UNRESOLVABLE, 'why': str(exc)}
        if args.receipt:
            append_receipt(args.receipt, result)
        print(json.dumps(result, sort_keys=True))
        return EXIT_REFUSED
    if args.dry_run:
        print(json.dumps(closure, indent=1, sort_keys=True))
        return EXIT_PASS
    if args.replay_receipts is not None:
        if args.replay_index is None:
            parser.error('--replay-receipts needs --replay-index')
        candidates = replay_candidates(args.replay_receipts, args.replay_index)
    else:
        candidates = _read_candidates(args.candidates)
    result = dict(evaluate(candidates, closure), candidates=len(candidates))
    if args.receipt:
        append_receipt(args.receipt, result)
    print(json.dumps(result, indent=1, sort_keys=True))
    return EXIT_REFUSED if result['verdict'] == 'REFUSED' else EXIT_PASS


if __name__ == '__main__':
    sys.exit(main())
