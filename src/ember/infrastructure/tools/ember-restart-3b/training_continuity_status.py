"""Issue #2119 section 6: a training-continuity status producer.

Composes read-only status that answers "where is this lineage, right now" from sources already
produced elsewhere in this tool: a governed hour-result (or the GENESIS bootstrap case) for the
selected checkpoint and its parent, the diagnostic-allowance ledger (`training_continuity_ledger`)
for occupancy and postponement against the same policy the reservation gate enforces, and the
identity of whatever is currently dispatched or queued next.

This is a different concept from gen_readme_status.py's CURRENT_SUBJECT_FIELDS, which reports
model-birth / capability-credit status for the public record. This module reports training
CONTINUITY status: selected checkpoint and parent, retained applied targets, the last learning
measurement or "pending", the current declared purpose, diagnostic occupancy and postponement,
and the next segment or its blocker. Every input is caller-supplied and already verified by its
own producer (the hour result is bound-read by cia_hour.py, the ledger rows are read verbatim by
training_continuity_ledger.read_rows) -- this module performs no independent verification and no
filesystem discovery beyond the one ledger read every caller already needs.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pending_continuation
from training_continuity_ledger import (
    GENESIS_SENTINEL,
    diagnostic_occupancy_seconds,
    ledger_path,
    load_policy,
    require_authority_reference,
    postponement_seconds,
    read_rows,
)

STATUS_SCHEMA = 'ember-training-continuity-status-v2'
LINEAGE_SCHEMA = 'ember-training-lineage-ancestry-v1'  # training_lineage_ancestry.SCHEMA; compared, not imported, to keep this module torch- and walk-free
UNDEFINED = 'UNDEFINED'
CLAIM_PREDICATE_MISSING = 'frozen claim-budget predicate file (ruling mail 51039: contract owner is the data lane; the lead rules)'


def lineage_status(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Retained applied positions over the WHOLE lineage, each hour counted once.

    `record` is the output of `training_lineage_ancestry.walk_lineage` for the selected head
    (which already refused any gap, swap, replay or cycle), or None for the GENESIS case. Nothing is
    summed here: the walk derived the total twice (deltas and cursor) and this only reports it.
    """
    if record is None:
        return {'depth': 0, 'retained_applied_positions': 0, 'retained_global_steps': 0}
    if record.get('schema') != LINEAGE_SCHEMA:
        raise ValueError('lineage record schema differs')
    return {
        'depth': record['depth'],
        'genesis_manifest_sha256': record['genesis_manifest_sha256'],
        'retained_applied_positions': record['cumulative_applied_token_delta'],
        'retained_global_steps': record['cumulative_step_delta'],
    }


def claim_budget_eligible_status(predicate_path: Path | None = None) -> dict[str, Any]:
    """Claim-budget-eligible positions: UNDEFINED until the frozen predicate file exists.

    Per ruling mail 51039, no predicate is frozen yet, so this reads UNDEFINED and names what is missing. When the
    file exists but this module has no evaluator for its schema, it refuses rather than guess: a number
    computed from a rule nobody froze would be an invented claim figure.
    """
    if predicate_path is None or not Path(predicate_path).is_file():
        return {'status': UNDEFINED, 'missing': CLAIM_PREDICATE_MISSING}
    raise ValueError('claim-budget predicate file present but no evaluator exists for its schema yet')


def gpu_owner_status(lease: Mapping[str, Any] | None) -> dict[str, Any]:
    """Who holds the GPU now, from a caller-supplied lease record (job occupancy, not sampled
    device utilization). None is reported as not_reported, never as idle."""
    if lease is None:
        return {'status': 'not_reported'}
    return {'status': 'held', 'owner': lease.get('owner'), 'run_id': lease.get('run_id'),
            'training_job_purpose': lease.get('training_job_purpose')}


def selected_checkpoint_status(hour_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """The selected checkpoint and its parent, and the LAST hour's applied positions.

    The lineage-wide retained count is `lineage_status`; this section's count is one hour only and is
    named accordingly (it was `retained_applied_positions`, which read as the lineage total).

    `hour_result` is the bound hour-result.json dict for the checkpoint currently selected as
    the lineage head, or None when no hour has ever published one (the GENESIS case). Reads
    only fields cia_hour.py's own publisher already writes -- introduces no second measurement.
    """
    if hour_result is None:
        return {
            'child_manifest_sha256': GENESIS_SENTINEL,
            'parent_manifest_sha256': None,
            'last_hour_applied_positions': 0,
        }
    return {
        'child_manifest_sha256': hour_result['child_manifest_sha256'],
        'parent_manifest_sha256': hour_result['parent_manifest_sha256'],
        'last_hour_applied_positions': int(hour_result['applied_positions']),
    }


def last_learning_measurement_status(measurement: Mapping[str, Any] | None) -> dict[str, Any]:
    """The most recent learning measurement bound to the selected checkpoint, or 'pending'.

    `measurement` is caller-supplied (e.g. a protected-evaluation receipt keyed to the same
    child_manifest_sha256) rather than discovered here -- this module composes status from
    named inputs; it does not walk the filesystem for an evidence class it does not own.
    """
    if measurement is None:
        return {'status': 'pending'}
    return {'status': 'measured', 'measurement': dict(measurement)}


def current_purpose_status(identity: Mapping[str, Any] | None) -> dict[str, Any]:
    """The declared purpose of whatever is currently dispatched against this lineage, or None
    when nothing is currently running."""
    if identity is None:
        return {'training_job_purpose': None, 'run_id': None}
    return {
        'training_job_purpose': identity.get('training_job_purpose'),
        'run_id': identity.get('run_id'),
    }


def diagnostic_allowance_status(
    *, custody_parent: Path, lineage_sha: str, policy: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Occupancy and postponement for this lineage against the same policy the reservation gate
    (`training_continuity_ledger.reserve_diagnostic_dispatch`) enforces. Read-only: this never
    appends to the ledger, it only re-derives the same two quantities from the same rows."""
    policy = load_policy() if policy is None else policy
    require_authority_reference(policy)
    rows = read_rows(ledger_path(custody_parent))
    occupancy = diagnostic_occupancy_seconds(rows, lineage_sha)
    postponement = postponement_seconds(rows, lineage_sha, now=now)
    return {
        'diagnostic_occupancy_seconds': occupancy,
        'max_diagnostic_occupancy_seconds': policy['max_diagnostic_occupancy_seconds'],
        'postponement_seconds': postponement,
        'max_postponement_seconds': policy['max_postponement_seconds'],
        'at_occupancy_limit': occupancy >= policy['max_diagnostic_occupancy_seconds'],
        'at_postponement_limit': postponement >= policy['max_postponement_seconds'],
    }


def next_segment_status(
    *, next_identity: Mapping[str, Any] | None = None, blocker: str | None = None,
) -> dict[str, Any]:
    """The next segment queued against this lineage, or the named reason none is dispatchable.

    Exactly one of `next_identity` (a prepared-but-not-yet-launched identity dict) or `blocker`
    (a human-readable reason) must be given; both None or both set is refused, so this can never
    silently claim readiness -- or silently claim a block -- that the caller has not stated.
    """
    if (next_identity is None) == (blocker is None):
        raise ValueError('next_segment_status needs exactly one of next_identity or blocker')
    if blocker is not None:
        return {'status': 'blocked', 'blocker': blocker}
    return {
        'status': 'ready',
        'training_job_purpose': next_identity.get('training_job_purpose'),
        'run_id': next_identity.get('run_id'),
    }


def training_continuity_status(
    *, custody_parent: Path, hour_result: Mapping[str, Any] | None,
    current_identity: Mapping[str, Any] | None, measurement: Mapping[str, Any] | None,
    next_identity: Mapping[str, Any] | None = None, next_blocker: str | None = None,
    policy: Mapping[str, Any] | None = None, now: float | None = None,
    lineage_record: Mapping[str, Any] | None = None, gpu_lease: Mapping[str, Any] | None = None,
    claim_predicate_path: Path | None = None, pending_receipts_root: Path | None = None,
) -> dict[str, Any]:
    """Issue #2119 section 6's status record: composes the functions above for one lineage.

    `pending_receipts_root` (row 15): when given, the next segment or its blocker is read from the durable
    `next-segment.json` beside the pointer (pending_continuation), for THIS lineage head, and `next_identity`/`next_blocker`
    must not also be given; a record for another head reads blocked, a corrupt record refuses.
    Selected checkpoint and parent, the lineage-wide retained applied positions (from the ancestry
    walk), claim-budget-eligible positions (UNDEFINED until the frozen predicate exists), last
    learning measurement or pending, GPU owner and purpose, diagnostic occupancy and postponement,
    and the next segment or its blocker -- one call, one dict, no field computed twice.

    When an hour result is given, `lineage_record` is required and its head must be that hour's child:
    the walk and the hour result are two views of one checkpoint, and a mismatch refuses."""
    if hour_result is not None:
        if lineage_record is None:
            raise ValueError('a published hour result needs the lineage ancestry record for its head')
        if lineage_record.get('head_manifest_sha256') != hour_result['child_manifest_sha256']:
            raise ValueError('lineage ancestry head differs from the hour result child')
    elif lineage_record is not None:
        raise ValueError('a lineage ancestry record needs the hour result of the same head')
    lineage_sha = (hour_result['child_manifest_sha256'] if hour_result is not None
                   else GENESIS_SENTINEL)
    if pending_receipts_root is not None:
        if next_identity is not None or next_blocker is not None:
            raise ValueError('the pending record supplies the next segment; do not also pass next_identity or next_blocker')
        recovered = pending_continuation.read_pending_continuation(pending_receipts_root, current_head_sha256=lineage_sha)
        next_identity, next_blocker = recovered.get('next_identity'), recovered.get('blocker')
    return {
        'schema': STATUS_SCHEMA,
        'lineage_checkpoint_manifest_sha256': lineage_sha,
        'lineage': lineage_status(lineage_record),
        'claim_budget_eligible': claim_budget_eligible_status(claim_predicate_path),
        'gpu_owner': gpu_owner_status(gpu_lease),
        'checkpoint': selected_checkpoint_status(hour_result),
        'learning_measurement': last_learning_measurement_status(measurement),
        'purpose': current_purpose_status(current_identity),
        'diagnostic_allowance': diagnostic_allowance_status(
            custody_parent=custody_parent, lineage_sha=lineage_sha, policy=policy, now=now),
        'next_segment': next_segment_status(next_identity=next_identity, blocker=next_blocker),
    }
