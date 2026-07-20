#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind parameter_counter's six independently-measured axes into the identity manifest.

cond3 increment-1 (parameter_identity, 160 census rows): the identity manifest's
``parameters`` section must not be hand-typed or fixture-constant. This module is the
one wiring path between ``tools/ember-restart-3b/parameter_counter.execute_counter``
(the trusted, isolated counter that inspects a *live* checkpoint under ``-I``) and
``scripts/ember_01_identity/validate_identity`` (the manifest-shape validator).

Two functions:

- ``bind_parameter_identity`` calls the real counter against a live checkpoint manifest
  and model config, then projects its six measured axes + subject_checkpoint_sha256
  into a manifest ``parameters`` section and ``checkpoint.byte_sha256``. It never
  invents a parameter count — every value traces to ``execute_counter``'s MEASURED
  receipt.
- ``verify_parameter_identity_binding`` re-derives the same six axes from the supplied
  realization receipt and fails closed (raises ``ParameterIdentityMismatch``, naming the
  axis) the instant the manifest's claimed value diverges from the receipt's measured
  value for that axis, or the checkpoint identity diverges. This is the round-trip
  proof surface: tamper one axis in the manifest without touching the receipt and this
  raises; tamper nothing and it is silent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

_COUNTER_MODULE_DIR = (
    Path(__file__).resolve().parents[2] / "tools" / "ember-restart-3b"
)
if str(_COUNTER_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_COUNTER_MODULE_DIR))

from parameter_counter import execute_counter  # noqa: E402  (path seam above)

# Maps the manifest's parameter field names (schema-v1.json / validate_identity.py
# REQUIRED_PATHS) to the realization receipt's field names
# (parameter_counter.REALIZATION_RECEIPT_FIELDS). Six axes, cond3 increment-1 scope.
AXIS_MAP: Mapping[str, str] = {
    "allocated": "allocated_parameters",
    "unique": "unique_parameters",
    "trainable": "trainable_parameters",
    "served": "served_parameters",
    "active": "active_parameters",
    "actually_trained": "episode_trainable_parameters",
}


class ParameterIdentityMismatch(ValueError):
    """A manifest's claimed parameter identity diverges from measured evidence."""


def _canonical_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(receipt), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def measure_live_checkpoint(
    *, model_config: Path, checkpoint_manifest: Path, active_expert: str = "shared"
) -> dict[str, Any]:
    """Run the real, isolated counter against a live checkpoint. No fixture path."""
    return execute_counter(
        model_config=model_config,
        checkpoint_manifest=checkpoint_manifest,
        active_expert=active_expert,
    )


def bind_parameter_identity(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Project a MEASURED realization receipt into the manifest's parameter/checkpoint fields.

    ``receipt`` must be the return value of ``measure_live_checkpoint``
    (equivalently ``parameter_counter.execute_counter``), i.e. an already-validated
    ``ember-sparse-realization-receipt-v1`` receipt bound to a real checkpoint.
    """
    if receipt.get("result") != "MEASURED" or receipt.get("verification_boundary") != "VERIFIED_MEASURED":
        raise ParameterIdentityMismatch(
            "receipt is not measured evidence; refusing to bind an unverified count"
        )
    receipt_hash = _canonical_receipt_sha256(receipt)
    bound = dict(manifest)
    bound["checkpoint"] = {**dict(manifest.get("checkpoint", {})), "byte_sha256": receipt["subject_checkpoint_sha256"]}
    bound["parameters"] = {
        **{field: receipt[axis] for field, axis in AXIS_MAP.items()},
        "evidence_receipts": {field: [receipt_hash] for field in AXIS_MAP},
    }
    evaluation = dict(manifest.get("evaluation", {}))
    evaluation["subject_checkpoint_sha256"] = receipt["subject_checkpoint_sha256"]
    bound["evaluation"] = evaluation
    return bound


def verify_parameter_identity_binding(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> None:
    """Fail closed the instant a manifest's parameter axis diverges from the receipt.

    Raises ``ParameterIdentityMismatch`` naming the exact axis (or the checkpoint
    identity) that no longer matches the independently measured evidence. Silent
    (returns None) when every bound value matches.
    """
    parameters = manifest.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ParameterIdentityMismatch("manifest has no parameters section to verify")
    for field, axis in AXIS_MAP.items():
        claimed = parameters.get(field)
        measured = receipt.get(axis)
        if claimed != measured:
            raise ParameterIdentityMismatch(
                f"parameters.{field} claims {claimed!r} but the live-checkpoint "
                f"counter measured {axis}={measured!r}"
            )
    checkpoint = manifest.get("checkpoint")
    claimed_checkpoint = checkpoint.get("byte_sha256") if isinstance(checkpoint, Mapping) else None
    if claimed_checkpoint != receipt.get("subject_checkpoint_sha256"):
        raise ParameterIdentityMismatch(
            "checkpoint.byte_sha256 does not match the counter's subject_checkpoint_sha256"
        )
