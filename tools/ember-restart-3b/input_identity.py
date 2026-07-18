# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Worktree-invariant, content-addressed training-input admission for #812."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class InputIdentityError(ValueError):
    """A fail-closed input admission error with a stable machine-readable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class ResolvedInputIdentity:
    identity_manifest: str
    artifact_id: str
    shard_path: str
    sha256: str
    bytes: int
    selection_source: str
    admission_receipt_path: str | None = None
    admission_receipt_sha256: str | None = None

    def packet_value(self) -> dict[str, Any]:
        value = {
            "identity_manifest": self.identity_manifest,
            "artifact_id": self.artifact_id,
            "shard_path": self.shard_path,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }
        if self.admission_receipt_path is not None and self.admission_receipt_sha256 is not None:
            value["admission_receipt_path"] = self.admission_receipt_path
            value["admission_receipt_sha256"] = self.admission_receipt_sha256
        return value

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative_file(repo_root: Path, value: str, *, missing_code: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value:
        raise InputIdentityError("wrong_identity", "path must be a non-empty repository-relative string")
    normalized = PurePosixPath(value.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise InputIdentityError("wrong_identity", "path must remain inside the selected worktree")
    relative = normalized.as_posix()
    resolved = (repo_root / relative).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise InputIdentityError("wrong_identity", "path escapes the selected worktree") from exc
    if not resolved.is_file():
        raise InputIdentityError(missing_code, f"required file is absent: {relative}")
    return resolved, relative


def _load_contract(config_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputIdentityError("wrong_identity", f"cannot read config contract: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("training"), dict):
        raise InputIdentityError("wrong_identity", "config must declare a training object")
    return payload


def resolve_input_identity(
    *,
    repo_root: Path,
    config_path: Path,
    input_identity_arg: str | None = None,
) -> ResolvedInputIdentity:
    """Resolve bytes from the selected worktree, never CWD or an ambient default."""

    repo_root = repo_root.resolve()
    try:
        config_relative = config_path.resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise InputIdentityError("wrong_identity", "config must reside in the selected worktree") from exc
    contract = _load_contract(repo_root / config_relative)
    training = contract["training"]
    requested = input_identity_arg
    selection_source = "explicit_cli" if requested is not None else "contract_default"
    if requested is None:
        requested = training.get("input_identity_manifest")
    manifest_path, manifest_relative = _relative_file(repo_root, requested, missing_code="missing_input")
    try:
        identity = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputIdentityError("wrong_identity", f"input identity manifest is unreadable: {exc}") from exc
    if not isinstance(identity, dict) or identity.get("schema_version") != "ember-input-identity-v1":
        raise InputIdentityError("wrong_identity", "input identity schema is not admitted")
    artifact_id = identity.get("artifact_id")
    expected_id = training.get("expected_input_artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id or artifact_id != expected_id:
        raise InputIdentityError("wrong_identity", "input artifact identity does not match the contract")
    shard_path, shard_relative = _relative_file(repo_root, identity.get("shard_path"), missing_code="missing_input")
    actual_sha = _sha256(shard_path)
    actual_bytes = shard_path.stat().st_size
    expected_sha = identity.get("sha256")
    expected_bytes = identity.get("bytes")
    if not isinstance(expected_sha, str) or actual_sha != expected_sha:
        raise InputIdentityError("byte_drift", "shard content hash differs from the selected identity")
    if not isinstance(expected_bytes, int) or actual_bytes != expected_bytes:
        raise InputIdentityError("byte_drift", "shard byte count differs from the selected identity")
    receipt_relative: str | None = None
    receipt_sha256: str | None = None
    if artifact_id == "owned-four-domain-production-rung-v1":
        from production_rung import ARTIFACT_ID, RECEIPT_RELATIVE, SHARD_RELATIVE, verify_bound_rung

        if artifact_id != ARTIFACT_ID or shard_relative != SHARD_RELATIVE:
            raise InputIdentityError("wrong_identity", "production rung identity does not bind the canonical owned shard")
        receipt_path, receipt_relative = _relative_file(repo_root, identity.get("admission_receipt_path"), missing_code="missing_input")
        expected_receipt_sha = identity.get("admission_receipt_sha256")
        if receipt_relative != RECEIPT_RELATIVE or not isinstance(expected_receipt_sha, str):
            raise InputIdentityError("wrong_identity", "production rung identity lacks the canonical admission receipt")
        receipt_sha256 = _sha256(receipt_path)
        if receipt_sha256 != expected_receipt_sha:
            raise InputIdentityError("byte_drift", "production rung receipt hash differs from the selected identity")
        try:
            verify_bound_rung(root=repo_root, shard_path=shard_path, receipt_path=receipt_path)
        except ValueError as error:
            raise InputIdentityError("wrong_identity", f"production rung receipt verification failed: {error}") from error
    return ResolvedInputIdentity(
        identity_manifest=manifest_relative,
        artifact_id=artifact_id,
        shard_path=shard_relative,
        sha256=actual_sha,
        bytes=actual_bytes,
        selection_source=selection_source,
        admission_receipt_path=receipt_relative,
        admission_receipt_sha256=receipt_sha256,
    )


def build_launch_packet(
    *,
    repo_root: Path,
    config_path: Path,
    input_identity_arg: str | None = None,
) -> dict[str, Any]:
    """Build the live caller packet; the selected identity is a required value."""

    repo_root = repo_root.resolve()
    identity = resolve_input_identity(
        repo_root=repo_root,
        config_path=config_path,
        input_identity_arg=input_identity_arg,
    )
    config_relative = config_path.resolve().relative_to(repo_root).as_posix()
    return {
        "schema_version": "ember-launch-packet-v1",
        "config_path": config_relative,
        "config_sha256": _sha256(repo_root / config_relative),
        "requested_input_identity": identity.identity_manifest,
        "selection_source": identity.selection_source,
        "input_identity": identity.packet_value(),
    }


def validate_launch_packet(packet: dict[str, Any], *, repo_root: Path) -> dict[str, str]:
    """Re-resolve and consume the caller identity; decorative fields fail closed."""

    if not isinstance(packet, dict) or packet.get("schema_version") != "ember-launch-packet-v1":
        raise InputIdentityError("caller_omission", "launch packet schema is absent")
    if not isinstance(packet.get("config_path"), str) or not isinstance(packet.get("requested_input_identity"), str):
        raise InputIdentityError("caller_omission", "caller did not forward config and selected input identity")
    if not isinstance(packet.get("input_identity"), dict):
        raise InputIdentityError("caller_omission", "caller did not forward resolved input identity")
    repo_root = repo_root.resolve()
    config_path, _ = _relative_file(repo_root, packet["config_path"], missing_code="caller_omission")
    if packet.get("config_sha256") != _sha256(config_path):
        raise InputIdentityError("config_drift", "launch config bytes changed after packet construction")
    resolved = resolve_input_identity(
        repo_root=repo_root,
        config_path=config_path,
        input_identity_arg=packet["requested_input_identity"],
    )
    if packet["input_identity"] != resolved.packet_value():
        raise InputIdentityError("decorative_argument", "caller packet identity was not the consumed identity")
    return {"decision": "ACCEPTED", "input_sha256": resolved.sha256}


def read_admitted_shard_bytes(packet: dict[str, Any], *, repo_root: Path) -> bytes:
    """Read the consumer artifact once and bind that exact buffer to the launch packet."""

    identity = packet.get("input_identity") if isinstance(packet, dict) else None
    if not isinstance(identity, dict):
        raise InputIdentityError("caller_omission", "launch packet lacks a concrete input identity")
    shard_path, _ = _relative_file(repo_root.resolve(), identity.get("shard_path"), missing_code="missing_input")
    try:
        shard_bytes = shard_path.read_bytes()
    except OSError as exc:
        raise InputIdentityError("missing_input", "admitted shard cannot be read by the consumer") from exc
    expected_sha = identity.get("sha256")
    expected_bytes = identity.get("bytes")
    if not isinstance(expected_sha, str) or _sha256_bytes(shard_bytes) != expected_sha:
        raise InputIdentityError("byte_drift", "admitted shard changed after launch admission")
    if not isinstance(expected_bytes, int) or len(shard_bytes) != expected_bytes:
        raise InputIdentityError("byte_drift", "admitted shard byte count changed after launch admission")
    return shard_bytes


def emit_integration_receipt(
    packet: dict[str, Any],
    validation: dict[str, str],
    *,
    code_commit: str,
) -> dict[str, Any]:
    """Produce a path-free receipt payload for a later bounded write."""

    if not isinstance(code_commit, str) or re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
        raise InputIdentityError("wrong_identity", "receipt requires an exact code commit")
    if validation.get("decision") != "ACCEPTED":
        raise InputIdentityError("wrong_identity", "only accepted launch packets receive a receipt")
    identity = packet["input_identity"]
    receipt = {
        "schema_version": "ember-input-integration-receipt-v1",
        "code_commit": code_commit,
        "config_sha256": packet["config_sha256"],
        "input_identity_manifest": identity["identity_manifest"],
        "input_artifact_sha256": identity["sha256"],
        "validator_sha256": _sha256(Path(__file__)),
        "launch_decision": validation["decision"],
        "selection_source": packet["selection_source"],
    }
    admission_receipt_sha256 = identity.get("admission_receipt_sha256")
    if admission_receipt_sha256 is not None:
        if not isinstance(admission_receipt_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", admission_receipt_sha256) is None:
            raise InputIdentityError("wrong_identity", "input admission receipt hash is malformed")
        receipt["input_admission_receipt_sha256"] = admission_receipt_sha256
    return receipt
