"""Issue #2119 sections 3 and 5: the lineage's applied updates, counted once, from the manifests alone.

The selected-continuation-head pointer names ONE checkpoint. `training_continuity_status` used to report
that checkpoint's last hour only (`retained_applied_positions` = one hour's `applied_positions`). Nothing
on master walked the parent links, so no code could answer "how many applied tokens does this lineage
hold since genesis, with no hour counted twice". This module walks `lineage.parent_checkpoint` from a
published child to genesis using ONLY each `checkpoint-manifest.json` (no payload read, no hashing of
tensor files), and refuses on the first failure.

Checks per hop (child C, parent P, both read from their own manifest file):
  * P's manifest bytes hash to C's `lineage.parent_manifest_sha256` (a stale, swapped or forged parent
    refuses; this is the same file-bytes digest `cia_hour` calls the manifest sha256);
  * C.data_cursor.tokens_seen - C.lineage.token_delta == P.data_cursor.tokens_seen, and the same for
    global_step / step_delta (a replayed or double-credited hour breaks this equality);
  * no manifest digest appears twice in one walk (a cycle refuses); depth is capped.
The head's own `tokens_seen` must equal genesis tokens plus the sum of the deltas, so the cumulative figure
is derived twice (cursor and deltas) and both must agree.

The walk terminates ONLY on the caller's expected genesis. A manifest that has no `lineage.parent_checkpoint`
is a genesis claim, and it is accepted only when its file-bytes digest equals `expected_genesis_manifest_sha256`:
a child whose `parent_checkpoint` (or whole `lineage` block) was removed would otherwise read as a fresh genesis
and the walk would count a truncated lineage as complete (Vera's finding on row 3a; red fixtures in
test_training_lineage_ancestry.py).

Stdlib only. Read-only. The caller supplies the head directory (the trained-child directory the selected
pointer names) and the expected genesis digest; this module discovers nothing else.

CLI (the receipt keeps the exact command, the exit status and the per-hop chain, so a verdict can be re-read
without re-running the walk):
  python training_lineage_ancestry.py --head DIR --genesis SHA256 [--receipt PATH]
exit 0 = counted; exit 2 = refused (the receipt then carries the refusal text and no chain).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA = 'ember-training-lineage-ancestry-v1'
RECEIPT_SCHEMA = 'ember-training-lineage-ancestry-receipt-v1'
MANIFEST_NAME = 'checkpoint-manifest.json'
MAX_DEPTH = 256


class AncestryRefusal(ValueError):
    """The lineage cannot be counted: the message names the first failing ancestor."""


def _read_manifest(directory: Path) -> tuple[dict[str, Any], str]:
    path = Path(directory) / MANIFEST_NAME
    if not path.is_file():
        raise AncestryRefusal(f'ancestor {directory}: {MANIFEST_NAME} absent')
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
    except ValueError as error:
        raise AncestryRefusal(f'ancestor {directory}: manifest is not JSON ({error})') from None
    if not isinstance(manifest, dict):
        raise AncestryRefusal(f'ancestor {directory}: manifest is not an object')
    return manifest, hashlib.sha256(raw).hexdigest()


def _nonnegative_int(value: Any, what: str, where: Path) -> int:
    if type(value) is not int or value < 0:
        raise AncestryRefusal(f'ancestor {where}: {what} must be a nonnegative integer, got {value!r}')
    return value


def _cursor(manifest: Mapping[str, Any], where: Path) -> tuple[int, int]:
    cursor = manifest.get('data_cursor')
    if not isinstance(cursor, Mapping):
        raise AncestryRefusal(f'ancestor {where}: data_cursor absent')
    return (_nonnegative_int(cursor.get('tokens_seen'), 'data_cursor.tokens_seen', where),
            _nonnegative_int(cursor.get('global_step'), 'data_cursor.global_step', where))


def _digest_arg(value: Any, what: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in '0123456789abcdef' for ch in value):
        raise AncestryRefusal(f'{what} must be a 64-character lowercase hex sha256, got {value!r}')
    return value


def walk_lineage(head_directory: Path | str, *, expected_genesis_manifest_sha256: str,
                 max_depth: int = MAX_DEPTH) -> dict[str, Any]:
    """Count the lineage ending at `head_directory`; refuse (AncestryRefusal) on any gap.

    The walk ends only at a manifest whose digest is `expected_genesis_manifest_sha256`; any other
    manifest with no parent link (a removed `parent_checkpoint`, a removed `lineage` block, a foreign
    lineage's genesis) refuses.

    Returns a closed record: head and genesis manifest digests, depth, the cumulative applied tokens
    and steps derived from the deltas, the head's own cursor values (which must equal them), and the
    chain from genesis to head with each hour's delta.
    """
    expected_genesis = _digest_arg(expected_genesis_manifest_sha256, 'expected genesis manifest sha256')
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    directory = Path(head_directory)
    expect_sha: str | None = None  # the digest the CHILD declared for this directory's manifest
    while True:
        if len(chain) >= max_depth:
            raise AncestryRefusal(f'lineage deeper than {max_depth} at {directory} (cycle?)')
        manifest, digest = _read_manifest(directory)
        if expect_sha is not None and digest != expect_sha:
            raise AncestryRefusal(
                f'ancestor {directory}: manifest digest {digest} differs from the {expect_sha} its child declared')
        if digest in seen:
            raise AncestryRefusal(f'ancestor {directory}: manifest {digest} appears twice (cycle or replay)')
        seen.add(digest)
        tokens_seen, global_step = _cursor(manifest, directory)
        lineage = manifest.get('lineage') if isinstance(manifest.get('lineage'), Mapping) else {}
        parent_dir = lineage.get('parent_checkpoint')
        entry: dict[str, Any] = {
            'directory': str(directory), 'manifest_sha256': digest,
            'tokens_seen': tokens_seen, 'global_step': global_step,
        }
        if parent_dir in (None, ''):
            if digest != expected_genesis:
                raise AncestryRefusal(
                    f'ancestor {directory}: the walk ended at manifest {digest}, which is not the expected genesis '
                    f'{expected_genesis} (its parent link or lineage block is absent, or it belongs to another lineage)')
            entry['token_delta'] = None
            entry['step_delta'] = None
            chain.append(entry)
            break
        if not isinstance(parent_dir, str):
            raise AncestryRefusal(f'ancestor {directory}: lineage.parent_checkpoint is not a path')
        if digest == expected_genesis:
            raise AncestryRefusal(f'ancestor {directory}: the expected genesis {digest} declares a parent (genesis has none)')
        parent_sha = lineage.get('parent_manifest_sha256')
        if not isinstance(parent_sha, str) or len(parent_sha) != 64:
            raise AncestryRefusal(f'ancestor {directory}: lineage.parent_manifest_sha256 absent or malformed')
        entry['token_delta'] = _nonnegative_int(lineage.get('token_delta'), 'lineage.token_delta', directory)
        entry['step_delta'] = _nonnegative_int(lineage.get('step_delta'), 'lineage.step_delta', directory)
        chain.append(entry)
        expect_sha = parent_sha
        directory = Path(parent_dir.replace('\\', '/'))
    chain.reverse()  # genesis -> head
    genesis, head = chain[0], chain[-1]
    # hop continuity: each child's cursor is exactly its parent's cursor plus its own delta
    for parent, child in zip(chain, chain[1:]):
        if child['tokens_seen'] - child['token_delta'] != parent['tokens_seen']:
            raise AncestryRefusal(
                f"hop into {child['directory']}: tokens_seen {child['tokens_seen']} minus token_delta "
                f"{child['token_delta']} is not the parent's {parent['tokens_seen']} (duplicate or missing credit)")
        if child['global_step'] - child['step_delta'] != parent['global_step']:
            raise AncestryRefusal(
                f"hop into {child['directory']}: global_step {child['global_step']} minus step_delta "
                f"{child['step_delta']} is not the parent's {parent['global_step']}")
    cumulative_tokens = sum(entry['token_delta'] for entry in chain[1:])
    cumulative_steps = sum(entry['step_delta'] for entry in chain[1:])
    if genesis['tokens_seen'] + cumulative_tokens != head['tokens_seen']:
        raise AncestryRefusal('head tokens_seen differs from genesis plus the summed deltas')
    if genesis['global_step'] + cumulative_steps != head['global_step']:
        raise AncestryRefusal('head global_step differs from genesis plus the summed step deltas')
    return {
        'schema': SCHEMA,
        'head_manifest_sha256': head['manifest_sha256'],
        'genesis_manifest_sha256': genesis['manifest_sha256'],
        'depth': len(chain),
        'genesis_tokens_seen': genesis['tokens_seen'],
        'cumulative_applied_token_delta': cumulative_tokens,
        'cumulative_step_delta': cumulative_steps,
        'head_tokens_seen': head['tokens_seen'],
        'head_global_step': head['global_step'],
        'chain': chain,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the walk and write a receipt that preserves the command, the exit status and the per-hop chain."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--head', required=True, type=Path)
    parser.add_argument('--genesis', required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args(argv)
    receipt: dict[str, Any] = {'schema': RECEIPT_SCHEMA, 'command': [Path(__file__).name, *argv],
                               'head': str(args.head), 'expected_genesis_manifest_sha256': args.genesis}
    try:
        record = walk_lineage(args.head, expected_genesis_manifest_sha256=args.genesis)
    except AncestryRefusal as refusal:
        receipt.update({'exit_status': 2, 'refusal': str(refusal)})
        status_code = 2
    else:
        receipt.update({'exit_status': 0, 'record': {k: v for k, v in record.items() if k != 'chain'},
                        'chain': record['chain']})
        status_code = 0
    text = json.dumps(receipt, indent=1, sort_keys=True)
    if args.receipt is not None:
        args.receipt.write_text(text + '\n', encoding='utf-8', newline='\n')
    print(text)
    return status_code


if __name__ == '__main__':
    raise SystemExit(main())
