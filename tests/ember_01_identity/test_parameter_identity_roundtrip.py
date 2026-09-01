# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 increment-1: parameter_identity round-trips a LIVE checkpoint, fail-closed.

Not a fixture round-trip: the checkpoint is a real, tiny (hidden_size=32, layers=2)
UnifiedDecoder checkpoint written to disk with real torch tensors and a real
checkpoint-manifest.json, then measured by the trusted, isolated
``parameter_counter.execute_counter`` (the same counter production uses under
``-I``). The identity manifest's ``parameters`` section and ``checkpoint.byte_sha256``
are bound to that MEASURED receipt via
``scripts.ember_01_identity.parameter_identity_binding``, then the bound manifest is
schema-validated by ``validate_identity.validate_manifest``.

Round-trip: emit -> validate_identity PASS.
Six negatives: tamper each of the six parameter axes one at a time (allocated, unique,
trainable, served, active, actually_trained) -> verify_parameter_identity_binding fails
closed, naming the tampered axis.
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

ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = ROOT / "tests" / "ember_restart_model" / "domain-governance"
if not (_FIXTURE_DIR / "checkpoint_fixture.py").is_file():
    _fixture_candidates = sorted(
        (ROOT / "tests" / "ember_restart_model").glob("**/checkpoint_fixture.py")
    )
    if len(_fixture_candidates) != 1:
        raise RuntimeError("checkpoint_fixture.py must have exactly one migration location")
    _FIXTURE_DIR = _fixture_candidates[0].parent
for _extra in (
    ROOT / "tools" / "ember-restart-3b",
    _FIXTURE_DIR,
    ROOT / "scripts" / "ember_01_identity",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from model import RestartDecoderConfig, UnifiedDecoder  # noqa: E402
from checkpoint_fixture import write_checkpoint_artifacts  # noqa: E402

import validate_identity  # noqa: E402
from parameter_identity_binding import (  # noqa: E402
    AXIS_MAP,
    ParameterIdentityMismatch,
    bind_parameter_identity,
    measure_live_checkpoint,
    verify_parameter_identity_binding,
)


def _base_manifest() -> dict:
    """A minimal, schema-valid OWNED_CANDIDATE manifest with everything outside
    checkpoint/parameters left honestly unresolved (this increment's scope is the
    parameter_identity binding only, not the other 13 census categories)."""
    return {
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02B",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "schema": "ember-model-experiment-identity-v1",
        "identity": {
            "model_id": "ember-cond3-inc1-roundtrip",
            "experiment_id": "cond3-increment-1-parameter-identity",
            "run_id": "run-cond3-inc1-001",
            "checkpoint_id": "checkpoint-cond3-inc1-001",
            "disposition": "OWNED_CANDIDATE",
            "selected_as_owned_ember": False,
        },
        "architecture": {
            "source": "tools/ember-restart-3b/model.py",
            "sha256": "a" * 64,
        },
        "checkpoint": {
            "format": "ember-restart-3b-checkpoint-manifest-v1",
            "byte_sha256": "0" * 64,  # overwritten by bind_parameter_identity
            "tensors": [],  # filled from real shard records below
            "ancestry": [],
            "recovery_state": "CLEAN",
        },
        "tokenizer": {"id": "owned-tokenizer-fixture", "sha256": "b" * 64},
        "data": {
            "corpus_id": "owned-corpus-fixture",
            "sha256": "c" * 64,
            "ordering_sha256": "d" * 64,
            "curriculum_sha256": "e" * 64,
            "verifier_sha256": "f" * 64,
            "clean_genesis": True,
            "accepted_input": {
                "input_id": "cond3-increment-1",
                "authority_id": "ember-01-cond3-inc1",
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
            "evidence_receipts": {name: [] for name in AXIS_MAP},
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
                "receipt_sha256": {"status": "unresolved", "reason": "cond3 increment-1 does not train"},
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
            "process_identity": {"status": "unresolved", "reason": "cond3 increment-1 is not a running server"},
            "process_receipt_sha256": {"status": "unresolved", "reason": "cond3 increment-1 is not a running server"},
            "protocol": "test-v1",
            "device": "cpu",
            "runtime_dependencies": [],
            "resource_lease_id": {"status": "unresolved", "reason": "cond3 increment-1 has no resource lease"},
        },
        "evaluation": {
            "benchmark_id": "cond3-increment-1-roundtrip",
            "version": "v1",
            "split": "test",
            "harness_sha256": "a" * 64,
            "subject_checkpoint_sha256": "0" * 64,  # overwritten by bind_parameter_identity
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


class ParameterIdentityRoundtripTests(unittest.TestCase):
    def _write_live_checkpoint(self, directory: Path, *, seed: int) -> tuple[Path, Path]:
        """Write a REAL tiny checkpoint (not a fixture constant) and return
        (model_config_path, checkpoint_manifest_path)."""
        config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )
        model = UnifiedDecoder(config, genesis_seed=seed)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(
            (p for p in model.parameters() if p.requires_grad), lr=1e-4
        )
        config_path = directory / "config.json"
        config_path.write_text(
            json.dumps({
                "architecture_revision": "ember-sparse-3b-v2",
                "model": {
                    "hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                    "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }),
            encoding="utf-8",
        )
        write_checkpoint_artifacts(
            model, optimizer, directory / "checkpoint", launch_seed=seed,
            rng_state={
                "cpu": torch.get_rng_state().clone(),
                "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8)),
            },
            data_cursor={"shard": f"cond3-inc1-seed-{seed}", "record_index": 0, "global_step": 0, "tokens_seen": 0},
            model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
            contract_sha256="d" * 64,
            expert_genesis_sha256=model.expert_bank_genesis_hashes(),
        )
        manifest_path = directory / "checkpoint" / "checkpoint-manifest.json"
        return config_path, manifest_path

    def _tensors_from_shards(self, manifest_path: Path) -> list[dict]:
        """Project the checkpoint manifest's real shard hashes into tensor-shaped rows.

        These are not weight tensors (the schema field is reused as the checkpoint's
        content-addressed shard evidence); every sha256 is a real digest of real
        checkpoint bytes on disk, never a hardcoded constant.
        """
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return [
            {
                "name": record["path"],
                "shape": [int(record["bytes"])],
                "dtype": "ember-checkpoint-shard-v1",
                "sha256": record["sha256"],
            }
            for record in manifest["shards"]
        ]

    def test_roundtrip_emit_then_validate_identity_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, manifest_path = self._write_live_checkpoint(root, seed=101)
            receipt = measure_live_checkpoint(
                model_config=config_path, checkpoint_manifest=manifest_path, active_expert="shared"
            )
            self.assertEqual(receipt["result"], "MEASURED")
            self.assertEqual(receipt["verification_boundary"], "VERIFIED_MEASURED")
            self.assertRegex(receipt["subject_checkpoint_sha256"], r"^[0-9a-f]{64}$")
            # The subject checkpoint address is the real manifest bytes on disk, not a
            # hardcoded constant.
            self.assertEqual(
                receipt["subject_checkpoint_sha256"],
                hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            )

            manifest = _base_manifest()
            manifest["checkpoint"]["tensors"] = self._tensors_from_shards(manifest_path)
            bound = bind_parameter_identity(manifest, receipt)

            # Every one of the six axes traces to the live-checkpoint receipt, not to
            # this test's own arithmetic.
            for field, axis in AXIS_MAP.items():
                self.assertEqual(bound["parameters"][field], receipt[axis])
            self.assertEqual(bound["checkpoint"]["byte_sha256"], receipt["subject_checkpoint_sha256"])

            # The binding is internally self-consistent against the receipt it was
            # bound from -- re-derived from the real checkpoint bytes on disk, not
            # just compared field-to-field.
            verify_parameter_identity_binding(
                bound, receipt,
                checkpoint_manifest=manifest_path, model_config=config_path,
            )

            # And the bound manifest is schema-valid end to end.
            validated = validate_identity.validate_manifest(bound)
            self.assertEqual(validated["schema"], "ember-model-experiment-identity-v1")

    def test_six_axes_fail_closed_on_tamper(self) -> None:
        """Tampering any one of the six parameter axes must be caught by
        verify_parameter_identity_binding, naming that exact axis, without touching
        the underlying receipt (the independently measured ground truth)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, manifest_path = self._write_live_checkpoint(root, seed=202)
            receipt = measure_live_checkpoint(
                model_config=config_path, checkpoint_manifest=manifest_path, active_expert="shared"
            )
            manifest = _base_manifest()
            manifest["checkpoint"]["tensors"] = self._tensors_from_shards(manifest_path)
            bound = bind_parameter_identity(manifest, receipt)
            # sanity: clean binding passes, re-derived from the real checkpoint on disk
            verify_parameter_identity_binding(
                bound, receipt,
                checkpoint_manifest=manifest_path, model_config=config_path,
            )

            for field in AXIS_MAP:
                with self.subTest(axis=field):
                    tampered = copy.deepcopy(bound)
                    tampered["parameters"][field] = tampered["parameters"][field] + 1
                    with self.assertRaisesRegex(ParameterIdentityMismatch, field):
                        verify_parameter_identity_binding(
                            tampered, receipt,
                            checkpoint_manifest=manifest_path, model_config=config_path,
                        )

    def test_checkpoint_identity_tamper_fails_closed(self) -> None:
        """Rebinding checkpoint.byte_sha256 away from the receipt's subject is caught
        as well -- the parameter axes alone are not sufficient identity."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, manifest_path = self._write_live_checkpoint(root, seed=303)
            receipt = measure_live_checkpoint(
                model_config=config_path, checkpoint_manifest=manifest_path, active_expert="shared"
            )
            manifest = _base_manifest()
            manifest["checkpoint"]["tensors"] = self._tensors_from_shards(manifest_path)
            bound = bind_parameter_identity(manifest, receipt)
            bound["checkpoint"]["byte_sha256"] = "f" * 64
            with self.assertRaisesRegex(ParameterIdentityMismatch, "checkpoint.byte_sha256"):
                verify_parameter_identity_binding(
                    bound, receipt,
                    checkpoint_manifest=manifest_path, model_config=config_path,
                )

    def test_bind_refuses_a_receipt_that_is_not_measured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, manifest_path = self._write_live_checkpoint(root, seed=404)
            receipt = measure_live_checkpoint(
                model_config=config_path, checkpoint_manifest=manifest_path, active_expert="shared"
            )
            unmeasured = {**receipt, "result": "UNVERIFIED"}
            manifest = _base_manifest()
            manifest["checkpoint"]["tensors"] = self._tensors_from_shards(manifest_path)
            with self.assertRaises(ParameterIdentityMismatch):
                bind_parameter_identity(manifest, unmeasured)

    def test_verify_rejects_forged_receipt_via_recompute(self) -> None:
        """The audit's exact spoof, inverted: a hand-authored receipt with a fake
        checkpoint sha256 (never derived from any real checkpoint bytes) and fake
        parameter counts, paired with a real checkpoint written for a DIFFERENT run,
        must fail closed the instant verify_parameter_identity_binding re-derives the
        real hash from disk -- it never gets far enough to trust the fake counts.

        Before the fix this would have passed a naive field-to-field comparison as
        long as the manifest's ``parameters``/``checkpoint.byte_sha256`` were copied
        from the same forged receipt (bind_parameter_identity's own MEASURED gate is
        also bypassed here by constructing ``bound`` by hand, exactly the shape a
        compromised caller could produce without ever running the real counter)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A real checkpoint exists on disk -- but it is NOT the checkpoint the
            # forged receipt below claims to be evidence for.
            config_path, manifest_path = self._write_live_checkpoint(root, seed=505)

            forged_receipt = {
                "schema_version": "ember-sparse-realization-receipt-v1",
                "verification_boundary": "VERIFIED_MEASURED",
                "result": "MEASURED",
                "model_config_sha256": "a" * 64,
                "subject_checkpoint_sha256": "e" * 64,  # never derived from real bytes
                "architecture_revision": "ember-sparse-3b-v2",
                "counter_sha256": "b" * 64,
                "allocated_parameters": 999_000_000,
                "unique_parameters": 999_000_000,
                "trainable_parameters": 999_000_000,
                "served_parameters": 999_000_000,
                "active_parameters": 999_000_000,
                "episode_trainable_parameters": 999_000_000,
                "active_expert_ids": ["shared"],
                "expert_genesis_sha256": {},
                "expert_parameter_sha256": {},
            }

            manifest = _base_manifest()
            manifest["checkpoint"]["tensors"] = self._tensors_from_shards(manifest_path)
            bound = dict(manifest)
            # Hand-construct the bound manifest exactly as bind_parameter_identity
            # would -- but from the forged receipt, never a real MEASURED one.
            bound["checkpoint"] = {**manifest["checkpoint"], "byte_sha256": forged_receipt["subject_checkpoint_sha256"]}
            bound["parameters"] = {
                **{field: forged_receipt[axis] for field, axis in AXIS_MAP.items()},
                "evidence_receipts": {field: ["deadbeef" * 8] for field in AXIS_MAP},
            }
            bound["evaluation"] = {**manifest["evaluation"], "subject_checkpoint_sha256": forged_receipt["subject_checkpoint_sha256"]}

            with self.assertRaisesRegex(ParameterIdentityMismatch, "subject_checkpoint_sha256"):
                verify_parameter_identity_binding(
                    bound, forged_receipt,
                    checkpoint_manifest=manifest_path, model_config=config_path,
                )


if __name__ == "__main__":
    unittest.main()
