"""Issue #2119 rows 5/14: the PRODUCER of `arm-results.json`.

`retention_eligibility.write_arm_results` is the single writer and refuses a record the adjudicator would refuse, but nothing
called it, so `adjudicated_eligible_descendant` read "no arm results" (False) for every run. This module is the caller: it
turns two SCORED arms (control, treatment) into the typed arm records the adjudicator reads and writes them, exclusively,
into the run custody BEFORE the runner's outcome seam (`record_retention_outcome`) reads that custody.

Every number is read from a scored receipt, never typed. A missing, unscored or protected-set arm is written as an
unpublished arm only where the checkpoint genuinely did not publish; a published arm that lacks its metric, manifest digests or
developmental class makes `write_arm_results` raise `EligibilityRefusal` here, at the producer, so the refusal is visible
before the ledger outcome is recorded (and the outcome then reads NOT eligible, never eligible by default).

Stdlib only; loaded by path like its siblings.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import retention_eligibility as elig


class ArmProducerRefusal(ValueError):
    """The scored receipts cannot be turned into a typed arm record."""


def _metric_from_receipt(receipt: Mapping[str, Any], dotted: str) -> float:
    node: Any = receipt
    for part in dotted.split('.'):
        if not isinstance(node, Mapping) or part not in node:
            raise ArmProducerRefusal(f'the scored receipt has no {dotted!r}')
        node = node[part]
    if not elig._number(node):
        raise ArmProducerRefusal(f'the scored receipt {dotted!r} is not a finite number')
    return float(node)


def build_arm(arm_id: str, *, published: bool, parent_manifest_sha256: str | None = None, child_manifest_sha256: str | None = None,
              applied_positions: int = 0, metric_name: str | None = None, metric_value: float | None = None,
              measurement_set_class: str = 'developmental') -> dict[str, Any]:
    """One typed arm record. An unpublished arm carries no digests and no metric (the adjudicator never reads them)."""
    if not published:
        return {'arm_id': arm_id, 'published': False, 'parent_manifest_sha256': None, 'child_manifest_sha256': None,
                'metric': {}, 'measurement_set_class': measurement_set_class, 'applied_positions': 0}
    if metric_name is None or metric_value is None:
        raise ArmProducerRefusal(f'the {arm_id} arm is published but has no metric')
    return {'arm_id': arm_id, 'published': True, 'parent_manifest_sha256': parent_manifest_sha256,
            'child_manifest_sha256': child_manifest_sha256, 'metric': {metric_name: metric_value},
            'measurement_set_class': measurement_set_class, 'applied_positions': applied_positions}


SCORED_RECEIPT_SCHEMAS = frozenset({'ember-2119-child-episode-nll-v1', 'ember-2119-child-nll-v1'})
MEASUREMENT_CLASSES = frozenset({'developmental', 'protected'})
# Mandatory frozen bindings (review 63986 R2, ruling 63996): population (episode plan + shard ledger), mixture, run (the arm's checkpoint receipt and the
# frozen declaration) and source (scorer + tokenizer). A caller that omits any of them, or gives a non-digest, is refused; nothing defaults.
MANDATORY_BINDING_KEYS = ('episode_plan_sha256', 'shard_ledger_sha256', 'mixture_identity_sha256', 'frozen_declaration_sha256',
                          'checkpoint_receipt_sha256', 'scorer_sha256', 'tokenizer_sha256')


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _bind_receipt_to_arm(arm_id: str, receipt: Mapping[str, Any], *, metric_path: str, child_manifest_sha256: str,
                         required_bindings: Mapping[str, Any], declaration_classes: Mapping[str, str]) -> str:
    """Bind the scored receipt to the declared arm from its OWN contents and return the measurement class derived from it.
    Nothing here trusts a caller label: the class comes from the receipt's frozen-declaration digest looked up in the trusted
    `declaration_classes` map, and identity comes from the receipt's checkpoint binding and `required_bindings`."""
    if receipt.get('schema') not in SCORED_RECEIPT_SCHEMAS:
        raise ArmProducerRefusal(f'the {arm_id} receipt schema {receipt.get("schema")!r} is not a scored-receipt schema')
    bindings = receipt.get('bindings')
    if not isinstance(bindings, Mapping):
        raise ArmProducerRefusal(f'the {arm_id} scored receipt carries no bindings')
    if bindings.get('checkpoint_manifest_sha256') != child_manifest_sha256:
        raise ArmProducerRefusal(f'the {arm_id} scored receipt is bound to checkpoint {bindings.get("checkpoint_manifest_sha256")!r}, '
                                 f'not the declared child {child_manifest_sha256!r}')
    for key, want in required_bindings.items():
        if bindings.get(key) != want:
            raise ArmProducerRefusal(f'the {arm_id} scored receipt binding {key!r} is {bindings.get(key)!r}, not the required {want!r}')
    parent_node: Any = receipt
    for part in metric_path.split('.')[:-1]:
        parent_node = parent_node.get(part) if isinstance(parent_node, Mapping) else None
    for node in (receipt, parent_node):
        if isinstance(node, Mapping) and node.get('status') == 'NOT_MEASURED':
            raise ArmProducerRefusal(f'the {arm_id} scored receipt is unscored (NOT_MEASURED at or above {metric_path!r})')
    declaration = bindings.get('frozen_declaration_sha256')
    measurement_class = declaration_classes.get(declaration) if isinstance(declaration, str) else None
    if measurement_class not in MEASUREMENT_CLASSES:
        raise ArmProducerRefusal(f'the {arm_id} scored receipt frozen_declaration_sha256 {declaration!r} has no trusted measurement class')
    return measurement_class


def arm_from_scored_receipt(arm_id: str, receipt_path: Path | None, *, metric_name: str, metric_path: str,
                            parent_manifest_sha256: str, child_manifest_sha256: str | None, applied_positions: int,
                            required_bindings: Mapping[str, Any], declaration_classes: Mapping[str, str],
                            expected_receipt_sha256: str | None = None) -> dict[str, Any]:
    """A published arm from its scored receipt (metric read from `metric_path`, e.g. 'arms.fresh.mean_nll'), or an
    unpublished arm when the child did not publish (`child_manifest_sha256` is None and no receipt). A published arm's receipt
    must be a scored-receipt schema bound to THIS child manifest and to every `required_bindings` entry (for example the
    frozen declaration and mixture identity shared by the pair); the measurement class is derived from the receipt's frozen
    declaration through `declaration_classes`, never supplied; the source receipt digest is retained on the arm record.
    `required_bindings` must carry every MANDATORY_BINDING_KEYS entry as a sha256 and `declaration_classes` must be nonempty (neither defaults);
    a published arm also needs `expected_receipt_sha256`, the digest of the scored receipt's bytes from the frozen-binding entry."""
    if child_manifest_sha256 is None:
        if receipt_path is not None:
            raise ArmProducerRefusal(f'the {arm_id} arm has a scored receipt but no published child manifest')
        return build_arm(arm_id, published=False)
    if receipt_path is None or not Path(receipt_path).is_file():
        raise ArmProducerRefusal(f'the {arm_id} arm published a child but its scored receipt is absent')
    missing = [key for key in MANDATORY_BINDING_KEYS if not elig._is_sha256((required_bindings or {}).get(key))]
    if missing:
        raise ArmProducerRefusal(f'the {arm_id} arm has no frozen sha256 for the mandatory bindings {missing}')
    if not declaration_classes:
        raise ArmProducerRefusal(f'the {arm_id} arm has no trusted declaration-to-class map')
    if not elig._is_sha256(expected_receipt_sha256):
        raise ArmProducerRefusal(f'the {arm_id} arm has no frozen digest for its scored receipt')
    if _file_sha256(Path(receipt_path)) != expected_receipt_sha256:
        raise ArmProducerRefusal(f'the {arm_id} scored receipt bytes differ from the frozen receipt digest')
    receipt = json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    if not isinstance(receipt, Mapping):
        raise ArmProducerRefusal(f'the {arm_id} scored receipt is not a JSON object')
    measurement_class = _bind_receipt_to_arm(arm_id, receipt, metric_path=metric_path, child_manifest_sha256=child_manifest_sha256,
                                             required_bindings=dict(required_bindings), declaration_classes=dict(declaration_classes))
    arm = build_arm(arm_id, published=True, parent_manifest_sha256=parent_manifest_sha256,
                    child_manifest_sha256=child_manifest_sha256, applied_positions=applied_positions,
                    metric_name=metric_name, metric_value=_metric_from_receipt(receipt, metric_path),
                    measurement_set_class=measurement_class)
    arm['source_receipt_sha256'] = _file_sha256(Path(receipt_path))
    arm['source_receipt_schema'] = receipt['schema']
    return arm


def produce_arm_results(identity: Mapping[str, Any], *, custody: Path, control: Any, treatment: Any) -> Path:
    """The producer call: validate the identity's frozen rule, then write `arm-results.json` exclusively into `custody`.
    Raises `retention_eligibility.EligibilityRefusal` for a record the adjudicator would refuse (nothing is written) and for a
    second call in the same custody (never overwritten)."""
    return elig.write_arm_results(identity, control=control, treatment=treatment, custody=Path(custody))
