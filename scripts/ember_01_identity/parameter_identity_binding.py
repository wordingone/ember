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
- ``verify_parameter_identity_binding`` takes the live ``checkpoint_manifest`` and
  ``model_config`` paths (never just the receipt dict) and re-derives every value it
  checks from bytes on disk: it re-hashes the checkpoint manifest file to catch a
  receipt whose ``subject_checkpoint_sha256`` does not match any checkpoint that
  actually exists, re-hashes the model config file and binds it to the receipt's
  ``model_config_sha256`` when the receipt carries that field, then re-runs the
  real, isolated ``execute_counter`` against those same paths and compares its
  freshly measured six axes + checkpoint hash against the receipt's claims. Only
  after that independent re-derivation does it fall back to the manifest-vs-receipt
  field comparison. It fails closed (raises ``ParameterIdentityMismatch``, naming
  the axis or the checkpoint identity) the instant any claimed value diverges from
  what is independently, freshly measured -- including when the re-derivation itself
  errors for any reason (not only ``ValueError``). This is the round-trip proof
  surface: tamper one axis in the manifest without touching the receipt and this
  raises; hand-author a receipt with no matching checkpoint on disk and this raises;
  tamper nothing and it is silent.

  Scope: this verification path covers shared-routed receipts only
  (``active_expert_ids == ["shared"]``, the only routing ``bind_parameter_identity``
  currently emits). A specialist-routed receipt (``active_expert_ids`` naming one of
  the four expert banks) demands ``execute_counter``'s external parent/root manifest
  chain and P2B stream authority inputs that this function does not thread through;
  rather than silently mis-verify such a receipt, it fails closed immediately naming
  the scope gap. Specialist-routed verification is a deliberately separate,
  not-yet-implemented path.
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
from parameter_counter import _sha256 as _hash_file  # noqa: E402  (streaming file hash, no full-file read)

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
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    checkpoint_manifest: Path,
    model_config: Path,
    active_expert: str | None = None,
) -> None:
    """Fail closed the instant claimed identity diverges from bytes on disk.

    ``checkpoint_manifest`` and ``model_config`` are the live paths the receipt
    claims to be evidence for -- they are the single authoritative source of
    checkpoint bytes for this verification, never the receipt dict alone. Two
    independent re-derivations run before any field-to-field comparison:

    1. The checkpoint manifest file is re-hashed from disk (streaming reads, same
       mechanism as ``parameter_counter._sha256``) and compared against the
       receipt's claimed ``subject_checkpoint_sha256``. A receipt naming a hash
       with no matching checkpoint on disk fails here.
    2. The real, isolated ``execute_counter`` is re-run against those same paths,
       independently re-measuring all six parameter axes and the checkpoint
       identity. A hand-authored receipt with fabricated counts fails here even
       if its checkpoint hash happens to match.

    Only once both re-derivations agree with the receipt does this fall back to
    the manifest-vs-receipt field comparison (which still catches a manifest that
    diverges from an otherwise-honest receipt). Raises
    ``ParameterIdentityMismatch`` naming the exact axis (or the checkpoint
    identity) that fails to independently re-derive. Silent (returns None) when
    every bound value matches the freshly measured evidence.
    """
    checkpoint_manifest = Path(checkpoint_manifest)
    model_config = Path(model_config)

    claimed_subject_sha256 = receipt.get("subject_checkpoint_sha256")
    try:
        real_checkpoint_sha256 = _hash_file(checkpoint_manifest)
    except OSError as error:
        raise ParameterIdentityMismatch(
            f"checkpoint_manifest at {checkpoint_manifest} could not be read from "
            f"disk to re-derive its hash; receipt claims "
            f"subject_checkpoint_sha256={claimed_subject_sha256!r} but no such "
            f"checkpoint bytes exist to verify against ({error})"
        ) from error
    if real_checkpoint_sha256 != claimed_subject_sha256:
        raise ParameterIdentityMismatch(
            f"receipt claims subject_checkpoint_sha256={claimed_subject_sha256!r} "
            f"but the checkpoint manifest bytes on disk hash to "
            f"{real_checkpoint_sha256!r}"
        )

    claimed_model_config_sha256 = receipt.get("model_config_sha256")
    if claimed_model_config_sha256 is not None:
        try:
            real_model_config_sha256 = _hash_file(model_config)
        except OSError as error:
            raise ParameterIdentityMismatch(
                f"model_config at {model_config} could not be read from disk to "
                f"re-derive its hash; receipt claims "
                f"model_config_sha256={claimed_model_config_sha256!r} but no such "
                f"config bytes exist to verify against ({error})"
            ) from error
        if real_model_config_sha256 != claimed_model_config_sha256:
            raise ParameterIdentityMismatch(
                f"receipt claims model_config_sha256={claimed_model_config_sha256!r} "
                f"but the model config bytes on disk hash to "
                f"{real_model_config_sha256!r}"
            )

    resolved_active_expert = active_expert
    if resolved_active_expert is None:
        active_expert_ids = receipt.get("active_expert_ids")
        resolved_active_expert = (
            active_expert_ids[0]
            if isinstance(active_expert_ids, list) and active_expert_ids
            else "shared"
        )
    if resolved_active_expert != "shared":
        raise ParameterIdentityMismatch(
            "verify_parameter_identity_binding covers shared-routed receipts only "
            f"(resolved active_expert={resolved_active_expert!r} from "
            f"active_expert_ids={receipt.get('active_expert_ids')!r}); "
            "specialist-routed receipts require execute_counter's external "
            "parent/root manifest chain, which this function does not thread "
            "through, and are a separate, not-yet-implemented verification path"
        )
    try:
        remeasured = measure_live_checkpoint(
            model_config=model_config,
            checkpoint_manifest=checkpoint_manifest,
            active_expert=resolved_active_expert,
        )
    except Exception as error:
        raise ParameterIdentityMismatch(
            f"re-running the live-checkpoint counter against {checkpoint_manifest} "
            f"failed; the receipt's evidence does not independently re-derive "
            f"({type(error).__name__}: {error})"
        ) from error

    for field, axis in AXIS_MAP.items():
        measured = remeasured.get(axis)
        claimed = receipt.get(axis)
        if measured != claimed:
            raise ParameterIdentityMismatch(
                f"receipt claims {axis}={claimed!r} but re-running the live-checkpoint "
                f"counter independently measured {axis}={measured!r}"
            )
    if remeasured.get("subject_checkpoint_sha256") != claimed_subject_sha256:
        raise ParameterIdentityMismatch(
            "receipt's subject_checkpoint_sha256 diverges from the re-measured "
            "counter result"
        )

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
