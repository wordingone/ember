"""Issue #2119 rows 13 and 19: what the lineage status says about the candidate child that was NOT retained, and whether any hour was credited twice.

    audit_candidate(candidate_record_path=..., lineage_record=..., ruling_log_path=..., ruling_id=..., refusal_receipt_path=...)

Every fact is read from a named file and quoted with that file's sha256; nothing is taken from caller text (a `--blocker` string cannot feed it):
  1. the candidate record (`candidate-continuation-head.json`, schema ember-candidate-continuation-head-v1) names the candidate child, its parent and its hour result;
  2. the hour result's bytes must hash to the record's sha, and its child and parent must be the record's;
  3. the ruling row (`stage: RULED`, `verdict`) is read from the loop log by `ruling_id`; the receipt sha it cites must be a prefix of the refusal
     receipt file's sha256, and that receipt must bind to the candidate checkpoint manifest;
  4. the candidate is looked up in the retained ancestry chain: absent + a REFUTED ruling = REFUSED_NOT_RETAINED, absent + no ruling = UNRULED_NOT_RETAINED
     (still reported, never dropped), present + a REFUTED ruling = refusal (the readout would contradict itself);
  5. `duplicate_credit_check` re-derives, from the chain alone, that every manifest appears once and that each hour's delta moves the cursor from its parent's
     exactly once; the candidate's applied positions are credited to the lineage only if the candidate is in the chain.

`public_view()` reduces every path to its file name for the committed page (the page carries no local filesystem path).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA = 'ember-lineage-candidate-audit-v1'
CANDIDATE_SCHEMA = 'ember-candidate-continuation-head-v1'
REFUTED_VERDICTS = ('REFUTED',)
STATUSES = ('REFUSED_NOT_RETAINED', 'UNRULED_NOT_RETAINED', 'RETAINED_IN_CHAIN', 'NO_CANDIDATE')


class CandidateAuditRefusal(ValueError):
    pass


class DuplicateCreditRefusal(CandidateAuditRefusal):
    pass


def _path(text: str) -> Path:
    return Path(str(text).replace('\\', '/'))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def duplicate_credit_check(chain: list[Mapping[str, Any]], *, head_tokens_seen: int, head_global_step: int) -> dict[str, Any]:
    """Each manifest once; each hop advances the cursor from its parent's by exactly its own delta; the deltas sum to the head cursor."""
    if not chain:
        raise DuplicateCreditRefusal('the retained chain is empty')
    digests = [entry['manifest_sha256'] for entry in chain]
    repeated = sorted({digest for digest in digests if digests.count(digest) > 1})
    if repeated:
        raise DuplicateCreditRefusal(f'manifest {repeated[0]} is counted more than once in the retained chain (duplicate advance)')
    tokens = chain[0]['tokens_seen']
    steps = chain[0]['global_step']
    for entry in chain[1:]:
        tokens += entry['token_delta']
        steps += entry['step_delta']
        if entry['tokens_seen'] != tokens or entry['global_step'] != steps:
            raise DuplicateCreditRefusal(
                f"hop into {entry['manifest_sha256']}: its cursor ({entry['tokens_seen']} tokens, step {entry['global_step']}) is not the running "
                f'total ({tokens}, {steps}) of its ancestors plus its own delta (duplicate or missing credit)')
    if tokens != head_tokens_seen or steps != head_global_step:
        raise DuplicateCreditRefusal('the summed hop deltas differ from the head cursor')
    return {
        'hops_checked': len(chain) - 1,
        'distinct_manifests': len(digests),
        'each_hour_counted_once': True,
        'summed_token_delta': tokens - chain[0]['tokens_seen'],
        'summed_step_delta': steps - chain[0]['global_step'],
    }


def _read_ruling_row(log_path: Path, ruling_id: str) -> dict[str, Any]:
    raw = log_path.read_bytes()
    found = None
    for number, line in enumerate(raw.split(b'\n'), start=1):
        if ruling_id.encode() not in line:
            continue
        try:
            row = json.loads(line.decode('utf-8'))
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('id') == ruling_id and row.get('stage') == 'RULED':
            found = (number, line, row)
    if found is None:
        raise CandidateAuditRefusal(f'no RULED row with id {ruling_id!r} in {log_path.name}')
    number, line, row = found
    return {'path': str(log_path), 'row_number': number, 'row_sha256': _sha256_bytes(line), 'row_id': ruling_id,
            'verdict': row.get('verdict'), 'because': row.get('because'), 'seat': row.get('seat'), 'ts': row.get('ts'),
            'log_sha256_as_read': _sha256_bytes(raw)}


def audit_candidate(*, candidate_record_path: Path | None, lineage_record: Mapping[str, Any], ruling_log_path: Path | None = None,
                    ruling_id: str | None = None, refusal_receipt_path: Path | None = None) -> dict[str, Any]:
    if candidate_record_path is None or not Path(candidate_record_path).is_file():
        return {'schema': SCHEMA, 'status': 'NO_CANDIDATE', 'candidate': None, 'retained': None, 'refusal_ruling': None,
                'duplicate_credit': duplicate_credit_check(lineage_record['chain'], head_tokens_seen=lineage_record['head_tokens_seen'],
                                                           head_global_step=lineage_record['head_global_step'])}
    record_path = Path(candidate_record_path)
    record_bytes = record_path.read_bytes()
    record = json.loads(record_bytes.decode('utf-8'))
    if record.get('schema') != CANDIDATE_SCHEMA:
        raise CandidateAuditRefusal(f'candidate record schema is not {CANDIDATE_SCHEMA}')
    candidate = record['candidate_checkpoint_manifest_sha256']
    parent = record['parent_checkpoint_manifest_sha256']
    hour_path = _path(record['hour_result_path'])
    hour_bytes = hour_path.read_bytes()
    if _sha256_bytes(hour_bytes) != record['hour_result_sha256']:
        raise CandidateAuditRefusal('the candidate hour result bytes do not hash to the record hour_result_sha256')
    hour = json.loads(hour_bytes.decode('utf-8'))
    if hour.get('child_manifest_sha256') != candidate or hour.get('parent_manifest_sha256') != parent:
        raise CandidateAuditRefusal('the candidate hour result child or parent differs from the candidate record')
    chain = list(lineage_record['chain'])
    duplicate = duplicate_credit_check(chain, head_tokens_seen=lineage_record['head_tokens_seen'], head_global_step=lineage_record['head_global_step'])
    in_chain = candidate in {entry['manifest_sha256'] for entry in chain}

    ruling = None
    if ruling_id is not None:
        if ruling_log_path is None or refusal_receipt_path is None:
            raise CandidateAuditRefusal('a ruling id needs the ruling log and the refusal receipt it cites')
        ruling = _read_ruling_row(Path(ruling_log_path), ruling_id)
        receipt_path = Path(refusal_receipt_path)
        receipt_bytes = receipt_path.read_bytes()
        receipt_sha = _sha256_bytes(receipt_bytes)
        cited = re.search(r'receipt\s+\S+\s+sha256\s+([0-9a-f]{8,64})', str(ruling.get('because') or ''))
        if cited is None or not receipt_sha.startswith(cited.group(1)):
            raise CandidateAuditRefusal('the receipt sha the ruling row cites is not a prefix of the refusal receipt file sha256')
        bound = json.loads(receipt_bytes.decode('utf-8')).get('bindings', {}).get('checkpoint_manifest_sha256')
        if bound != candidate:
            raise CandidateAuditRefusal('the refusal receipt is not bound to the candidate checkpoint manifest')
        ruling.update({'receipt_path': str(receipt_path), 'receipt_sha256': receipt_sha})
    refuted = ruling is not None and ruling['verdict'] in REFUTED_VERDICTS
    if in_chain and refuted:
        raise CandidateAuditRefusal('the candidate is in the retained chain although its ruling is REFUTED')
    if in_chain:
        status = 'RETAINED_IN_CHAIN'
    elif refuted:
        status = 'REFUSED_NOT_RETAINED'
    elif ruling is None:
        status = 'UNRULED_NOT_RETAINED'
    else:
        raise CandidateAuditRefusal(f"the ruling verdict {ruling['verdict']!r} is neither a refusal nor a retention")
    applied = int(hour['applied_positions'])
    return {
        'schema': SCHEMA,
        'status': status,
        'candidate': {
            'manifest_sha256': candidate, 'parent_manifest_sha256': parent,
            'parent_is_selected_head': parent == lineage_record['head_manifest_sha256'],
            'applied_positions_of_that_hour': applied,
            'record': {'path': str(record_path), 'sha256': _sha256_bytes(record_bytes)},
            'hour_result': {'path': str(hour_path), 'sha256': record['hour_result_sha256']},
        },
        'retained': {'candidate_in_retained_chain': in_chain, 'positions_credited_to_lineage': applied if in_chain else 0},
        'refusal_ruling': ruling,
        'duplicate_credit': duplicate,
    }


def public_view(audit: Mapping[str, Any]) -> dict[str, Any]:
    """The same audit with every filesystem path reduced to its file name, the free-text ruling reason and the ruling seat's name dropped
    (the repo-guard `names` check refuses an operator name in a tracked file; the row sha and number identify the ruling), for the committed page."""
    view = json.loads(json.dumps(audit))

    def strip(node):
        if isinstance(node, dict):
            for key in list(node):
                if key in ('path', 'receipt_path'):
                    node[key] = Path(str(node[key]).replace('\\', '/')).name
                elif key in ('because', 'seat'):
                    del node[key]
                else:
                    strip(node[key])
        elif isinstance(node, list):
            for item in node:
                strip(item)

    strip(view)
    return view
