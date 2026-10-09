"""Production caller for the between-hours head move (#2119 row 15; ruling/review due 2026-10-07 03:00Z).

Class fix for the per-hour promote_hNN_v1.py scripts, which each called advance_selected_continuation_head directly and left the
pending-continuation record stale (a segment record for the OLD head reads BLOCKED for the new head). This caller moves the head ONLY through
pending_continuation.advance_and_record_pending (e0450bb3), so there is no second head write and the next-segment record is written for the new head in the same operation.
It is used between hours only, on ruling's ruling mail (--ruling=ID); the hour itself publishes a candidate and never calls a head mover.

  promote(spec, *, pending, sch, row)  -> dict outcome; raises SystemExit never (the CLI maps outcome['code'] to the exit status)
  python promote_with_pending_v1.py SPEC.json --ruling=ID

Spec (JSON, closed): repo_root, receipts_root, published_checkpoint_root, hour_result_path, expected_parent, expected_child, ledger,
score_receipt, score_receipt_sha256, and exactly one of next={training_job_purpose, run_id} or blocker. The score receipt is checked here with
post_hour_promotion_gate.cadence_problems (scorer-v12 receipt with scores for exactly expected_child on the frozen plan, bytes hashing to the cited
digest) BEFORE any move, so a head cannot advance on a header, a wrong digest, another child or another plan. The only declared override is the optional
score_plan_sha256: a scored-pair run scores on its own frozen entry's plan and its route names that plan. That plan carries its provenance in
score_plan_binding {entry[, entry_sha256]}: the frozen prelaunch entry must hash to the scored_pair_binding_sha256 that the RUN's frozen identity holds. The
mover reads that identity itself: <hour_result_path's directory>/prediction.json (bytes hashing to the hour result's prediction_sha256) carries `identity`, a
RETENTION_ELIGIBLE_EXPERIMENT identity with the digest. A caller-named entry_sha256 is only compared with it and refused on disagreement; it is never the
anchor. The entry must name the declared plan and the head being advanced from. A plan other than the cadence plan with no binding, with no readable run
identity, or with a binding that does not match is refused before any move. Outcome codes:
  0 PROMOTED_AND_RECORDED         pointer == expected_child AND the pending readback equals the requested record exactly: {'next_identity': {purpose, run_id}}
                                  for next, or {'blocker': <the requested text>} for blocker (a missing or stale record is never that blocker)
  4 REFUSED_BEFORE_MOVE           prevalidation, the head CAS, or the published-child check refused; pointer and pending bytes identical to before (asserted).
                                  The published child's manifest digest is re-derived from <published_checkpoint_root>/checkpoint-manifest.json and must
                                  equal expected_child BEFORE any mutation (review 63367 P1-2)
  7 LATE_WRITE_FAILURE            pointer moved, the pending write failed or its readback differs from the requested record: NO rollback claimed; the
                                  next-segment read is whatever the readback says (BLOCKED when missing/stale); mail ruling (review 63367 P2-5)
  6 MOVED_TO_UNEXPECTED_HEAD      pointer is not expected_child after a clean return
  8 PROMOTED_SNAPSHOT_FAILED      optional spec key snapshot={expected_genesis, custody_parent[, snapshot_path][, page_path][, gpu_window_marker][, measurement_receipt][, hold_record]}: the head moved and the pending record is exact, but
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

SPEC_FIELDS = {'repo_root', 'receipts_root', 'published_checkpoint_root', 'hour_result_path', 'expected_parent', 'expected_child', 'ledger',
               'score_receipt', 'score_receipt_sha256'}
# The one declared override of the cadence's frozen plan: a scored-pair run scores on its own frozen entry's plan, so its route may name that plan here.
# Nothing else about the check changes (schema, scorer marker, scores, exact child, digest).
SPEC_OPTIONAL = {'next', 'blocker', 'snapshot', 'score_plan_sha256', 'score_plan_binding'}
# A declared plan other than the cadence plan is accepted only with its provenance: the frozen prelaunch scored-pair entry whose bytes hash to the digest the
# RUN's identity froze (scored_pair_binding_sha256), read by this mover from the child's custody (prediction.json, bound by the hour result), never from the
# caller. The plan must be that entry's own episode plan and the entry's parent must be the head being advanced from.
PLAN_BINDING_KEYS = {'entry'}
PLAN_BINDING_OPTIONAL = {'entry_sha256'}
SCORED_PAIR_PURPOSE = 'RETENTION_ELIGIBLE_EXPERIMENT'
PREDICTION_FILENAME = 'prediction.json'
HERE = Path(__file__).resolve().parent


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


# the hook already accepts these; the production caller whitelisted four of them, so a real hour could not bind the frozen claim predicate or a ruling
SNAPSHOT_OPTIONAL_STRINGS = ('snapshot_path', 'page_path', 'claim_predicate', 'candidate_record', 'ruling_log', 'ruling_id', 'refusal_receipt',
                             'gpu_window_marker', 'measurement_receipt', 'hold_record')
SNAPSHOT_KEYS = {'expected_genesis', 'custody_parent', *SNAPSHOT_OPTIONAL_STRINGS}


def run_identity(spec):
    """(identity, None) for the RUN's frozen scored-pair identity, or (None, why) when the standalone path cannot read one. The identity is read here, from
    the published child's custody: <hour_result_path's directory>/prediction.json, whose bytes must hash to the hour result's prediction_sha256, holds
    `identity`. The hour result itself must sit in the published child's own custody directory (next to published_checkpoint_root) and name that child's
    manifest digest, so a caller cannot supply a separate self-consistent receipt group for the same child."""
    hour = Path(spec['hour_result_path'])
    root = Path(spec['published_checkpoint_root'])
    try:
        in_custody = hour.resolve(strict=True).parent == root.resolve(strict=True).parent
        hour_doc = json.loads(hour.read_bytes())
        raw = (hour.parent / PREDICTION_FILENAME).read_bytes()
        prediction = json.loads(raw)
        derived_child = _sha(root / 'checkpoint-manifest.json')
    except (OSError, ValueError) as error:
        return None, f'no run identity can be read from the child custody ({type(error).__name__}): a plan other than the cadence plan is refused'
    # The hour result and the prediction beside it must be the published child's OWN custody, not a self-consistent group the caller points at: the hour
    # result sits next to the published child root (the measurement directory the hour wrote) and names that child's manifest digest.
    if not in_custody:
        return None, 'the hour result is not in the own custody directory of the published child (next to published_checkpoint_root): a foreign receipt group is refused'
    if not isinstance(hour_doc, dict) or hour_doc.get('child_manifest_sha256') != derived_child:
        return None, 'the hour result does not name the manifest digest of the published child: it is the receipt of another child'
    if not isinstance(hour_doc, dict) or not isinstance(prediction, dict) or hour_doc.get('prediction_sha256') != hashlib.sha256(raw).hexdigest():
        return None, f'{PREDICTION_FILENAME} in the child custody does not hash to the hour result\'s prediction_sha256: a plan other than the cadence plan is refused'
    identity = prediction.get('identity')
    if not isinstance(identity, dict) or identity.get('training_job_purpose') != SCORED_PAIR_PURPOSE:
        return None, f'the run identity is not a {SCORED_PAIR_PURPOSE} identity: it froze no scored-pair entry, so a plan other than the cadence plan is refused'
    digest = identity.get('scored_pair_binding_sha256')
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        return None, 'the run identity carries no sha256 scored_pair_binding_sha256'
    return identity, None


def plan_binding_problem(spec):
    """Why the declared score plan has no provenance (None = the cadence plan, or the plan of a frozen entry bound as above). Reads bytes only."""
    declared, binding = spec.get('score_plan_sha256'), spec.get('score_plan_binding')
    if declared is None and binding is None:
        return None
    if declared is None:
        return 'score_plan_binding names no score_plan_sha256 to bind'
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import post_hour_promotion_gate as cadence  # noqa: E402
    import scored_pair_entry as entry_mod  # noqa: E402
    if binding is None:
        if declared == cadence.CADENCE_PLAN_SHA256:
            return None
        return ('a declared score_plan_sha256 other than the cadence plan has no frozen-entry provenance: the frozen plan must come with '
                'score_plan_binding {entry} (the prelaunch entry whose digest the run identity froze)')
    if (not isinstance(binding, dict) or not PLAN_BINDING_KEYS <= set(binding) <= PLAN_BINDING_KEYS | PLAN_BINDING_OPTIONAL
            or not isinstance(binding['entry'], str) or not binding['entry']
            or ('entry_sha256' in binding and (not isinstance(binding['entry_sha256'], str) or re.fullmatch(r'[0-9a-f]{64}', binding['entry_sha256']) is None))):
        return 'score_plan_binding must be {entry: path[, entry_sha256: 64-hex]}'
    identity, problem = run_identity(spec)
    if problem is not None:
        return problem
    digest = identity[entry_mod.IDENTITY_DIGEST_FIELD]
    if 'entry_sha256' in binding and binding['entry_sha256'] != digest:
        return (f'the caller-named entry_sha256 {binding["entry_sha256"][:8]} is not the scored_pair_binding_sha256 {digest[:8]} that the run identity froze: '
                'a self-consistent foreign entry is not this run\'s entry')
    try:
        entry = entry_mod.load_frozen_binding({entry_mod.IDENTITY_DIGEST_FIELD: digest}, Path(binding['entry']))
    except entry_mod.ScoredPairRefusal as error:
        return f'the frozen entry behind the declared plan is refused: {error}'
    if entry['bindings']['episode_plan_sha256'] != declared:
        return f'the declared score plan {str(declared)[:8]} is not the frozen plan of its entry {entry["bindings"]["episode_plan_sha256"][:8]}'
    if entry['parent_manifest_sha256'] != spec.get('expected_parent'):
        return 'the frozen entry names a different parent than the head being advanced from'
    return None


def promote(spec, *, pending, sch, row, ruling, snapshot=None):
    extra = set(spec) - SPEC_FIELDS - SPEC_OPTIONAL
    missing = SPEC_FIELDS - set(spec)
    if extra or missing or ('next' in spec) == ('blocker' in spec):
        return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': f'spec not closed: missing={sorted(missing)} extra={sorted(extra)} next-xor-blocker={("next" in spec) != ("blocker" in spec)}'}
    if not ruling:
        return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'no --ruling (no self-granted advance)'}
    # Row 20 enforced at the head mover itself, not only in the dispatch gate: "a missing score receipt means no advance". The receipt must be a scorer-v12
    # receipt with scores, for exactly expected_child, on the frozen plan (or the one plan the caller declares), and hash to the cited digest. Refused before
    # the intent row, the pointer read and any move, so the selected head and the pending record stay as they were.
    if not all(isinstance(spec[name], str) and spec[name] for name in ('score_receipt', 'score_receipt_sha256')):
        return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'score_receipt and score_receipt_sha256 must be non-empty strings: a missing score receipt means no advance'}
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import post_hour_promotion_gate as cadence  # noqa: E402
    provenance = plan_binding_problem(spec)
    if provenance is not None:
        out = {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'score plan has no frozen-entry provenance: ' + provenance}
        row(kind='refuse_before_move', **{k: v for k, v in out.items() if k != 'code'})
        return out
    problems = cadence.cadence_problems(spec['expected_child'], Path(spec['score_receipt']), spec['score_receipt_sha256'],
                                        plan_sha256=spec.get('score_plan_sha256', cadence.CADENCE_PLAN_SHA256))
    if problems:
        out = {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'score receipt refused: ' + '; '.join(problems), 'score_receipt': spec['score_receipt'],
               'score_receipt_sha256': spec['score_receipt_sha256']}
        row(kind='refuse_before_move', **{k: v for k, v in out.items() if k != 'code'})
        return out
    if 'snapshot' in spec:
        shot = spec['snapshot']
        if snapshot is None or not isinstance(shot, dict) or set(shot) - SNAPSHOT_KEYS or not {'expected_genesis', 'custody_parent'} <= set(shot):
            return {'code': 4, 'status': 'REFUSED_BEFORE_MOVE', 'why': 'snapshot spec must be {expected_genesis, custody_parent[, snapshot_path][, page_path][, claim_predicate][, candidate_record][, ruling_log][, ruling_id][, refusal_receipt][, gpu_window_marker][, measurement_receipt][, hold_record]} with a snapshot writer; refused before the move so a bad spec cannot land after it'}
        # Values, not just keys: a None or non-string path would raise inside the writer after the head moved.
        if (not isinstance(shot['expected_genesis'], str) or not re.fullmatch(r'[0-9a-f]{64}', shot['expected_genesis'])
                or not isinstance(shot['custody_parent'], str) or not shot['custody_parent']
                or any(name in shot and (not isinstance(shot[name], str) or not shot[name]) for name in SNAPSHOT_OPTIONAL_STRINGS)
                or (('ruling_id' in shot) != ('ruling_log' in shot and 'refusal_receipt' in shot))):
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
        if out['snapshot']['status'] != 'WRITTEN' or out['snapshot'].get('page', {}).get('status') == 'FAILED':
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
