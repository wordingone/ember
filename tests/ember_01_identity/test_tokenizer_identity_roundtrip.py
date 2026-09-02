# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 increment: tokenizer_identity binds the RUNNING tokenizer, fail-closed.

Not a raw-file-hash round-trip: a real ByteLevel BPE tokenizer.json is trained to disk and
driven through the REAL production loader
(``token_shards_v0._production_tokenizer(match_added_tokens=False)`` -- the ENCODE_SEMANTICS
the shards were generated under, which strips ``added_tokens`` in memory). The identity
manifest's ``tokenizer.sha256`` is bound to the sha of the POST-STRIP runtime tokenizer
(``Tokenizer.to_str()``), never the raw file bytes; the raw-file provenance sha is carried
in the receipt. The bound manifest is schema-validated by the real
``validate_identity.validate_manifest``.

Round-trip: measure -> bind -> validate_identity PASS, and the bound quantity is proven to
be the RUNTIME object (running sha != provenance sha).
Negatives (all fail closed, naming the field): running-identity tamper (tokenizer.sha256);
provenance tamper in the receipt; raw-file byte drift on disk (the A1 sha-drift analog);
empty tokenizer.id; missing artifact.
"""

from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _extra in (ROOT / "scripts" / "ember_01_identity", ROOT / "scripts"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import validate_identity  # noqa: E402
from tokenizer_identity_binding import (  # noqa: E402
    TokenizerIdentityMismatch,
    bind_tokenizer_identity,
    measure_tokenizer_identity,
    verify_tokenizer_identity_binding,
)


def _train_real_tokenizer(path: Path, *, seed: int) -> None:
    """Train a REAL ByteLevel BPE tokenizer to disk with 8 reserved specials at ids 0..7.

    Genuine tokenizers artifact (not a hand-authored constant): specials occupy 0..7, the
    full byte alphabet follows, so a stripped special literal encodes to byte-level ids >= 8
    -- exactly what the production loader's strip-probe requires. Distinct seed -> distinct
    training text -> distinct bytes -> distinct sha."""
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

    tk = Tokenizer(models.BPE())
    tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tk.decoder = decoders.ByteLevel()
    specials = [f"<res{i}>" for i in range(8)]
    trainer = trainers.BpeTrainer(
        vocab_size=400,
        special_tokens=specials,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    corpus = [
        f"the quick brown fox number {seed} jumps over the lazy dog",
        f"ember cond3 tokenizer identity binding seed {seed} runtime object",
        f"content addressed running tokenizer not the raw file {seed}",
    ] * 20
    tk.train_from_iterator(corpus, trainer)
    tk.save(str(path))


def _base_manifest() -> dict:
    """Minimal schema-valid OWNED_CANDIDATE manifest; tokenizer.id/sha256 overwritten by
    the binding. Everything outside the tokenizer section is honestly unresolved (this
    increment's scope is the tokenizer_identity binding only)."""
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
        "architecture": {"source": "src/ember/infrastructure/tools/ember-restart-3b/model.py", "sha256": "a" * 64},
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
            "allocated": 0, "unique": 0, "active": 0, "trainable": 0, "served": 0,
            "actually_trained": 0,
            "evidence_receipts": {
                name: []
                for name in ("allocated", "unique", "active", "trainable", "served", "actually_trained")
            },
        },
        "training": {
            "steps": 0, "effective_tokens": 0,
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
            "protocol": "test-v1", "device": "cpu", "runtime_dependencies": [],
            "resource_lease_id": {"status": "unresolved", "reason": "cond3 tokenizer increment has no resource lease"},
        },
        "evaluation": {
            "benchmark_id": "cond3-tokenizer-roundtrip", "version": "v1", "split": "test",
            "harness_sha256": "a" * 64, "subject_checkpoint_sha256": "0" * 64,
            "comparator_identity": "none", "comparator_sha256": "b" * 64,
            "score": {"status": "unresolved", "reason": "no benchmark was executed"},
            "uncertainty": {"status": "unresolved", "reason": "no benchmark was executed"},
            "receipt_sha256": {"status": "unresolved", "reason": "no benchmark was executed"},
            "counts_toward_owned_completion": False,
        },
        "provenance": {
            "ownership": "OWNED_CLEAN_GENESIS", "exclusion_reasons": [],
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
    def test_roundtrip_binds_running_object_then_validate_identity_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tok_path = root / "tokenizer.json"
            _train_real_tokenizer(tok_path, seed=101)

            receipt = measure_tokenizer_identity(tok_path)
            self.assertEqual(receipt["result"], "MEASURED")
            self.assertRegex(receipt["running_identity_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(receipt["provenance_sha256"], r"^[0-9a-f]{64}$")
            # Provenance sha is the raw file bytes on disk.
            self.assertEqual(
                receipt["provenance_sha256"], hashlib.sha256(tok_path.read_bytes()).hexdigest()
            )
            # THE load-bearing assertion: the bound quantity is the RUNTIME object, not the
            # raw file. The post-strip tokenizer serializes to something other than the file
            # bytes, so the two shas MUST differ -- a raw-file binding would collapse them.
            self.assertNotEqual(
                receipt["running_identity_sha256"], receipt["provenance_sha256"],
                "running identity must be the post-strip runtime object, not the raw file",
            )

            manifest = _base_manifest()
            bound = bind_tokenizer_identity(
                manifest, receipt, tokenizer_id="owned-tokenizer-cond3"
            )
            self.assertEqual(bound["tokenizer"]["sha256"], receipt["running_identity_sha256"])
            self.assertEqual(bound["tokenizer"]["id"], "owned-tokenizer-cond3")
            # tokenizer.sha256 is NOT the raw-file sha.
            self.assertNotEqual(bound["tokenizer"]["sha256"], receipt["provenance_sha256"])

            # Re-derives from the real loader, not field-to-field.
            verify_tokenizer_identity_binding(bound, receipt, tokenizer_json_path=tok_path)

            # Schema-valid end to end via the REAL consumer.
            validated = validate_identity.validate_manifest(bound)
            self.assertEqual(validated["schema"], "ember-model-experiment-identity-v1")
            self.assertEqual(validated["tokenizer"]["sha256"], receipt["running_identity_sha256"])

    def test_running_identity_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tok_path = root / "tokenizer.json"
            _train_real_tokenizer(tok_path, seed=202)
            receipt = measure_tokenizer_identity(tok_path)
            bound = bind_tokenizer_identity(_base_manifest(), receipt, tokenizer_id="owned-tokenizer-cond3")
            verify_tokenizer_identity_binding(bound, receipt, tokenizer_json_path=tok_path)  # sanity

            tampered = copy.deepcopy(bound)
            tampered["tokenizer"]["sha256"] = "f" * 64
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "tokenizer.sha256"):
                verify_tokenizer_identity_binding(tampered, receipt, tokenizer_json_path=tok_path)

    def test_provenance_tamper_in_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tok_path = root / "tokenizer.json"
            _train_real_tokenizer(tok_path, seed=303)
            receipt = measure_tokenizer_identity(tok_path)
            bound = bind_tokenizer_identity(_base_manifest(), receipt, tokenizer_id="owned-tokenizer-cond3")

            tampered_receipt = {**receipt, "provenance_sha256": "e" * 64}
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "provenance_sha256"):
                verify_tokenizer_identity_binding(bound, tampered_receipt, tokenizer_json_path=tok_path)

    def test_raw_file_byte_drift_fails_closed(self) -> None:
        """Mutating the tokenizer bytes on disk after binding (the production loader's
        sha-drift guard / A1_SCAN_TOKENIZER_SHA_DRIFT analog) must be caught."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tok_path = root / "tokenizer.json"
            _train_real_tokenizer(tok_path, seed=404)
            receipt = measure_tokenizer_identity(tok_path)
            bound = bind_tokenizer_identity(_base_manifest(), receipt, tokenizer_id="owned-tokenizer-cond3")
            verify_tokenizer_identity_binding(bound, receipt, tokenizer_json_path=tok_path)  # sanity

            tok_path.write_bytes(tok_path.read_bytes() + b" ")
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "sha drift|provenance_sha256"):
                verify_tokenizer_identity_binding(bound, receipt, tokenizer_json_path=tok_path)

    def test_empty_tokenizer_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tok_path = root / "tokenizer.json"
            _train_real_tokenizer(tok_path, seed=505)
            receipt = measure_tokenizer_identity(tok_path)
            bound = bind_tokenizer_identity(_base_manifest(), receipt, tokenizer_id="owned-tokenizer-cond3")
            tampered = copy.deepcopy(bound)
            tampered["tokenizer"]["id"] = "   "
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "tokenizer.id"):
                verify_tokenizer_identity_binding(tampered, receipt, tokenizer_json_path=tok_path)
            with self.assertRaisesRegex(TokenizerIdentityMismatch, "tokenizer.id"):
                bind_tokenizer_identity(_base_manifest(), receipt, tokenizer_id="")

    def test_missing_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tok_path = root / "tokenizer.json"
            _train_real_tokenizer(tok_path, seed=606)
            receipt = measure_tokenizer_identity(tok_path)
            bound = bind_tokenizer_identity(_base_manifest(), receipt, tokenizer_id="owned-tokenizer-cond3")
            missing = root / "does-not-exist-tokenizer.json"
            with self.assertRaises(TokenizerIdentityMismatch):
                verify_tokenizer_identity_binding(bound, receipt, tokenizer_json_path=missing)
            with self.assertRaises(TokenizerIdentityMismatch):
                measure_tokenizer_identity(missing)


if __name__ == "__main__":
    unittest.main()
