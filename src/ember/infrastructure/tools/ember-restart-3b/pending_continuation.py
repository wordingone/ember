"""Issue #2119 row 15: the durable pending-continuation record (`next-segment.json`).

The status producer used to take the next segment (`next_identity`) or its blocker (`next_blocker`) from its caller, so a fresh
process that had only the disk could not say what was queued next. This record keeps that fact beside the selected-head
pointer, written under the SAME lock the pointer uses (row 6b) so a pointer advance and a pending write never interleave.

Closed schema `ember-next-segment-v1`:
  ready:   schema, lineage_checkpoint_manifest_sha256, status='ready',   training_job_purpose, run_id, written_at
  blocked: schema, lineage_checkpoint_manifest_sha256, status='blocked', blocker, written_at
`lineage_checkpoint_manifest_sha256` is the head the record was written for. A reader given a different current head reports
BLOCKED ("no next segment recorded for the current head"), never ready. A missing record reads blocked; a record that is
not valid JSON, has the wrong schema, extra or missing fields, or a bad value is REFUSED, never read as ready.

Stdlib only; reuses selected_continuation_head's pointer lock and pointer reader.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import selected_continuation_head as head_pointer

SCHEMA = 'ember-next-segment-v1'
FILENAME = 'next-segment.json'
READY = 'ready'
BLOCKED = 'blocked'
MISSING_BLOCKER = 'no pending-continuation record'
STALE_BLOCKER = 'no next segment recorded for the current head'
_COMMON = {'schema', 'lineage_checkpoint_manifest_sha256', 'status', 'written_at'}
_READY_FIELDS = _COMMON | {'training_job_purpose', 'run_id'}
_BLOCKED_FIELDS = _COMMON | {'blocker'}


class PendingContinuationRefusal(ValueError):
    """The pending record is corrupt, malformed or being written for a head that is not current."""


def pending_path(receipts_root: Path) -> Path:
    return Path(receipts_root) / FILENAME


def _is_head(value: Any) -> bool:
    return isinstance(value, str) and (value == head_pointer.GENESIS_SENTINEL or (len(value) == 64 and all(c in '0123456789abcdef' for c in value)))


def validate_record(payload: Any) -> dict[str, Any]:
    """Closed-schema validation; raises PendingContinuationRefusal naming the first defect."""
    if not isinstance(payload, dict):
        raise PendingContinuationRefusal('pending-continuation record is not an object')
    if payload.get('schema') != SCHEMA:
        raise PendingContinuationRefusal(f'pending-continuation schema must be {SCHEMA!r}')
    status = payload.get('status')
    if status not in (READY, BLOCKED):
        raise PendingContinuationRefusal("pending-continuation status must be 'ready' or 'blocked'")
    if set(payload) != (_READY_FIELDS if status == READY else _BLOCKED_FIELDS):
        raise PendingContinuationRefusal('pending-continuation fields are not closed for its status')
    if not _is_head(payload['lineage_checkpoint_manifest_sha256']):
        raise PendingContinuationRefusal('pending-continuation head must be a sha256 hex string or GENESIS')
    written = payload['written_at']
    if not isinstance(written, (int, float)) or isinstance(written, bool):
        raise PendingContinuationRefusal('pending-continuation written_at must be numeric')
    texts = ('training_job_purpose', 'run_id') if status == READY else ('blocker',)
    for name in texts:
        if not isinstance(payload[name], str) or not payload[name].strip():
            raise PendingContinuationRefusal(f'pending-continuation {name} must be a non-empty string')
    return payload


def _pending_candidate(
    *, lineage_checkpoint_manifest_sha256: str,
    training_job_purpose: str | None, run_id: str | None, blocker: str | None,
    now: float | None,
) -> dict[str, Any]:
    """Validate a pending record before any caller mutates the selected-head pointer."""
    ready = training_job_purpose is not None or run_id is not None
    if ready == (blocker is not None):
        raise PendingContinuationRefusal('write needs exactly one of (training_job_purpose and run_id) or blocker')
    candidate: dict[str, Any] = {
        'schema': SCHEMA, 'lineage_checkpoint_manifest_sha256': lineage_checkpoint_manifest_sha256,
        'status': READY if ready else BLOCKED, 'written_at': time.time() if now is None else now,
    }
    if ready:
        candidate.update(training_job_purpose=training_job_purpose, run_id=run_id)
    else:
        candidate['blocker'] = blocker
    return validate_record(candidate)


def write_pending_continuation(
    receipts_root: Path, *, lineage_checkpoint_manifest_sha256: str,
    training_job_purpose: str | None = None, run_id: str | None = None, blocker: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Atomically write the record for the CURRENT head. Exactly one of (purpose and run_id) or blocker.

    The current head is re-read under the pointer lock; a record for any other head is refused before any byte is written,
    so a stale writer cannot publish a ready segment for a head the pointer has already left."""
    receipts_root = Path(receipts_root)
    candidate = _pending_candidate(
        lineage_checkpoint_manifest_sha256=lineage_checkpoint_manifest_sha256,
        training_job_purpose=training_job_purpose, run_id=run_id, blocker=blocker, now=now,
    )
    target = pending_path(receipts_root)
    with head_pointer._pointer_lock(head_pointer.pointer_path(receipts_root)):
        current = head_pointer.current_head_sha256(receipts_root)
        if current != lineage_checkpoint_manifest_sha256:
            raise PendingContinuationRefusal(
                f'refusing to record a pending segment for head {lineage_checkpoint_manifest_sha256!r}: the selected head is {current!r}')
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.parent / f'.{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp'
        try:
            with open(staged, 'xb') as handle:
                handle.write((json.dumps(candidate, indent=2, sort_keys=True) + '\n').encode('utf-8'))
                handle.flush()
                os.fsync(handle.fileno())
            validate_record(json.loads(staged.read_text(encoding='utf-8')))
            os.replace(staged, target)
        finally:
            try:
                staged.unlink()
            except FileNotFoundError:
                pass
    return candidate

def advance_and_record_pending(
    *, repo_root: Path, receipts_root: Path, published_checkpoint_root: Path,
    hour_result_path: Path, hour_result_sha256: str,
    expected_parent_checkpoint_manifest_sha256: str,
    training_job_purpose: str | None = None, run_id: str | None = None,
    blocker: str | None = None, now: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Advance a verified published head, then record the next identity/blocker for that new head.

    The next record is validated against the expected parent before advancing, so invalid dispatch
    inputs cannot move the pointer. The two durable writes use their existing compare-and-swap
    locks. If another writer races between them or the pending write fails, the selected pointer
    may already name the new head, but the old/missing pending record will read BLOCKED for that
    head; it cannot appear ready for the wrong lineage.
    """
    _pending_candidate(
        lineage_checkpoint_manifest_sha256=expected_parent_checkpoint_manifest_sha256,
        training_job_purpose=training_job_purpose, run_id=run_id, blocker=blocker, now=now,
    )
    selected_head = head_pointer.advance_selected_continuation_head(
        repo_root=repo_root,
        receipts_root=receipts_root,
        published_checkpoint_root=published_checkpoint_root,
        hour_result_path=hour_result_path,
        hour_result_sha256=hour_result_sha256,
        expected_parent_checkpoint_manifest_sha256=expected_parent_checkpoint_manifest_sha256,
        now=now,
    )
    pending_record = write_pending_continuation(
        receipts_root,
        lineage_checkpoint_manifest_sha256=selected_head['lineage_checkpoint_manifest_sha256'],
        training_job_purpose=training_job_purpose,
        run_id=run_id,
        blocker=blocker,
        now=now,
    )
    return {'selected_head': selected_head, 'pending_continuation': pending_record}


def read_pending_continuation(receipts_root: Path, *, current_head_sha256: str) -> dict[str, Any]:
    """The disk's answer, shaped for `training_continuity_status.next_segment_status`: either
    {'next_identity': {training_job_purpose, run_id}} or {'blocker': reason}. Holds no state between calls."""
    path = pending_path(receipts_root)
    if not path.is_file():
        return {'blocker': MISSING_BLOCKER}
    try:
        record = validate_record(json.loads(path.read_text(encoding='utf-8')))
    except json.JSONDecodeError as exc:
        raise PendingContinuationRefusal(f'pending-continuation record is not valid JSON: {exc}') from exc
    if record['lineage_checkpoint_manifest_sha256'] != current_head_sha256:
        return {'blocker': STALE_BLOCKER}
    if record['status'] == BLOCKED:
        return {'blocker': record['blocker']}
    return {'next_identity': {'training_job_purpose': record['training_job_purpose'], 'run_id': record['run_id']}}


def main(argv: list[str] | None = None) -> int:
    """The lawful command-line writer and reader (row 15). `write` records the next segment, or its blocker, for the CURRENT head only: it goes through
    write_pending_continuation (the pointer lock, a head re-read under it, a closed-schema record, an atomic replace) and never moves the pointer.
    `read` prints what a fresh interpreter sees for the head (default: the live pointer's head). Exit 0 done, 3 refused."""
    import argparse
    parser = argparse.ArgumentParser(description=main.__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    write = sub.add_parser('write')
    write.add_argument('--receipts-root', required=True, type=Path)
    write.add_argument('--head', required=True, help='the lineage head the record is for; refused unless it is the pointer\'s current head')
    write.add_argument('--purpose')
    write.add_argument('--run-id')
    write.add_argument('--blocker')
    read = sub.add_parser('read')
    read.add_argument('--receipts-root', required=True, type=Path)
    read.add_argument('--head', help='default: the pointer\'s current head')
    args = parser.parse_args(argv)
    try:
        if args.command == 'write':
            record = write_pending_continuation(args.receipts_root, lineage_checkpoint_manifest_sha256=args.head,
                                                training_job_purpose=args.purpose, run_id=args.run_id, blocker=args.blocker)
            print(json.dumps({'status': 'WRITTEN', 'record': record, 'path': str(pending_path(args.receipts_root))}, sort_keys=True))
        else:
            head = args.head or head_pointer.current_head_sha256(args.receipts_root)
            print(json.dumps({'head': head, 'read': read_pending_continuation(args.receipts_root, current_head_sha256=head)}, sort_keys=True))
    except (PendingContinuationRefusal, ValueError) as error:
        print(json.dumps({'status': 'REFUSED', 'error': f'{type(error).__name__}: {error}'}, sort_keys=True))
        return 3
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
