#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind the training OPTIMIZER subsystem's identity into the identity manifest.

cond3 increment (optimizer category): the identity manifest's
``training.optimizer_state_sha256`` must not carry an optimizer-state digest unless
that digest is the sha256 of the *actual* optimizer state bytes produced by the
optimizer that was REALIZED for this genesis run. A hand-typed or borrowed optimizer
digest may never be projected into the manifest.

Two real production consumers already constrain the optimizer subsystem; this module is
the wiring path that keeps the manifest honest against BOTH, and its verifier
re-derives (never restates) their invariants:

- ``scripts/ember_01_identity/validate_identity.validate_manifest`` treats
  ``training.optimizer_state_sha256`` as a GENESIS_BOUND field (validate_identity.py
  ~line 152) AND requires the artifact bundle to supply a ``training.optimizer_state``
  artifact whose content hashes to it (validate_identity.py ~line 1083, finding
  ``admission.artifact_hash_mismatch`` for ``training.optimizer_state``). That is the
  state-bytes half of the optimizer identity: the digest in the manifest must equal the
  sha256 of the optimizer state bytes actually admitted.
- A signed ``ember-optimizer-realization-v1`` receipt (``result == "REALIZED"``)
  carries the realized implementation, hyperparameters, state format, implementation
  source, parameter-group convention, parameter-name/local-ID mapping, and trusted
  verifier identity. The identity contract binds each field plus a canonical
  content-address of that receipt. That is the contract half: the optimizer that
  produced the state is the realized one, not an arbitrary optimizer.

``bind_optimizer_identity`` projects the state-bytes digest into the manifest, deriving
it from the actual optimizer state bytes (never hand-typed) and only after a signed
REALIZED realization receipt authorises the optimizer that produced them.
``verify_optimizer_identity_binding`` fails closed -- naming the exact field -- the
instant ``training.optimizer_state_sha256`` diverges from the sha256 of the supplied
optimizer state bytes, or the realization receipt is not a VERIFIED/REALIZED
``ember-optimizer-realization-v1`` naming a concrete optimizer contract. The round-trip
is proved end-to-end against the real ``validate_manifest`` in
tests/ember_01_identity/domain-governance/test_optimizer_identity_roundtrip.py.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# The optimizer-realization schema + result that src/ember/governance/scripts/ember_restart/contract.py binds
# (contract.py ~line 798-799). The realization receipt authorises the optimizer whose
# state bytes are projected into the manifest.
OPTIMIZER_REALIZATION_SCHEMA = "ember-optimizer-realization-v1"
OPTIMIZER_REALIZATION_RESULT = "REALIZED"

# Contract fields carried by the independently verified realization receipt. Each must
# be present and concrete before its state bytes may be credited as the manifest's
# optimizer identity. ``realization_receipt_sha256`` is deliberately excluded: it is
# derived below from canonical receipt content rather than self-attested by the receipt.
OPTIMIZER_RECEIPT_CONTRACT_FIELDS: tuple[str, ...] = (
    "implementation",
    "hyperparameters",
    "state_format",
    "implementation_source_sha256",
    "param_group_mapping_convention",
    "param_name_optimizer_id_mapping_sha256",
    "trusted_verifier_id",
)

OPTIMIZER_CONTRACT_FIELDS: tuple[str, ...] = (
    *OPTIMIZER_RECEIPT_CONTRACT_FIELDS,
    "realization_receipt_sha256",
)


class OptimizerIdentityMismatch(ValueError):
    """A manifest's claimed optimizer identity diverges from measured evidence."""


def _state_digest(optimizer_state_bytes: bytes) -> str:
    return hashlib.sha256(optimizer_state_bytes).hexdigest()


def canonical_realization_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    """Content-address a realization receipt without depending on file formatting."""
    canonical = json.dumps(
        dict(receipt),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _require_realized_receipt(receipt: Mapping[str, Any]) -> None:
    """Fail closed unless ``receipt`` is a VERIFIED/REALIZED optimizer realization."""
    schema = receipt.get("schema_version")
    if schema != OPTIMIZER_REALIZATION_SCHEMA:
        raise OptimizerIdentityMismatch(
            f"realization receipt schema_version={schema!r} is not "
            f"{OPTIMIZER_REALIZATION_SCHEMA!r}; refusing to credit a non-optimizer "
            "realization as optimizer identity"
        )
    result = receipt.get("result")
    if result != OPTIMIZER_REALIZATION_RESULT:
        raise OptimizerIdentityMismatch(
            f"realization receipt result={result!r} is not "
            f"{OPTIMIZER_REALIZATION_RESULT!r}; refusing to bind an unrealized optimizer"
        )
    for field in OPTIMIZER_RECEIPT_CONTRACT_FIELDS:
        value = receipt.get(field)
        if value is None or (isinstance(value, (str, Mapping)) and not value):
            raise OptimizerIdentityMismatch(
                f"realization receipt is missing a concrete optimizer contract "
                f"field {field!r}; the optimizer that produced the state is unnamed"
            )


def bind_optimizer_identity(
    manifest: Mapping[str, Any],
    optimizer_state_bytes: bytes,
    realization_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the optimizer state-bytes digest into ``training.optimizer_state_sha256``.

    The digest is always re-derived from ``optimizer_state_bytes`` (the actual admitted
    optimizer state), never taken from the manifest or the receipt -- so a borrowed or
    hand-typed optimizer digest cannot be laundered in. The projection only happens once
    a signed REALIZED ``ember-optimizer-realization-v1`` receipt authorises the optimizer
    that produced those bytes. Returns a new manifest with the training section rebound.
    """
    _require_realized_receipt(realization_receipt)
    training = manifest.get("training")
    if not isinstance(training, Mapping):
        raise OptimizerIdentityMismatch(
            "manifest has no training section to bind optimizer identity into"
        )
    bound = dict(manifest)
    bound_training = dict(training)
    bound_training["optimizer_state_sha256"] = _state_digest(optimizer_state_bytes)
    bound_training["optimizer_contract"] = {
        field: realization_receipt[field]
        for field in OPTIMIZER_RECEIPT_CONTRACT_FIELDS
    }
    bound_training["optimizer_contract"][
        "realization_receipt_sha256"
    ] = canonical_realization_receipt_sha256(realization_receipt)
    bound["training"] = bound_training
    return bound


def verify_optimizer_identity_binding(
    manifest: Mapping[str, Any],
    optimizer_state_bytes: bytes,
    realization_receipt: Mapping[str, Any],
) -> None:
    """Fail closed the instant the manifest's optimizer identity diverges from evidence.

    Re-derives every checked value from the actual optimizer state bytes and the signed
    realization receipt (never restates the manifest against itself):

    1. The realization receipt must be a VERIFIED/REALIZED
       ``ember-optimizer-realization-v1`` naming a concrete optimizer contract (mirrors
       contract.py's ``training.optimizer_receipt.<field>: binding mismatch``).
    2. ``training.optimizer_state_sha256`` must equal the sha256 of the supplied
       optimizer state bytes (mirrors validate_identity.py's
       ``admission.artifact_hash_mismatch`` for ``training.optimizer_state``).

    Raises ``OptimizerIdentityMismatch`` naming the exact field that fails. Silent
    (returns None) when the bound digest matches the real optimizer state bytes.
    """
    _require_realized_receipt(realization_receipt)
    training = manifest.get("training")
    if not isinstance(training, Mapping):
        raise OptimizerIdentityMismatch(
            "manifest has no training section to verify optimizer identity"
        )
    claimed = training.get("optimizer_state_sha256")
    expected = _state_digest(optimizer_state_bytes)
    if claimed != expected:
        raise OptimizerIdentityMismatch(
            f"training.optimizer_state_sha256={claimed!r} is not the sha256 of the "
            f"admitted optimizer state bytes ({expected!r}); a hand-typed or borrowed "
            "optimizer digest cannot be credited as this genesis run's optimizer identity"
        )

    # cond3 CONTRACT-half: when the manifest declares the optimizer contract identity,
    # every field must equal the signed REALIZED realization receipt's field (mirrors
    # contract.py's ``training.optimizer_receipt.<field>: binding mismatch``). A manifest
    # optimizer contract that diverges from the realized optimizer -- or omits a field --
    # fails closed naming the exact field. Absent contract is legal HERE (state-half
    # only, this function does not gate on disposition) -- but as of B4
    # (ember01plan.md SS B4 L1061-1082) an absent contract is NOT legal fleet-wide: a
    # manifest with identity.disposition == "OWNED_ADMITTED" is rejected by
    # validate_identity.validate_manifest's admission.optimizer_contract_missing check
    # before this function is ever reached for that manifest's contract-half. This
    # The binding below independently compares all realized evidence fields and the
    # canonical receipt content address; schema completeness alone is insufficient.
    optimizer_contract = training.get("optimizer_contract")
    if optimizer_contract is not None:
        if not isinstance(optimizer_contract, Mapping):
            raise OptimizerIdentityMismatch(
                "training.optimizer_contract is not an object; the optimizer contract "
                "identity cannot be bound to the realization receipt"
            )
        for field in OPTIMIZER_RECEIPT_CONTRACT_FIELDS:
            manifest_value = optimizer_contract.get(field)
            receipt_value = realization_receipt.get(field)
            if manifest_value is None or (
                isinstance(manifest_value, (str, Mapping)) and not manifest_value
            ):
                raise OptimizerIdentityMismatch(
                    f"training.optimizer_contract_{field}: missing; the optimizer that "
                    "produced the state is unnamed in the manifest contract identity"
                )
            if manifest_value != receipt_value:
                raise OptimizerIdentityMismatch(
                    f"training.optimizer_contract_{field}: binding mismatch "
                    f"(manifest={manifest_value!r} != realized receipt={receipt_value!r}); "
                    "the manifest optimizer contract is not the realized optimizer"
                )
        manifest_receipt_sha = optimizer_contract.get("realization_receipt_sha256")
        expected_receipt_sha = canonical_realization_receipt_sha256(
            realization_receipt
        )
        if manifest_receipt_sha != expected_receipt_sha:
            raise OptimizerIdentityMismatch(
                "training.optimizer_contract_realization_receipt_sha256: "
                f"binding mismatch (manifest={manifest_receipt_sha!r} != canonical "
                f"realized receipt={expected_receipt_sha!r}); the manifest optimizer "
                "contract is not bound to the supplied realization evidence"
            )
