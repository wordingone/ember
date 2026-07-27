#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind a benchmark/evaluation result's identity into the identity manifest.

cond3 increment (evaluation_benchmark category): the identity manifest's
``evaluation`` section must not credit a benchmark score to the owned Ember unless
that score was measured against the *exact* owned checkpoint bytes, by a signed
``evaluation_result`` receipt whose claimed benchmark fields match the manifest. A
score run on a borrowed/comparator checkpoint may never be projected as owned
completion credit.

The single production consumer that already enforces this is
``scripts/ember_01_identity/validate_identity.validate_manifest`` -- specifically the
two cross-checks it runs over ``evaluation``:

- ``evaluation.subject_checkpoint_sha256 == checkpoint.byte_sha256`` (owned-vs-borrowed;
  validate_identity.py ~line 911-913, finding ``evaluation.subject_checkpoint_mismatch``);
- for an ``OWNED_ADMITTED`` manifest, the signed ``evaluation_result`` receipt named by
  ``evaluation.receipt_sha256`` must resolve, carry ``evidence_class ==
  "evaluation_result"``, be signed by a pinned verifier, bind ``subject_checkpoint_sha256
  == checkpoint.byte_sha256``, and claim every benchmark field
  (``benchmark_id, version, split, harness_sha256, comparator_identity,
  comparator_sha256, score, uncertainty, counts_toward_owned_completion``) exactly as the
  manifest states (validate_identity.py ~line 934-963, findings
  ``admission.receipt_*`` / ``admission.evaluation_receipt``).

This module is the wiring path INTO that consumer: it projects a MEASURED, signed
evaluation_result receipt into the manifest's ``evaluation`` section (never a hand-typed
score), always setting ``subject_checkpoint_sha256`` to the manifest's own checkpoint
bytes so a borrowed-subject receipt cannot be laundered into owned credit. Its
``verify_evaluation_identity_binding`` fails closed -- naming the exact field -- the
instant the manifest's evaluation identity diverges from the signed receipt or from the
checkpoint bytes, mirroring (and re-deriving, not restating) the invariants
validate_manifest enforces. The round-trip is proved end-to-end against the real
validate_manifest in tests/ember_01_identity/test_evaluation_identity_roundtrip.py.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# The benchmark-identity fields the manifest's evaluation section must carry and the
# signed evaluation_result receipt must independently claim (validate_identity.py's
# expected_claims set for the evaluation receipt, plus the subject checkpoint binding).
EVALUATION_CLAIM_FIELDS: tuple[str, ...] = (
    "benchmark_id",
    "version",
    "split",
    "harness_sha256",
    "comparator_identity",
    "comparator_sha256",
    "score",
    "uncertainty",
    "counts_toward_owned_completion",
)

EVALUATION_EVIDENCE_CLASS = "evaluation_result"


class EvaluationIdentityMismatch(ValueError):
    """A manifest's claimed evaluation identity diverges from measured evidence."""


def _canonical_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(receipt), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_evaluation_identity(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Project a signed evaluation_result receipt into the manifest's evaluation section.

    ``receipt`` must be an ``evaluation_result`` evidence receipt whose
    ``result == "VERIFIED"`` and whose ``subject_checkpoint_sha256`` equals the
    manifest's ``checkpoint.byte_sha256`` -- i.e. the score was measured against THIS
    owned checkpoint. Every benchmark field is taken from the receipt's own claims;
    nothing is invented. ``evaluation.receipt_sha256`` is set to the receipt's canonical
    hash so validate_manifest can resolve it back to this exact receipt.
    """
    if receipt.get("evidence_class") != EVALUATION_EVIDENCE_CLASS:
        raise EvaluationIdentityMismatch(
            "receipt is not an evaluation_result; refusing to bind a non-evaluation "
            f"evidence class {receipt.get('evidence_class')!r}"
        )
    if receipt.get("result") != "VERIFIED":
        raise EvaluationIdentityMismatch(
            "evaluation receipt is not VERIFIED; refusing to bind an unverified score"
        )
    checkpoint = manifest.get("checkpoint")
    checkpoint_hash = checkpoint.get("byte_sha256") if isinstance(checkpoint, Mapping) else None
    if receipt.get("subject_checkpoint_sha256") != checkpoint_hash:
        raise EvaluationIdentityMismatch(
            "evaluation receipt's subject_checkpoint_sha256="
            f"{receipt.get('subject_checkpoint_sha256')!r} is not this manifest's "
            f"owned checkpoint bytes {checkpoint_hash!r}; a benchmark measured on a "
            "borrowed checkpoint cannot be bound as owned completion credit"
        )
    for field in EVALUATION_CLAIM_FIELDS:
        if field not in receipt:
            raise EvaluationIdentityMismatch(
                f"evaluation receipt is missing required benchmark claim {field!r}"
            )
    bound = dict(manifest)
    evaluation = dict(manifest.get("evaluation", {}))
    for field in EVALUATION_CLAIM_FIELDS:
        evaluation[field] = receipt[field]
    evaluation["subject_checkpoint_sha256"] = checkpoint_hash
    evaluation["receipt_sha256"] = _canonical_receipt_sha256(receipt)
    bound["evaluation"] = evaluation
    return bound


def verify_evaluation_identity_binding(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> None:
    """Fail closed the instant the manifest's evaluation identity diverges from evidence.

    Re-derives every checked value from the signed receipt and the manifest's own
    checkpoint bytes (never restates the manifest against itself):

    1. evaluation.subject_checkpoint_sha256 must equal checkpoint.byte_sha256 -- the
       owned-vs-borrowed rule. A benchmark whose subject is any other checkpoint is a
       borrowed score and cannot be credited (mirrors validate_identity.py's
       ``evaluation.subject_checkpoint_mismatch``).
    2. The receipt must be an ``evaluation_result`` with ``result == "VERIFIED"`` whose
       ``subject_checkpoint_sha256`` also equals the owned checkpoint bytes (mirrors
       validate_identity.py's ``admission.receipt_class_mismatch`` /
       ``admission.receipt_result_mismatch`` / ``admission.receipt_checkpoint_mismatch``).
    3. Every benchmark field in the manifest must equal the receipt's own claim
       (mirrors ``admission.receipt_claim_mismatch``).
    4. evaluation.receipt_sha256 must resolve to this exact receipt by canonical hash
       (mirrors ``admission.evaluation_receipt`` / ``admission.receipt_hash_mismatch``).

    Raises ``EvaluationIdentityMismatch`` naming the exact field that fails. Silent
    (returns None) when every bound value matches the signed evidence.
    """
    evaluation = manifest.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise EvaluationIdentityMismatch("manifest has no evaluation section to verify")
    checkpoint = manifest.get("checkpoint")
    checkpoint_hash = checkpoint.get("byte_sha256") if isinstance(checkpoint, Mapping) else None

    subject = evaluation.get("subject_checkpoint_sha256")
    if subject != checkpoint_hash:
        raise EvaluationIdentityMismatch(
            f"evaluation.subject_checkpoint_sha256={subject!r} is not the owned "
            f"checkpoint bytes {checkpoint_hash!r}; borrowed-subject scores cannot be "
            "credited as owned completion"
        )
    if receipt.get("evidence_class") != EVALUATION_EVIDENCE_CLASS:
        raise EvaluationIdentityMismatch(
            f"receipt evidence_class={receipt.get('evidence_class')!r} is not "
            f"{EVALUATION_EVIDENCE_CLASS!r}"
        )
    if receipt.get("result") != "VERIFIED":
        raise EvaluationIdentityMismatch(
            f"receipt result={receipt.get('result')!r} is not VERIFIED"
        )
    if receipt.get("subject_checkpoint_sha256") != checkpoint_hash:
        raise EvaluationIdentityMismatch(
            "receipt subject_checkpoint_sha256="
            f"{receipt.get('subject_checkpoint_sha256')!r} does not match the owned "
            f"checkpoint bytes {checkpoint_hash!r}"
        )
    for field in EVALUATION_CLAIM_FIELDS:
        claimed = evaluation.get(field)
        measured = receipt.get(field)
        if claimed != measured:
            raise EvaluationIdentityMismatch(
                f"evaluation.{field} claims {claimed!r} but the signed "
                f"evaluation_result receipt measured {field!r}={measured!r}"
            )
    expected_digest = _canonical_receipt_sha256(receipt)
    if evaluation.get("receipt_sha256") != expected_digest:
        raise EvaluationIdentityMismatch(
            f"evaluation.receipt_sha256={evaluation.get('receipt_sha256')!r} does not "
            f"resolve to the signed evaluation_result receipt ({expected_digest!r})"
        )
