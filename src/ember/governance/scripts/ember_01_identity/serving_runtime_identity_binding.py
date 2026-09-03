#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind the serving runtime's executable identity into the identity manifest, fail-closed.

cond3 increment (serving_runtime category): the identity manifest's ``backend`` object
(``backend.executable_sha256``) must be the identity of the real, on-disk serving
executable the trusted owned-seat resolver actually admits before granting a serving
seat -- never a hand-typed placeholder standing in for "the executable" (the census's own
stated requirement for this category: "bind server identity to verified checkpoint and
executable bytes").

CRITICAL -- bind the RUNTIME object the real consumers check, not an invented placeholder:

- The real runtime serving consumer is
  ``scripts/ember_restart/development_cli_seat.resolve_development_seat``. It resolves an
  OWNED_DEVELOPMENT serving seat only after re-hashing every file in a closed runtime-bundle
  file set (``RUNTIME_FILES``, development_cli_seat.py lines 48-64) via its own streaming
  ``_sha256`` (lines 114-119, ``open("rb")`` + 1MiB chunks) and requiring the fresh digest
  equal BOTH the runtime-bundle index's declared hash for that path AND the development
  manifest's own ``server.sha256`` binding (lines 260-266:
  ``if resolved[field] != resolved_runtime[relative]: raise ValueError(...)``). The exact
  file this resolver treats as "the server" is
  ``src/ember/infrastructure/tools/ember-restart-3b/serve_owned_openai.py`` -- the same script whose
  ``LoadedOwnedRuntime.from_paths`` (serve_owned_openai.py) answers ``/v1/models`` and
  ``/v1/chat/completions`` and whose own ``server_source_sha256 = sha(Path(__file__))``
  (serve_owned_openai.py line 665, reusing ``infer.sha`` -- the identical streaming
  sha256 algorithm) is served back to every client as part of the owned identity payload.
  A serving seat the resolver would actually grant is provably tied, byte-for-byte, to
  this one file.
- ``validate_identity``'s own OWNED_ADMITTED admission gate resolves
  ``backend.executable_sha256`` through the exact same generic content-address mechanism
  every other artifact-bound category uses: ``required_artifacts["backend.executable"]``
  (validate_identity.py line 1085) is checked against
  ``hashlib.sha256(bytes.fromhex(artifact_bundle["artifacts"]["backend.executable"]["content_hex"]))``
  (validate_identity.py ~line 1108-1122, ``admission.artifact_hash_mismatch`` /
  ``admission.artifact_missing``) -- a fresh re-derivation from caller-supplied bytes, never
  a restatement of the manifest against itself. The admission gate additionally requires
  ``backend.process_identity.executable_sha256 == backend.executable_sha256``
  (validate_identity.py ~line 1009-1018, ``admission.backend_process_executable_mismatch``)
  and resolves ``backend.process_receipt_sha256`` through ``_resolve_admission_receipt``
  with ``expected_claims={"process_identity": ..., ...}`` -- so a serving executable
  identity that only satisfies the artifact-bundle check while diverging from
  ``process_identity`` still fails closed.

CRITICAL -- the WRONG object for this category, made concrete by the shared test suite's
own fixture (``tests/ember_01_identity/domain-governance/test_validate_identity.py``
``ARTIFACT_BYTES["backend.executable"] = b"owned backend executable"``): a hand-typed
placeholder byte string. It is sound-in-shape (a real sha256 of real bytes) yet is the
identity of nothing any client is ever served by -- ``development_cli_seat.py``'s own
``_require_file_hash`` (which this module's ``verify_server_identity_binding`` re-invokes)
would reject it the instant it is checked against ``src/ember/infrastructure/tools/ember-restart-3b/
serve_owned_openai.py``'s actual on-disk bytes, because a placeholder can never equal a
real file's content-address except by construction.

So: ``bind_server_identity`` projects, and ``verify_server_identity_binding`` re-derives,
the same raw-bytes sha256 of the serving entrypoint file that
``development_cli_seat.resolve_development_seat`` fail-closed gates and that
``serve_owned_openai.py`` itself serves back as ``server_source_sha256`` -- via the trusted
resolver's own hasher (``development_cli_seat._sha256``), imported here, never
re-implemented. A hand-typed placeholder, or a hash of any file other than the real serving
entrypoint, can never be laundered into ``backend.executable_sha256``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

_DEV_SEAT_MODULE_DIR = (
    Path(__file__).resolve().parents[5]
    / "src" / "ember" / "governance" / "scripts" / "ember_restart"
)
if str(_DEV_SEAT_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_DEV_SEAT_MODULE_DIR))

# The REAL runtime serving-seat consumer's own hasher. Imported directly so this binding is
# provably against the same bytes ``resolve_development_seat`` fail-closed gates before
# granting a serving seat -- never a re-implementation that could drift from it.
from development_cli_seat import _sha256 as _consumer_sha256  # noqa: E402

SERVING_RUNTIME_IDENTITY_SCHEMA = "ember-serving-runtime-identity-receipt-v1"
_REPOSITORY_PATH = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
SERVER_ENTRYPOINT_RELATIVE_PATH = next(
    relative
    for relative in (
        "src/ember/infrastructure/tools/ember-restart-3b/serve_owned_openai.py",
        "tools/ember-restart-3b/serve_owned_openai.py",
    )
    if (_REPOSITORY_PATH / relative).is_file()
)


class ServingRuntimeIdentityMismatch(ValueError):
    """A manifest's claimed serving runtime executable identity diverges from measured evidence."""


def measure_server_executable_identity(server_path: Path) -> dict[str, Any]:
    """Measure the running serving runtime's executable identity from the real entrypoint file.

    Reads the real, on-disk serving entrypoint's raw bytes (for the artifact-bundle
    ``content_hex`` validate_identity's admission gate re-hashes) and computes the runtime
    identity via the trusted owned-seat resolver's own streaming hasher
    (``development_cli_seat._sha256``) -- never a re-implementation, and never the parsed/
    re-serialized form of anything (this is a flat source file: its own bytes ARE the
    object every real consumer content-addresses). Nothing is invented: every bound byte
    traces to the real file's own bytes.
    """
    path = Path(server_path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ServingRuntimeIdentityMismatch(
            f"serving runtime executable at {path} could not be read to content-address "
            f"it ({error})"
        ) from error
    executable_sha256 = _consumer_sha256(path)
    return {
        "schema_version": SERVING_RUNTIME_IDENTITY_SCHEMA,
        "result": "MEASURED",
        "executable_relative_path": SERVER_ENTRYPOINT_RELATIVE_PATH,
        "executable_sha256": executable_sha256,
        "executable_bytes_hex": raw.hex(),
    }


def bind_server_identity(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Project a MEASURED serving-executable receipt into ``manifest.backend.executable_sha256``.

    Binds to the receipt's measured ``executable_sha256`` -- the real, on-disk serving
    entrypoint's identity, content-addressed via the trusted owned-seat resolver's own
    hasher -- NEVER a hand-typed placeholder. Any existing ``backend`` fields
    (``process_identity``, ``protocol``, ``device``, ``runtime_dependencies``,
    ``resource_lease_id``, ``process_receipt_sha256``) are preserved untouched -- this
    binding is additive, never a replacement of fields outside its scope.
    """
    if receipt.get("result") != "MEASURED":
        raise ServingRuntimeIdentityMismatch(
            "receipt is not measured evidence; refusing to bind an unmeasured serving "
            "runtime executable identity"
        )
    executable_sha256 = receipt.get("executable_sha256")
    if not isinstance(executable_sha256, str) or len(executable_sha256) != 64:
        raise ServingRuntimeIdentityMismatch(
            f"receipt executable_sha256 is not a 64-hex digest: {executable_sha256!r}"
        )
    bound = dict(manifest)
    backend = dict(bound.get("backend") or {})
    backend["executable_sha256"] = executable_sha256
    bound["backend"] = backend
    return bound


def artifact_bundle_entry(receipt: Mapping[str, Any]) -> dict[str, str]:
    """Return the ``artifact_bundle["artifacts"]["backend.executable"]`` entry for a receipt.

    Same generic content-addressed artifact slot every other OWNED_ADMITTED category's own
    source/executable bytes are supplied through
    (validate_identity.py's ``required_artifacts["backend.executable"]`` check). Requires
    the REAL on-disk executable bytes measured by ``measure_server_executable_identity`` so
    the admission gate's fresh ``hashlib.sha256(bytes.fromhex(content_hex))``
    re-derivation matches ``backend.executable_sha256`` against the true served file, never
    an invented placeholder.
    """
    executable_sha256 = receipt.get("executable_sha256")
    content_hex = receipt.get("executable_bytes_hex")
    if not isinstance(executable_sha256, str) or not isinstance(content_hex, str):
        raise ServingRuntimeIdentityMismatch(
            "receipt lacks executable_sha256/executable_bytes_hex to build an "
            "artifact_bundle entry"
        )
    return {"sha256": executable_sha256, "content_hex": content_hex}


def verify_server_identity_binding(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    server_path: Path,
) -> None:
    """Fail closed the instant the manifest's serving executable identity diverges from evidence.

    Re-derives everything checked from the actual serving entrypoint bytes on disk (never
    restates the manifest against itself, and never trusts the receipt alone):

    1. The entrypoint file is re-read and re-hashed via the trusted owned-seat resolver's
       own streaming hasher (``development_cli_seat._sha256``) -- the same function
       ``resolve_development_seat`` fail-closed gates before granting a serving seat. A
       file that no longer exists or is unreadable fails here.
    2. ``receipt.executable_sha256`` and ``manifest.backend.executable_sha256`` must both
       equal the freshly re-derived digest. A pointer bound to a hand-typed placeholder
       (the wrong object for this category, per the shared fixture's own
       ``ARTIFACT_BYTES["backend.executable"]``), or to a hash of any file other than the
       real serving entrypoint, fails here.
    3. If ``manifest.backend.process_identity.executable_sha256`` is present, it must also
       equal the freshly re-derived digest -- mirrors the real admission gate's own
       ``admission.backend_process_executable_mismatch`` invariant
       (validate_identity.py: "running process executable is not the artifact-bound
       backend").

    Raises ``ServingRuntimeIdentityMismatch`` naming the exact field. Silent when every
    bound value matches the freshly measured evidence.
    """
    backend = manifest.get("backend")
    if not isinstance(backend, Mapping):
        raise ServingRuntimeIdentityMismatch("manifest has no backend section to verify")

    path = Path(server_path)
    try:
        real_sha256 = _consumer_sha256(path)
    except OSError as error:
        raise ServingRuntimeIdentityMismatch(
            f"serving runtime executable at {path} could not be read to re-derive its "
            f"identity ({error})"
        ) from error

    claimed_receipt_sha256 = receipt.get("executable_sha256")
    if claimed_receipt_sha256 != real_sha256:
        raise ServingRuntimeIdentityMismatch(
            f"receipt claims executable_sha256={claimed_receipt_sha256!r} but the serving "
            f"runtime executable at {path} independently re-derives to {real_sha256!r} "
            f"(sha drift, or the receipt was measured against a different file)"
        )

    claimed = backend.get("executable_sha256")
    if claimed != real_sha256:
        raise ServingRuntimeIdentityMismatch(
            f"manifest claims backend.executable_sha256={claimed!r} but the serving "
            f"runtime executable at {path} -- read via the trusted owned-seat resolver's "
            f"own hasher (scripts/ember_restart/development_cli_seat._sha256), the same "
            f"object resolve_development_seat fail-closed gates before granting a serving "
            f"seat, and the same object serve_owned_openai.py itself serves back as "
            f"server_source_sha256 -- content-addresses to {real_sha256!r}; a binding to a "
            f"hand-typed placeholder or any other reconstruction fails here"
        )

    process_identity = backend.get("process_identity")
    if isinstance(process_identity, Mapping):
        claimed_process_sha256 = process_identity.get("executable_sha256")
        if claimed_process_sha256 is not None and claimed_process_sha256 != real_sha256:
            raise ServingRuntimeIdentityMismatch(
                f"manifest claims backend.process_identity.executable_sha256="
                f"{claimed_process_sha256!r} but the serving runtime executable at {path} "
                f"independently re-derives to {real_sha256!r} -- mirrors the real "
                f"admission gate's admission.backend_process_executable_mismatch invariant"
            )
