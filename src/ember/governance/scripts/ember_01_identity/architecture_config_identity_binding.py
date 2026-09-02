#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind the model's architecture config into the identity manifest, fail-closed.

cond3 increment (architecture_config category): the identity manifest's ``architecture``
object (``architecture.source`` + ``architecture.sha256``) must be the identity of the
model config the real, trusted consumer actually checks -- not a hand-typed or
re-serialized substitute.

CRITICAL -- bind the RUNTIME object the real consumer checks, not an inferred
reconstruction of it (the census's own stated requirement for this category: "bind
canonical architecture bytes and reject inferred identity"):

- The real runtime architecture consumer is
  ``tools/ember-restart-3b/parameter_counter.execute_counter`` (the trusted, isolated
  sparse-checkpoint-realization counter that ``parameter_identity_binding.py`` already
  wires against for the parameter axes). At parameter_counter.py line 696 it reads the
  model config file via ``_read_json_snapshot``, which is ``_read_bytes_snapshot`` (a
  streaming ``hashlib.sha256`` of the RAW BYTES read from disk) followed by
  ``json.loads``. At line 802 it fails closed with
  ``ValueError("checkpoint model-config hash mismatch")`` unless the checkpoint
  manifest's ``model_config_sha256`` equals that raw-bytes digest -- and it further
  requires ``config.get("architecture_revision") == ARCHITECTURE_REVISION`` (line 697)
  and a structurally valid decoder shape via ``_model_shape`` (line 699: hidden_size,
  layers, attention_heads, vocab_size, tied embeddings, and the sparse modality/routing
  declarations) before it will accept the config at all.
- ``validate_identity``'s own OWNED_ADMITTED admission gate resolves ``architecture.sha256``
  through the exact same shape of check: the manifest's ``architecture.sha256`` must equal
  ``hashlib.sha256(bytes.fromhex(artifact_bundle["artifacts"]["architecture"]["content_hex"]))``
  (validate_identity.py ~line 1094-1120, ``admission.artifact_hash_mismatch`` /
  ``admission.artifact_missing``) -- again a RAW-BYTES content address, never a
  canonicalized re-serialization of the parsed config.

Unlike the receipt/tokenizer lessons (where the wrong object was the raw on-disk bytes and
the right object was a canonically-reserialized or in-memory-transformed form), this
category inverts: the trusted counter and the validator BOTH content-address the literal
artifact bytes on disk. The wrong object here is an *inferred* identity -- a hash computed
by re-serializing the parsed config (e.g. ``json.dumps(config, sort_keys=True,
separators=(",", ":"))``) instead of hashing the actual bytes the counter reads and the
checkpoint manifest's ``model_config_sha256`` is checked against. A config file stored with
different indentation, key order, or trailing whitespace than its canonical reserialization
would make the trusted counter's own ``model_config_sha256`` check (and validate_identity's
artifact-bundle check) FAIL against a manifest bound to the reserialized form -- the binding
would be sound-in-shape yet point at the wrong object.

So: ``bind_architecture_identity`` projects, and ``verify_architecture_identity_binding``
re-derives, the same raw-bytes sha256 of the model config file that
``parameter_counter.execute_counter`` reads and validate_identity's admission gate checks --
via the trusted counter's own hasher (``parameter_counter._sha256``) and its own shape/
revision gate (``parameter_counter._model_shape`` / ``ARCHITECTURE_REVISION``), imported
here, never re-implemented. A hand-typed digest, or one computed from a re-serialized
reconstruction of the config rather than the literal bytes on disk, can never be laundered
into ``architecture.sha256``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

_COUNTER_MODULE_DIR = Path(__file__).resolve().parents[2] / "tools" / "ember-restart-3b"
if str(_COUNTER_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_COUNTER_MODULE_DIR))

# The REAL runtime architecture-config consumer. We import its own file-hasher, shape
# validator, and required architecture revision directly so the binding is provably
# against the same objects the trusted, isolated counter checks -- never a
# re-implementation that could drift from it.
from parameter_counter import _sha256 as _hash_file  # noqa: E402
from parameter_counter import _model_shape, ARCHITECTURE_REVISION  # noqa: E402

ARCHITECTURE_IDENTITY_SCHEMA = "ember-architecture-identity-receipt-v1"


class ArchitectureIdentityMismatch(ValueError):
    """A manifest's claimed architecture identity diverges from measured evidence."""


def _read_model_config(path: Path) -> tuple[dict[str, Any], str]:
    """Read a model config file and content-address its RAW bytes (the runtime object).

    Mirrors ``parameter_counter._read_json_snapshot`` exactly: a streaming sha256 of the
    bytes as they sit on disk, then a JSON parse. Never a re-serialization of the parsed
    result -- that would be a DIFFERENT object than what the trusted counter hashes.
    """
    resolved = Path(path)
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise ArchitectureIdentityMismatch(
            f"model config at {resolved} could not be read to content-address it ({error})"
        ) from error
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchitectureIdentityMismatch(
            f"model config bytes at {resolved} are not a JSON config object ({error})"
        ) from error
    if not isinstance(config, dict):
        raise ArchitectureIdentityMismatch(
            f"model config at {resolved} must be a JSON object; got {type(config).__name__}"
        )
    return config, hashlib.sha256(raw).hexdigest()


def measure_architecture_identity(model_config_path: Path) -> dict[str, Any]:
    """Measure the running architecture identity from a real model config file.

    Reads and parses the config, requires the trusted counter's own
    ``ARCHITECTURE_REVISION`` and structurally valid ``_model_shape`` (the same gates
    ``execute_counter`` applies before it will accept the config at all), and computes
    the runtime identity as the raw-bytes sha256 of the file -- independently
    cross-checked against the trusted counter's own streaming hasher. Nothing is
    invented: the bound identity traces to the bytes on disk, re-derived through the
    real consumer's own functions.
    """
    path = Path(model_config_path)
    config, file_sha256 = _read_model_config(path)
    if config.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ArchitectureIdentityMismatch(
            f"model config at {path} declares architecture_revision="
            f"{config.get('architecture_revision')!r}, not the trusted counter's "
            f"required {ARCHITECTURE_REVISION!r} (parameter_counter.ARCHITECTURE_REVISION)"
        )
    try:
        shape = _model_shape(config)
    except ValueError as error:
        raise ArchitectureIdentityMismatch(
            f"model config at {path} does not realize a valid decoder shape under the "
            f"trusted counter's own shape check (parameter_counter._model_shape: {error})"
        ) from error
    independent_sha256 = _hash_file(path)
    if independent_sha256 != file_sha256:
        raise ArchitectureIdentityMismatch(
            f"model config bytes at {path} hashed to {file_sha256!r} on read, but the "
            f"trusted counter's own streaming hasher (parameter_counter._sha256) computed "
            f"{independent_sha256!r} for the same path (sha drift)"
        )
    return {
        "schema_version": ARCHITECTURE_IDENTITY_SCHEMA,
        "result": "MEASURED",
        "architecture_revision": config["architecture_revision"],
        "config_sha256": file_sha256,
        "shape": dict(shape),
    }


def bind_architecture_identity(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any], *, source: str
) -> dict[str, Any]:
    """Project a MEASURED architecture receipt into the manifest's ``architecture`` object.

    ``architecture.sha256`` binds to the receipt's ``config_sha256`` -- the raw-bytes
    identity of the model config file the trusted counter reads and validate_identity's
    admission gate content-addresses -- NEVER a hand-typed or re-serialized substitute.
    ``architecture.source`` is the caller's stated non-empty provenance (e.g. the config
    path or its production role); it is never invented from the receipt.
    """
    if receipt.get("result") != "MEASURED":
        raise ArchitectureIdentityMismatch(
            "receipt is not measured evidence; refusing to bind an unmeasured "
            "architecture identity"
        )
    if not isinstance(source, str) or not source.strip():
        raise ArchitectureIdentityMismatch(
            f"architecture.source must be a non-empty string; got {source!r}"
        )
    config_sha256 = receipt.get("config_sha256")
    if not isinstance(config_sha256, str) or len(config_sha256) != 64:
        raise ArchitectureIdentityMismatch(
            f"receipt config_sha256 is not a 64-hex digest: {config_sha256!r}"
        )
    bound = dict(manifest)
    bound["architecture"] = {"source": source, "sha256": config_sha256}
    return bound


def verify_architecture_identity_binding(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    model_config_path: Path,
) -> None:
    """Fail closed the instant the manifest's architecture identity diverges from evidence.

    Re-derives everything checked from the actual model config bytes on disk via the
    real trusted-counter functions (never restates the manifest against itself, and
    never trusts the receipt alone):

    1. The config file is re-read and re-hashed (raw bytes, cross-checked against the
       trusted counter's own streaming hasher) and re-validated against
       ``ARCHITECTURE_REVISION`` and ``_model_shape`` -- the same gates
       ``execute_counter`` applies. A config that no longer satisfies them fails here.
    2. ``receipt.config_sha256`` and ``manifest.architecture.sha256`` must both equal the
       freshly re-derived raw-bytes sha256. A pointer bound to a re-serialized/
       canonicalized reconstruction of the config (an "inferred" identity, the census's
       named failure mode for this category), or to any object other than the literal
       bytes on disk, fails here.
    3. ``receipt.shape`` must equal the freshly re-derived shape.
    4. ``architecture.source`` must be present and non-empty.

    Raises ``ArchitectureIdentityMismatch`` naming the exact field. Silent when every
    bound value matches the freshly measured evidence.
    """
    architecture = manifest.get("architecture")
    if not isinstance(architecture, Mapping):
        raise ArchitectureIdentityMismatch("manifest has no architecture section to verify")

    claimed_source = architecture.get("source")
    if not isinstance(claimed_source, str) or not claimed_source.strip():
        raise ArchitectureIdentityMismatch(
            f"architecture.source must be a present, non-empty string; got {claimed_source!r}"
        )

    path = Path(model_config_path)
    real_config, real_file_sha256 = _read_model_config(path)
    independent_sha256 = _hash_file(path)
    if independent_sha256 != real_file_sha256:
        raise ArchitectureIdentityMismatch(
            f"model config bytes at {path} hashed to {real_file_sha256!r} on read, but "
            f"the trusted counter's own streaming hasher (parameter_counter._sha256) "
            f"computed {independent_sha256!r} for the same path (sha drift)"
        )

    if real_config.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ArchitectureIdentityMismatch(
            f"model config at {path} declares architecture_revision="
            f"{real_config.get('architecture_revision')!r}, not the trusted counter's "
            f"required {ARCHITECTURE_REVISION!r}"
        )
    try:
        real_shape = _model_shape(real_config)
    except ValueError as error:
        raise ArchitectureIdentityMismatch(
            f"model config at {path} does not realize a valid decoder shape under the "
            f"trusted counter's own shape check (parameter_counter._model_shape: {error})"
        ) from error

    claimed_config_sha256 = receipt.get("config_sha256")
    if claimed_config_sha256 != real_file_sha256:
        raise ArchitectureIdentityMismatch(
            f"receipt claims config_sha256={claimed_config_sha256!r} but the model "
            f"config bytes on disk at {path} hash to {real_file_sha256!r} (sha drift, or "
            f"the receipt was measured against a different config)"
        )
    if receipt.get("shape") != real_shape:
        raise ArchitectureIdentityMismatch(
            f"receipt claims shape={receipt.get('shape')!r} but the model config at "
            f"{path} independently re-derives (parameter_counter._model_shape) to "
            f"shape={real_shape!r}"
        )

    claimed = architecture.get("sha256")
    if claimed != real_file_sha256:
        raise ArchitectureIdentityMismatch(
            f"manifest claims architecture.sha256={claimed!r} but the model config bytes "
            f"on disk at {path} -- the object the trusted, isolated counter "
            f"(parameter_counter.execute_counter) checks the checkpoint manifest's "
            f"model_config_sha256 against, and validate_identity's admission gate "
            f"content-addresses -- hash to {real_file_sha256!r}; a re-serialized or "
            f"otherwise inferred reconstruction of the config, rather than its literal "
            f"artifact bytes, fails here"
        )
