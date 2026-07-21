#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind a RECEIPT's runtime identity into the identity manifest, fail-closed.

cond3 increment (receipt_identity category): every ``*receipt_sha256`` pointer the
manifest carries -- ``evaluation.receipt_sha256``, ``backend.process_receipt_sha256``,
``training.stopping_rule.receipt_sha256``,
``data.accepted_input.forwarding_receipt_sha256``, and the parameter / mechanism /
capability / native-modality evidence-receipt digests -- is a RECEIPT IDENTITY: the key
by which the real runtime receipt consumer resolves and re-verifies a receipt out of the
receipt bundle. This module binds that identity to the object the consumer actually keys
on, and its verifier re-derives (never restates) the consumer's own invariant.

CRITICAL -- bind the RUNTIME object, not the on-disk receipt file (same hard-won lesson as
the tokenizer binding, where the raw-file sha was the WRONG object):

- The real runtime receipt consumer is
  ``scripts/ember_01_identity/validate_identity._resolve_admission_receipt``
  (validate_identity.py ~line 433). Given a manifest digest it does
  ``receipt = receipt_bundle.get(digest)`` and then, at validate_identity.py line 454,
  fails closed with ``admission.receipt_hash_mismatch`` unless
  ``_receipt_sha256(receipt) == digest``. Every manifest receipt pointer is resolved
  through this one path (evaluation.receipt_sha256 at ~line 938, backend
  process_receipt_sha256 at ~line 1021, forwarding_receipt_sha256 at ~line 1262,
  stopping_rule.receipt_sha256 at ~line 1461, parameter/mechanism/capability/native
  receipts throughout).
- ``validate_identity._receipt_sha256`` (validate_identity.py line 351-355) is
  ``sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False))`` -- the sha of the receipt's CANONICAL, in-memory compact-JSON
  serialization. That is the runtime object. It is NOT the sha256 of the receipt file's
  on-disk bytes: a receipt stored pretty-printed (``indent=2``), with a different key
  order, trailing newline, or non-canonical spacing hashes to a DIFFERENT value than its
  canonical form. A manifest bound to the file-bytes sha would make the runtime
  consumer's ``_receipt_sha256(receipt) != digest`` check FAIL -- the binding would be
  sound-in-shape yet point at the wrong object.

So: the identity ``bind_receipt_identity`` projects, and ``verify_receipt_identity_binding``
re-derives, is the consumer's own ``_receipt_sha256`` of the parsed receipt object -- the
identical function the real consumer calls, imported here, never re-implemented. The
raw-file sha of the receipt as stored on disk is recorded as provenance in the evidence
record (and re-checked by ``verify_`` to prove the on-disk bytes parse to the very object
bound), but it is deliberately NOT what the manifest field carries.

``bind_receipt_identity`` refuses to project anything but the canonically-derived
identity of an actual receipt object (a hand-typed or borrowed digest can never be
laundered into a receipt pointer). ``verify_receipt_identity_binding`` fails closed --
naming the exact field -- the instant the manifest's receipt pointer diverges from the
canonical identity the runtime consumer would compute, or the on-disk receipt bytes no
longer parse to the bound object.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

_SCRIPT_DIR = Path(__file__).resolve().parent  # ember/scripts/ember_01_identity
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# The REAL runtime receipt consumer. We import its canonical-identity function directly so
# the binding is provably against the same object the consumer keys receipts on -- never a
# re-implementation that could drift from it.
import validate_identity  # noqa: E402
from validate_identity import _receipt_sha256  # noqa: E402

RECEIPT_IDENTITY_SCHEMA = "ember-receipt-identity-receipt-v1"


class ReceiptIdentityMismatch(ValueError):
    """A manifest's claimed receipt identity diverges from measured evidence."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_receipt_identity(receipt: Mapping[str, Any]) -> str:
    """Return the runtime receipt identity -- the consumer's own ``_receipt_sha256``.

    Delegates to ``validate_identity._receipt_sha256`` (the exact function
    ``_resolve_admission_receipt`` calls at validate_identity.py:454 to verify every
    receipt pointer), so the identity bound here is by construction the identity the
    runtime consumer keys the receipt bundle on -- not a re-implementation, not the
    on-disk file sha.
    """
    if not isinstance(receipt, Mapping):
        raise ReceiptIdentityMismatch(
            f"receipt must be a JSON object to content-address; got {type(receipt).__name__}"
        )
    return _receipt_sha256(receipt)


def _get(payload: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _set(manifest: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Return a shallow-copied manifest with ``path`` rebound to ``value``."""
    parts = path.split(".")
    root = dict(manifest)
    cursor = root
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, Mapping):
            raise ReceiptIdentityMismatch(
                f"manifest has no object at {part!r} to bind receipt identity path {path!r}"
            )
        child = dict(child)
        cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value
    return root


def measure_receipt_identity(receipt_file_path: Path) -> dict[str, Any]:
    """Measure a receipt's runtime identity from its on-disk bytes.

    Reads and parses the receipt file, computes the runtime identity via the consumer's
    own ``_receipt_sha256`` of the PARSED object, and records the raw-file sha as
    provenance. Nothing is invented: the bound identity traces to the parsed object, the
    provenance sha to the exact bytes on disk.
    """
    path = Path(receipt_file_path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ReceiptIdentityMismatch(
            f"receipt artifact at {path} could not be read to content-address it ({error})"
        ) from error
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiptIdentityMismatch(
            f"receipt bytes at {path} are not a JSON receipt object ({error})"
        ) from error
    identity = canonical_receipt_identity(receipt)
    return {
        "schema_version": RECEIPT_IDENTITY_SCHEMA,
        "result": "MEASURED",
        "canonical_identity_sha256": identity,
        "provenance_file_sha256": hashlib.sha256(raw).hexdigest(),
    }


def bind_receipt_identity(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    field_path: str,
) -> dict[str, Any]:
    """Project a receipt's runtime identity into the named manifest receipt pointer.

    The digest is always the consumer's ``_receipt_sha256`` of the actual receipt object
    (never taken from the manifest or hand-typed), so a borrowed or file-bytes sha cannot
    be projected in. ``field_path`` is the dotted manifest path of the receipt pointer to
    rebind (e.g. ``evaluation.receipt_sha256``). Returns a new manifest.
    """
    if not isinstance(receipt, Mapping):
        raise ReceiptIdentityMismatch(
            "receipt is not a JSON object; refusing to bind a non-receipt as receipt identity"
        )
    if not isinstance(field_path, str) or not field_path.strip():
        raise ReceiptIdentityMismatch(
            f"field_path must be a non-empty dotted manifest path; got {field_path!r}"
        )
    present, _ = _get(manifest, field_path)
    if not present:
        raise ReceiptIdentityMismatch(
            f"manifest has no receipt pointer at {field_path!r} to bind"
        )
    return _set(dict(manifest), field_path, canonical_receipt_identity(receipt))


def verify_receipt_identity_binding(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    field_path: str,
    receipt_file_path: Path | None = None,
    provenance_file_sha256: str | None = None,
) -> None:
    """Fail closed the instant a manifest receipt pointer diverges from its runtime identity.

    Re-derives every checked value from the actual receipt object via the real consumer
    (never restates the manifest against itself):

    1. ``manifest[field_path]`` must equal ``_receipt_sha256(receipt)`` -- the identity the
       runtime consumer (``_resolve_admission_receipt``, validate_identity.py:454) computes
       and keys the receipt bundle on. A pointer bound to the on-disk file sha, or to any
       object other than this receipt's canonical serialization, fails here (mirrors the
       consumer's ``admission.receipt_hash_mismatch``).
    2. If ``receipt_file_path`` is supplied, the on-disk bytes are re-hashed against
       ``provenance_file_sha256`` (when given) AND re-parsed; the parsed object must equal
       the receipt being bound -- proving the bound identity was derived from the very
       bytes on disk, and that binding to the file-bytes sha (the wrong object) is NOT what
       the manifest carries.

    Raises ``ReceiptIdentityMismatch`` naming the exact field. Silent when the bound
    pointer matches the freshly re-derived runtime identity.
    """
    if not isinstance(receipt, Mapping):
        raise ReceiptIdentityMismatch(
            f"receipt for {field_path!r} is not a JSON object to verify against"
        )
    present, claimed = _get(manifest, field_path)
    if not present:
        raise ReceiptIdentityMismatch(
            f"manifest has no receipt pointer at {field_path!r} to verify"
        )

    real_identity = _receipt_sha256(receipt)
    if claimed != real_identity:
        raise ReceiptIdentityMismatch(
            f"manifest claims {field_path}={claimed!r} but the receipt's canonical runtime "
            f"identity (validate_identity._receipt_sha256, the value the receipt consumer "
            f"keys the bundle on) is {real_identity!r}; a raw-file sha or any non-canonical "
            f"object fails here"
        )

    if receipt_file_path is not None:
        path = Path(receipt_file_path)
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ReceiptIdentityMismatch(
                f"receipt artifact at {path} could not be read to re-derive its provenance "
                f"for {field_path!r} ({error})"
            ) from error
        file_sha = hashlib.sha256(raw).hexdigest()
        if provenance_file_sha256 is not None and file_sha != provenance_file_sha256:
            raise ReceiptIdentityMismatch(
                f"receipt evidence claims provenance_file_sha256={provenance_file_sha256!r} "
                f"but the bytes on disk at {path} hash to {file_sha!r} (sha drift)"
            )
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReceiptIdentityMismatch(
                f"receipt bytes at {path} for {field_path!r} do not parse as a receipt "
                f"object ({error})"
            ) from error
        if parsed != dict(receipt):
            raise ReceiptIdentityMismatch(
                f"receipt bytes on disk at {path} parse to a different object than the one "
                f"bound at {field_path!r}; the bound runtime identity was not derived from "
                f"these bytes"
            )
