"""Issue #2119 (review 63986 R2, ruling 63996; causal repair after review 64088): the ONE entry from a scored pair to the pending-aware promotion.

    PRELAUNCH frozen entry (digest in the run identity)  +  POST-RUN arm-publication.json (written by the scoring chain)
        -> arm_results_producer -> runner.finalize_retention_outcome -> promote_with_pending (pending-aware head move)

Two files, in the order the run actually happens:

1. The FROZEN PRELAUNCH ENTRY is a JSON file whose sha256 is frozen in the run identity (`scored_pair_binding_sha256`) when the run is declared.
   It carries only what is known before the run: run_id, the parent (frozen start), the metric, the six common bindings (episode plan, shard
   ledger, mixture identity, frozen declaration, scorer, tokenizer) and the promotion target. It carries NO per-arm post-run values: a declared
   identity cannot hold a digest of its own future outputs.
2. The POST-RUN `arm-publication.json` is created EXCLUSIVELY in the run custody by the scoring chain (`write_arm_publication`) after both arms
   are scored. Per arm it records the published root, hour-result path, applied positions, the scored receipt and the checkpoint receipt; every
   digest in it (child manifest, scored receipt, checkpoint receipt) is DERIVED by hashing the files at that moment, never typed, and is
   re-derived again at finalize so a file edited in between is refused.

Every scored receipt must then carry the FROZEN prelaunch bindings (a receipt scored on another population or mixture is refused, whoever supplies
it) and its own checkpoint-receipt binding equal to the derived digest. The measurement class comes from the identity's frozen rule
(`selection.evaluation_set_class`) keyed by the frozen declaration digest. Promotion is attempted only for the arm the adjudicator names
eligible, only with a ruling, with `expected_child` derived from that arm's published root.

Stdlib only; loaded by path like its siblings. The runner module and the promotion callable are passed in (no import of the runner here).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import arm_results_producer as producer
import retention_eligibility as elig

ENTRY_SCHEMA = 'ember-2119-scored-pair-binding-v2'
PUBLICATION_SCHEMA = 'ember-2119-arm-publication-v1'
PUBLICATION_FILENAME = 'arm-publication.json'
IDENTITY_DIGEST_FIELD = 'scored_pair_binding_sha256'
COMMON_BINDING_KEYS = tuple(key for key in producer.MANDATORY_BINDING_KEYS if key != 'checkpoint_receipt_sha256')
ENTRY_FIELDS = {'schema', 'run_id', 'bindings', 'metric', 'parent_manifest_sha256', 'promote'}
PROMOTE_FIELDS = {'repo_root', 'receipts_root', 'ledger'}
ROLES = ('control', 'treatment')
PUBLISH_INPUT_FIELDS = {'published_checkpoint_root', 'hour_result_path', 'applied_positions', 'receipt', 'checkpoint_receipt'}
PUBLISHED_ARM_FIELDS = PUBLISH_INPUT_FIELDS | {'published', 'child_manifest_sha256', 'receipt_sha256', 'checkpoint_receipt_sha256'}


class ScoredPairRefusal(ValueError):
    """The frozen entry, the identity, the publication or the scored pair cannot be turned into a finalized, promotable outcome."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _derive(role: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    """One published arm's record with every digest derived from the files now."""
    if not isinstance(spec, Mapping) or set(spec) != PUBLISH_INPUT_FIELDS:
        raise ScoredPairRefusal(f'the {role} publication needs exactly {sorted(PUBLISH_INPUT_FIELDS)} or None')
    if not isinstance(spec['applied_positions'], int) or isinstance(spec['applied_positions'], bool) or spec['applied_positions'] < 0:
        raise ScoredPairRefusal(f'the {role} publication applied_positions must be a nonnegative integer')
    try:
        derived = {'child_manifest_sha256': _sha256_file(Path(spec['published_checkpoint_root']) / 'checkpoint-manifest.json'),
                   'receipt_sha256': _sha256_file(Path(spec['receipt'])),
                   'checkpoint_receipt_sha256': _sha256_file(Path(spec['checkpoint_receipt']))}
    except OSError as error:
        raise ScoredPairRefusal(f'the {role} publication names a file that cannot be read: {error}') from error
    return dict(spec, published=True, **derived)


def write_arm_publication(custody: Path, *, arms: Mapping[str, Any]) -> Path:
    """The scoring chain's post-run step: `arms[role]` is a dict of PUBLISH_INPUT_FIELDS for a published arm, or None for an arm that did not
    publish. Created exclusively (never overwritten); every digest is derived from the files here."""
    if not isinstance(arms, Mapping) or set(arms) != set(ROLES):
        raise ScoredPairRefusal('the publication needs exactly a control and a treatment entry')
    record = {'schema': PUBLICATION_SCHEMA}
    for role in ROLES:
        record[role] = {'published': False} if arms[role] is None else _derive(role, arms[role])
    path = Path(custody) / PUBLICATION_FILENAME
    try:
        with open(path, 'x', encoding='utf-8') as stream:
            stream.write(json.dumps(record, indent=2, sort_keys=True))
    except FileExistsError as error:
        raise ScoredPairRefusal('arm-publication.json already exists in this custody (never overwritten)') from error
    return path


def _read_publication(custody: Path) -> dict[str, dict[str, Any]]:
    """The publication, re-derived from the files NOW: any file edited since publication (or a hand-written digest) is refused."""
    path = Path(custody) / PUBLICATION_FILENAME
    if not path.is_file():
        raise ScoredPairRefusal('no arm-publication.json in this custody: the scoring chain has not published the arms')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise ScoredPairRefusal(f'arm-publication.json is not JSON: {error}') from error
    if not isinstance(record, dict) or set(record) != {'schema', *ROLES} or record['schema'] != PUBLICATION_SCHEMA:
        raise ScoredPairRefusal('arm-publication.json is not the closed publication schema')
    out = {}
    for role in ROLES:
        arm = record[role]
        if not isinstance(arm, dict):
            raise ScoredPairRefusal(f'the {role} publication is not an object')
        if arm == {'published': False}:
            out[role] = arm
            continue
        if set(arm) != PUBLISHED_ARM_FIELDS or arm['published'] is not True:
            raise ScoredPairRefusal(f'the {role} publication is not the closed published-arm schema')
        rederived = _derive(role, {key: arm[key] for key in PUBLISH_INPUT_FIELDS})
        if rederived != arm:
            raise ScoredPairRefusal(f'the {role} publication differs from the files it names (edited since publication)')
        out[role] = arm
    return out


def load_frozen_binding(identity: Mapping[str, Any], entry_path: Path) -> dict[str, Any]:
    """The prelaunch entry, accepted only when its bytes hash to the digest frozen in the identity and every field is closed and well formed."""
    pinned = identity.get(IDENTITY_DIGEST_FIELD)
    if not elig._is_sha256(pinned):
        raise ScoredPairRefusal(f'the identity carries no frozen {IDENTITY_DIGEST_FIELD}')
    try:
        raw = Path(entry_path).read_bytes()
    except OSError as error:
        raise ScoredPairRefusal(f'the frozen-binding entry is unreadable: {error}') from error
    if hashlib.sha256(raw).hexdigest() != pinned:
        raise ScoredPairRefusal('the entry bytes differ from the digest frozen in the identity')
    try:
        entry = json.loads(raw)
    except ValueError as error:
        raise ScoredPairRefusal(f'the frozen-binding entry is not JSON: {error}') from error
    if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS or entry['schema'] != ENTRY_SCHEMA:
        raise ScoredPairRefusal('the frozen-binding entry is not the closed prelaunch scored-pair schema (no per-arm post-run fields)')
    bindings = entry['bindings']
    if not isinstance(bindings, dict) or set(bindings) != set(COMMON_BINDING_KEYS) or not all(elig._is_sha256(v) for v in bindings.values()):
        raise ScoredPairRefusal(f'the entry bindings must be exactly {sorted(COMMON_BINDING_KEYS)} as sha256 digests')
    metric = entry['metric']
    if not isinstance(metric, dict) or set(metric) != {'name', 'path'} or not all(isinstance(v, str) and v for v in metric.values()):
        raise ScoredPairRefusal('the entry metric needs a nonempty name and path')
    if not elig._is_sha256(entry['parent_manifest_sha256']):
        raise ScoredPairRefusal('the entry parent_manifest_sha256 is not a sha256')
    promote = entry['promote']
    if (not isinstance(promote, dict) or not PROMOTE_FIELDS <= set(promote) or set(promote) - PROMOTE_FIELDS - {'next', 'blocker'}
            or ('next' in promote) == ('blocker' in promote)):
        raise ScoredPairRefusal('the entry promote block needs repo_root, receipts_root, ledger and exactly one of next or blocker')
    return entry


def _arm_records(entry, rule, publication) -> dict[str, dict[str, Any]]:
    """Both typed arm records: bindings from the frozen entry, per-arm values from the derived publication; nothing is written."""
    declaration_classes = {entry['bindings']['frozen_declaration_sha256']: rule['selection']['evaluation_set_class']}
    records = {}
    for role in ROLES:
        pub = publication[role]
        published = pub.get('published') is True
        records[role] = producer.arm_from_scored_receipt(
            rule[role + '_arm_id'], Path(pub['receipt']) if published else None,
            metric_name=entry['metric']['name'], metric_path=entry['metric']['path'], parent_manifest_sha256=entry['parent_manifest_sha256'],
            child_manifest_sha256=pub['child_manifest_sha256'] if published else None,
            applied_positions=pub['applied_positions'] if published else 0,
            required_bindings=dict(entry['bindings'], checkpoint_receipt_sha256=pub['checkpoint_receipt_sha256'] if published else None),
            declaration_classes=declaration_classes, expected_receipt_sha256=pub['receipt_sha256'] if published else None)
    return records


def _readjudicate(rule: Mapping[str, Any], arm_results: Path) -> dict[str, Any] | None:
    """The adjudicator's verdict over the arm-results file now on disk, or None when adjudication refuses (nothing is written)."""
    try:
        arms = json.loads(arm_results.read_text(encoding='utf-8'))
        verdict = elig.adjudicate(rule, arms['control'], arms['treatment'], expected_rule_sha256=arms['rule_sha256'])
        return json.loads(json.dumps(verdict, sort_keys=True))     # the same JSON round trip the verdict file went through
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def finalize_scored_pair(identity: Mapping[str, Any], *, entry_path: Path, custody: Path, parent: Path, runner: Any,
                         promote_fn: Callable[..., dict[str, Any]], ruling: str | None) -> dict[str, Any]:
    """The whole chain. Raises ScoredPairRefusal / ArmProducerRefusal / EligibilityRefusal before anything is written when the entry, the
    publication or any scored receipt does not bind; resumes (never re-writes) when arm-results.json from an interrupted earlier call already
    equals the pair rebuilt now. Returns {'finalized', 'eligible', 'verdict', 'promotion'}; promotion is the promote_fn outcome, or a
    NOT_ATTEMPTED_* string (no eligible arm, or no ruling)."""
    entry = load_frozen_binding(identity, entry_path)
    rule = elig.validate_identity_rule(identity)
    custody = Path(custody)
    run_id = entry['run_id']
    if not isinstance(run_id, str) or not run_id or identity.get('run_id') != run_id or custody.name != 'measurement-' + run_id:
        raise ScoredPairRefusal('the entry run_id does not match the identity and this custody directory')
    if entry['parent_manifest_sha256'] != rule['frozen_start_manifest_sha256']:
        raise ScoredPairRefusal('the entry parent differs from the identity rule frozen start')
    publication = _read_publication(custody)
    records = _arm_records(entry, rule, publication)
    arm_results = custody / elig.ARM_RESULTS_FILENAME
    if arm_results.is_file():
        written = json.loads(arm_results.read_text(encoding='utf-8'))
        if written.get('control') != records['control'] or written.get('treatment') != records['treatment']:
            raise ScoredPairRefusal('arm-results.json already exists and differs from the pair rebuilt from the frozen entry and publication')
    else:
        producer.produce_arm_results(identity, custody=custody, control=records['control'], treatment=records['treatment'])
    marker_path = custody / runner.OUTCOME_RECORDED_FILENAME
    verdict_path = custody / 'eligibility-verdict.json'
    if marker_path.is_file():
        # review 64090: a first call with no ruling, or a crash after finalization and before promotion, leaves the one-writer outcome marker. A later
        # call validates and REUSES that completed outcome (never deletes the marker, never finalizes twice): it must be this run's, a real bool,
        # and agree with the arm results rebuilt above and the adjudicator's verdict file.
        try:
            marker = json.loads(marker_path.read_text(encoding='utf-8'))
        except ValueError as error:
            raise ScoredPairRefusal(f'the recorded-outcome marker is not JSON: {error}') from error
        if (not isinstance(marker, dict) or marker.get('run_id') != run_id or type(marker.get('eligible_descendant_published')) is not bool
                or not arm_results.is_file()):
            raise ScoredPairRefusal('the recorded-outcome marker is not this run\'s completed outcome over these arm results')
        eligible = marker['eligible_descendant_published']
        saved = json.loads(verdict_path.read_text(encoding='utf-8')) if verdict_path.is_file() else None
        if eligible != (saved is not None and saved.get('eligible_arm') is not None):
            raise ScoredPairRefusal('the recorded outcome disagrees with the eligibility verdict on disk')
        # review 65622 P1: the saved verdict is never trusted. Re-adjudicate the arm results rebuilt above under the frozen rule and require the
        # WHOLE saved verdict to equal that result, so an edited eligible_arm (or any other edited field) refuses before any promotion.
        rederived = _readjudicate(rule, arm_results)
        if eligible:
            if saved is None or rederived is None or saved != rederived:
                raise ScoredPairRefusal('the saved eligibility verdict differs from the adjudication of the rebuilt arm records')
        elif saved is not None and saved != rederived:
            raise ScoredPairRefusal('the saved eligibility verdict differs from the adjudication of the rebuilt arm records')
        verdict = rederived if eligible else saved
        resumed = True
    else:
        eligible = runner.finalize_retention_outcome(identity, custody=custody, parent=parent)
        verdict = json.loads(verdict_path.read_text(encoding='utf-8')) if verdict_path.is_file() else None
        resumed = False
    out: dict[str, Any] = {'finalized': True, 'resumed_completed_outcome': resumed, 'eligible': eligible, 'verdict': verdict,
                           'promotion': 'NOT_ATTEMPTED_NO_ELIGIBLE_ARM'}
    eligible_arm = None if verdict is None else verdict.get('eligible_arm')
    if not eligible or eligible_arm is None:
        return out
    role = next(r for r in ROLES if rule[r + '_arm_id'] == eligible_arm)
    if not ruling:
        out['promotion'] = 'NOT_ATTEMPTED_NO_RULING'
        return out
    promote = entry['promote']
    spec = {'repo_root': promote['repo_root'], 'receipts_root': promote['receipts_root'], 'ledger': promote['ledger'],
            'published_checkpoint_root': publication[role]['published_checkpoint_root'],
            'hour_result_path': publication[role]['hour_result_path'],
            'expected_parent': entry['parent_manifest_sha256'], 'expected_child': records[role]['child_manifest_sha256']}
    spec['next' if 'next' in promote else 'blocker'] = promote['next' if 'next' in promote else 'blocker']
    out['promotion'] = promote_fn(spec, ruling=ruling)
    return out
