"""Issue #2119 row 7: claim-eligible advancement accounting, bound to the approved claim-budget predicate.

Binds `claim-budget-eligible-target-predicate-20261003.json` (sha256 PREDICATE_SHA256, approved by Leo 51279; issue comment 5975159177).
Three quantities stay separate and are never substituted for one another:

* physical applied positions (a counter of the input/decoder positions; NOT the unit),
* applied loss-target exposure (every positive-loss occurrence, repeats included),
* claim-eligible unique targets (|U|): a canonical target counts once, at its ORIGINAL first positive-loss training occurrence on
  the frozen selected ancestry, and only when every condition of the predicate is TRUE.

Selected ancestry is DERIVED by walking parent links from the selected head, never taken from a caller flag; a segment off that
walk is a refused branch, reported separately, and its encounters are not prior consumption. Eligibility of a target is DERIVED from
its condition evidence (any FALSE -> FALSE; any missing/unknown -> UNDETERMINED; all TRUE -> TRUE), never a caller-supplied Boolean.
A replay never mints fresh credit, including after a FALSE or UNDETERMINED original. When any original occurrence, identity,
loss mask, provenance or ancestry link is missing, `eligible_unique_total` and the bucket counts are None (NOT zero, NOT the
physical positions), with the missing evidence named; `proved_true_unique` is reported under its own name with complete=False.

Stdlib only; loaded by path (no sibling imports).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

from typing import Any, Mapping, Sequence

PREDICATE_SHA256 = '3a2b13004730c3391e136024b2a063bcd1bed2406c18fee44440f04f28841b87'
PREDICATE_SCHEMA = 'ember-claim-budget-predicate-v1'
REPORT_SCHEMA = 'ember-claim-accounting-v1'
BUCKETS = ('HUMAN_SOURCE_EVIDENCED', 'THIRD_PARTY_AI_GENERATED', 'MIXED_UNRESOLVED', 'ORIGIN_UNKNOWN')
CONDITIONS = ('rights_provenance_ok', 'protected_clear', 'caps_ok', 'not_own_or_fixture')
TRUE, FALSE, UNDETERMINED = 'TRUE', 'FALSE', 'UNDETERMINED'


class AccountingRefusal(ValueError):
    """The record cannot be accounted (wrong predicate pin, cyclic ancestry, mixed budget units, malformed target)."""


def derive_eligibility(target: Mapping[str, Any]) -> tuple[str, str]:
    """(status, reason) from the target's condition evidence; the bucket must also be named for TRUE."""
    evidence = target.get('conditions')
    if not isinstance(evidence, Mapping):
        return UNDETERMINED, 'no condition evidence'
    def known_true(value):   # strict: the boolean True or the string 'TRUE' only (1, 1.0, 'true', [] never qualify)
        return value is True or (isinstance(value, str) and value == TRUE)

    def known_false(value):
        return value is False or (isinstance(value, str) and value == FALSE)

    for name in CONDITIONS:
        if known_false(evidence.get(name)):
            return FALSE, f'{name} is known false'
    missing = [name for name in CONDITIONS if not known_true(evidence.get(name))]
    if missing:
        return UNDETERMINED, 'missing or unknown: ' + ', '.join(missing)
    if target.get('origin_bucket') not in BUCKETS:
        return UNDETERMINED, 'origin bucket missing (a missing origin is never human)'
    return TRUE, 'every condition established'


def _key(target: Mapping[str, Any]) -> tuple:
    key = target.get('key')
    if not (isinstance(key, (list, tuple)) and len(key) == 3 and isinstance(key[0], str) and key[0]
            and isinstance(key[1], str) and isinstance(key[2], int) and not isinstance(key[2], bool)):
        raise AccountingRefusal('a target key is [canonical_training_item_id, target_field, target_ordinal]')
    return tuple(key)


def _ancestry(segments: Sequence[Mapping[str, Any]], head: str) -> tuple[list[str], list[str]]:
    """(genesis-to-head ids, missing-link notes). Raises on a cycle or a duplicate id."""
    by_id: dict[str, Mapping[str, Any]] = {}
    for segment in segments:
        sid = segment.get('segment_id')
        if not isinstance(sid, str) or not sid or sid in by_id:
            raise AccountingRefusal('segments need unique non-empty segment_id values')
        by_id[sid] = segment
    if head not in by_id:
        return [], [f'selected head {head!r} is not among the supplied segments']
    chain, seen, cursor, missing = [], set(), head, []
    while cursor is not None:
        if cursor in seen:
            raise AccountingRefusal('the selected ancestry is cyclic')
        seen.add(cursor)
        if cursor not in by_id:
            missing.append(f'ancestry link {cursor!r} is missing')
            break
        chain.append(cursor)
        if 'parent_segment_id' not in by_id[cursor]:
            missing.append(f'segment {cursor!r}: parent_segment_id is absent, so its ancestry link is unknown (null names a genesis)')
            break
        cursor = by_id[cursor]['parent_segment_id']
    return list(reversed(chain)), missing


def account(segments: Sequence[Mapping[str, Any]], *, head_segment_id: str, predicate_sha256: str) -> dict[str, Any]:
    if predicate_sha256 != PREDICATE_SHA256:
        raise AccountingRefusal('the predicate digest differs from the approved frozen predicate')
    by_id = {s.get('segment_id'): s for s in segments}
    chain, missing_links = _ancestry(segments, head_segment_id)
    selected = set(chain)
    refused = [{'segment_id': s['segment_id'], 'reason': 'not on the selected ancestry (discarded branch): contributes nothing, '
                'and its encounters are not prior consumption'} for s in segments if s['segment_id'] not in selected]
    missing: list[str] = list(missing_links)
    units = set()
    for sid in chain:
        unit = by_id[sid].get('budget_unit_id')
        if isinstance(unit, str) and unit.strip():
            units.add(unit)
        else:
            missing.append(f'segment {sid!r}: budget_unit_id is absent (the frozen budget unit is unproved)')
    if len(units) > 1:
        raise AccountingRefusal('budget unit revisions differ across the selected ancestry; they cannot be silently summed')
    excluded: list[dict[str, Any]] = []
    first_seen: dict[tuple, dict[str, Any]] = {}      # key -> original first positive-loss occurrence
    per_segment: list[dict[str, Any]] = []
    physical = loss_exposure = proved = 0
    buckets_true = {name: 0 for name in BUCKETS}
    undetermined_keys: set[tuple] = set()
    coverage_gap = False   # an earlier selected segment whose targets/flags are unknown: later "first" occurrences are unproved
    unresolved_after_gap: set[tuple] = set()
    for sid in chain:
        segment = by_id[sid]
        physical += int(segment.get('applied_positions') or 0)
        row = {'segment_id': sid, 'applied_positions': int(segment.get('applied_positions') or 0), 'eligible_increment': 0,
               'exposure': 0}
        published, advanced = segment.get('published'), segment.get('advanced_head')
        if not (isinstance(published, bool) and isinstance(advanced, bool)):
            missing.append(f'{sid}: published/advanced_head evidence is absent or not boolean')
            row['eligible_increment'] = None
            row['status'] = 'UNDETERMINED'
            per_segment.append(row)
            coverage_gap = True
            continue
        if not (published and advanced):
            excluded.append({'segment_id': sid, 'reason': 'known not a published, head-advancing segment'})
            row['status'] = 'EXCLUDED'
            per_segment.append(row)
            continue
        targets = segment.get('targets')
        if targets is None:
            names = segment.get('missing_evidence') or ['per-target identities and actual loss masks']
            missing.extend(f'{sid}: {name}' for name in names)
            row['eligible_increment'] = None
            row['status'] = 'UNDETERMINED'
            per_segment.append(row)
            coverage_gap = True
            continue
        open_here = False
        for target in targets:
            key = _key(target)
            loss_flag = target.get('positive_loss')
            if loss_flag is False:
                continue   # known masked / input-only: no loss occurrence, so no consumption on this ancestry
            if loss_flag is not True:
                # the mask is absent: the original first occurrence cannot be established, and a later positive replay cannot mint it
                if key not in first_seen:
                    first_seen[key] = {'segment_id': sid, 'status': UNDETERMINED, 'reason': 'positive-loss mask absent'}
                    undetermined_keys.add(key)
                    open_here = True
                    missing.append(f'{sid} {list(key)}: positive-loss mask absent')
                continue
            row['exposure'] += 1
            loss_exposure += 1
            if key in first_seen:
                continue   # a replay adds exposure only, whatever the original's status
            if coverage_gap:
                # an earlier selected segment's target coverage is unknown: this occurrence may be a replay of an unseen first one
                first_seen[key] = {'segment_id': sid, 'status': UNDETERMINED, 'reason': 'earlier coverage unknown'}
                unresolved_after_gap.add(key)
                undetermined_keys.add(key)
                row['eligible_increment'] = None
                open_here = True
                continue
            status, reason = derive_eligibility(target)
            first_seen[key] = {'segment_id': sid, 'status': status, 'reason': reason}
            if status == TRUE:
                proved += 1
                buckets_true[target['origin_bucket']] += 1
                row['eligible_increment'] += 1
            elif status == FALSE:
                excluded.append({'key': list(key), 'segment_id': sid, 'reason': reason})
            else:
                undetermined_keys.add(key)
                open_here = True
                missing.append(f'{sid} {list(key)}: {reason}')
        row['status'] = 'UNDETERMINED_TARGETS' if open_here else 'DETERMINED'
        per_segment.append(row)
    if unresolved_after_gap:
        missing.append(f'{len(unresolved_after_gap)} positive-loss target(s) follow a selected segment with unknown coverage; '
                       'their original first occurrence cannot be established, so none is credited')
    complete = not missing and not undetermined_keys
    if complete and sum(buckets_true.values()) != proved:
        raise AccountingRefusal('the origin buckets do not partition the eligible total')
    return {'schema': REPORT_SCHEMA, 'predicate_sha256': PREDICATE_SHA256, 'predicate_schema': PREDICATE_SCHEMA,
            'budget_unit_id': next(iter(units), None), 'head_segment_id': head_segment_id,
            'status': 'DETERMINED' if complete else 'UNDETERMINED',
            'eligible_unique_total': proved if complete else None,
            'bucket_counts': dict(buckets_true) if complete else None,
            'proved_true_unique': {'count': proved, 'buckets': dict(buckets_true), 'complete': complete},
            'missing_evidence': missing, 'applied_loss_target_exposure': loss_exposure,
            'physical_positions': physical, 'per_segment': per_segment, 'excluded': excluded,
            'refused_branches': refused, 'selected_segment_ids': chain,
            'unresolved_after_coverage_gap': sorted([list(k) for k in unresolved_after_gap])}
