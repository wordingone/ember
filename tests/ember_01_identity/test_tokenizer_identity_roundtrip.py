# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 increment: tokenizer_identity round-trips a REAL tokenizer artifact, fail-closed.

Not a fixture round-trip: a real tokenizer artifact (a small ``tokenizer.json``) is
written to disk, content-addressed by ``tokenizer_identity_binding`` (streaming sha256 of
the bytes, the same mechanism the a1 loader's ``file_sha256`` uses), bound into the
identity manifest's ``tokenizer`` section, and the bound manifest is schema-validated by
``validate_identity.validate_manifest``.

Round-trip: emit -> validate_identity PASS.
Negatives: tamper tokenizer.sha256 -> fail closed naming the field; mutate the tokenizer
bytes on disk after binding (drift) -> fail closed; empty tokenizer.id -> fail closed;
tokenizer artifact missing on disk -> fail closed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _extra in (ROOT / "scripts" / "ember_01_identity",):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import validate_identity  # noqa: E402
from tokenizer_identity_binding import (  # noqa: E402
    TokenizerIdentityMismatch,
    bind_tokenizer_identity,
    measure_tokenizer_artifact,
    verify_tokenizer_identity_binding,
)


def _write_real_tokenizer(directory: Path, *, seed: int) -> Path:
    """Write a REAL tokenizer.json to disk (not a fixture constant) and return its path.

    A minimal but genuine tokenizer-shaped JSON artifact; its bytes are what the binding
    content-addresses. Distinct ``seed`` -> distinct bytes -> distinct sha256.
    """
    path = directory / "tokenizer.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "model": {
                    "type": "BPE",
                    "vocab": {f"tok{seed}_{i}": i for i in range(16)},
                    "merges": [f"tok{seed}_{i} tok{seed}_{i + 1}" for i in range(8)],
                },
                "added_tokens": [{"id": 0, "content": "<pad>"}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _base_manifest() -> dict:
    """A minimal, schema-valid OWNED_CANDIDATE manifest with everything outside the
    tokenizer section left honestly unresolved (this increment's scope is the
    tokenizer_identity binding only). tokenizer.id/sha256 are overwritten by
    bind_tokenizer_identity."""
    return {
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02B",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "schema": "ember-model-experiment-identity-v1",
        "identity": {
            "model_id": "ember-cond3-tokenizer-roundtrip",
            "experiment_id": "cond3-tokenizer-identity",
            "run_id": "run-cond3-tokenizer-001",
            "checkpoint_id": "checkpoint-cond3-tokenizer-001",
            "disposition": "OWNED_CANDIDATE",
            "selected_as_owned_ember": False,
        },
        "architecture": {
            "source": "tools/ember-restart-3b/model.py",
            "sha256": "a" * 64,
        },
        "checkpoint": {
            "format": "ember-restart-3b-checkpoint-manifest-v1",
            "byte_sha256": "0" * 64,
            "tensors": [
                {
                    "name": "cond3-tokenizer-shard-0",
                    "shape": [1],
                    "dtype": "ember-checkpoint-shard-v1",
                    "sha256": hashlib.sha256(b"cond3-tokenizer-shard-0").hexdigest(),
                },
            ],
            "ancestry": [],
            "recovery_state": "CLEAN",
        },
        "tokenizer": {"id": "placeholder", "sha256": "b" * 64},  # overwritten by binding
        "data": {
            "corpus_id": "owned-corpus-fixture",
            "sha256": "c" * 64,
            "ordering_sha256": "d" * 64,
            "curriculum_sha256": "e" * 64,
            "verifier_sha256": "f" * 64,
            "clean_genesis": True,
            "accepted_input": {
                "input_id": "cond3-tokenizer",
                "authority_id": "ember-01-cond3-tokenizer",
                "authority_record_sha256": "1" * 64,
                "authority": "UNRESOLVED",
                "shard_manifest_sha256": "2" * 64,
                "caller_sha256": "3" * 64,
                "gate_sha256": "4" * 64,
                "validator_sha256": "5" * 64,
                "forwarding_receipt_sha256": "6" * 64,
            },
        },
        "parameters": {
            "allocated": 0,
            "unique": 0,
            "active": 0,
            "trainable": 0,
            "served": 0,
            "actually_trained": 0,
            "evidence_receipts": {
                name: []
                for name in ("allocated", "unique", "active", "trainable", "served", "actually_trained")
            },
        },
        "training": {
            "steps": 0,
            "effective_tokens": 0,
            "modality_mixture": {"text": 1.0, "image": 0.0, "audio": 0.0},
            "optimizer_state_sha256": "7" * 64,
            "numerics": {"profile": "fp32-cpu-test", "sha256": "8" * 64},
            "stopping_rule": {
                "criterion_id": "sufficient-pretraining-v1",
                "result": "NOT_REACHED",
                "receipt_sha256": {"status": "unresolved", "reason": "cond3 tokenizer increment does not train"},
            },
        },
        "capabilities": {
            "native_modalities": {
                "text": {"state": "UNVERIFIED", "evidence_receipts": []},
                "image": {"state": "UNVERIFIED", "evidence_receipts": []},
                "audio": {"state": "UNVERIFIED", "evidence_receipts": []},
            },
            "reasoning": {"state": "UNVERIFIED", "evidence_receipts": []},
            "structured_tool_use": {"state": "UNVERIFIED", "evidence_receipts": []},
        },
        "mechanisms": {
            "experts": [], "router": [], "temporary_adapters": [], "permanent_merges": [],
            "memory_substrates": [], "world_models": [], "dreaming_updates": [], "deletion_objects": [],
        },
        "backend": {
            "executable_sha256": "9" * 64,
            "process_identity": {"status": "unresolved", "reason": "cond3 tokenizer increment is not a running server"},
            "process_receipt_sha256": {"status": "unresolved", "reason": "cond3 tokenizer increment is not a running server"},
            "protocol": "test-v1",
            "device": "cpu",
            "runtime_dependencies": [],
            "resource_lease_id": {"status": "unresolved", "reason": "cond3 tokenizer increment has no resource lease"},
        },
        "evaluation": {
            "benchmark_id": "cond3-tokenizer-roundtrip",
            "version": "v1",
            "split": "test",
            "harness_sha256": "a" * 64,
            "subject_checkpoint_sha256": "0" * 64,
            "comparator_identity": "none",
            "comparator_sha256": "b" * 64,
            "score": {"status": "unresolved", "reason": "no benchmark was executed"},
            "uncertainty": {"status": "unresolved", "reason": "no benchmark was executed"},
            "receipt_sha256": {"status": "unresolved", "reason": "no benchmark was executed"},
            "counts_toward_owned_completion": False,
        },
        "provenance": {
            "ownership": "OWNED_CLEAN_GENESIS",
            "exclusion_reasons": [],
            "learned_signal_sources": ["owned_training_data"],
            "neural_capability_credit_sources": ["owned_checkpoint"],
        },
        "unresolved": [
            "training.stopping_rule.receipt_sha256",
            "backend.process_identity",
            "backend.process_receipt_sha256",
            "backend.resource_lease_id",
            "evaluation.score",
            "evaluation.uncertainty",
            "evaluation.receipt_sha256",
        ],
    }


class TokenizerIdentityRoundtripTests(unittest.TestCase):
    def test_roundtrip_emit_then_validate_identity_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer_path = _write_real_tokenizer(root, seed=101)

            # The measured content address is the real tokenizer bytes on disk, not a
            # hardcoded constant.
            measured = measure_tokenizer_artifact(tokenizer_path)
            self.assertRegex(measured, r"^[0-9a-f]{64}$")
            self.assertEqual(measured, hashlib.sha256(tokenizer_path.read_bytes()).hexdigest())

            manifest = _base_manifest()
            bound = bind_tokenizer_identity(
                manifest, tokenizer_id="owned-tokenizer-cond3", tokenizer_artifact=tokenizer_path
            )
            self.assertEqual(bound["tokenizer"]["sha256"], measured)
            self.assertEqual(bound["tokenizer"]["id"], "owned-tokenizer-cond3")

            # The binding re-derives from the real bytes on disk, not field-to-field.
            verify_tokenizer_identity_binding(bound, tokenizer_artifact=tokenizer_path)

            # And the bound manifest is schema-valid end to end via the REAL consumer.
            validated = validate_identity.validate_manifest(bound)
            self.assertEqual(validated["schema"], "ember-model-experiment-identity-v1")
            self.assertEqual(validated["tokenizer"]["sha256"], measured)

    def test_sha256_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer_path = _write_real_tokenizer(root, seed=202)
            bound = bind_tokenizer_identity(
                _base_manifest(), tokenizer_id="owned-tokenizer-cond3", tokenizer_artifact=tokenizer_path
            )
            verify_tokenizer_identity_binding(bound, tokenizer_artifact=tokenizer_path)  # sanity

            tampered = copy.deepcopy(bound)
            tampered["tokenizer"]["sha256"] = "f" * 64
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "tokenizer.sha256"):
                verify_tokenizer_identity_binding(tampered, tokenizer_artifact=tokenizer_path)

    def test_artifact_byte_drift_fails_closed(self) -> None:
        """Mutating the tokenizer bytes on disk after binding (the a1
        A1_SCAN_TOKENIZER_SHA_DRIFT case) must be caught on re-derivation."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer_path = _write_real_tokenizer(root, seed=303)
            bound = bind_tokenizer_identity(
                _base_manifest(), tokenizer_id="owned-tokenizer-cond3", tokenizer_artifact=tokenizer_path
            )
            verify_tokenizer_identity_binding(bound, tokenizer_artifact=tokenizer_path)  # sanity

            # Drift the bytes on disk; the bound sha256 is now stale.
            tokenizer_path.write_text(tokenizer_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "tokenizer.sha256"):
                verify_tokenizer_identity_binding(bound, tokenizer_artifact=tokenizer_path)

    def test_empty_tokenizer_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer_path = _write_real_tokenizer(root, seed=404)
            bound = bind_tokenizer_identity(
                _base_manifest(), tokenizer_id="owned-tokenizer-cond3", tokenizer_artifact=tokenizer_path
            )
            tampered = copy.deepcopy(bound)
            tampered["tokenizer"]["id"] = "   "
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "tokenizer.id"):
                verify_tokenizer_identity_binding(tampered, tokenizer_artifact=tokenizer_path)
            # And bind refuses an empty id up front.
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "tokenizer.id"):
                bind_tokenizer_identity(_base_manifest(), tokenizer_id="", tokenizer_artifact=tokenizer_path)

    def test_missing_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tokenizer_path = _write_real_tokenizer(root, seed=505)
            bound = bind_tokenizer_identity(
                _base_manifest(), tokenizer_id="owned-tokenizer-cond3", tokenizer_artifact=tokenizer_path
            )
            missing = root / "does-not-exist-tokenizer.json"
            with self.assertRaises(TokenizerIdentityMismatch):
                verify_tokenizer_identity_binding(bound, tokenizer_artifact=missing)
            # bind also refuses a missing artifact (no bytes to content-address).
            with self.assertRaises(TokenizerIdentityMismatch):
                bind_tokenizer_identity(_base_manifest(), tokenizer_id="x", tokenizer_artifact=missing)


if __name__ == "__main__":
    unittest.main()
