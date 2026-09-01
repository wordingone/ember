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

Checkpoint-byte identity is resolved by ``resolve_checkpoint_byte_identity`` /
``_resolve_checkpoint_envelope``: the ACTUAL checkpoint bytes, never a checkpoint
INDEX JSON's own digest and never an aggregate invented inside this module --
see that function's docstring for the resolution rule
(state/failure-classes/semantic-validation-without-bytes-2026-07-25.md).

Rework (2026-07-25, round-2 parked-cure correction): round 2 disambiguated
checkpoint shape by sniffing the artifact bytes (JSON with a non-empty
``shards`` list -> sharded; anything else -> singular, hashed RAW). The
supplier of the checkpoint artifact also supplies the cert that names its
expected digest, so a hostile supplier chooses which branch runs and
therefore how hard they are checked -- rule 5 of the failure-class doc. The
verifier proved this: a 3-byte file ``b"xyz"`` with the cert's
``checkpoint.byte_sha256`` hand-set to ``sha256("xyz")`` took the singular
branch and was admitted. Round 2's sharded branch was also a defect one
level further in: its aggregate (sha256 over sorted ``path:sha256`` lines)
appears nowhere but this module and its own tests -- an unratified
reconstruction the real schema does not carry.

This rework binds to the identity the cert schema already expresses instead:
one checkpoint shard's canonical tensor envelope, measured via
``ember_01_identity.checkpoint_save_load_identity_binding.measure_checkpoint_identity``
(the trusted counter's own safe reader -- the same binding
``ember_01_identity``'s own checkpoint-identity category uses everywhere
else). There is no raw-file fallback: a ``checkpointPath`` that is not a
JSON object with a ``shards`` list naming EXACTLY ONE shard is a refusal
naming the shape it got and the shape it needs. A checkpoint index naming
MORE than one shard is also refused -- the ``ember-model-experiment-identity-v1``
schema's ``checkpoint`` object (manifests/ember-01-identity/schema-v1.json)
carries exactly one ``byte_sha256`` for one measured envelope; it has no
field for a multi-shard aggregate, and inventing one inside this bridge is
exactly the defect class this rework closes. A genuinely multi-shard
checkpoint (e.g. the MoE ``ember-sparse-checkpoint-v5`` production writer,
which always emits a shared-model shard + an optimizer shard + one shard per
expert bank) needs a schema/contract change, not a bridge-invented formula;
see the rework report for the ruling-request writeup.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_IDENTITY_DIR = Path(__file__).resolve().parents[5] / "scripts" / "ember_01_identity"
if str(_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_IDENTITY_DIR))

from checkpoint_save_load_identity_binding import (  # noqa: E402
    CheckpointSaveLoadIdentityMismatch,
    measure_checkpoint_identity,
)

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


def _resolve_checkpoint_envelope(
    checkpoint_path: Path, *, root: Path | None = None
) -> tuple[bytes | None, list[str]]:
    """Resolve the checkpoint's canonical tensor-envelope bytes at
    ``checkpoint_path``, fail-closed. Returns ``(envelope_bytes, errors)``.

    ``root`` is the directory the index's shard ``path`` entry is relative to
    (the run manifest's own root, matching ``contract.py::_verify_checkpoint``
    -- shard paths there are relative to the manifest root, NOT to the
    checkpoint index file's own directory). Defaults to
    ``checkpoint_path.parent`` when not supplied.

    Exactly ONE shape is recognised: ``checkpoint_path`` names a checkpoint
    INDEX JSON carrying a ``shards`` list with EXACTLY ONE entry
    (``{path, ...}`` -- the exact top-level shape ``contract.py`` enforces on
    the run manifest side). There is no raw-file fallback and no branch
    selected by sniffing the artifact's own bytes: an artifact whose shape
    does not match this is refused, naming the shape it got and the shape it
    needs. That is the whole fix -- round 2 let a hostile supplier of the
    checkpoint artifact also choose (via the artifact's own shape) how hard
    it was checked (state/failure-classes/semantic-validation-without-bytes-2026-07-25.md,
    rule 5).

    The one named shard's ACTUAL bytes are read via the trusted counter's own
    safe reader (``checkpoint_save_load_identity_binding.measure_checkpoint_identity``)
    and its canonical tensor-envelope bytes are returned -- fail closed
    (empty bytes, no result) if the shard is missing or the trusted reader
    cannot parse it as a real checkpoint.

    A checkpoint index naming MORE than one shard is ALSO refused, not
    silently aggregated: the ``ember-model-experiment-identity-v1`` schema's
    ``checkpoint`` object expresses exactly one canonical envelope identity.
    Binding N>1 shards to that one field would require this module to invent
    an aggregate convention -- exactly the defect class this rework closes
    (round 2's own ``path:sha256``-lines formula, appearing nowhere else in
    the tree). That case is a schema/contract gap; it goes to a ruling
    request, never into this function.
    """
    try:
        raw = checkpoint_path.read_bytes()
    except OSError as exc:
        return None, [f"checkpointPath: unreadable: {exc}"]

    try:
        candidate = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, [
            "checkpointPath: not a recognised checkpoint shape -- expected a checkpoint "
            "INDEX JSON with a 'shards' list naming exactly one real checkpoint shard; got "
            "bytes that are not valid UTF-8 JSON. There is no raw-file fallback -- a "
            "checkpoint artifact whose shape is not recognised is refused outright."
        ]
    shards = candidate.get("shards") if isinstance(candidate, dict) else None
    if not isinstance(shards, list) or not shards:
        return None, [
            "checkpointPath: not a recognised checkpoint shape -- expected an object with a "
            "non-empty 'shards' list. There is no raw-file fallback -- a checkpoint artifact "
            "whose shape is not recognised is refused outright."
        ]
    if len(shards) != 1:
        return None, [
            f"checkpointPath: checkpoint index names {len(shards)} shards, but the "
            "ember-model-experiment-identity-v1 cert schema's checkpoint object "
            "(manifests/ember-01-identity/schema-v1.json) expresses exactly ONE canonical "
            "tensor-envelope identity (checkpoint.byte_sha256 for a single measured shard) -- "
            "it has no field for a multi-shard aggregate. Binding N>1 shards to that one field "
            "would require inventing an aggregate convention inside this bridge, which is "
            "exactly the defect class this rework closes. This is a schema/contract gap, not a "
            "bridge defect -- it needs a ruling (the way GAP-3 was ruled), not a bridge-invented "
            "identity."
        ]

    shard = shards[0]
    if not isinstance(shard, dict):
        return None, ["checkpointPath: shards[0]: expected object"]
    shard_path_raw = shard.get("path")
    if not isinstance(shard_path_raw, str) or not shard_path_raw:
        return None, ["checkpointPath: shards[0].path: missing"]

    shard_root = root if root is not None else checkpoint_path.parent
    shard_path = (shard_root / shard_path_raw).resolve()
    try:
        measured = measure_checkpoint_identity(shard_path)
    except CheckpointSaveLoadIdentityMismatch as exc:
        return None, [
            f"checkpointPath: shards[0] at {shard_path} failed measurement via the trusted "
            f"counter's safe reader ({exc}). The checkpoint-byte identity is always measured "
            "from the real shard, never taken from the index's own declared digest or from "
            "the shard file's raw bytes."
        ]
    return bytes.fromhex(measured["checkpoint_bytes_hex"]), []


def resolve_checkpoint_byte_identity(
    checkpoint_path: Path, *, root: Path | None = None
) -> tuple[str | None, list[str]]:
    """The checkpoint-BYTE identity at ``checkpoint_path``, fail-closed --
    ``sha256`` of the canonical tensor envelope ``_resolve_checkpoint_envelope``
    resolves (never a checkpoint INDEX JSON's own digest, never a bridge-
    invented multi-shard aggregate). See that function's docstring for the
    resolution rule."""
    envelope_bytes, errors = _resolve_checkpoint_envelope(checkpoint_path, root=root)
    if errors:
        return None, errors
    assert envelope_bytes is not None
    return hashlib.sha256(envelope_bytes).hexdigest(), []


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

    # Step 1.5 (moved ahead of Step 2, rework 2026-07-25): resolve the
    # checkpoint's canonical envelope bytes FIRST, fail-closed, so Step 2 can
    # pass them to validate_identity.py's own --checkpoint re-derivation
    # branch (validate_identity.py:686-687) -- which otherwise never fires,
    # per rule 1 of the failure-class doc. checkpointPath always names a
    # checkpoint INDEX JSON with exactly one shard; a raw file, a missing
    # 'shards' list, or more than one shard is refused (see
    # _resolve_checkpoint_envelope's docstring) -- never a bridge-invented
    # fallback or aggregate.
    checkpoint_path_raw = seat_config.get("checkpointPath")
    if not isinstance(checkpoint_path_raw, str) or not checkpoint_path_raw:
        return _refuse(["checkpointPath: missing — cannot bind cert to checkpoint bytes"])
    checkpoint_path = Path(checkpoint_path_raw)
    checkpoint_root_raw = seat_config.get("checkpointRoot")
    checkpoint_root = Path(checkpoint_root_raw) if isinstance(checkpoint_root_raw, str) else None
    checkpoint_envelope_bytes, checkpoint_errors = _resolve_checkpoint_envelope(
        checkpoint_path, root=checkpoint_root
    )
    if checkpoint_errors:
        return _refuse(checkpoint_errors)
    assert checkpoint_envelope_bytes is not None
    actual_checkpoint_sha256 = hashlib.sha256(checkpoint_envelope_bytes).hexdigest()

    # Step 2: the SAME validator the /model path uses — single authority.
    # --checkpoint carries the SAME envelope bytes just resolved above, so
    # validate_identity's own per-tensor re-hash branch always fires against
    # the real shard -- never silently skipped (rule 1/5: a validator
    # parameter that exists and is not passed is a defect, not a default).
    validator = (repo_root / VALIDATOR_RELPATH).resolve()
    if not validator.is_file():
        return _refuse([f"validate_identity.py: not found at {validator}"])
    with tempfile.TemporaryDirectory(prefix="seat-bridge-checkpoint-") as scratch_dir:
        scratch_checkpoint = Path(scratch_dir) / "checkpoint-envelope.bin"
        scratch_checkpoint.write_bytes(checkpoint_envelope_bytes)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(validator),
                    str(cert_path),
                    "--checkpoint",
                    str(scratch_checkpoint),
                ],
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

    # Step 5 (negative #1): the ACTUAL checkpoint bytes (resolved at Step 1.5,
    # above, and independently re-derived by validate_identity.py's own
    # --checkpoint branch in Step 2) must hash to the cert checkpoint.byte_sha256.
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
