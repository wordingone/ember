#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive the owned-seat identity FROM the cert schema-v1 manifest, fail-closed.

The seat loader stops being an independent identity authority (goal cert #3 +
goal line 95). Every identity-bearing seat field is DERIVED from a referenced
``ember-model-experiment-identity-v1`` manifest, pinned by digest, validated by
``scripts/ember_01_identity/validate_identity.py`` (the SAME validator the
``/model`` path uses — single authority), and bound to the exact checkpoint
bytes on disk. Any failure at any step REFUSES the seat load. No fallback.

Field derivation (frozen spec, state/specs/cond3-seat-bridge-spec.md):
  seat checkpointSha256  <- cert checkpoint.byte_sha256
  seat modelConfigSha256 <- cert architecture.sha256
  seat tokenizerSha256   <- cert tokenizer.sha256
  seat id                <- cert identity.model_id
  seat disposition       <- cert identity.disposition
Operational-only seat fields (e.g. endpointUrl) are kept, never cert-derived.

Checkpoint-byte identity (Step 5) is resolved by ``resolve_checkpoint_byte_identity``:
the ACTUAL checkpoint bytes, never a checkpoint INDEX JSON's own digest --
see that function's docstring for the singular-vs-sharded resolution rule
(state/failure-classes/semantic-validation-without-bytes-2026-07-25.md).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

VALIDATOR_RELPATH = Path("scripts") / "ember_01_identity" / "validate_identity.py"

# Overlapping identity fields: seat key -> path into the cert manifest.
DERIVED_FIELDS: dict[str, tuple[str, str]] = {
    "checkpointSha256": ("checkpoint", "byte_sha256"),
    "modelConfigSha256": ("architecture", "sha256"),
    "tokenizerSha256": ("tokenizer", "sha256"),
    "id": ("identity", "model_id"),
    "disposition": ("identity", "disposition"),
}
# Identity fields carried from the cert manifest, never reinvented.
CARRIED_IDENTITY_FIELDS = ("experiment_id", "run_id", "checkpoint_id")


def _refuse(errors: list[str]) -> dict[str, Any]:
    return {"valid": False, "seat": None, "errors": errors}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_checkpoint_byte_identity(
    checkpoint_path: Path, *, root: Path | None = None
) -> tuple[str | None, list[str]]:
    """Resolve the checkpoint-BYTE identity at ``checkpoint_path``, fail-closed.

    ``root`` is the directory shard ``path`` entries are relative to (the run
    manifest's own root, matching ``contract.py::_verify_checkpoint`` --
    shard paths there are relative to the manifest root, NOT to the
    checkpoint index file's own directory). Defaults to
    ``checkpoint_path.parent`` when not supplied.

    Two shapes are supported, disambiguated by the artifact bytes themselves
    (never by a caller-supplied flag, so there is no unchecked branch to lie
    about which shape is in play):

    - **Singular**: ``checkpoint_path`` names the checkpoint bytes directly.
      Returns the sha256 of the raw file.
    - **Sharded**: ``checkpoint_path`` names a checkpoint INDEX JSON carrying
      a non-empty ``shards`` list of ``{path, sha256, bytes}`` records (the
      exact shape ``contract.py::_verify_checkpoint`` enforces on the run
      manifest side). Every load-bearing shard's ACTUAL on-disk bytes are
      hashed and must equal its OWN declared per-shard sha256 (and declared
      size, when present) -- fail closed on any missing file, size mismatch,
      or hash mismatch. The returned identity is the canonical aggregate
      digest over the *verified* ``(path, sha256)`` pairs, sorted by path so
      the identity is independent of on-disk shard ordering.

    The index JSON's OWN digest (its self-consistency hash) is NEVER
    returned as the checkpoint-byte identity -- that substitution (index
    self-consistency reported under a name that means checkpoint byte
    identity) is exactly the defect class this function closes
    (state/failure-classes/semantic-validation-without-bytes-2026-07-25.md).
    A tampered shard is invisible to a check that only re-hashes the index.
    """
    try:
        raw = checkpoint_path.read_bytes()
    except OSError as exc:
        return None, [f"checkpointPath: unreadable: {exc}"]

    index: dict[str, Any] | None = None
    try:
        candidate = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        candidate = None
    if (
        isinstance(candidate, dict)
        and isinstance(candidate.get("shards"), list)
        and candidate["shards"]
    ):
        index = candidate

    if index is None:
        # Singular checkpoint: the named file IS the checkpoint bytes.
        return hashlib.sha256(raw).hexdigest(), []

    shard_root = root if root is not None else checkpoint_path.parent
    errors: list[str] = []
    canonical_pairs: list[tuple[str, str]] = []
    for position, shard in enumerate(index["shards"]):
        prefix = f"checkpoint.shards[{position}]"
        if not isinstance(shard, dict):
            errors.append(f"{prefix}: expected object")
            continue
        shard_path_raw = shard.get("path")
        shard_sha256 = shard.get("sha256")
        if not isinstance(shard_path_raw, str) or not shard_path_raw:
            errors.append(f"{prefix}.path: missing")
            continue
        if not isinstance(shard_sha256, str) or not shard_sha256:
            errors.append(f"{prefix}.sha256: missing")
            continue
        shard_path = (shard_root / shard_path_raw).resolve()
        try:
            actual_shard_sha256 = _sha256_file(shard_path)
        except OSError as exc:
            errors.append(f"{prefix}.path: unreadable: {exc}")
            continue
        if actual_shard_sha256 != shard_sha256:
            errors.append(
                f"{prefix}: shard bytes do not match declared sha256 "
                f"(declared {shard_sha256}, actual {actual_shard_sha256})"
            )
            continue
        shard_bytes = shard.get("bytes")
        if isinstance(shard_bytes, int) and not isinstance(shard_bytes, bool):
            actual_size = shard_path.stat().st_size
            if actual_size != shard_bytes:
                errors.append(
                    f"{prefix}.bytes: size mismatch (declared {shard_bytes}, actual {actual_size})"
                )
                continue
        canonical_pairs.append((shard_path_raw, shard_sha256))

    if errors:
        return None, errors

    canonical_pairs.sort(key=lambda pair: pair[0])
    canonical_blob = "\n".join(f"{path}:{sha}" for path, sha in canonical_pairs).encode("utf-8")
    return hashlib.sha256(canonical_blob).hexdigest(), []


def derive_seat_identity(
    seat_config: dict[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Fail-closed derivation of the owned-seat identity from the cert manifest.

    Returns ``{"valid": True, "seat": {...}, "errors": []}`` or a REFUSE result
    ``{"valid": False, "seat": None, "errors": [...]}``. Never raises for
    content failures; every step failure is a REFUSE.
    """
    errors: list[str] = []
    if not isinstance(seat_config, dict):
        return _refuse(["seat config: expected object"])

    # Step 0 (negative #5): a seat with NO cert reference is an independent
    # identity authority — prohibited outright.
    cert_path_raw = seat_config.get("certManifestPath")
    cert_digest = seat_config.get("certManifestDigest")
    if not isinstance(cert_path_raw, str) or not cert_path_raw:
        return _refuse(
            ["certManifestPath: missing — seat may not assert identity without a cert manifest"]
        )
    # Step 1 (negative #3): the digest pins the exact manifest bytes.
    if not isinstance(cert_digest, str) or not cert_digest:
        return _refuse(["certManifestDigest: missing — unpinned cert manifest is refused"])

    cert_path = Path(cert_path_raw)
    try:
        cert_bytes = cert_path.read_bytes()
    except OSError as exc:
        return _refuse([f"certManifestPath: unreadable: {exc}"])
    # Step 1 (negative #4): bytes must match the pinned digest.
    actual_digest = hashlib.sha256(cert_bytes).hexdigest()
    if actual_digest != cert_digest:
        return _refuse(
            [
                "certManifestDigest: cert manifest bytes do not match pinned digest "
                f"(pinned {cert_digest}, actual {actual_digest})"
            ]
        )
    # Strict UTF-8 + well-formed JSON (axis 1); the validator re-checks schema.
    try:
        cert = json.loads(cert_bytes.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _refuse([f"cert manifest: not strict-UTF-8 well-formed JSON: {exc}"])
    if not isinstance(cert, dict):
        return _refuse(["cert manifest: expected top-level object"])

    # Step 2: the SAME validator the /model path uses — single authority.
    validator = (repo_root / VALIDATOR_RELPATH).resolve()
    if not validator.is_file():
        return _refuse([f"validate_identity.py: not found at {validator}"])
    try:
        completed = subprocess.run(
            [sys.executable, str(validator), str(cert_path)],
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _refuse([f"validate_identity.py: execution failed: {exc}"])
    if completed.returncode != 0:
        detail = (completed.stdout or completed.stderr or "").strip()[:2000]
        return _refuse(
            [f"validate_identity.py: cert manifest invalid (exit {completed.returncode}): {detail}"]
        )

    # Step 3: DERIVE the overlapping fields from the cert manifest.
    derived: dict[str, Any] = {}
    for seat_field, (section, key) in DERIVED_FIELDS.items():
        container = cert.get(section)
        value = container.get(key) if isinstance(container, dict) else None
        if value is None:
            errors.append(f"cert manifest.{section}.{key}: missing — cannot derive {seat_field}")
        derived[seat_field] = value
    identity = cert.get("identity")
    if isinstance(identity, dict):
        for field in CARRIED_IDENTITY_FIELDS:
            derived[field] = identity.get(field)
        selected = identity.get("selected_as_owned_ember")
    else:
        selected = None
    if errors:
        return _refuse(errors)

    # Step 4 (negatives #2/#5): any overlapping seat field must EQUAL the
    # cert-derived value byte-for-byte — the seat is never a second authority.
    for seat_field in DERIVED_FIELDS:
        if seat_field in seat_config and seat_config[seat_field] != derived[seat_field]:
            errors.append(
                f"{seat_field}: seat value does not equal cert-derived value "
                f"(seat {seat_config[seat_field]!r}, cert {derived[seat_field]!r})"
            )
    if errors:
        return _refuse(errors)

    # Step 5 (negative #1): the ACTUAL checkpoint bytes must hash to the cert
    # checkpoint.byte_sha256 -- resolved via resolve_checkpoint_byte_identity,
    # which verifies every load-bearing shard when checkpointPath names a
    # sharded checkpoint index (never the index's own self-consistency hash).
    checkpoint_path_raw = seat_config.get("checkpointPath")
    if not isinstance(checkpoint_path_raw, str) or not checkpoint_path_raw:
        return _refuse(["checkpointPath: missing — cannot bind cert to checkpoint bytes"])
    checkpoint_path = Path(checkpoint_path_raw)
    checkpoint_root_raw = seat_config.get("checkpointRoot")
    checkpoint_root = Path(checkpoint_root_raw) if isinstance(checkpoint_root_raw, str) else None
    actual_checkpoint_sha256, checkpoint_errors = resolve_checkpoint_byte_identity(
        checkpoint_path, root=checkpoint_root
    )
    if checkpoint_errors:
        return _refuse(checkpoint_errors)
    if actual_checkpoint_sha256 != derived["checkpointSha256"]:
        return _refuse(
            [
                "checkpoint bytes: sha256 does not match cert checkpoint.byte_sha256 "
                f"(cert {derived['checkpointSha256']}, actual {actual_checkpoint_sha256})"
            ]
        )

    # Step 6 (negative #6): an OWNED_CANDIDATE serves but is never admitted or
    # credit-bearing; only OWNED_ADMITTED with selected_as_owned_ember may be.
    disposition = derived["disposition"]
    admitted = disposition == "OWNED_ADMITTED" and selected is True
    derived["admitted"] = admitted
    derived["creditBearing"] = admitted
    derived["selectedAsOwnedEmber"] = selected is True

    # Operational-only seat fields are kept, never cert-derived.
    for field, value in seat_config.items():
        if field in ("certManifestPath", "certManifestDigest", "checkpointPath"):
            derived[field] = value
        elif field not in DERIVED_FIELDS:
            derived[field] = value

    return {"valid": True, "seat": derived, "errors": []}


def require_admitted_seat(seat: dict[str, Any]) -> dict[str, Any]:
    """REFUSE any path that selects/counts a non-admitted seat as admitted."""
    if not isinstance(seat, dict) or seat.get("admitted") is not True:
        disposition = seat.get("disposition") if isinstance(seat, dict) else None
        raise PermissionError(
            f"seat with disposition {disposition!r} is not OWNED_ADMITTED+selected: "
            "it may not be selected or counted as admitted/credit-bearing"
        )
    return seat
