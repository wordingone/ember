"""Issue #2119 rows 5/14: retention eligibility decided by a rule frozen BEFORE the experiment.

Master decided eligibility from the run's own launch-success flag (cia_step_runner `launch_succeeded`), so a treatment that
lost its metric still counted as an eligible descendant. This module is the adjudicator the caller now uses:

* `parse_rule` reads the dispatch identity's `training_experiment_continuation_rule` as a CLOSED rule (frozen common start,
  control arm id, treatment arm id, the selection rule) and derives `rule_sha256` from its canonical bytes. The identity is pinned
  by the prediction digest before launch, so the rule cannot be edited afterwards; `adjudicate` also takes the digest recorded at
  launch and refuses a different one.
* `adjudicate(rule, control, treatment)` is deterministic from numbers. The treatment is eligible only if it published, descends
  from the frozen start, and beats the control's metric by `min_delta` in `direction` on a DEVELOPMENTAL measurement. Otherwise
  the control is eligible iff it published and descends from the same frozen start (the fallback when the treatment is rejected).
  Exactly one arm's applied positions are retained; the arms are never summed.
* `adjudicated_eligible_descendant` is the runner's caller: False unless the run succeeded AND `arm-results.json` exists in the
  custody AND adjudication returns an eligible arm. It is never True by default and never True when adjudication refuses.

Stdlib only; loaded by the runner by path (no sibling imports).
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

RULE_SCHEMA = 'ember-retention-eligibility-rule-v1'
ARM_RESULTS_FILENAME = 'arm-results.json'
REFUSAL_FILENAME = 'eligibility-refusal.json'
CONTROL_ELIGIBLE = 'CONTROL_ELIGIBLE'
TREATMENT_ELIGIBLE = 'TREATMENT_ELIGIBLE'
NONE_ELIGIBLE = 'NONE_ELIGIBLE'
_RULE_FIELDS = {'schema', 'frozen_start_manifest_sha256', 'control_arm_id', 'treatment_arm_id', 'selection'}
_SELECTION_FIELDS = {'metric', 'direction', 'min_delta', 'evaluation_set_class'}


class EligibilityRefusal(ValueError):
    """The rule or the arm results cannot support an eligibility decision."""


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_rule(text: Any) -> dict[str, Any]:
    """The closed rule from the identity's continuation-rule text, with `rule_sha256` derived (never self-declared)."""
    if not isinstance(text, str) or not text.strip():
        raise EligibilityRefusal('the continuation rule is missing')
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EligibilityRefusal(f'the continuation rule is not a JSON eligibility rule: {exc}') from exc
    if not isinstance(raw, dict) or set(raw) != _RULE_FIELDS:
        raise EligibilityRefusal('the eligibility rule must carry exactly: ' + ', '.join(sorted(_RULE_FIELDS)))
    if raw['schema'] != RULE_SCHEMA:
        raise EligibilityRefusal(f'the eligibility rule schema must be {RULE_SCHEMA!r}')
    if not _is_sha256(raw['frozen_start_manifest_sha256']):
        raise EligibilityRefusal('the frozen common start must be a sha256 manifest digest')
    control, treatment = raw['control_arm_id'], raw['treatment_arm_id']
    if not all(isinstance(v, str) and v.strip() for v in (control, treatment)) or control == treatment:
        raise EligibilityRefusal('the control and treatment arms need distinct non-empty ids')
    selection = raw['selection']
    if not isinstance(selection, dict) or set(selection) != _SELECTION_FIELDS:
        raise EligibilityRefusal('the selection rule must carry exactly: ' + ', '.join(sorted(_SELECTION_FIELDS)))
    if not isinstance(selection['metric'], str) or not selection['metric'].strip():
        raise EligibilityRefusal('the selection metric must be a non-empty name')
    if selection['direction'] not in ('lower', 'higher'):
        raise EligibilityRefusal("the selection direction must be 'lower' or 'higher'")
    if not _number(selection['min_delta']) or selection['min_delta'] < 0:
        raise EligibilityRefusal('the selection min_delta must be a finite number >= 0')
    if selection['evaluation_set_class'] != 'developmental':
        raise EligibilityRefusal('selection may use a developmental evaluation set only (never the protected test)')
    rule = dict(raw)
    rule['rule_sha256'] = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return rule


def validate_identity_rule(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Dispatch-time check for a RETENTION_ELIGIBLE_EXPERIMENT identity: the rule parses, and its frozen start is the
    identity's own parent checkpoint (the experiment starts where the rule says it does)."""
    rule = parse_rule(identity.get('training_experiment_continuation_rule'))
    parent = identity.get('parent_checkpoint')
    if not isinstance(parent, Mapping) or parent.get('manifest_sha256') != rule['frozen_start_manifest_sha256']:
        raise EligibilityRefusal('the eligibility rule\'s frozen start differs from the identity\'s parent checkpoint')
    return rule


def _arm(arm: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(arm, Mapping):
        raise EligibilityRefusal(f'the {label} arm result is missing')
    if not isinstance(arm.get('published'), bool):
        raise EligibilityRefusal(f'the {label} arm result needs a boolean published')
    if arm['published']:
        # a published arm needs complete typed bindings before it can ever be eligible: nothing defaults to eligible
        if arm.get('measurement_set_class') == 'protected':
            raise EligibilityRefusal(f'the {label} arm was measured on the protected set; selection on it is refused')
        if arm.get('measurement_set_class') != 'developmental':
            raise EligibilityRefusal(f'the {label} arm needs measurement_set_class "developmental" (missing or unknown class)')
        if not _is_sha256(arm.get('child_manifest_sha256')):
            raise EligibilityRefusal(f'the {label} arm is published but carries no valid child_manifest_sha256')
        if not _is_sha256(arm.get('parent_manifest_sha256')):
            raise EligibilityRefusal(f'the {label} arm is published but carries no valid parent_manifest_sha256')
        positions = arm.get('applied_positions')
        if not isinstance(positions, int) or isinstance(positions, bool) or positions < 0:
            raise EligibilityRefusal(f'the {label} arm applied_positions must be a nonnegative integer')
    return arm


def adjudicate(rule: Mapping[str, Any], control: Any, treatment: Any, *, expected_rule_sha256: str | None = None) -> dict[str, Any]:
    """Deterministic verdict from the numbers; raises EligibilityRefusal where the record cannot support one."""
    if expected_rule_sha256 is not None:
        if not _is_sha256(expected_rule_sha256):
            raise EligibilityRefusal('the rule digest recorded at launch is not a sha256')
        if expected_rule_sha256 != rule.get('rule_sha256'):
            raise EligibilityRefusal('the rule digest differs from the one recorded at launch (the rule was edited after launch)')
    control, treatment = _arm(control, 'control'), _arm(treatment, 'treatment')
    if control.get('arm_id') != rule['control_arm_id'] or treatment.get('arm_id') != rule['treatment_arm_id']:
        raise EligibilityRefusal('the arm results do not carry the rule\'s control and treatment arm ids')
    for label, arm in (('control', control), ('treatment', treatment)):
        if arm.get('measurement_set_class') == 'protected':
            raise EligibilityRefusal(f'the {label} arm was measured on the protected set; selection on it is refused')
        if arm['published'] and arm.get('parent_manifest_sha256') != rule['frozen_start_manifest_sha256']:
            raise EligibilityRefusal(f'the {label} arm\'s parent differs from the frozen start (the baseline moved)')
    if (control['published'] and treatment['published'] and control.get('child_manifest_sha256') is not None
            and control.get('child_manifest_sha256') == treatment.get('child_manifest_sha256')):
        raise EligibilityRefusal('the two arms published the same checkpoint: no experiment happened')
    selection = rule['selection']
    treatment_wins, reason = False, 'the treatment did not publish'
    if treatment['published']:
        if not control['published']:
            reason = 'the control did not publish, so there is no baseline to beat'
        else:
            values = []
            for label, arm in (('control', control), ('treatment', treatment)):
                value = (arm.get('metric') or {}).get(selection['metric']) if isinstance(arm.get('metric'), Mapping) else None
                if not _number(value):
                    raise EligibilityRefusal(f'the {label} arm has no finite {selection["metric"]!r} for a published checkpoint')
                values.append(float(value))
            gain = (values[0] - values[1]) if selection['direction'] == 'lower' else (values[1] - values[0])
            treatment_wins = gain > 0 and gain >= selection['min_delta']
            reason = (f'the treatment beat the control by {gain!r} (needs >= {selection["min_delta"]!r})' if treatment_wins
                      else f'the treatment gain {gain!r} is below the required {selection["min_delta"]!r}')
    if treatment_wins:
        eligible, verdict = treatment, TREATMENT_ELIGIBLE
    elif control['published']:
        eligible, verdict = control, CONTROL_ELIGIBLE
    else:
        eligible, verdict, reason = None, NONE_ELIGIBLE, reason + '; the control did not publish either'
    retained = 0 if eligible is None else int(eligible.get('applied_positions', 0))
    if retained < 0:
        raise EligibilityRefusal('applied_positions must be nonnegative')
    return {'verdict': verdict, 'eligible_arm': None if eligible is None else eligible['arm_id'],
            'retained_applied_positions': retained, 'reason': reason, 'rule_sha256': rule['rule_sha256']}


def write_arm_results(identity: Mapping[str, Any], *, control: Any, treatment: Any, custody: Path) -> Path:
    """The single-sourced writer for `arm-results.json`: the producer (the orchestration that has both arms' published
    checkpoints and developmental measurements) calls this before the runner's outcome seam. It binds the identity's own
    rule digest, and refuses to write a record the adjudicator would refuse, so a malformed record is caught at the producer."""
    rule = validate_identity_rule(identity)
    adjudicate(rule, control, treatment, expected_rule_sha256=rule['rule_sha256'])   # raises EligibilityRefusal on a bad record
    path = Path(custody) / ARM_RESULTS_FILENAME
    payload = json.dumps({'rule_sha256': rule['rule_sha256'], 'control': control, 'treatment': treatment}, indent=2, sort_keys=True)
    try:
        with open(path, 'x', encoding='utf-8') as stream:   # exclusive creation: no check-then-write window for another writer
            stream.write(payload)
    except FileExistsError as exc:
        raise EligibilityRefusal('arm-results.json already exists in this custody (never overwritten)') from exc
    return path


def adjudicated_eligible_descendant(identity: Mapping[str, Any], *, run_succeeded: bool, custody: Path) -> bool:
    """The runner's caller for `record_retention_experiment_outcome(eligible_descendant_published=...)`.
    False when the run failed, when no arm results exist, or when adjudication refuses (the refusal is written beside them);
    True only when adjudication names an eligible arm."""
    if not run_succeeded:
        return False
    custody = Path(custody)
    arms_path = custody / ARM_RESULTS_FILENAME
    if not arms_path.is_file():
        return False
    try:
        rule = validate_identity_rule(identity)
        arms = json.loads(arms_path.read_text(encoding='utf-8'))
        if not isinstance(arms, dict) or set(arms) != {'rule_sha256', 'control', 'treatment'}:
            raise EligibilityRefusal('arm-results.json must hold exactly rule_sha256, control and treatment')
        # arms['rule_sha256'] is the digest the arm producer recorded at launch; it must be present, well-formed and the identity's
        if not _is_sha256(arms['rule_sha256']):
            raise EligibilityRefusal('arm-results.json carries no valid launch rule digest')
        verdict = adjudicate(rule, arms['control'], arms['treatment'], expected_rule_sha256=arms['rule_sha256'])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:   # EligibilityRefusal and JSONDecodeError are ValueErrors
        (custody / REFUSAL_FILENAME).write_text(json.dumps({'refused': f'{type(exc).__name__}: {exc}'}, indent=2, sort_keys=True), encoding='utf-8')
        return False
    (custody / 'eligibility-verdict.json').write_text(json.dumps(verdict, indent=2, sort_keys=True), encoding='utf-8')
    return verdict['eligible_arm'] is not None
