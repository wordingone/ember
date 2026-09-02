# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 (architecture_config): the model's architecture identity round-trips its
consumer, fail-closed.

Not a narrative assertion: the positive case builds a REAL signed OWNED_ADMITTED identity
manifest (the same ``admitted_manifest`` machinery the production validator suite uses)
and runs the actual production consumer, ``validate_identity.validate_manifest``. That
consumer resolves ``architecture.sha256`` through its OWNED_ADMITTED artifact-bundle gate
(validate_identity.py ~line 1094-1120): the manifest's ``architecture.sha256`` must equal
``sha256`` of the ``content_hex`` bytes the admission bundle carries under artifact id
``"architecture"`` -- ``admission.artifact_hash_mismatch`` / ``admission.artifact_missing``
otherwise. That same raw-bytes identity is what the trusted, isolated
``parameter_counter.execute_counter`` (``tools/ember-restart-3b/parameter_counter.py``)
reads and checks a checkpoint manifest's ``model_config_sha256`` against (line 802), after
requiring the config's own ``ARCHITECTURE_REVISION`` and a structurally valid
``_model_shape`` (hidden_size / layers / attention_heads / vocab_size / tied embeddings /
sparse routing declarations).

Fail-closed negatives drive the manifest's architecture identity out of agreement with the
consumer's own identity and assert the REAL validator flags it RED:

1. architecture pointer bound to a CANONICALIZED RE-SERIALIZATION of the parsed config
   (an "inferred" identity -- this category's named failure mode, the census's own words:
   "bind canonical architecture bytes and reject inferred identity") instead of the raw
   bytes on disk -> admission.artifact_hash_mismatch
2. architecture pointer resolves to nothing in the artifact bundle ->
   admission.artifact_missing

A parallel block exercises the wiring module
(``architecture_config_identity_binding.verify_architecture_identity_binding``) directly,
proving the same invariant re-derives and fails closed independent of the full admission
bundle -- including that binding to a re-serialized reconstruction of the config (rather
than its literal artifact bytes) is rejected, that a config declaring the wrong
architecture revision or an invalid decoder shape is rejected at measurement time, and that
sha drift on the config file is caught on re-verification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
COUNTER_DIR = ROOT / "tools" / "ember-restart-3b"
TEST_DIR = Path(__file__).parent
for _extra in (SCRIPT_DIR, COUNTER_DIR, TEST_DIR):
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
    VERIFIER_BYTES,
    TEST_PUBLIC_KEY_HEX,
)

from parameter_counter import ARCHITECTURE_REVISION, EXPERT_NAMES  # noqa: E402

from architecture_config_identity_binding import (  # noqa: E402
    ArchitectureIdentityMismatch,
    bind_architecture_identity,
    measure_architecture_identity,
    verify_architecture_identity_binding,
)

SOURCE = "tools/ember-restart-3b/parameter_counter.py:model_config"


def _valid_config(*, hidden_size: int = 256, layers: int = 2, attention_heads: int = 4, vocab_size: int = 1024) -> dict:
    """A structurally valid model config -- satisfies parameter_counter._model_shape."""
    return {
        "architecture_revision": ARCHITECTURE_REVISION,
        "model": {
            "hidden_size": hidden_size,
            "layers": layers,
            "attention_heads": attention_heads,
            "vocab_size": vocab_size,
            "tied_embeddings": True,
            "expert_routing": {"expert_names": list(EXPERT_NAMES)},
            "image_projection": {"input_shape": [48, 48, 3], "output_size": hidden_size},
            "audio_projection": {"frame_samples": 640, "output_size": hidden_size},
        },
    }


def _write_config(path: Path, config: dict, *, indent: int | None = 2) -> bytes:
    """Write a config to disk in a NON-canonical form (pretty-printed, key-ordered as
    authored) -- the realistic on-disk shape, distinct from a compact sort_keys
    reserialization."""
    raw = json.dumps(config, indent=indent).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _canonical_reserialization_sha256(config: dict) -> str:
    """The WRONG object for this category: a canonicalized re-serialization of the parsed
    config, rather than the literal bytes on disk the trusted counter reads."""
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


class ArchitectureConfigIdentityRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
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
    def test_owned_architecture_identity_round_trips(self) -> None:
        payload, receipts = admitted_manifest()
        bundle = artifact_authority(payload)

        config_path = Path(self._tmp.name) / "model-config.json"
        raw = _write_config(config_path, _valid_config())

        receipt = measure_architecture_identity(config_path)
        payload = bind_architecture_identity(payload, receipt, source=SOURCE)
        self.assertEqual(payload["architecture"]["sha256"], receipt["config_sha256"])
        self.assertEqual(
            payload["architecture"]["sha256"], hashlib.sha256(raw).hexdigest()
        )

        # Point the admission bundle's "architecture" artifact at the SAME real bytes the
        # binding was measured from, so the real consumer's identity gate is exercised
        # honestly (not merely shape-satisfied by an unrelated placeholder).
        bundle["artifact_bundle"]["artifacts"]["architecture"] = {
            "sha256": receipt["config_sha256"],
            "content_hex": raw.hex(),
        }

        result = validate_manifest(payload, receipt_bundle=receipts, **bundle)
        self.assertEqual(result, payload)

    # ---- fail-closed negatives at the REAL consumer --------------------------------
    def test_architecture_pointer_bound_to_inferred_reserialization_flagged(self) -> None:
        """Binding the pointer to a canonicalized RE-SERIALIZATION (the wrong, "inferred"
        object for this category) instead of the raw bytes on disk is rejected."""
        payload, receipts = admitted_manifest()
        bundle = artifact_authority(payload)

        config = _valid_config()
        config_path = Path(self._tmp.name) / "model-config.json"
        raw = _write_config(config_path, config)  # pretty-printed on-disk bytes
        real_sha256 = hashlib.sha256(raw).hexdigest()
        inferred_sha256 = _canonical_reserialization_sha256(config)
        # The pretty-printed on-disk bytes and their canonical reserialization are
        # different objects -- exactly the drift this category must reject.
        self.assertNotEqual(real_sha256, inferred_sha256)

        # Bind the manifest to the WRONG (inferred) object, but let the bundle carry the
        # REAL bytes under "architecture" -- so the consumer's identity gate (not a
        # dangling-pointer path) is what fires.
        payload["architecture"]["sha256"] = inferred_sha256
        bundle["artifact_bundle"]["artifacts"]["architecture"] = {
            "sha256": inferred_sha256,
            "content_hex": raw.hex(),
        }
        codes = _error_codes(payload, receipt_bundle=receipts, **bundle)
        self.assertIn("admission.artifact_hash_mismatch", codes)

    def test_dangling_architecture_pointer_flagged(self) -> None:
        payload, receipts = admitted_manifest()
        bundle = artifact_authority(payload)
        del bundle["artifact_bundle"]["artifacts"]["architecture"]
        codes = _error_codes(payload, receipt_bundle=receipts, **bundle)
        self.assertIn("admission.artifact_missing", codes)

    # ---- wiring-module invariants (independent re-derivation) -----------------------
    def test_binding_module_round_trips_and_fails_closed(self) -> None:
        config = _valid_config()
        config_path = Path(self._tmp.name) / "model-config.json"
        raw = _write_config(config_path, config)

        receipt = measure_architecture_identity(config_path)
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(receipt["config_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            receipt["shape"],
            {"hidden_size": 256, "layers": 2, "attention_heads": 4, "vocab_size": 1024},
        )

        manifest: dict = {}
        bound = bind_architecture_identity(manifest, receipt, source=SOURCE)
        self.assertEqual(bound["architecture"], {"source": SOURCE, "sha256": receipt["config_sha256"]})

        # Silent on the honestly-bound manifest.
        verify_architecture_identity_binding(bound, receipt, model_config_path=config_path)

        # Pointer bound to a canonicalized re-serialization (the wrong, inferred object)
        # -> fail closed naming the field.
        tampered = copy.deepcopy(bound)
        tampered["architecture"]["sha256"] = _canonical_reserialization_sha256(config)
        with self.assertRaises(ArchitectureIdentityMismatch) as ctx:
            verify_architecture_identity_binding(tampered, receipt, model_config_path=config_path)
        self.assertIn("architecture.sha256", str(ctx.exception))

        # receipt.shape diverging from a fresh re-derivation -> fail closed.
        bad_shape_receipt = dict(receipt)
        bad_shape_receipt["shape"] = {**receipt["shape"], "hidden_size": 999}
        with self.assertRaises(ArchitectureIdentityMismatch):
            verify_architecture_identity_binding(bound, bad_shape_receipt, model_config_path=config_path)

        # architecture.source missing/empty -> fail closed.
        no_source = copy.deepcopy(bound)
        no_source["architecture"]["source"] = ""
        with self.assertRaises(ArchitectureIdentityMismatch):
            verify_architecture_identity_binding(no_source, receipt, model_config_path=config_path)

        # sha drift: the config file changes underneath the bound manifest -> fail closed.
        config_path.write_bytes(json.dumps({**config, "extra": "drift"}, indent=2).encode("utf-8"))
        with self.assertRaises(ArchitectureIdentityMismatch):
            verify_architecture_identity_binding(bound, receipt, model_config_path=config_path)

        # A non-empty but non-MEASURED receipt cannot be bound.
        with self.assertRaises(ArchitectureIdentityMismatch):
            bind_architecture_identity(manifest, {**receipt, "result": "PENDING"}, source=SOURCE)

        # An empty source cannot be bound.
        with self.assertRaises(ArchitectureIdentityMismatch):
            bind_architecture_identity(manifest, receipt, source="   ")

    def test_measure_rejects_wrong_architecture_revision(self) -> None:
        config = {**_valid_config(), "architecture_revision": "ember-sparse-3b-v1"}
        config_path = Path(self._tmp.name) / "model-config.json"
        _write_config(config_path, config)
        with self.assertRaises(ArchitectureIdentityMismatch) as ctx:
            measure_architecture_identity(config_path)
        self.assertIn("architecture_revision", str(ctx.exception))

    def test_measure_rejects_invalid_decoder_shape(self) -> None:
        # hidden_size not divisible by attention_heads -> parameter_counter._model_shape
        # rejects it; the binding module must propagate that as a fail-closed error, not
        # silently accept a structurally invalid architecture.
        config = _valid_config(hidden_size=257, attention_heads=4)
        config_path = Path(self._tmp.name) / "model-config.json"
        _write_config(config_path, config)
        with self.assertRaises(ArchitectureIdentityMismatch) as ctx:
            measure_architecture_identity(config_path)
        self.assertIn("valid decoder shape", str(ctx.exception))

    def test_measure_rejects_non_object_config(self) -> None:
        config_path = Path(self._tmp.name) / "model-config.json"
        config_path.write_bytes(b"[1, 2, 3]")
        with self.assertRaises(ArchitectureIdentityMismatch):
            measure_architecture_identity(config_path)


if __name__ == "__main__":
    unittest.main()
