# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 (receipt_identity): a receipt's identity round-trips its consumer, fail-closed.

Not a narrative assertion: the positive case builds a REAL signed OWNED_ADMITTED identity
manifest (the same ``admitted_manifest`` machinery the production validator suite uses --
real signed evidence receipts keyed into a receipt bundle) and runs the actual production
consumer, ``validate_identity.validate_manifest``. That consumer resolves every manifest
receipt pointer through ``_resolve_admission_receipt`` (validate_identity.py ~line 433),
whose identity gate at line 454 fails closed with ``admission.receipt_hash_mismatch``
unless ``_receipt_sha256(receipt) == digest`` -- the digest being the manifest's
``*receipt_sha256`` pointer. The receipt identity that round-trips is that canonical
``_receipt_sha256`` of the receipt object, NOT the sha of the receipt file's on-disk bytes.

Fail-closed negatives drive the manifest's receipt identity out of agreement with the
consumer's own identity and assert the REAL validator flags it RED:

1. receipt pointer bound to the on-disk FILE sha (pretty-printed bytes -- the WRONG
   object) instead of the canonical ``_receipt_sha256`` -> admission.receipt_hash_mismatch
2. receipt pointer points at nothing -> admission.evaluation_receipt

A parallel block exercises the wiring module
(``receipt_identity_binding.verify_receipt_identity_binding``) directly, proving the same
invariant re-derives and fails closed independent of the full admission bundle -- including
that binding to the raw-file sha (the tokenizer-lesson wrong object) is rejected, and that
the on-disk bytes must parse to the very receipt object bound.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
MOVED_SCRIPT_PATH = ROOT / "src" / "ember" / "governance" / "scripts" / "ember_01_identity"
TEST_DIR = Path(__file__).parent
for _extra in (SCRIPT_DIR, MOVED_SCRIPT_PATH, TEST_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import validate_identity as identity_validator  # noqa: E402
from validate_identity import validate_manifest, IdentityValidationError  # noqa: E402

# Reuse the production-grade signed-manifest builders from the validator's own suite so the
# positive round-trip is exercised against real evidence, not a hand-mocked shape.
import test_validate_identity as tvi  # noqa: E402
from test_validate_identity import (  # noqa: E402
    admitted_manifest,
    artifact_authority,
    receipt_sha256,
    VERIFIER_BYTES,
    TEST_PUBLIC_KEY_HEX,
)

from receipt_identity_binding import (  # noqa: E402
    ReceiptIdentityMismatch,
    bind_receipt_identity,
    canonical_receipt_identity,
    measure_receipt_identity,
    verify_receipt_identity_binding,
)

FIELD = "evaluation.receipt_sha256"


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


class ReceiptIdentityRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        registry = _pin_verifier(Path(self._tmp.name))
        self._orig_registry = identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH
        self._orig_floor = identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR
        identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH = registry
        identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR = 1
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
    def test_owned_receipt_identity_round_trips(self) -> None:
        payload, receipts = admitted_manifest()
        eval_receipt = receipts[payload["evaluation"]["receipt_sha256"]]
        # The wiring module derives the SAME digest the consumer keys the bundle on, from
        # the actual receipt object.
        rebound = bind_receipt_identity(payload, eval_receipt, field_path=FIELD)
        self.assertEqual(
            rebound["evaluation"]["receipt_sha256"],
            payload["evaluation"]["receipt_sha256"],
        )
        self.assertEqual(
            rebound["evaluation"]["receipt_sha256"],
            canonical_receipt_identity(eval_receipt),
        )
        result = validate_manifest(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertEqual(result, payload)

    # ---- fail-closed negatives at the REAL consumer --------------------------------
    def test_receipt_pointer_bound_to_file_sha_flagged(self) -> None:
        """Binding the pointer to the on-disk FILE sha (wrong object) is rejected."""
        payload, receipts = admitted_manifest()
        canonical_digest = payload["evaluation"]["receipt_sha256"]
        eval_receipt = receipts[canonical_digest]
        # A receipt as stored on disk, pretty-printed -- its file-bytes sha differs from the
        # canonical _receipt_sha256 the consumer keys on.
        file_bytes = json.dumps(eval_receipt, indent=2, sort_keys=True).encode("utf-8")
        file_sha = hashlib.sha256(file_bytes).hexdigest()
        self.assertNotEqual(file_sha, canonical_digest)  # the two objects are different
        # Bind the manifest to the wrong object and let the bundle resolve it, so the
        # consumer's identity gate (not a dangling-pointer path) is what fires.
        receipts[file_sha] = eval_receipt
        payload["evaluation"]["receipt_sha256"] = file_sha
        codes = _error_codes(
            payload, receipt_bundle=receipts, **artifact_authority(payload)
        )
        self.assertIn("admission.receipt_hash_mismatch", codes)

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
        eval_receipt = receipts[payload["evaluation"]["receipt_sha256"]]

        # Silent on the honestly-bound pointer.
        verify_receipt_identity_binding(payload, eval_receipt, field_path=FIELD)

        # bind derives the canonical identity and re-verifies.
        rebound = bind_receipt_identity(payload, eval_receipt, field_path=FIELD)
        self.assertEqual(
            rebound["evaluation"]["receipt_sha256"], canonical_receipt_identity(eval_receipt)
        )
        verify_receipt_identity_binding(rebound, eval_receipt, field_path=FIELD)

        # Provenance round-trips from the on-disk bytes: measure a stored receipt file,
        # bind, and verify against those very bytes.
        receipt_file = Path(self._tmp.name) / "eval_receipt.json"
        receipt_file.write_text(
            json.dumps(eval_receipt, indent=2, sort_keys=True), encoding="utf-8"
        )
        evidence = measure_receipt_identity(receipt_file)
        self.assertEqual(
            evidence["canonical_identity_sha256"], canonical_receipt_identity(eval_receipt)
        )
        # The tokenizer lesson, made concrete: the file-bytes provenance sha is NOT the
        # bound identity.
        self.assertNotEqual(
            evidence["provenance_file_sha256"], evidence["canonical_identity_sha256"]
        )
        verify_receipt_identity_binding(
            rebound,
            eval_receipt,
            field_path=FIELD,
            receipt_file_path=receipt_file,
            provenance_file_sha256=evidence["provenance_file_sha256"],
        )

        # Pointer bound to the raw-file sha (the wrong object) -> fail closed naming field.
        tampered = copy.deepcopy(payload)
        tampered["evaluation"]["receipt_sha256"] = evidence["provenance_file_sha256"]
        with self.assertRaises(ReceiptIdentityMismatch) as ctx:
            verify_receipt_identity_binding(tampered, eval_receipt, field_path=FIELD)
        self.assertIn("receipt_sha256", str(ctx.exception))

        # On-disk bytes that parse to a DIFFERENT receipt object -> fail closed.
        other_file = Path(self._tmp.name) / "other_receipt.json"
        other = dict(eval_receipt)
        other["evidence_class"] = "reasoning"
        other_file.write_text(json.dumps(other, indent=2), encoding="utf-8")
        with self.assertRaises(ReceiptIdentityMismatch):
            verify_receipt_identity_binding(
                rebound, eval_receipt, field_path=FIELD, receipt_file_path=other_file
            )

        # Provenance sha drift vs the bytes on disk -> fail closed.
        with self.assertRaises(ReceiptIdentityMismatch):
            verify_receipt_identity_binding(
                rebound,
                eval_receipt,
                field_path=FIELD,
                receipt_file_path=receipt_file,
                provenance_file_sha256="d" * 64,
            )

        # A non-object receipt cannot be bound.
        with self.assertRaises(ReceiptIdentityMismatch):
            bind_receipt_identity(payload, ["not", "a", "receipt"], field_path=FIELD)

        # The binding generalises across every receipt pointer, not just evaluation:
        # the backend process-identity receipt round-trips through the same path.
        backend_digest = payload["backend"]["process_receipt_sha256"]
        backend_receipt = receipts[backend_digest]
        verify_receipt_identity_binding(
            payload, backend_receipt, field_path="backend.process_receipt_sha256"
        )
        self.assertEqual(
            canonical_receipt_identity(backend_receipt), backend_digest
        )


if __name__ == "__main__":
    unittest.main()
