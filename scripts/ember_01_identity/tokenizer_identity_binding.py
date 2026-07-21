#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind a tokenizer artifact's identity into the identity manifest, fail-closed.

cond3 increment (tokenizer_data_lineage category, tokenizer sub-field): the identity
manifest's ``tokenizer`` section must not be hand-typed or fixture-constant. Its
``sha256`` must be the content hash of the *actual* tokenizer artifact bytes on disk,
never a copied constant -- the same content-addressing the recovered shard-generation
tokenizer already enforces at load time.

The two production consumers this binding wires against:

- ``scripts/ember_01_identity/validate_identity.validate_manifest`` -- the manifest-shape
  validator. ``tokenizer.sha256`` is a REQUIRED_PATH, a HASH_PATH (must be a 64-hex
  content address), a BINDING_PATH, and a member of the closed ``tokenizer`` object
  ``{id, sha256}`` (validate_identity.py lines 76-77, 142, 162-163, 226). For an
  ``OWNED_ADMITTED`` manifest it is additionally required to resolve to real
  content-addressed artifact bytes in the artifact bundle (validate_identity.py's
  ``required_artifacts["tokenizer"]``, ~line 1067).
- ``scripts/a1_predicate_scan.load_stripped_tokenizer`` -- the real tokenizer loader,
  which computes ``file_sha256(tokenizer_json_path)`` and raises
  ``A1_SCAN_TOKENIZER_SHA_DRIFT`` the instant the tokenizer bytes on disk do not hash to
  the expected sha. This module's ``verify_`` is the manifest-side analog of that drift
  guard: it re-derives ``tokenizer.sha256`` from the bytes on disk, not from the receipt
  or from the manifest against itself.

Two functions (mirroring ``parameter_identity_binding`` exactly -- additive, no schema
change, ``verify_`` fails closed on any divergence):

- ``bind_tokenizer_identity`` hashes the real tokenizer artifact file (streaming reads,
  same mechanism as the a1 loader's ``file_sha256``) and projects that MEASURED digest
  into the manifest's ``tokenizer.sha256``, setting ``tokenizer.id`` from the caller's
  stated identity. It never invents a hash -- every value traces to bytes on disk.
- ``verify_tokenizer_identity_binding`` re-hashes the same tokenizer artifact from disk
  and fails closed -- raising ``TokenizerIdentityMismatch`` naming the exact field -- the
  instant the manifest's ``tokenizer.sha256`` diverges from the freshly measured hash,
  the ``tokenizer.id`` is absent/empty, or the artifact cannot be read (a manifest naming
  a tokenizer with no bytes on disk to verify against). Silent (returns None) when the
  bound identity matches the bytes.

DEFERRED (out of this smallest-increment scope): the ``OWNED_ADMITTED`` artifact-bundle
resolution -- proving ``tokenizer.sha256`` also appears as a content-addressed entry in
the ``ember-artifact-bundle-v1`` bundle -- is a separate, non-additive path that threads
the full artifact bundle through validate_manifest's admission gate; it is not
implemented here. This increment binds the tokenizer's own identity (id + content hash of
the artifact) for the OWNED_CANDIDATE shape; admission-bundle binding is a later leg.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

_HASH_CHUNK_BYTES = 1 << 20  # 1 MiB streaming reads; never a full-file read


class TokenizerIdentityMismatch(ValueError):
    """A manifest's claimed tokenizer identity diverges from measured evidence."""


def _hash_file(path: Path) -> str:
    """Streaming sha256 of a file's bytes on disk (mirrors a1 file_sha256)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure_tokenizer_artifact(tokenizer_artifact: Path) -> str:
    """Content-address the real tokenizer artifact on disk. No fixture constant."""
    return _hash_file(Path(tokenizer_artifact))


def bind_tokenizer_identity(
    manifest: Mapping[str, Any], *, tokenizer_id: str, tokenizer_artifact: Path
) -> dict[str, Any]:
    """Project a MEASURED tokenizer content hash into the manifest's tokenizer section.

    ``tokenizer_artifact`` is the real tokenizer file on disk (e.g. a ``tokenizer.json``);
    its bytes are hashed here and become ``tokenizer.sha256``. ``tokenizer_id`` is the
    caller's stated tokenizer identity (a non-empty string), bound to ``tokenizer.id``.
    Nothing is invented: the sha256 traces to bytes on disk.
    """
    if not isinstance(tokenizer_id, str) or not tokenizer_id.strip():
        raise TokenizerIdentityMismatch(
            f"tokenizer.id must be a non-empty string; got {tokenizer_id!r}"
        )
    artifact_path = Path(tokenizer_artifact)
    try:
        measured_sha256 = _hash_file(artifact_path)
    except OSError as error:
        raise TokenizerIdentityMismatch(
            f"tokenizer artifact at {artifact_path} could not be read from disk to "
            f"content-address it ({error}); refusing to bind a tokenizer identity with "
            "no bytes on disk"
        ) from error
    bound = dict(manifest)
    bound["tokenizer"] = {
        **dict(manifest.get("tokenizer", {})),
        "id": tokenizer_id,
        "sha256": measured_sha256,
    }
    return bound


def verify_tokenizer_identity_binding(
    manifest: Mapping[str, Any], *, tokenizer_artifact: Path
) -> None:
    """Fail closed the instant the manifest's tokenizer identity diverges from disk.

    ``tokenizer_artifact`` is the single authoritative source of tokenizer bytes for this
    verification -- never the manifest against itself. The artifact is re-hashed from disk
    (streaming reads) and compared against ``tokenizer.sha256``; a manifest naming a
    tokenizer whose bytes do not hash to the claimed content address, or whose artifact
    cannot be read at all, fails here (the manifest-side analog of the a1 loader's
    ``A1_SCAN_TOKENIZER_SHA_DRIFT``). ``tokenizer.id`` must also be a present, non-empty
    string. Raises ``TokenizerIdentityMismatch`` naming the exact field that fails. Silent
    (returns None) when the bound identity matches the bytes on disk.
    """
    tokenizer = manifest.get("tokenizer")
    if not isinstance(tokenizer, Mapping):
        raise TokenizerIdentityMismatch("manifest has no tokenizer section to verify")

    claimed_id = tokenizer.get("id")
    if not isinstance(claimed_id, str) or not claimed_id.strip():
        raise TokenizerIdentityMismatch(
            f"tokenizer.id must be a present, non-empty string; got {claimed_id!r}"
        )

    claimed_sha256 = tokenizer.get("sha256")
    artifact_path = Path(tokenizer_artifact)
    try:
        real_sha256 = _hash_file(artifact_path)
    except OSError as error:
        raise TokenizerIdentityMismatch(
            f"tokenizer artifact at {artifact_path} could not be read from disk to "
            f"re-derive its hash; manifest claims tokenizer.sha256={claimed_sha256!r} but "
            f"no such tokenizer bytes exist to verify against ({error})"
        ) from error
    if real_sha256 != claimed_sha256:
        raise TokenizerIdentityMismatch(
            f"manifest claims tokenizer.sha256={claimed_sha256!r} but the tokenizer "
            f"artifact bytes on disk hash to tokenizer.sha256={real_sha256!r}"
        )
