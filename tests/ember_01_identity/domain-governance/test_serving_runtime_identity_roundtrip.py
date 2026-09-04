# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 (serving_runtime): a serving executable's identity round-trips its consumer,
fail-closed.

Not a narrative assertion: the positive case builds a REAL signed OWNED_ADMITTED identity
manifest (the same ``admitted_manifest`` machinery the production validator suite uses) and
runs the actual production consumer, ``validate_identity.validate_manifest``. That consumer
resolves ``backend.executable_sha256`` through the generic artifact-bundle content-address
mechanism every OWNED_ADMITTED category's own source bytes are supplied through
(validate_identity.py ``required_artifacts["backend.executable"]`` ~line 1085, checked
against a fresh ``hashlib.sha256(bytes.fromhex(artifact_bundle["artifacts"]
["backend.executable"]["content_hex"]))`` at ~line 1108-1122 --
``admission.artifact_hash_mismatch`` on divergence) AND requires
``backend.process_identity.executable_sha256 == backend.executable_sha256`` (~line
1009-1018, ``admission.backend_process_executable_mismatch``). The real, external runtime
consumer this binding measures its identity from is
``scripts/ember_restart/development_cli_seat.resolve_development_seat`` -- the trusted
owned-seat resolver that grants an OWNED_DEVELOPMENT serving seat only after re-hashing
``src/ember/infrastructure/tools/ember-restart-3b/serve_owned_openai.py`` (the file that actually answers
``/v1/models`` and ``/v1/chat/completions``) via its own streaming ``_sha256`` and
requiring the fresh digest match the declared runtime-bundle binding. This binding measures
that same real, on-disk file via the resolver's own hasher -- never a hand-typed
placeholder, never a reimplementation.

Fail-closed negatives drive the manifest's serving executable identity out of agreement
with the consumer's own identity and assert the REAL validator flags it RED:

1. the artifact-bundle's supplied bytes for ``backend.executable`` are a hand-typed
   placeholder (the WRONG object for this category -- literally the shared test suite's own
   ``ARTIFACT_BYTES["backend.executable"]`` constant) instead of the real serving
   entrypoint's measured bytes -> admission.artifact_hash_mismatch
2. ``backend.process_identity.executable_sha256`` diverges from ``backend.executable_sha256``
   -> admission.backend_process_executable_mismatch

A parallel block exercises the wiring module
(``serving_runtime_identity_binding.verify_server_identity_binding``) directly, proving the
same invariant re-derives and fails closed independent of the full admission bundle --
including that binding to a placeholder (rather than the real entrypoint's bytes) is
rejected, that a receipt measured against a different file is rejected, and that a
process_identity divergence is caught even outside the full admission gate.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
MOVED_SCRIPT_PATH = ROOT / "src" / "ember" / "governance" / "scripts" / "ember_01_identity"
TEST_DIR = Path(__file__).parent
for _extra in (SCRIPT_DIR, MOVED_SCRIPT_PATH, TEST_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import validate_identity as identity_validator  # noqa: E402
from validate_identity import validate_manifest, IdentityValidationError  # noqa: E402

# Reuse the production-grade signed-manifest builders from the validator's own suite so the
# positive round-trip is exercised against real evidence, not a hand-mocked shape.
import test_validate_identity as tvi  # noqa: E402
from test_validate_identity import (  # noqa: E402
    admitted_manifest,
    artifact_authority,
    rebind_receipt,
    ARTIFACT_BYTES,
    VERIFIER_BYTES,
    TEST_PUBLIC_KEY_HEX,
)

from serving_runtime_identity_binding import (  # noqa: E402
    ServingRuntimeIdentityMismatch,
    SERVER_ENTRYPOINT_RELATIVE_PATH,
    artifact_bundle_entry,
    bind_server_identity,
    measure_server_executable_identity,
    verify_server_identity_binding,
)

SERVER_PATH = ROOT / SERVER_ENTRYPOINT_RELATIVE_PATH


def _pin_verifier(tmpdir: Path) -> Path:
    """Replicate test_validate_identity's autouse verifier pinning for unittest."""
    registry = tmpdir / "trusted-verifiers-v1.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "ember-trusted-verifier-registry-v1",
                "verifiers": [
                    {
                        "verifier_sha256": hashlib.sha256(VERIFIER_BYTES).hexdigest(),
                        "public_key_ed25519": TEST_PUBLIC_KEY_HEX,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry


def _error_codes(payload, **kwargs) -> set[str]:
    try:
        validate_manifest(payload, **kwargs)
    except IdentityValidationError as error:
        return {finding["code"] for finding in error.findings}
    return set()


def _admitted_with_real_server_identity() -> tuple[dict, dict[str, dict], dict, dict]:
    """Build a real OWNED_ADMITTED manifest with backend.executable_sha256 honestly bound
    to the real, on-disk serving entrypoint's measured identity -- process_identity and its
    signed receipt kept consistent, exactly as the admission gate requires."""
    payload, receipts = admitted_manifest()
    bundle = artifact_authority(payload)

    receipt = measure_server_executable_identity(SERVER_PATH)
    payload = bind_server_identity(payload, receipt)
    bundle["artifact_bundle"]["artifacts"]["backend.executable"] = artifact_bundle_entry(
        receipt
    )

    new_process_identity = dict(payload["backend"]["process_identity"])
    new_process_identity["executable_sha256"] = receipt["executable_sha256"]
    payload["backend"]["process_identity"] = new_process_identity
    old_digest = payload["backend"]["process_receipt_sha256"]
    new_digest = rebind_receipt(
        payload, receipts, old_digest, process_identity=new_process_identity
    )
    payload["backend"]["process_receipt_sha256"] = new_digest

    return payload, receipts, bundle, receipt


class ServingRuntimeIdentityRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        registry = _pin_verifier(Path(self._tmp.name))
        self._orig_registry = identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH
        self._orig_floor = identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR
        identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH = registry
        identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR = 1
        cache = getattr(identity_validator, "_pinned_verifier_entries", None)
        if cache is not None and hasattr(cache, "cache_clear"):
            cache.cache_clear()

    def tearDown(self) -> None:
        identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH = self._orig_registry
        identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR = self._orig_floor
        cache = getattr(identity_validator, "_pinned_verifier_entries", None)
        if cache is not None and hasattr(cache, "cache_clear"):
            cache.cache_clear()
        self._tmp.cleanup()

    # ---- positive round-trip through the REAL consumer ----------------------------
    def test_owned_server_identity_round_trips(self) -> None:
        payload, receipts, bundle, receipt = _admitted_with_real_server_identity()
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(
            payload["backend"]["executable_sha256"], receipt["executable_sha256"]
        )
        self.assertEqual(
            payload["backend"]["process_identity"]["executable_sha256"],
            receipt["executable_sha256"],
        )

        result = validate_manifest(payload, receipt_bundle=receipts, **bundle)
        self.assertEqual(result, payload)

    # ---- fail-closed negatives at the REAL consumer --------------------------------
    def test_artifact_bundle_placeholder_bytes_flagged(self) -> None:
        """The artifact-bundle's supplied bytes for backend.executable are a hand-typed
        placeholder (the shared fixture's own ARTIFACT_BYTES constant, the WRONG object for
        this category) instead of the real serving entrypoint's measured bytes."""
        payload, receipts, bundle, receipt = _admitted_with_real_server_identity()

        placeholder = ARTIFACT_BYTES["backend.executable"]
        placeholder_sha256 = hashlib.sha256(placeholder).hexdigest()
        self.assertNotEqual(placeholder_sha256, receipt["executable_sha256"])
        bundle["artifact_bundle"]["artifacts"]["backend.executable"] = {
            "sha256": placeholder_sha256,
            "content_hex": placeholder.hex(),
        }

        codes = _error_codes(payload, receipt_bundle=receipts, **bundle)
        self.assertIn("admission.artifact_hash_mismatch", codes)

    def test_process_identity_executable_divergence_flagged(self) -> None:
        payload, receipts, bundle, receipt = _admitted_with_real_server_identity()
        payload = copy.deepcopy(payload)
        payload["backend"]["process_identity"]["executable_sha256"] = "1" * 64

        codes = _error_codes(payload, receipt_bundle=receipts, **bundle)
        self.assertIn("admission.backend_process_executable_mismatch", codes)

    # ---- wiring-module invariants (independent re-derivation) -----------------------
    def test_binding_module_round_trips_and_fails_closed(self) -> None:
        receipt = measure_server_executable_identity(SERVER_PATH)
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(
            receipt["executable_relative_path"], SERVER_ENTRYPOINT_RELATIVE_PATH
        )
        self.assertEqual(
            hashlib.sha256(bytes.fromhex(receipt["executable_bytes_hex"])).hexdigest(),
            receipt["executable_sha256"],
        )

        manifest: dict = {
            "backend": {
                "protocol": "loopback-http",
                "device": "cuda",
                "runtime_dependencies": [],
                "resource_lease_id": "fixture-lease",
            }
        }
        bound = bind_server_identity(manifest, receipt)
        self.assertEqual(bound["backend"]["executable_sha256"], receipt["executable_sha256"])
        # Fields outside this binding's scope are preserved, never clobbered.
        self.assertEqual(bound["backend"]["protocol"], "loopback-http")
        self.assertEqual(bound["backend"]["device"], "cuda")

        # Silent on the honestly-bound manifest.
        verify_server_identity_binding(bound, receipt, server_path=SERVER_PATH)

        entry = artifact_bundle_entry(receipt)
        self.assertEqual(entry["sha256"], receipt["executable_sha256"])
        self.assertEqual(
            hashlib.sha256(bytes.fromhex(entry["content_hex"])).hexdigest(),
            receipt["executable_sha256"],
        )

        # Pointer bound to a hand-typed placeholder (the wrong object for this category)
        # -> fail closed naming the field.
        tampered = copy.deepcopy(bound)
        placeholder_sha256 = hashlib.sha256(
            ARTIFACT_BYTES["backend.executable"]
        ).hexdigest()
        tampered["backend"]["executable_sha256"] = placeholder_sha256
        with self.assertRaises(ServingRuntimeIdentityMismatch) as ctx:
            verify_server_identity_binding(tampered, receipt, server_path=SERVER_PATH)
        self.assertIn("backend.executable_sha256", str(ctx.exception))

        # receipt.executable_sha256 diverging from a fresh re-derivation (measured against
        # a DIFFERENT real file) -> fail closed.
        other_path = next(
            candidate
            for candidate in (
                ROOT / "src" / "ember" / "runtime" / "infer.py",
            )
            if candidate.is_file()
        )
        other_receipt = measure_server_executable_identity(other_path)
        self.assertNotEqual(
            other_receipt["executable_sha256"], receipt["executable_sha256"]
        )
        with self.assertRaises(ServingRuntimeIdentityMismatch):
            verify_server_identity_binding(bound, other_receipt, server_path=SERVER_PATH)

        # backend.process_identity.executable_sha256 diverging from the bound/measured
        # identity -> fail closed, mirroring admission.backend_process_executable_mismatch.
        with_process_identity = copy.deepcopy(bound)
        with_process_identity["backend"]["process_identity"] = {
            "pid": 1,
            "start_time_utc": "2026-07-12T00:00:00Z",
            "executable_sha256": "2" * 64,
            "command_sha256": "3" * 64,
            "nonce": "fixture-process",
        }
        with self.assertRaises(ServingRuntimeIdentityMismatch) as ctx:
            verify_server_identity_binding(
                with_process_identity, receipt, server_path=SERVER_PATH
            )
        self.assertIn("process_identity.executable_sha256", str(ctx.exception))

        # A consistent process_identity (matching the bound identity) is silent.
        consistent_process_identity = copy.deepcopy(bound)
        consistent_process_identity["backend"]["process_identity"] = {
            "pid": 1,
            "start_time_utc": "2026-07-12T00:00:00Z",
            "executable_sha256": receipt["executable_sha256"],
            "command_sha256": "3" * 64,
            "nonce": "fixture-process",
        }
        verify_server_identity_binding(
            consistent_process_identity, receipt, server_path=SERVER_PATH
        )

        # A non-empty but non-MEASURED receipt cannot be bound.
        with self.assertRaises(ServingRuntimeIdentityMismatch):
            bind_server_identity(manifest, {**receipt, "result": "PENDING"})

        # A missing serving executable file fails closed at measurement time.
        with self.assertRaises(ServingRuntimeIdentityMismatch):
            measure_server_executable_identity(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "does-not-exist.py")

        # artifact_bundle_entry refuses a receipt lacking the raw bytes it needs.
        with self.assertRaises(ServingRuntimeIdentityMismatch):
            artifact_bundle_entry({"executable_sha256": receipt["executable_sha256"]})


if __name__ == "__main__":
    unittest.main()
