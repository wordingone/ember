"""Issue #2119 row 8 (producer half): the committed training-continuity snapshot the continuity page renders.

The page (gen_readme_status.py) is generated from committed files only, because the merge gate cannot read the receipts drive.
This module writes the one committed file it renders -- `manifests/ember-training-continuity-status-v1.json` -- from the dict
`training_continuity_status.training_continuity_status()` returns, plus when it was captured and the head it describes. It is run
at a publication boundary (after an hour's pointer advance), never inside a training step.

`check_live` is the freshness check available where the receipts drive IS visible: the snapshot's head against the live selected
head. The merge gate cannot run it, so the page states `captured_at` and the head digest instead of claiming currency.

Stdlib only; `selected_continuation_head` is imported lazily by `check_live` when no head reader is injected.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

SNAPSHOT_SCHEMA = 'ember-training-continuity-snapshot-v1'
STATUS_SCHEMA = 'ember-training-continuity-status-v2'   # training_continuity_status.STATUS_SCHEMA; a test compares the two
DEFAULT_PATH = Path(__file__).resolve().parents[5] / 'manifests' / 'ember-training-continuity-status-v1.json'


def utc_stamp(now: float | None = None) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() if now is None else now))


def build_snapshot(status: Mapping[str, Any], *, captured_at: str | None = None) -> dict[str, Any]:
    """The committed record: exactly the status dict, its capture time and the head it describes."""
    if status.get('schema') != STATUS_SCHEMA:
        raise ValueError(f'status schema must be {STATUS_SCHEMA}')
    head = status.get('lineage_checkpoint_manifest_sha256')
    if not isinstance(head, str) or not head:
        raise ValueError('status carries no lineage head digest')
    return {'schema_version': SNAPSHOT_SCHEMA, 'captured_at': captured_at or utc_stamp(), 'head_manifest_sha256': head,
            'status': dict(status)}


def write_snapshot(path: Path, snapshot: Mapping[str, Any]) -> Path:
    """Atomic replace (tmp + fsync + os.replace), LF line endings, sorted keys so the committed bytes are deterministic."""
    if snapshot.get('schema_version') != SNAPSHOT_SCHEMA:
        raise ValueError('not a continuity snapshot')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    data = (json.dumps(snapshot, indent=2, sort_keys=True) + '\n').encode('utf-8')
    with open(tmp, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    return path


def check_live(snapshot_path: Path, receipts_root: Path | None = None, *,
               current_head: Callable[[], str] | None = None) -> dict[str, Any]:
    """Compare the committed snapshot's head with the live selected head. `stale` is True when they differ. A missing or
    unreadable snapshot raises (the page refuses in the same case); the live-head reader is injected for tests, otherwise it is
    `selected_continuation_head.current_head_sha256(receipts_root)`."""
    snapshot = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != SNAPSHOT_SCHEMA:
        raise ValueError('not a continuity snapshot')
    if current_head is None:
        if receipts_root is None:
            raise ValueError('check_live needs a receipts root or a head reader')
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import selected_continuation_head
        live = selected_continuation_head.current_head_sha256(Path(receipts_root))
    else:
        live = current_head()
    return {'stale': live != snapshot['head_manifest_sha256'], 'snapshot_head': snapshot['head_manifest_sha256'],
            'live_head': live, 'captured_at': snapshot.get('captured_at')}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-live', action='store_true', help='exit 1 when the committed snapshot head is not the live selected head')
    parser.add_argument('--snapshot', default=str(DEFAULT_PATH))
    parser.add_argument('--receipts-root', required=True)
    args = parser.parse_args(argv)
    if not args.check_live:
        parser.error('writing a snapshot is a library call (build_snapshot/write_snapshot) made by the publication-boundary caller')
    verdict = check_live(Path(args.snapshot), Path(args.receipts_root))
    print(json.dumps(verdict, sort_keys=True))
    return 1 if verdict['stale'] else 0


if __name__ == '__main__':
    sys.exit(main())
