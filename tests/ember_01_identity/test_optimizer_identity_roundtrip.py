# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 (optimizer): the optimizer subsystem's identity round-trips, fail-closed.

Not a narrative assertion: the positive case builds a REAL signed OWNED_ADMITTED
identity manifest (the same ``admitted_manifest`` / ``artifact_authority`` machinery the
production validator suite uses) and runs the actual production consumer,
``validate_identity.validate_manifest``. That consumer is the code path that round-trips
the optimizer state-bytes identity (validate_identity.py ~line 152 genesis-bound + ~line
1083 artifact-bundle hash check for ``training.optimizer_state``): the digest in
``training.optimizer_state_sha256`` must equal the sha256 of the ``training.optimizer_state``
artifact bytes actually supplied.

Fail-closed negatives drive the manifest's optimizer identity out of agreement with the
real optimizer state bytes and assert the REAL validator flags it RED (never silently
passes):

1. optimizer state bytes tampered vs the manifest digest
   -> admission.artifact_hash_mismatch (training.optimizer_state)
2. manifest optimizer digest tampered vs the supplied state bytes
   -> admission.artifact_hash_mismatch (training.optimizer_state)

A parallel block exercises the wiring module
(``optimizer_identity_binding.verify_optimizer_identity_binding``) directly, proving the
same invariants re-derive and fail closed independent of the full admission bundle:
a REALIZED realization receipt is required, and the manifest digest must equal the sha256
of the actual optimizer state bytes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
TEST_DIR = Path(__file__).parent
for _extra in (SCRIPT_DIR, TEST_DIR):
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
    ARTIFACT_BYTES,
    VERIFIER_BYTES,
    TEST_PUBLIC_KEY_HEX,
)

from optimizer_identity_binding import (  # noqa: E402
    OptimizerIdentityMismatch,
    bind_optimizer_identity,
    canonical_realization_receipt_sha256,
    verify_optimizer_identity_binding,
)

# The actual optimizer state bytes the validator suite admits as the
# ``training.optimizer_state`` artifact -- the real bytes whose sha256 is the manifest's
# optimizer identity (test_validate_identity.py ARTIFACT_BYTES).
OPTIMIZER_STATE_BYTES = ARTIFACT_BYTES["training.optimizer_state"]

# A signed REALIZED optimizer-realization receipt shaped exactly as
# scripts/ember_restart/contract.py binds it (schema_version / result / implementation /
# hyperparameters / state_format). Contract half of the optimizer identity.
REALIZATION_RECEIPT = {
    "schema_version": "ember-optimizer-realization-v1",
    "result": "REALIZED",
    "implementation": "bitsandbytes.optim.AdamW8bit",
    "hyperparameters": {"learning_rate": 1e-4, "weight_decay": 0.1},
    "state_format": "bitsandbytes-device-resident-8bit-adamw-state-dict-v1",
    "implementation_source_sha256": "d" * 64,
    "param_group_mapping_convention": "by-module-qualified-name",
    "param_name_optimizer_id_mapping_sha256": "e" * 64,
    "trusted_verifier_id": "fixture-optimizer-realization-verifier",
    "model_config_sha256": "a" * 64,
}


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


def _optimizer_findings(payload, **kwargs) -> set[str]:
    """Codes for findings that name the training.optimizer_state artifact specifically."""
    try:
        validate_manifest(payload, **kwargs)
    except IdentityValidationError as error:
        return {
            finding["code"]
            for finding in error.findings
            if "training.optimizer_state" in json.dumps(finding)
        }
    return set()


class OptimizerIdentityRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

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
    def test_owned_optimizer_identity_round_trips(self) -> None:
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        # The production admission path consumes the content-addressed, signed
        # realization receipt installed by admitted_manifest.
        result = validate_manifest(payload, receipt_bundle=receipts, **authority)
        self.assertEqual(result, payload)

        # The standalone wiring module independently derives and verifies its complete
        # optimizer identity. Its local REALIZATION_RECEIPT is not allowed to impersonate
        # the separately signed production-admission receipt bundle.
        rebound = bind_optimizer_identity(
            payload, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
        )
        self.assertEqual(
            rebound["training"]["optimizer_state_sha256"],
            payload["training"]["optimizer_state_sha256"],
        )
        self.assertEqual(
            rebound["training"]["optimizer_contract"],
            self._valid_contract(),
        )
        verify_optimizer_identity_binding(
            rebound, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
        )

    # ---- fail-closed negatives at the REAL consumer --------------------------------
    def test_tampered_optimizer_state_bytes_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        # Swap the admitted optimizer state artifact bytes; the manifest digest (bound to
        # the honest bytes) no longer matches what the bundle supplies.
        tampered = dict(authority["artifact_bundle"]["artifacts"]["training.optimizer_state"])
        tampered_bytes = b"borrowed optimizer state that was never realized"
        tampered["content_hex"] = tampered_bytes.hex()
        tampered["sha256"] = hashlib.sha256(tampered_bytes).hexdigest()
        authority["artifact_bundle"]["artifacts"]["training.optimizer_state"] = tampered
        codes = _optimizer_findings(payload, receipt_bundle=receipts, **authority)
        self.assertIn("admission.artifact_hash_mismatch", codes)

    def test_tampered_manifest_optimizer_digest_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        # Hand-type a different optimizer digest into the manifest; the supplied optimizer
        # state artifact bytes no longer hash to it.
        payload["training"]["optimizer_state_sha256"] = "c" * 64
        codes = _optimizer_findings(payload, receipt_bundle=receipts, **authority)
        self.assertIn("admission.artifact_hash_mismatch", codes)

    # ---- wiring-module invariants (independent re-derivation) -----------------------
    def test_binding_module_round_trips_and_fails_closed(self) -> None:
        payload, _ = admitted_manifest()
        artifact_authority(payload)  # sets training.optimizer_state_sha256 = sha256(bytes)
        payload["training"]["optimizer_contract"] = self._valid_contract()

        # Silent on honest bytes + a REALIZED receipt.
        verify_optimizer_identity_binding(
            payload, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
        )

        # bind derives the honest digest and re-verifies.
        rebound = bind_optimizer_identity(
            payload, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
        )
        self.assertEqual(
            rebound["training"]["optimizer_state_sha256"],
            hashlib.sha256(OPTIMIZER_STATE_BYTES).hexdigest(),
        )
        verify_optimizer_identity_binding(
            rebound, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
        )

        # Manifest digest diverges from the real optimizer state bytes -> fail closed
        # naming training.optimizer_state_sha256.
        tampered = copy.deepcopy(payload)
        tampered["training"]["optimizer_state_sha256"] = "9" * 64
        with self.assertRaises(OptimizerIdentityMismatch) as ctx:
            verify_optimizer_identity_binding(
                tampered, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
            )
        self.assertIn("optimizer_state_sha256", str(ctx.exception))

        # An unrealized optimizer receipt cannot authorise a binding.
        unrealized = dict(REALIZATION_RECEIPT, result="PENDING")
        with self.assertRaises(OptimizerIdentityMismatch):
            verify_optimizer_identity_binding(
                payload, OPTIMIZER_STATE_BYTES, unrealized
            )

        # A non-optimizer realization receipt cannot authorise a binding.
        wrong_schema = dict(REALIZATION_RECEIPT, schema_version="ember-eval-result-v1")
        with self.assertRaises(OptimizerIdentityMismatch):
            bind_optimizer_identity(payload, OPTIMIZER_STATE_BYTES, wrong_schema)

        # A realization receipt with no concrete optimizer contract cannot authorise it.
        unnamed = dict(REALIZATION_RECEIPT)
        del unnamed["implementation"]
        with self.assertRaises(OptimizerIdentityMismatch):
            bind_optimizer_identity(payload, OPTIMIZER_STATE_BYTES, unnamed)

    # ---- cond3 CONTRACT-half + B4 REQUIRED-half: optimizer contract identity binds to
    # the receipt AND (ember01plan.md SS B4 L1061-1082) is now REQUIRED -- never
    # legally absent -- for a manifest with identity.disposition == "OWNED_ADMITTED"
    # (current owned-admission legs). Today, before this PR, an absent
    # optimizer_contract passed identity validation unconditionally; that is the
    # defect this battery proves closed. -----------------------------------------

    # The 5 B4 residual identity fields (ember01plan.md item 5 / SS B4 L1070-1082):
    # optimizer implementation source hash, param-group mapping convention,
    # param-name<->optimizer-local-ID mapping identity, realization-receipt identity,
    # and trusted-verifier identity. Together with the 3 original contract fields
    # (implementation / hyperparameters / state_format) these are the 8 fields
    # schema-v1.json's training.optimizer_contract now requires in full whenever a
    # contract is declared at all.
    B4_RESIDUAL_CONTRACT_FIELDS: tuple[str, ...] = (
        "implementation_source_sha256",
        "param_group_mapping_convention",
        "param_name_optimizer_id_mapping_sha256",
        "realization_receipt_sha256",
        "trusted_verifier_id",
    )
    ALL_CONTRACT_FIELDS: tuple[str, ...] = (
        "implementation",
        "hyperparameters",
        "state_format",
    ) + B4_RESIDUAL_CONTRACT_FIELDS

    @staticmethod
    def _valid_contract() -> dict:
        # The manifest optimizer contract identity that equals the signed REALIZED
        # ember-optimizer-realization-v1 receipt scripts/ember_restart/contract.py binds
        # (the first 3 fields), PLUS the 5 B4 residual identity fields REQUIRED as of
        # this PR (ember01plan.md SS B4 L1061-1082). A complete contract -- every one
        # of the 8 fields present and well-formed -- is the GREEN case; the mutation
        # battery below deletes one field at a time off a deep copy of this dict.
        return {
            "implementation": REALIZATION_RECEIPT["implementation"],
            "hyperparameters": dict(REALIZATION_RECEIPT["hyperparameters"]),
            "state_format": REALIZATION_RECEIPT["state_format"],
            "implementation_source_sha256": REALIZATION_RECEIPT[
                "implementation_source_sha256"
            ],
            "param_group_mapping_convention": REALIZATION_RECEIPT[
                "param_group_mapping_convention"
            ],
            "param_name_optimizer_id_mapping_sha256": REALIZATION_RECEIPT[
                "param_name_optimizer_id_mapping_sha256"
            ],
            "realization_receipt_sha256": canonical_realization_receipt_sha256(
                REALIZATION_RECEIPT
            ),
            "trusted_verifier_id": REALIZATION_RECEIPT["trusted_verifier_id"],
        }

    def test_optimizer_contract_round_trips_through_real_consumer(self) -> None:
        # POSITIVE (GREEN): production admission validates the complete optimizer
        # contract against its content-addressed signed receipt.
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        result = validate_manifest(payload, receipt_bundle=receipts, **authority)
        self.assertEqual(result, payload)

        # The standalone wiring module is exercised separately with its own REALIZED
        # receipt; it does not borrow the production receipt bundle's authority.
        contract = self._valid_contract()
        self.assertEqual(set(contract), set(self.ALL_CONTRACT_FIELDS))
        standalone = copy.deepcopy(payload)
        standalone["training"]["optimizer_contract"] = contract
        verify_optimizer_identity_binding(
            standalone, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
        )

    def test_optimizer_contract_absent_still_valid_when_not_owned_admitted(self) -> None:
        # ADDITIVE (unchanged, narrowed): a manifest whose disposition is NOT
        # OWNED_ADMITTED may still omit the optimizer contract entirely -- the
        # REQUIRED-half gate below is scoped to current owned-admission legs only,
        # never a blanket requirement (ember01plan.md SS B4: "make the contract
        # REQUIRED for current owned-admission legs").
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        del payload["training"]["optimizer_contract"]
        payload["identity"]["disposition"] = "OWNED_CANDIDATE"
        payload["identity"]["selected_as_owned_ember"] = False
        payload["evaluation"]["counts_toward_owned_completion"] = False
        self.assertNotIn("optimizer_contract", payload["training"])
        result = validate_manifest(payload, receipt_bundle=receipts, **authority)
        self.assertEqual(result, payload)

    def test_owned_admitted_optimizer_contract_absent_fails_closed(self) -> None:
        # NEGATIVE (RED, THE B4 DEFECT): before this PR, an OWNED_ADMITTED manifest
        # with NO training.optimizer_contract at all passed identity validation
        # unconditionally. It must now fail closed, naming the omission, at BOTH
        # enforcement layers: the JSON-schema if/then (schema-v1.json
        # b4_governed_conditional_requirement) and the named Python finding
        # (validate_identity.py's admission.optimizer_contract_missing).
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        del payload["training"]["optimizer_contract"]
        self.assertEqual(payload["identity"]["disposition"], "OWNED_ADMITTED")
        codes = _error_codes(payload, receipt_bundle=receipts, **authority)
        self.assertIn("admission.optimizer_contract_missing", codes)
        self.assertIn("schema.validation", codes)

    def test_optimizer_contract_residual_field_omission_mutation_battery(self) -> None:
        # MUTATION BATTERY (RED-per-field, frozen-spec-required): for EACH of the 8
        # required optimizer_contract fields (3 original + 5 B4 residual), a manifest
        # that declares a contract omitting JUST that one field must fail closed
        # naming training.optimizer_contract_invalid -- never a silent pass on a
        # partial contract. The complete contract (all 8 present) is proved GREEN by
        # test_optimizer_contract_round_trips_through_real_consumer above.
        for omitted_field in self.ALL_CONTRACT_FIELDS:
            with self.subTest(omitted_field=omitted_field):
                payload, receipts = admitted_manifest()
                authority = artifact_authority(payload)
                contract = self._valid_contract()
                del contract[omitted_field]
                payload["training"]["optimizer_contract"] = contract
                codes = _error_codes(payload, receipt_bundle=receipts, **authority)
                self.assertIn(
                    "training.optimizer_contract_invalid",
                    codes,
                    msg=f"omitting {omitted_field!r} did not fail closed",
                )

    def test_optimizer_contract_malformed_flagged_by_consumer(self) -> None:
        # NEGATIVE: a contract missing a concrete field is RED at the real consumer with a
        # named fail-closed code (never a silent pass).
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        contract = self._valid_contract()
        contract["implementation"] = ""  # blank: the optimizer is unnamed
        payload["training"]["optimizer_contract"] = contract
        codes = _error_codes(payload, receipt_bundle=receipts, **authority)
        self.assertIn("training.optimizer_contract_invalid", codes)

    def test_optimizer_contract_missing_field_flagged_by_consumer(self) -> None:
        # NEGATIVE: a contract omitting a required field is RED at the real consumer.
        payload, receipts = admitted_manifest()
        authority = artifact_authority(payload)
        contract = self._valid_contract()
        del contract["state_format"]
        payload["training"]["optimizer_contract"] = contract
        codes = _error_codes(payload, receipt_bundle=receipts, **authority)
        self.assertIn("training.optimizer_contract_invalid", codes)

    def test_optimizer_contract_mismatch_receipt_fails_closed(self) -> None:
        # NEGATIVE: a contract field that diverges from the REALIZED receipt fails closed
        # naming the exact field (mirrors contract.py binding-mismatch).
        payload, _ = admitted_manifest()
        artifact_authority(payload)
        contract = self._valid_contract()
        contract["implementation"] = "torch.optim.AdamW"  # not the realized optimizer
        payload["training"]["optimizer_contract"] = contract
        with self.assertRaises(OptimizerIdentityMismatch) as ctx:
            verify_optimizer_identity_binding(
                payload, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
            )
        self.assertIn("training.optimizer_contract_implementation", str(ctx.exception))

    def test_optimizer_contract_residual_mismatch_battery_fails_closed(self) -> None:
        mutations = {
            "implementation_source_sha256": "0" * 64,
            "param_group_mapping_convention": "foreign-ordering",
            "param_name_optimizer_id_mapping_sha256": "1" * 64,
            "realization_receipt_sha256": "2" * 64,
            "trusted_verifier_id": "foreign-verifier",
        }
        for field, mutated_value in mutations.items():
            with self.subTest(field=field):
                payload, _ = admitted_manifest()
                artifact_authority(payload)
                contract = self._valid_contract()
                contract[field] = mutated_value
                payload["training"]["optimizer_contract"] = contract
                with self.assertRaises(OptimizerIdentityMismatch) as ctx:
                    verify_optimizer_identity_binding(
                        payload,
                        OPTIMIZER_STATE_BYTES,
                        REALIZATION_RECEIPT,
                    )
                self.assertIn(
                    f"training.optimizer_contract_{field}",
                    str(ctx.exception),
                )

    def test_realization_receipt_residual_omission_battery_fails_closed(self) -> None:
        for field in (
            "implementation_source_sha256",
            "param_group_mapping_convention",
            "param_name_optimizer_id_mapping_sha256",
            "trusted_verifier_id",
        ):
            with self.subTest(field=field):
                payload, _ = admitted_manifest()
                artifact_authority(payload)
                payload["training"]["optimizer_contract"] = self._valid_contract()
                receipt = dict(REALIZATION_RECEIPT)
                del receipt[field]
                with self.assertRaises(OptimizerIdentityMismatch) as ctx:
                    verify_optimizer_identity_binding(
                        payload,
                        OPTIMIZER_STATE_BYTES,
                        receipt,
                    )
                self.assertIn(field, str(ctx.exception))

    def test_optimizer_contract_missing_field_fails_closed_in_binding(self) -> None:
        # NEGATIVE: the wiring module fails closed when a declared contract omits a field.
        payload, _ = admitted_manifest()
        artifact_authority(payload)
        contract = self._valid_contract()
        del contract["hyperparameters"]
        payload["training"]["optimizer_contract"] = contract
        with self.assertRaises(OptimizerIdentityMismatch) as ctx:
            verify_optimizer_identity_binding(
                payload, OPTIMIZER_STATE_BYTES, REALIZATION_RECEIPT
            )
        self.assertIn("training.optimizer_contract_hyperparameters", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
