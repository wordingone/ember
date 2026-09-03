# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 (evaluation_benchmark): a benchmark score round-trips its identity, fail-closed.

Not a narrative assertion: the positive case builds a REAL signed OWNED_ADMITTED
identity manifest (the same ``admitted_manifest`` machinery the production validator
tests use -- a real evaluation_result receipt signed by a pinned ed25519 verifier,
bound to a real checkpoint) and runs the actual production consumer,
``validate_identity.validate_manifest``. That consumer is the code path that
round-trips the evaluation identity (validate_identity.py ~line 911-963):

- ``evaluation.subject_checkpoint_sha256 == checkpoint.byte_sha256`` (owned-vs-borrowed);
- the signed ``evaluation_result`` receipt named by ``evaluation.receipt_sha256`` must
  resolve, be signed by a pinned verifier, bind the owned checkpoint, and claim every
  benchmark field exactly as the manifest states.

Six fail-closed negatives drive the manifest's evaluation identity out of agreement with
the signed evidence and assert the REAL validator flags it RED (never silently passes):

1. borrowed subject checkpoint credited as owned  -> evaluation.subject_checkpoint_mismatch
2. manifest benchmark_id tampered vs signed receipt -> admission.receipt_claim_mismatch
3. manifest score tampered vs signed receipt        -> admission.receipt_claim_mismatch
4. completion-credit flag tampered vs signed receipt-> admission.receipt_claim_mismatch
5. receipt re-signed for a DIFFERENT checkpoint     -> admission.receipt_checkpoint_mismatch
6. evaluation.receipt_sha256 points at nothing      -> admission.evaluation_receipt

A parallel block exercises the wiring module
(``evaluation_identity_binding.verify_evaluation_identity_binding``) directly, proving
the same invariants re-derive and fail closed independent of the full admission bundle.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
MOVED_SCRIPT_PATH = ROOT / "src" / "ember" / "governance" / "scripts" / "ember_01_identity"
TEST_DIR = Path(__file__).parent
for _extra in (SCRIPT_DIR, MOVED_SCRIPT_PATH, TEST_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import validate_identity as identity_validator  # noqa: E402
from validate_identity import validate_manifest, IdentityValidationError  # noqa: E402

# Reuse the production-grade signed-manifest builders from the validator's own suite so
# the positive round-trip is exercised against real evidence, not a hand-mocked shape.
import test_validate_identity as tvi  # noqa: E402
from test_validate_identity import (  # noqa: E402
    admitted_manifest,
    artifact_authority,
    rebind_receipt,
    receipt_sha256,
    VERIFIER_BYTES,
    TEST_PUBLIC_KEY_HEX,
)

from evaluation_identity_binding import (  # noqa: E402
    EvaluationIdentityMismatch,
    bind_evaluation_identity,
    verify_evaluation_identity_binding,
)


def _pin_verifier(tmpdir: Path) -> Path:
    """Replicate test_validate_identity's autouse verifier pinning for unittest."""
    registry = tmpdir / "trusted-verifiers-v1.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "ember-trusted-verifier-registry-v1",
                "verifiers": [
                    {
                        "verifier_sha256": hashlib.sha256(VERIFIER_BYTES).hexdigest(),
                        "public_key_ed25519": TEST_PUBLIC_KEY_HEX,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry


def _error_codes(payload, **kwargs) -> set[str]:
    try:
        validate_manifest(payload, **kwargs)
    except IdentityValidationError as error:
        return {finding["code"] for finding in error.findings}
    return set()


class EvaluationIdentityRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        registry = _pin_verifier(Path(self._tmp.name))
        # Pin the same low floor + registry the validator suite pins (module globals).
        self._orig_registry = identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH
        self._orig_floor = identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR
        identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH = registry
        identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR = 1
        # Some validator paths cache the pinned entries; clear if present.
        cache = getattr(identity_validator, "_pinned_verifier_entries", None)
        if cache is not None and hasattr(cache, "cache_clear"):
            cache.cache_clear()

    def tearDown(self) -> None:
        identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH = self._orig_registry
        identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR = self._orig_floor
        cache = getattr(identity_validator, "_pinned_verifier_entries", None)
        if cache is not None and hasattr(cache, "cache_clear"):
            cache.cache_clear()
        self._tmp.cleanup()

    # ---- positive round-trip through the REAL consumer ----------------------------
    def test_owned_benchmark_identity_round_trips(self) -> None:
        payload, receipts = admitted_manifest()
        result = validate_manifest(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertEqual(result, payload)

    # ---- fail-closed negatives at the REAL consumer --------------------------------
    def test_borrowed_subject_checkpoint_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        payload["evaluation"]["subject_checkpoint_sha256"] = "9" * 64  # borrowed subject
        codes = _error_codes(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertIn("evaluation.subject_checkpoint_mismatch", codes)

    def test_tampered_benchmark_id_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        payload["evaluation"]["benchmark_id"] = "not-the-signed-benchmark"
        codes = _error_codes(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertIn("admission.receipt_claim_mismatch", codes)

    def test_tampered_score_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        payload["evaluation"]["score"] = {"value": 0.123, "unit": "fixture-score"}
        codes = _error_codes(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertIn("admission.receipt_claim_mismatch", codes)

    def test_flipped_completion_credit_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        # Manifest claims a completion-credit value the signed receipt does not.
        payload["evaluation"]["counts_toward_owned_completion"] = False
        codes = _error_codes(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        # Either the receipt-claim cross-check or the disposition guard must fire;
        # both are fail-closed. The receipt-claim mismatch is the identity binding.
        self.assertIn("admission.receipt_claim_mismatch", codes)

    def test_receipt_rebound_to_other_checkpoint_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        old_digest = payload["evaluation"]["receipt_sha256"]
        new_digest = rebind_receipt(
            payload, receipts, old_digest, subject_checkpoint_sha256="9" * 64
        )
        payload["evaluation"]["receipt_sha256"] = new_digest
        codes = _error_codes(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertIn("admission.receipt_checkpoint_mismatch", codes)

    def test_dangling_receipt_pointer_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        payload["evaluation"]["receipt_sha256"] = "0" * 64  # resolves to nothing
        codes = _error_codes(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertIn("admission.evaluation_receipt", codes)

    # ---- wiring-module invariants (independent re-derivation) -----------------------
    def test_binding_module_round_trips_and_fails_closed(self) -> None:
        payload, receipts = admitted_manifest()
        checkpoint_hash = payload["checkpoint"]["byte_sha256"]
        eval_receipt = receipts[payload["evaluation"]["receipt_sha256"]]

        # Silent on honest bytes.
        verify_evaluation_identity_binding(payload, eval_receipt)

        # bind_evaluation_identity projects the signed receipt's claims back in.
        rebound = bind_evaluation_identity(payload, eval_receipt)
        self.assertEqual(
            rebound["evaluation"]["subject_checkpoint_sha256"], checkpoint_hash
        )
        verify_evaluation_identity_binding(rebound, eval_receipt)

        # Borrowed subject -> fail closed naming the field.
        tampered = copy.deepcopy(payload)
        tampered["evaluation"]["subject_checkpoint_sha256"] = "9" * 64
        with self.assertRaises(EvaluationIdentityMismatch):
            verify_evaluation_identity_binding(tampered, eval_receipt)

        # Benchmark field diverges from signed receipt -> fail closed.
        tampered2 = copy.deepcopy(payload)
        tampered2["evaluation"]["benchmark_id"] = "not-the-signed-benchmark"
        with self.assertRaises(EvaluationIdentityMismatch):
            verify_evaluation_identity_binding(tampered2, eval_receipt)

        # A non-evaluation receipt cannot be bound.
        not_eval = dict(eval_receipt)
        not_eval["evidence_class"] = "reasoning"
        with self.assertRaises(EvaluationIdentityMismatch):
            bind_evaluation_identity(payload, not_eval)


if __name__ == "__main__":
    unittest.main()
