# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 (checkpoint_save_load): a checkpoint's save/load identity round-trips its
consumer, fail-closed.

Not a narrative assertion: the positive case builds a REAL signed OWNED_ADMITTED identity
manifest (the same ``admitted_manifest`` machinery the production validator suite uses) and
runs the actual production consumer, ``validate_identity.validate_manifest``. That consumer
resolves ``checkpoint.byte_sha256`` (and, since OWNED_ADMITTED requires
``checkpoint.format == "ember-checkpoint-envelope-v1"``, ``checkpoint.tensors``) against a
caller-supplied ``checkpoint_bytes`` argument (validate_identity.py ~line 638-721):
``checkpoint.byte_hash_mismatch`` unless ``hashlib.sha256(checkpoint_bytes) ==
checkpoint.byte_sha256``, and ``checkpoint.envelope_tensor_mismatch`` unless the envelope's
own per-tensor hashes equal ``checkpoint.tensors``. The real runtime consumer that later
LOADS that same checkpoint is
``src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.load_checkpoint_artifacts`` -- it calls
``torch.load`` and ``model.load_state_dict`` / ``optimizer.load_state_dict``, but ONLY after
its own ``CheckpointIdentityMismatch`` gate (checkpoint_artifacts.py lines 1230-1243) confirms
the checkpoint's identity. This binding measures that identity from a REAL checkpoint shard
via the trusted, isolated counter's own safe metadata-only reader
(``src/ember/infrastructure/tools/ember-restart-3b/parameter_counter._load_checkpoint_metadata`` /
``_tensor_raw_bytes``) -- never ``torch.load`` itself, never a hand-typed digest.

Fail-closed negatives drive the manifest's checkpoint identity out of agreement with the
consumer's own identity and assert the REAL validator flags it RED:

1. checkpoint pointer bound to the raw bytes of the checkpoint's own ``.pt`` FILE (the WRONG
   object for this category -- empirically verified in the binding module's docstring:
   ``torch.save`` is not byte-deterministic across saves of identical tensor content) instead
   of the canonical per-tensor envelope -> checkpoint.byte_hash_mismatch
2. checkpoint bytes withheld entirely at OWNED_ADMITTED disposition ->
   admission.checkpoint_bytes_missing

A parallel block exercises the wiring module
(``checkpoint_save_load_identity_binding.verify_checkpoint_identity_binding``) directly,
proving the same invariant re-derives and fails closed independent of the full admission
bundle -- including that binding to the shard file's own bytes (rather than its literal
tensor storage bytes) is rejected, that an unsupported tensor storage dtype is rejected at
measurement time, and that sha drift on the checkpoint shard is caught on re-verification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
RESTART_TOOLS = next(candidate for candidate in (ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b", ROOT / "tools" / "ember-restart-3b") if (candidate / "parameter_counter.py").is_file())
COUNTER_PATH = RESTART_TOOLS
TEST_DIR = Path(__file__).parent
for _extra in (SCRIPT_DIR, COUNTER_PATH, TEST_DIR):
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
    CHECKPOINT_BYTES,
    VERIFIER_BYTES,
    TEST_PUBLIC_KEY_HEX,
)

from checkpoint_save_load_identity_binding import (  # noqa: E402
    CheckpointSaveLoadIdentityMismatch,
    bind_checkpoint_identity,
    measure_checkpoint_identity,
    verify_checkpoint_identity_binding,
)


def _write_fixture_shard(path: Path) -> None:
    """A real torch checkpoint shard whose sole tensor matches the shared test fixture's
    "fixture.weight" tensor exactly (name, shape [1], float32 zero content) -- so measuring
    it independently proves the fixture's hand-authored ``CHECKPOINT_BYTES`` constant is
    itself reconstructible from a REAL checkpoint via the trusted counter's own reader."""
    torch.save({"model": {"fixture.weight": torch.zeros(1, dtype=torch.float32)}}, path)


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


class CheckpointSaveLoadIdentityRoundTrip(unittest.TestCase):
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
    def test_owned_checkpoint_identity_round_trips(self) -> None:
        payload, receipts = admitted_manifest()
        bundle = artifact_authority(payload)

        shard_path = Path(self._tmp.name) / "shared.pt"
        _write_fixture_shard(shard_path)

        receipt = measure_checkpoint_identity(shard_path)
        self.assertEqual(receipt["result"], "MEASURED")
        # The REAL checkpoint's canonical envelope independently reconstructs the shared
        # fixture's hand-authored CHECKPOINT_BYTES constant exactly -- proving that constant
        # was never ungrounded, and that this module's extraction is correct.
        self.assertEqual(
            receipt["checkpoint_byte_sha256"], hashlib.sha256(CHECKPOINT_BYTES).hexdigest()
        )

        payload = bind_checkpoint_identity(payload, receipt)
        self.assertEqual(payload["checkpoint"]["byte_sha256"], receipt["checkpoint_byte_sha256"])
        self.assertEqual(payload["checkpoint"]["format"], "ember-checkpoint-envelope-v1")

        result = validate_manifest(payload, receipt_bundle=receipts, **bundle)
        self.assertEqual(result, payload)

    # ---- fail-closed negatives at the REAL consumer --------------------------------
    def test_checkpoint_bytes_bound_to_whole_file_instead_of_tensor_envelope_flagged(self) -> None:
        """Binding the runtime evidence to the checkpoint's own FILE bytes (the wrong,
        unstable object for this category) instead of the canonical tensor envelope is
        rejected."""
        payload, receipts = admitted_manifest()
        bundle = artifact_authority(payload)

        shard_path = Path(self._tmp.name) / "shared.pt"
        _write_fixture_shard(shard_path)
        receipt = measure_checkpoint_identity(shard_path)
        payload = bind_checkpoint_identity(payload, receipt)

        whole_file_bytes = shard_path.read_bytes()
        # The whole-file bytes and the canonical envelope are different objects -- exactly
        # the drift this category must reject.
        self.assertNotEqual(
            hashlib.sha256(whole_file_bytes).hexdigest(), payload["checkpoint"]["byte_sha256"]
        )

        bundle["checkpoint_bytes"] = whole_file_bytes
        codes = _error_codes(payload, receipt_bundle=receipts, **bundle)
        self.assertIn("checkpoint.byte_hash_mismatch", codes)

    def test_missing_checkpoint_bytes_flagged_for_owned_admission(self) -> None:
        payload, receipts = admitted_manifest()
        bundle = artifact_authority(payload)
        del bundle["checkpoint_bytes"]
        codes = _error_codes(payload, receipt_bundle=receipts, **bundle)
        self.assertIn("admission.checkpoint_bytes_missing", codes)

    # ---- wiring-module invariants (independent re-derivation) -----------------------
    def test_binding_module_round_trips_and_fails_closed(self) -> None:
        shard_path = Path(self._tmp.name) / "model-shard.pt"
        weight = torch.tensor([1.5, -2.25, 0.0], dtype=torch.float32)
        bias = torch.tensor([3, -1], dtype=torch.int8)
        torch.save({"model": {"layer.weight": weight, "layer.bias": bias}}, shard_path)

        receipt = measure_checkpoint_identity(shard_path)
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(len(receipt["tensors"]), 2)
        by_name = {row["name"]: row for row in receipt["tensors"]}
        self.assertEqual(
            by_name["layer.weight"]["sha256"],
            hashlib.sha256(weight.numpy().tobytes()).hexdigest(),
        )
        self.assertEqual(
            by_name["layer.bias"]["sha256"],
            hashlib.sha256(bias.numpy().tobytes()).hexdigest(),
        )

        manifest: dict = {"checkpoint": {"ancestry": [], "recovery_state": {}}}
        bound = bind_checkpoint_identity(manifest, receipt)
        self.assertEqual(bound["checkpoint"]["byte_sha256"], receipt["checkpoint_byte_sha256"])
        self.assertEqual(bound["checkpoint"]["format"], "ember-checkpoint-envelope-v1")
        # Fields outside this binding's scope are preserved, never clobbered.
        self.assertEqual(bound["checkpoint"]["ancestry"], [])
        self.assertEqual(bound["checkpoint"]["recovery_state"], {})

        # Silent on the honestly-bound manifest.
        verify_checkpoint_identity_binding(bound, receipt, shard_path=shard_path)

        # Pointer bound to the shard FILE's own bytes (the wrong, unstable object) -> fail
        # closed naming the field.
        tampered = copy.deepcopy(bound)
        tampered["checkpoint"]["byte_sha256"] = hashlib.sha256(
            shard_path.read_bytes()
        ).hexdigest()
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch) as ctx:
            verify_checkpoint_identity_binding(tampered, receipt, shard_path=shard_path)
        self.assertIn("checkpoint.byte_sha256", str(ctx.exception))

        # checkpoint.tensors diverging from a fresh re-derivation -> fail closed.
        tampered_tensors = copy.deepcopy(bound)
        tampered_tensors["checkpoint"]["tensors"][0]["sha256"] = "0" * 64
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch):
            verify_checkpoint_identity_binding(tampered_tensors, receipt, shard_path=shard_path)

        # checkpoint.format diverging from the envelope schema -> fail closed.
        tampered_format = copy.deepcopy(bound)
        tampered_format["checkpoint"]["format"] = "raw-torch-pickle-v1"
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch):
            verify_checkpoint_identity_binding(tampered_format, receipt, shard_path=shard_path)

        # receipt.tensors diverging from a fresh re-derivation -> fail closed.
        bad_tensors_receipt = dict(receipt)
        bad_tensors_receipt["tensors"] = [dict(receipt["tensors"][0])]
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch):
            verify_checkpoint_identity_binding(bound, bad_tensors_receipt, shard_path=shard_path)

        # sha drift: the checkpoint shard changes underneath the bound manifest -> fail closed.
        torch.save(
            {"model": {"layer.weight": weight, "layer.bias": bias, "extra.bias": torch.zeros(1)}},
            shard_path,
        )
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch):
            verify_checkpoint_identity_binding(bound, receipt, shard_path=shard_path)

        # A non-empty but non-MEASURED receipt cannot be bound.
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch):
            bind_checkpoint_identity(manifest, {**receipt, "result": "PENDING"})

    def test_measure_rejects_unsupported_storage_dtype(self) -> None:
        # LongStorage (int64) is not in the identity envelope's accepted dtype set.
        shard_path = Path(self._tmp.name) / "unsupported.pt"
        torch.save({"model": {"counter": torch.zeros(2, dtype=torch.int64)}}, shard_path)
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch) as ctx:
            measure_checkpoint_identity(shard_path)
        self.assertIn("does not support", str(ctx.exception))

    def test_measure_rejects_missing_model_state(self) -> None:
        shard_path = Path(self._tmp.name) / "no-model.pt"
        torch.save({"optimizer": {}}, shard_path)
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch):
            measure_checkpoint_identity(shard_path)

    def test_measure_rejects_non_checkpoint_file(self) -> None:
        shard_path = Path(self._tmp.name) / "not-a-checkpoint.pt"
        shard_path.write_bytes(b"not a zip archive at all")
        with self.assertRaises(CheckpointSaveLoadIdentityMismatch):
            measure_checkpoint_identity(shard_path)


if __name__ == "__main__":
    unittest.main()
