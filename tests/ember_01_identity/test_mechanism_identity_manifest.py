# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Proves mechanism_identity is fail-closed at the manifest layer via the REAL
scripts/ember_01_identity/validate_identity.py validate_manifest consumer.

Reuses the admitted-manifest + artifact-authority + receipt-signing plumbing already
built in test_validate_identity.py (imported as a module) rather than reimplementing it.
Never reimplements validate_manifest.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_validate_identity as tvi  # noqa: E402
import validate_identity as identity_validator  # noqa: E402

from validate_identity import IdentityValidationError, validate_manifest  # noqa: E402


@pytest.fixture(autouse=True)
def pinned_test_verifier_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same pin as test_validate_identity.py's autouse fixture (duplicated, not shared
    via import, since pytest autouse fixtures are file-scoped) -- trusts the fixture
    VERIFIER_BYTES key and lowers the parameter floor so the OWNED_ADMITTED plumbing in
    admitted_manifest()/artifact_authority() resolves the same way here."""
    registry = tmp_path / "trusted-verifiers-v1.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "ember-trusted-verifier-registry-v1",
                "verifiers": [
                    {
                        "verifier_sha256": hashlib.sha256(tvi.VERIFIER_BYTES).hexdigest(),
                        "public_key_ed25519": tvi.TEST_PUBLIC_KEY_HEX,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(identity_validator, "TRUSTED_VERIFIER_REGISTRY_PATH", registry)
    monkeypatch.setattr(identity_validator, "OWNED_ADMISSION_PARAMETER_FLOOR", 1)


def _bind_mechanism_evidence(
    receipts: dict,
    *,
    subject: str,
    verifier: str,
    group: str,
    mech_id: str,
    mech_sha: str,
    extra_claims: dict | None = None,
) -> str:
    claims = {"mechanism_id": mech_id, "mechanism_sha256": mech_sha}
    if extra_claims:
        claims.update(extra_claims)
    receipt = {
        "schema": "ember-identity-evidence-receipt-v1",
        "evidence_class": f"mechanism_{group}",
        "subject_checkpoint_sha256": subject,
        "verifier_sha256": verifier,
        "result": "VERIFIED",
        **claims,
    }
    tvi.sign_receipt(receipt)
    digest = tvi.receipt_sha256(receipt)
    receipts[digest] = receipt
    return digest


def build_admitted_with_mechanisms() -> tuple[dict, dict, dict, dict]:
    """OWNED_ADMITTED manifest with one populated expert, permanent_merge, and
    deletion_object -- mechanism bytes, merge ancestry, and deletion evidence all bound."""
    payload, receipts = tvi.admitted_manifest()
    kwargs = tvi.artifact_authority(payload)
    subject = payload["checkpoint"]["byte_sha256"]
    verifier = payload["data"]["verifier_sha256"]

    def add_mechanism(
        group: str, mech_id: str, content: bytes, state: str, extra_claims: dict | None = None
    ) -> str:
        sha = hashlib.sha256(content).hexdigest()
        digest = _bind_mechanism_evidence(
            receipts,
            subject=subject,
            verifier=verifier,
            group=group,
            mech_id=mech_id,
            mech_sha=sha,
            extra_claims=extra_claims,
        )
        payload["mechanisms"][group] = [
            {
                "id": mech_id,
                "sha256": sha,
                "state": state,
                "evidence_receipts": [digest],
            }
        ]
        kwargs["artifact_bundle"]["artifacts"][f"mechanism:{group}:{mech_id}"] = {
            "sha256": sha,
            "content_hex": content.hex(),
        }
        return sha

    shas = {
        "expert": add_mechanism("experts", "expert-0", b"owned expert weight bytes", "ACTIVE"),
        "merge": add_mechanism(
            "permanent_merges", "merge-0", b"owned merge ancestry bytes", "ACTIVE"
        ),
        "deletion": add_mechanism(
            "deletion_objects",
            "deletion-0",
            b"owned deleted capability bytes",
            "INACTIVE",
            extra_claims={"deletion_effect": "CAPABILITY_ERASED"},
        ),
    }
    return payload, receipts, kwargs, shas


def _codes(payload: dict, receipts: dict, **kwargs) -> set[str]:
    with pytest.raises(IdentityValidationError) as caught:
        validate_manifest(payload, receipt_bundle=receipts, **kwargs)
    return {finding["code"] for finding in caught.value.findings}


def test_positive_populated_mechanisms_validate_and_enroll_bytes() -> None:
    """POSITIVE: populated expert (bytes+state+evidence), permanent_merges entry (merge
    ancestry), deletion_objects entry (deletion evidence) all validate; each item's sha256
    is enrolled in required_artifacts (proven by non-raise -- the OWNED_ADMITTED admission
    path raises admission.artifact_missing/artifact_hash_mismatch on any unenrolled or
    mismatched mechanism artifact, per validate_identity.py L1101-1104)."""
    payload, receipts, kwargs, shas = build_admitted_with_mechanisms()

    result = validate_manifest(payload, receipt_bundle=receipts, **kwargs)

    assert result["mechanisms"]["experts"][0]["sha256"] == shas["expert"]
    assert result["mechanisms"]["permanent_merges"][0]["sha256"] == shas["merge"]
    assert result["mechanisms"]["deletion_objects"][0]["sha256"] == shas["deletion"]
    assert result["mechanisms"]["deletion_objects"][0]["state"] == "INACTIVE"


def test_negative_mechanism_bytes_tamper_is_red() -> None:
    """NEGATIVE-1 (bytes): tamper the expert's sha256 in the manifest without touching the
    bound artifact bytes/receipt -> admission.artifact_hash_mismatch (the enrolled artifact
    no longer matches the claimed identity bytes)."""
    payload, receipts, kwargs, _shas = build_admitted_with_mechanisms()
    tampered_sha = "f" * 64
    assert payload["mechanisms"]["experts"][0]["sha256"] != tampered_sha
    payload["mechanisms"]["experts"][0]["sha256"] = tampered_sha

    codes = _codes(payload, receipts, **kwargs)

    assert "admission.artifact_hash_mismatch" in codes


def test_negative_mechanism_bytes_malformed_hash_is_red() -> None:
    """NEGATIVE-1b (bytes, structural): a syntactically invalid sha256 on a mechanism item
    fails closed at the item-shape layer regardless of disposition/admission plumbing ->
    mechanism.identity_invalid (validate_identity.py L881-909)."""
    payload = tvi.valid_manifest()
    payload["mechanisms"]["experts"] = [
        {
            "id": "expert-0",
            "sha256": "not-a-sha256",
            "state": "ACTIVE",
            "evidence_receipts": [],
        }
    ]

    with pytest.raises(IdentityValidationError) as caught:
        validate_manifest(payload)
    codes = {finding["code"] for finding in caught.value.findings}

    assert "mechanism.identity_invalid" in codes


def test_negative_deletion_evidence_missing_is_red() -> None:
    """NEGATIVE-2 (deletion evidence): a claimed deletion_objects entry with its
    evidence_receipts stripped -> admission.mechanism_evidence (deletion evidence is not
    optional for an OWNED_ADMITTED disposition; validate_identity.py L1339-1346)."""
    payload, receipts, kwargs, _shas = build_admitted_with_mechanisms()
    payload["mechanisms"]["deletion_objects"][0]["evidence_receipts"] = []

    codes = _codes(payload, receipts, **kwargs)

    assert "admission.mechanism_evidence" in codes


def test_negative_merge_ancestry_forged_is_red() -> None:
    """NEGATIVE-3 (merge ancestry): a permanent_merges entry whose id no longer matches the
    id bound into its own evidence receipt (forged/incoherent ancestry claim) ->
    admission.receipt_claim_mismatch on mechanism_id (validate_identity.py
    _resolve_admission_receipt expected_claims check)."""
    payload, receipts, kwargs, _shas = build_admitted_with_mechanisms()
    payload["mechanisms"]["permanent_merges"][0]["id"] = "merge-forged"

    codes = _codes(payload, receipts, **kwargs)

    assert "admission.receipt_claim_mismatch" in codes


def test_negative_merge_ancestry_missing_evidence_is_red() -> None:
    """NEGATIVE-3b (merge ancestry, structural): a permanent_merges entry with its
    evidence_receipts stripped entirely -> admission.mechanism_evidence, same fail-closed
    shape as deletion evidence (both are mechanism groups bound by the same admission loop,
    validate_identity.py L1339-1346)."""
    payload, receipts, kwargs, _shas = build_admitted_with_mechanisms()
    payload["mechanisms"]["permanent_merges"][0]["evidence_receipts"] = []

    codes = _codes(payload, receipts, **kwargs)

    assert "admission.mechanism_evidence" in codes
