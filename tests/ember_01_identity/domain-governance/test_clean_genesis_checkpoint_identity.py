# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
IDENTITY_DIR = ROOT / "scripts" / "ember_01_identity"
if str(IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(IDENTITY_DIR))

from test_validate_identity import valid_manifest
from validate_identity import IdentityValidationError, validate_manifest


CHECKPOINT_UNRESOLVED_PATHS = {
    "checkpoint.byte_sha256",
    "checkpoint.tensors[0].sha256",
    "evaluation.subject_checkpoint_sha256",
}


def _unresolved() -> dict[str, str]:
    return {
        "status": "unresolved",
        "reason": "clean-genesis checkpoint bytes do not exist before model birth",
    }


def _prebirth_manifest() -> dict:
    payload = valid_manifest()
    payload["checkpoint"]["byte_sha256"] = _unresolved()
    payload["checkpoint"]["tensors"][0]["sha256"] = _unresolved()
    payload["evaluation"]["subject_checkpoint_sha256"] = _unresolved()
    payload["unresolved"] = sorted(
        [*payload["unresolved"], *CHECKPOINT_UNRESOLVED_PATHS]
    )
    return payload


def test_prebirth_checkpoint_identity_is_honestly_unresolved() -> None:
    payload = _prebirth_manifest()
    assert validate_manifest(payload) == payload


def test_require_resolved_refuses_every_prebirth_checkpoint_identity() -> None:
    with pytest.raises(IdentityValidationError) as raised:
        validate_manifest(_prebirth_manifest(), require_resolved=True)
    unresolved_details = {
        finding["detail"]
        for finding in raised.value.findings
        if finding["code"] == "field.unresolved"
    }
    assert CHECKPOINT_UNRESOLVED_PATHS <= unresolved_details


def test_checkpoint_bytes_cannot_bind_to_unresolved_identity() -> None:
    with pytest.raises(IdentityValidationError) as raised:
        validate_manifest(_prebirth_manifest(), checkpoint_bytes=b"post-birth checkpoint")
    assert "checkpoint.byte_hash_mismatch" in {
        finding["code"] for finding in raised.value.findings
    }


def test_existing_resolved_candidate_remains_valid() -> None:
    payload = valid_manifest()
    assert validate_manifest(payload) == payload
