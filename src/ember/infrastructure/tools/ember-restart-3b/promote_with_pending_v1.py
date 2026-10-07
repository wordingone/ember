"""Production caller for the between-hours head move (#2119 row 15; ruling/review due 2026-10-07 03:00Z).

Class fix for the per-hour promote_hNN_v1.py scripts, which each called advance_selected_continuation_head directly and left the
pending-continuation record stale (a segment record for the OLD head reads BLOCKED for the new head). This caller moves the head ONLY through
pending_continuation.advance_and_record_pending (e0450bb3), so there is no second head write and the next-segment record is written for the new head in the same operation.
It is used between hours only, on ruling's ruling mail (--ruling=ID); the hour itself publishes a candidate and never calls a head mover.

  promote(spec, *, pending, sch, row)  -> dict outcome; raises SystemExit never (the CLI maps outcome['code'] to the exit status)
  python promote_with_pending_v1.py SPEC.json --ruling=ID

Spec (JSON, closed): repo_root, receipts_root, published_checkpoint_root, hour_result_path, expected_parent, expected_child, ledger,
and exactly one of next={training_job_purpose, run_id} or blocker. Outcome codes:
  0 PROMOTED_AND_RECORDED         pointer == expected_child AND the pending readback equals the requested record exactly: {'next_identity': {purpose, run_id}}
                                  for next, or {'blocker': <the requested text>} for blocker (a missing or stale record is never that blocker)
  4 REFUSED_BEFORE_MOVE           prevalidation, the head CAS, or the published-child check refused; pointer and pending bytes identical to before (asserted).
                                  The published child's manifest digest is re-derived from <published_checkpoint_root>/checkpoint-manifest.json and must
                                  equal expected_child BEFORE any mutation (review 63367 P1-2)
  7 LATE_WRITE_FAILURE            pointer moved, the pending write failed or its readback differs from the requested record: NO rollback claimed; the
                                  next-segment read is whatever the readback says (BLOCKED when missing/stale); mail ruling (review 63367 P2-5)
  6 MOVED_TO_UNEXPECTED_HEAD      pointer is not expected_child after a clean return
  8 PROMOTED_SNAPSHOT_FAILED      optional spec key snapshot={expected_genesis, custody_parent[, snapshot_path]}: the head moved and the pending record is exact, but
                                  the continuity page snapshot (continuity_snapshot_hook) was not written; rerun continuity_snapshot_hook.py, do not repeat the move
Run with the window marker absent (python).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SPEC_FIELDS = {'repo_root', 'receipts_root', 'published_checkpoint_root', 'hour_result_path', 'expected_parent', 'expected_child', 'ledger'}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_row(ledger):
    def row(**fields):
        fields['ts'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        with open(ledger, 'a', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(fields, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
    return row


def promote(spec, *, pending, sch, row, ruling, snapshot=None):
    extra = set(spec) - SPEC_FIELDS - {'next', 'blocker', 'snapshot'}
    missing = SPEC_FIELDS - set(spec)
    if extra or missing or ('next' in spec) == ('blocker' in spec):
        return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': f'spec not closed: missing={sorted(missing)} extra={sorted(extra)} next-xor-blocker={("next" in spec) != ("blocker" in spec)}'}
    if not ruling:
        return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'no --ruling (no self-granted advance)'}
    if 'snapshot' in spec:
        shot = spec['snapshot']
        if snapshot is None or not isinstance(shot, dict) or set(shot) - {'expected_genesis', 'custody_parent', 'snapshot_path'} or not {'expected_genesis', 'custody_parent'} <= set(shot):
            return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'snapshot spec must be {expected_genesis, custody_parent[, snapshot_path]} with a snapshot writer; refused before the move so a bad spec cannot land after it'}
        # Values, not just keys: a None or non-string path would raise inside the writer after the head moved.
        if (not isinstance(shot['expected_genesis'], str) or not re.fullmatch(r'[0-9a-f]{64}', shot['expected_genesis'])
                or not isinstance(shot['custody_parent'], str) or not shot['custody_parent']
                or ('snapshot_path' in shot and (not isinstance(shot['snapshot_path'], str) or not shot['snapshot_path']))):
            return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'snapshot spec values must be a 64-hex expected_genesis and non-empty string custody_parent / snapshot_path; refused before the move'}
    if not callable(getattr(pending, 'advance_and_record_pending', None)):
        return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'pending_continuation has no advance_and_record_pending (tree lacks e0450bb3)'}
    rr = Path(spec['receipts_root'])
    ptr = sch.pointer_path(rr)
    before = _sha(ptr) if ptr.exists() else None
    hr = Path(spec['hour_result_path'])
    kwargs = dict(repo_root=Path(spec['repo_root']), receipts_root=rr, published_checkpoint_root=Path(spec['published_checkpoint_root']),
                  hour_result_path=hr, hour_result_sha256=_sha(hr), expected_parent_checkpoint_manifest_sha256=spec['expected_parent'])
    if 'next' in spec:
        kwargs.update(training_job_purpose=spec['next']['training_job_purpose'], run_id=spec['next']['run_id'])
    else:
        kwargs.update(blocker=spec['blocker'])
    # Repair 2 (review 63367 P1): bind the re-derived published child to the approved expected_child BEFORE any mutation. The child head is the digest of
    # the published root's checkpoint-manifest.json (selected_continuation_head module doc, line 26). A spec naming child A over a published root for
    # child B refuses here with the pointer and pending bytes untouched. Parent CAS stays in advance_selected_continuation_head.
    manifest_path = Path(spec['published_checkpoint_root']) / 'checkpoint-manifest.json'
    try:
        derived_child = _sha(manifest_path)
    except OSError as error:
        return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': f'published child manifest unreadable before the move: {type(error).__name__}: {error}'}
    if derived_child != spec['expected_child']:
        out = {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': f'published child {derived_child} is not the approved expected_child {spec["expected_child"]}',
               'pointer_sha_before': before, 'pointer_sha_after': _sha(ptr) if ptr.exists() else None}
        row(kind='refuse_before_move', **{k: v for k, v in out.items() if k != 'code'})
        return out
    row(kind='intent', op='promote via advance_and_record_pending', ruling=ruling, pointer_sha_before=before, expected_parent=spec['expected_parent'],
        expected_child=spec['expected_child'], hour_result_sha256=kwargs['hour_result_sha256'], next=spec.get('next'), blocker=spec.get('blocker'))
    try:
        pending.advance_and_record_pending(**kwargs)
    except Exception as error:  # noqa: BLE001 - classified below by what the disk says, never by the exception type
        current = sch.current_head_sha256(rr)
        if current == spec['expected_child']:
            after_read = pending.read_pending_continuation(rr, current_head_sha256=current)
            out = {'code': 7, 'status': 'LATE_WRITE_FAILURE', 'why': f'{type(error).__name__}: {error}', 'head': current,
                   'next_segment_read': after_read, 'rollback': 'none claimed'}
            row(kind='LATE_WRITE_FAILURE', **{k: v for k, v in out.items() if k != 'code'})
            return out
        after = _sha(ptr) if ptr.exists() else None
        out = {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': f'{type(error).__name__}: {error}', 'pointer_sha_before': before,
               'pointer_sha_after': after, 'pointer_bytes_identical': before == after}
        row(kind='refuse_before_move', **{k: v for k, v in out.items() if k != 'code'})
        if before != after:
            out.update(code=6, status='POINTER_CHANGED_ON_REFUSAL')
        return out
    current = sch.current_head_sha256(rr)
    read = pending.read_pending_continuation(rr, current_head_sha256=current)
    ok = current == spec['expected_child']
    # Repair 5 (review 63367 P2): success needs the COMPLETE readback to equal the requested record: the requested next identity, or the explicitly requested
    # blocker text. A missing/stale blocker, or a different next identity, is a late-write failure (code 7, no rollback claimed), never code 0.
    wanted = ({'next_identity': {'training_job_purpose': spec['next']['training_job_purpose'], 'run_id': spec['next']['run_id']}}
              if 'next' in spec else {'blocker': spec['blocker']})
    if ok and read != wanted:
        out = {'code': 7, 'status': 'LATE_WRITE_FAILURE', 'why': 'pending readback does not equal the requested record', 'head': current,
               'pointer_sha_after': _sha(ptr), 'requested_readback': wanted, 'next_segment_read': read, 'rollback': 'none claimed'}
        row(kind='LATE_WRITE_FAILURE', **{k: v for k, v in out.items() if k != 'code'})
        return out
    out = {'code': 0 if ok else 6, 'status': 'PROMOTED_AND_RECORDED' if ok else 'MOVED_TO_UNEXPECTED_HEAD', 'head': current,
           'pointer_sha_after': _sha(ptr), 'next_segment_read': read}
    row(kind='promote_outcome', **{k: v for k, v in out.items() if k != 'code'})
    if ok and 'snapshot' in spec:
        # Row 8: the page snapshot is written at this boundary. The head has moved, so a failure is code 8 (loud), never a rollback or a retry of the move.
        shot_spec = {**spec['snapshot'], 'published_checkpoint_root': spec['published_checkpoint_root'], 'hour_result_path': spec['hour_result_path'],
                     'receipts_root': spec['receipts_root']}
        if 'next' in spec:
            shot_spec['next'] = spec['next']
        else:
            shot_spec['blocker'] = spec['blocker']
        try:
            out['snapshot'] = snapshot(shot_spec)
        except Exception as error:  # noqa: BLE001 - the head already moved: a raising writer must still reach the outcome row and code 8
            out['snapshot'] = {'status': 'FAILED', 'why': f'{type(error).__name__}: {error}'}
        row(kind='snapshot_outcome', **out['snapshot'])
        if out['snapshot']['status'] != 'WRITTEN':
            out.update(code=8, status='PROMOTED_SNAPSHOT_FAILED')
    return out


def main(argv):
    marker = os.environ.get('EMBER_GPU_WINDOW_MARKER')
    if marker and Path(marker).exists():
        print('REFUSE: gpu-window-open exists')
        return 2
    args = [a for a in argv if not a.startswith('--')]
    ruling = next((a.split('=', 1)[1] for a in argv if a.startswith('--ruling=')), None)
    if len(args) != 1:
        print('usage: promote_with_pending_v1.py SPEC.json --ruling=ID')
        return 2
    spec = json.loads(Path(args[0]).read_text(encoding='utf-8'))
    sys.path.insert(0, str(Path(spec['repo_root']) / 'src/ember/infrastructure/tools/ember-restart-3b'))
    import pending_continuation as pending  # noqa: E402
    import selected_continuation_head as sch  # noqa: E402
    import continuity_snapshot_hook as hook  # noqa: E402
    out = promote(spec, pending=pending, sch=sch, row=make_row(spec['ledger']), ruling=ruling, snapshot=hook.publish_from_spec)
    print(json.dumps(out, sort_keys=True, default=str))
    return out['code']


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
