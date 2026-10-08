"""Issue #2119 row 8 (hook half): write the committed continuity snapshot at the publication boundary.

`continuity_snapshot.py` builds and atomically writes `manifests/ember-training-continuity-status-v1.json`, the one file the continuity
page renders; nothing called it. This hook is that call. It runs after the between-hours head move (promote_with_pending_v1), never
inside a training step: it walks the lineage ancestry from the published head, composes `training_continuity_status` for that head, and
writes the snapshot. The write is a working-tree change; committing it is the publication step, because the merge gate renders only
committed files.

The hook never raises. The head has already moved when it runs, so a failure is returned as `{'status': 'FAILED', 'why': ...}` for the
caller to make loud, and the page stays visibly stale (`continuity_snapshot.check_live` reports the old head) instead of silently
describing a head that is no longer current.

  publish_snapshot(...)  -> {'status': 'WRITTEN', 'path', 'head', 'captured_at'} | {'status': 'FAILED', 'why'}
  python continuity_snapshot_hook.py SPEC.json     (rerun after a FAILED outcome; exit 0 WRITTEN, 8 FAILED)
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

SPEC_FIELDS = {'published_checkpoint_root', 'hour_result_path', 'expected_genesis', 'custody_parent'}
SPEC_OPTIONAL = {'snapshot_path', 'receipts_root', 'next', 'blocker', 'claim_predicate', 'candidate_record', 'ruling_log', 'ruling_id',
                 'refusal_receipt', 'private_path', 'page_path'}


def publish_snapshot(*, head_directory: Path, hour_result_path: Path, expected_genesis_manifest_sha256: str,
                     custody_parent: Path, snapshot_path: Path | None = None, pending_receipts_root: Path | None = None,
                     next_identity: Mapping[str, Any] | None = None, next_blocker: str | None = None,
                     now: float | None = None, claim_predicate: Path | None = None, receipts_root: Path | None = None,
                     candidate_record: Path | None = None, ruling_log: Path | None = None, ruling_id: str | None = None,
                     refusal_receipt: Path | None = None, private_path: Path | None = None,
                     page_path: Path | None = None) -> dict[str, Any]:
    """`claim_predicate` (the approved frozen file; its bytes must hash to claim_accounting.PREDICATE_SHA256) makes the claim-budget section
    UNDETERMINED with its missing evidence named instead of UNDEFINED. The candidate audit reads `candidate_record` (default
    `receipts_root/candidate-continuation-head.json`) and, when `ruling_id` is given, the RULED row in `ruling_log` and the `refusal_receipt` it cites;
    a caller's `next_blocker` text never feeds it. `private_path` also writes the audit with full local paths (never committed).
    `page_path` (needs `receipts_root`) regenerates the live continuity page from the live pointer, this hour result and the new snapshot right
    after the snapshot write (`continuity_page_live`); the page says STALE if any input is missing or older, and a failure to write it is
    reported in `outcome['page']` without undoing the snapshot."""
    try:
        import continuity_snapshot
        import lineage_candidate_audit
        import training_continuity_status
        import training_lineage_ancestry
        hour_result = json.loads(Path(hour_result_path).read_text(encoding='utf-8'))
        record = training_lineage_ancestry.walk_lineage(
            head_directory, expected_genesis_manifest_sha256=expected_genesis_manifest_sha256)
        status = training_continuity_status.training_continuity_status(
            custody_parent=Path(custody_parent), hour_result=hour_result, current_identity=None, measurement=None,
            next_identity=next_identity, next_blocker=next_blocker, lineage_record=record,
            pending_receipts_root=pending_receipts_root, now=now,
            claim_predicate_path=Path(claim_predicate) if claim_predicate is not None else None)
        if candidate_record is None and receipts_root is not None:
            candidate_record = Path(receipts_root) / 'candidate-continuation-head.json'
        audit = lineage_candidate_audit.audit_candidate(
            candidate_record_path=candidate_record, lineage_record=record, ruling_log_path=ruling_log, ruling_id=ruling_id,
            refusal_receipt_path=refusal_receipt)
        if private_path is not None:
            continuity_snapshot.write_snapshot(Path(private_path), continuity_snapshot.build_snapshot(status, candidate_audit=audit))
        snapshot = continuity_snapshot.build_snapshot(status, candidate_audit=lineage_candidate_audit.public_view(audit))
        path = continuity_snapshot.write_snapshot(
            Path(snapshot_path) if snapshot_path is not None else continuity_snapshot.DEFAULT_PATH, snapshot)
    except Exception as error:  # noqa: BLE001 - the head already moved; report, never raise
        return {'status': 'FAILED', 'why': f'{type(error).__name__}: {error}'}
    outcome = {'status': 'WRITTEN', 'path': str(path), 'head': snapshot['head_manifest_sha256'], 'captured_at': snapshot['captured_at']}
    if page_path is not None:
        try:
            if receipts_root is None:
                raise ValueError('page_path needs receipts_root: the live head is read from the pointer, never from this snapshot')
            import continuity_page_live
            verdict = continuity_page_live.generate_live_page(snapshot_path=path, receipts_root=Path(receipts_root), out_path=Path(page_path),
                                                              receipt_paths=[Path(hour_result_path)])
            outcome['page'] = {'status': 'WRITTEN', 'path': str(page_path), 'state': verdict['state'], 'reasons': verdict['reasons']}
        except Exception as error:  # noqa: BLE001 - the snapshot is already written; report
            outcome['page'] = {'status': 'FAILED', 'why': f'{type(error).__name__}: {error}'}
    return outcome


def publish_from_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return _publish_from_spec(spec)
    except Exception as error:  # noqa: BLE001 - a wrong-typed spec value must be a FAILED result, never a raise after the head moved
        return {'status': 'FAILED', 'why': f'{type(error).__name__}: {error}'}


def _publish_from_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    extra = set(spec) - SPEC_FIELDS - SPEC_OPTIONAL
    missing = SPEC_FIELDS - set(spec)
    if extra or missing or ('next' in spec and 'blocker' in spec):
        return {'status': 'FAILED', 'why': f'snapshot spec not closed: missing={sorted(missing)} extra={sorted(extra)}'}
    for name in ('published_checkpoint_root', 'hour_result_path', 'custody_parent', 'snapshot_path', 'claim_predicate', 'candidate_record',
                 'ruling_log', 'ruling_id', 'refusal_receipt', 'private_path', 'page_path'):
        if name in spec and (not isinstance(spec[name], str) or not spec[name]):
            return {'status': 'FAILED', 'why': f'snapshot spec {name} must be a non-empty string; a present value is never replaced by the default'}
    receipts_root = spec.get('receipts_root')
    explicit = spec.get('next') is not None or spec.get('blocker') is not None
    if receipts_root is None and not explicit:
        return {'status': 'FAILED', 'why': 'snapshot spec names neither receipts_root (pending record), next, nor blocker'}
    return publish_snapshot(
        head_directory=Path(spec['published_checkpoint_root']), hour_result_path=Path(spec['hour_result_path']),
        expected_genesis_manifest_sha256=spec['expected_genesis'], custody_parent=Path(spec['custody_parent']),
        snapshot_path=Path(spec['snapshot_path']) if 'snapshot_path' in spec else None,
        pending_receipts_root=Path(receipts_root) if receipts_root and not explicit else None,
        next_identity=spec.get('next'), next_blocker=spec.get('blocker'),
        claim_predicate=Path(spec['claim_predicate']) if 'claim_predicate' in spec else None,
        receipts_root=Path(receipts_root) if receipts_root else None,
        candidate_record=Path(spec['candidate_record']) if 'candidate_record' in spec else None,
        ruling_log=Path(spec['ruling_log']) if 'ruling_log' in spec else None, ruling_id=spec.get('ruling_id'),
        refusal_receipt=Path(spec['refusal_receipt']) if 'refusal_receipt' in spec else None,
        private_path=Path(spec['private_path']) if 'private_path' in spec else None,
        page_path=Path(spec['page_path']) if 'page_path' in spec else None)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print('usage: continuity_snapshot_hook.py SPEC.json')
        return 2
    out = publish_from_spec(json.loads(Path(args[0]).read_text(encoding='utf-8')))
    print(json.dumps(out, sort_keys=True))
    return 0 if out['status'] == 'WRITTEN' else 8


if __name__ == '__main__':
    sys.exit(main())
