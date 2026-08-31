#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind a checkpoint's save/load identity into the identity manifest, fail-closed.

cond3 increment (checkpoint_save_load category): the identity manifest's ``checkpoint``
object (``checkpoint.format`` + ``checkpoint.byte_sha256`` + ``checkpoint.tensors``) must
be the identity of the real, on-disk checkpoint shard the trusted checkpoint persistence
path actually saves and loads -- never a hand-typed or re-serialized substitute.

CRITICAL -- bind the RUNTIME object the real consumer checks, not an inferred
reconstruction of it (this category's requirement, per the census: "validate full identity
before save, load, conversion, recovery, or merge"):

- The real runtime checkpoint save/load consumer is
  ``tools/ember-restart-3b/checkpoint_artifacts.load_checkpoint_artifacts``. It calls
  ``torch.load`` on each shard, then ``model.load_state_dict`` / ``optimizer.load_state_dict``
  (checkpoint_artifacts.py lines ~1247, ~1275-1279) -- and it ALREADY fails closed BEFORE any
  of that mutation with ``CheckpointIdentityMismatch`` unless the checkpoint's own
  ``checkpoint.byte_sha256`` (computed via the module's own streaming ``_sha256``) matches
  the recorded identity (checkpoint_artifacts.py lines 1230-1243). That module's own
  ``_bind_checkpoint_identity`` (lines 83-97) establishes the convention this binding
  mirrors: the checkpoint's identity is a content address of what is actually on disk, never
  an invented or reconstructed value.
- This cond3 manifest's ``checkpoint.byte_sha256`` field (validate_identity.py
  ``validate_manifest``, ~line 638-648) is checked against a caller-supplied
  ``checkpoint_bytes`` argument via a direct ``hashlib.sha256(checkpoint_bytes)`` compare --
  and, when ``checkpoint.format == "ember-checkpoint-envelope-v1"``, those bytes are further
  parsed as a closed JSON tensor envelope (``schema`` + ``tensors: [{name, shape, dtype,
  content_hex}]``) and independently re-hashed per tensor into ``checkpoint.tensors``
  (validate_identity.py lines 649-721). For ``OWNED_ADMITTED`` disposition this envelope
  format is the ONLY accepted checkpoint format (``admission.checkpoint_format_unsupported``
  otherwise, validate_identity.py line 1034-1040).

So the runtime object this category must bind is the real per-tensor storage bytes physically
present in an actual saved checkpoint shard -- read the same way the trusted, isolated counter
(``tools/ember-restart-3b/parameter_counter``) independently inspects checkpoints: via its own
metadata-only unpickler (``_load_checkpoint_metadata``) and raw-storage reader
(``_tensor_raw_bytes``), imported here, never reimplemented, and NEVER via ``torch.load``
itself (which executes the checkpoint's pickle opcodes -- the trusted counter's whole point is
that identity can be established WITHOUT that execution).

CRITICAL -- the WRONG object for this category, verified empirically (saving the identical
tensor content twice produces two different whole-file sha256 values: ``torch.save``'s zip
container embeds file-order and metadata that are not stable across saves): the raw bytes of
the on-disk ``.pt`` FILE. A manifest's ``checkpoint.byte_sha256`` bound to
``sha256(shard_path.read_bytes())`` would be sound-in-shape (it is a real sha256 of a real
file) yet unstable and NOT the object ``checkpoint.byte_sha256`` needs to equal -- the
canonical, deterministically-ordered per-tensor content envelope (``schema`` + sorted
``tensors`` with each tensor's own raw storage bytes as ``content_hex``) is the right object,
because it is invariant to the container's non-tensor framing and is exactly what the
validator's envelope-parsing path (and, transitively, ``checkpoint.tensors``) content-addresses.

``bind_checkpoint_identity`` refuses to project anything but the canonically-derived identity
of a real, measured checkpoint shard. ``verify_checkpoint_identity_binding`` fails closed --
naming the exact field -- the instant the manifest's checkpoint identity diverges from the
identity a fresh read of the real shard would produce.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

_COUNTER_MODULE_DIR = Path(__file__).resolve().parents[2] / "tools" / "ember-restart-3b"
if str(_COUNTER_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_COUNTER_MODULE_DIR))

# The REAL runtime checkpoint inspection primitives. We import the trusted, isolated
# counter's own metadata-only unpickler and raw-storage reader directly so the binding is
# provably against the same bytes the trusted counter (and, by the same convention,
# checkpoint_artifacts.py's load path) would independently re-derive -- never a
# re-implementation that could drift from it, and never torch.load's pickle execution.
from parameter_counter import _load_checkpoint_metadata, _tensor_raw_bytes  # noqa: E402
from parameter_counter import _TensorMetadata  # noqa: E402

CHECKPOINT_ENVELOPE_SCHEMA = "ember-checkpoint-envelope-v1"
CHECKPOINT_IDENTITY_SCHEMA = "ember-checkpoint-save-load-identity-receipt-v1"

# The subset of torch storage types the identity manifest's envelope format accepts
# (validate_identity.py's ``scalar_widths``). Deliberately narrower than the trusted
# counter's own ``_storage_element_bytes`` (which also accepts Double/Long/Int/Short/Bool
# storages for its OWN, unrelated genesis-hash use) -- a checkpoint tensor outside this set
# cannot be bound into this manifest's envelope at all.
_ENVELOPE_DTYPE_BY_STORAGE_TYPE = {
    "FloatStorage": "float32",
    "HalfStorage": "float16",
    "BFloat16Storage": "bfloat16",
    "CharStorage": "int8",
    "ByteStorage": "uint8",
}


class CheckpointSaveLoadIdentityMismatch(ValueError):
    """A manifest's claimed checkpoint save/load identity diverges from measured evidence."""


def _read_checkpoint_tensor_envelope(shard_path: Path) -> tuple[dict[str, Any], bytes]:
    """Read a real checkpoint shard's tensors via the trusted counter's own safe reader.

    Opens the shard as the zip archive ``torch.save`` produces and reads it with
    ``parameter_counter._load_checkpoint_metadata`` (a metadata-only unpickler that never
    executes tensor storage as code) followed by ``parameter_counter._tensor_raw_bytes``
    (the exact raw bytes of each tensor's contiguous base storage, read directly from the
    archive's ``data/<key>`` entry) -- the same safe, isolated inspection path the trusted
    counter uses to independently verify checkpoints without ``torch.load``. Returns the
    closed ``ember-checkpoint-envelope-v1`` envelope and its canonical (sorted-keys, compact)
    JSON encoding.
    """
    path = Path(shard_path)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise CheckpointSaveLoadIdentityMismatch(
            f"checkpoint shard at {path} could not be opened as a checkpoint archive ({error})"
        ) from error
    with archive:
        try:
            payload = _load_checkpoint_metadata(archive)
        except ValueError as error:
            raise CheckpointSaveLoadIdentityMismatch(
                f"checkpoint shard at {path} could not be safely inspected by the trusted "
                f"counter's metadata-only unpickler ({error})"
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("model"), dict):
            raise CheckpointSaveLoadIdentityMismatch(
                f"checkpoint shard at {path} has no 'model' state dict for "
                f"load_checkpoint_artifacts / load_state_dict to consume"
            )
        state = payload["model"]
        if not state:
            raise CheckpointSaveLoadIdentityMismatch(
                f"checkpoint shard at {path} declares an empty model state"
            )
        tensors: list[dict[str, Any]] = []
        for name in sorted(state):
            tensor = state[name]
            if not isinstance(tensor, _TensorMetadata):
                raise CheckpointSaveLoadIdentityMismatch(
                    f"checkpoint shard at {path} entry {name!r} is not tensor storage metadata"
                )
            dtype = _ENVELOPE_DTYPE_BY_STORAGE_TYPE.get(tensor.storage.storage_type)
            if dtype is None:
                raise CheckpointSaveLoadIdentityMismatch(
                    f"checkpoint shard at {path} tensor {name!r} uses storage type "
                    f"{tensor.storage.storage_type!r}, which the identity envelope does not "
                    f"support"
                )
            try:
                raw = _tensor_raw_bytes(archive, tensor)
            except ValueError as error:
                raise CheckpointSaveLoadIdentityMismatch(
                    f"checkpoint shard at {path} tensor {name!r} raw bytes could not be read "
                    f"from its storage ({error})"
                ) from error
            tensors.append(
                {
                    "name": name,
                    "shape": list(tensor.shape),
                    "dtype": dtype,
                    "content_hex": raw.hex(),
                }
            )
    envelope = {"schema": CHECKPOINT_ENVELOPE_SCHEMA, "tensors": tensors}
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return envelope, encoded


def measure_checkpoint_identity(shard_path: Path) -> dict[str, Any]:
    """Measure the running checkpoint save/load identity from a real checkpoint shard.

    Reads the shard's tensors via the trusted counter's own safe extraction primitives and
    computes the runtime identity as the sha256 of the canonical tensor envelope those raw
    bytes assemble into -- deliberately NOT the sha256 of the shard file's own bytes (see
    module docstring: that whole-file sha is provably unstable across saves of identical
    tensor content, and is the wrong object for this category). Nothing is invented: every
    bound byte traces to a tensor's real, on-disk storage bytes.
    """
    envelope, encoded = _read_checkpoint_tensor_envelope(Path(shard_path))
    byte_sha256 = hashlib.sha256(encoded).hexdigest()
    tensors = [
        {
            "name": row["name"],
            "shape": list(row["shape"]),
            "dtype": row["dtype"],
            "sha256": hashlib.sha256(bytes.fromhex(row["content_hex"])).hexdigest(),
        }
        for row in envelope["tensors"]
    ]
    return {
        "schema_version": CHECKPOINT_IDENTITY_SCHEMA,
        "result": "MEASURED",
        "checkpoint_format": CHECKPOINT_ENVELOPE_SCHEMA,
        "checkpoint_byte_sha256": byte_sha256,
        "checkpoint_bytes_hex": encoded.hex(),
        "tensors": tensors,
    }


def bind_checkpoint_identity(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Project a MEASURED checkpoint receipt into the manifest's ``checkpoint`` object.

    ``checkpoint.format`` and ``checkpoint.byte_sha256`` bind to the receipt's measured
    envelope identity -- the real, on-disk checkpoint shard's tensor content, content-addressed
    via the trusted counter's own safe reader -- NEVER a hand-typed or re-serialized
    substitute. ``checkpoint.tensors`` binds to the receipt's per-tensor identities. Any
    existing ``checkpoint.ancestry`` / ``checkpoint.recovery_state`` fields are preserved
    untouched -- this binding is additive, never a replacement of fields outside its scope.
    """
    if receipt.get("result") != "MEASURED":
        raise CheckpointSaveLoadIdentityMismatch(
            "receipt is not measured evidence; refusing to bind an unmeasured checkpoint "
            "save/load identity"
        )
    byte_sha256 = receipt.get("checkpoint_byte_sha256")
    if not isinstance(byte_sha256, str) or len(byte_sha256) != 64:
        raise CheckpointSaveLoadIdentityMismatch(
            f"receipt checkpoint_byte_sha256 is not a 64-hex digest: {byte_sha256!r}"
        )
    tensors = receipt.get("tensors")
    if not isinstance(tensors, list) or not tensors:
        raise CheckpointSaveLoadIdentityMismatch(
            "receipt tensors must be a nonempty list to bind checkpoint.tensors"
        )
    bound = dict(manifest)
    checkpoint = dict(bound.get("checkpoint") or {})
    checkpoint["format"] = receipt.get("checkpoint_format", CHECKPOINT_ENVELOPE_SCHEMA)
    checkpoint["byte_sha256"] = byte_sha256
    checkpoint["tensors"] = [dict(row) for row in tensors]
    bound["checkpoint"] = checkpoint
    return bound


def verify_checkpoint_identity_binding(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    shard_path: Path,
) -> None:
    """Fail closed the instant the manifest's checkpoint identity diverges from evidence.

    Re-derives everything checked from the actual checkpoint shard bytes on disk (never
    restates the manifest against itself, and never trusts the receipt alone):

    1. The shard is re-read via the trusted counter's own safe extraction path and
       re-encoded into the canonical tensor envelope. A shard that no longer parses, or whose
       tensors no longer content-address cleanly, fails here.
    2. ``receipt.checkpoint_byte_sha256`` and ``manifest.checkpoint.byte_sha256`` must both
       equal the freshly re-derived envelope sha256. A pointer bound to the raw checkpoint
       FILE's bytes (the wrong object for this category), or to any object other than the
       canonical per-tensor envelope, fails here.
    3. ``manifest.checkpoint.tensors`` and ``receipt.tensors`` must both equal the freshly
       re-derived per-tensor identities.
    4. ``manifest.checkpoint.format`` must equal the envelope schema.

    Raises ``CheckpointSaveLoadIdentityMismatch`` naming the exact field. Silent when every
    bound value matches the freshly measured evidence.
    """
    checkpoint = manifest.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise CheckpointSaveLoadIdentityMismatch("manifest has no checkpoint section to verify")

    path = Path(shard_path)
    real_envelope, real_encoded = _read_checkpoint_tensor_envelope(path)
    real_byte_sha256 = hashlib.sha256(real_encoded).hexdigest()
    real_tensors = [
        {
            "name": row["name"],
            "shape": list(row["shape"]),
            "dtype": row["dtype"],
            "sha256": hashlib.sha256(bytes.fromhex(row["content_hex"])).hexdigest(),
        }
        for row in real_envelope["tensors"]
    ]

    claimed_format = checkpoint.get("format")
    if claimed_format != CHECKPOINT_ENVELOPE_SCHEMA:
        raise CheckpointSaveLoadIdentityMismatch(
            f"manifest claims checkpoint.format={claimed_format!r} but the trusted counter's "
            f"reader always produces {CHECKPOINT_ENVELOPE_SCHEMA!r} for a real checkpoint shard"
        )

    claimed_receipt_sha256 = receipt.get("checkpoint_byte_sha256")
    if claimed_receipt_sha256 != real_byte_sha256:
        raise CheckpointSaveLoadIdentityMismatch(
            f"receipt claims checkpoint_byte_sha256={claimed_receipt_sha256!r} but the "
            f"checkpoint shard at {path} independently re-derives to {real_byte_sha256!r} "
            f"(sha drift, or the receipt was measured against a different shard)"
        )

    claimed = checkpoint.get("byte_sha256")
    if claimed != real_byte_sha256:
        raise CheckpointSaveLoadIdentityMismatch(
            f"manifest claims checkpoint.byte_sha256={claimed!r} but the checkpoint shard at "
            f"{path} -- read via the trusted counter's own safe metadata-only reader, the "
            f"same object load_checkpoint_artifacts verifies before any torch.load-driven "
            f"model/optimizer mutation -- content-addresses to {real_byte_sha256!r}; a "
            f"binding to the shard FILE's own raw bytes, or any other reconstruction, fails "
            f"here"
        )

    claimed_tensors = checkpoint.get("tensors")
    if claimed_tensors != real_tensors:
        raise CheckpointSaveLoadIdentityMismatch(
            f"manifest claims checkpoint.tensors={claimed_tensors!r} but the checkpoint shard "
            f"at {path} independently re-derives to tensors={real_tensors!r}"
        )
    if receipt.get("tensors") != real_tensors:
        raise CheckpointSaveLoadIdentityMismatch(
            f"receipt claims tensors={receipt.get('tensors')!r} but the checkpoint shard at "
            f"{path} independently re-derives to tensors={real_tensors!r}"
        )
