# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD checkpoint artifacts for the sparse vertical slice."""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import _default_optimizer_contract, _optimizer_realization, _select_detached_state, _validate_runtime_optimizer_realization, checkpoint_commit_preflight, load_checkpoint_artifacts, write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from run_vertical_slice import load_optimizer_contract


class CheckpointArtifactTests(unittest.TestCase):
    def test_commit_preflight_requires_streaming_peak_plus_reserve(self) -> None:
        plan = checkpoint_commit_preflight(
            available_commit_bytes=10_000,
            streaming_peak_bytes=4_000,
            reserve_bytes=6_000,
        )
        self.assertEqual(plan["required_commit_bytes"], 10_000)
        with self.assertRaisesRegex(RuntimeError, "host commit reserve"):
            checkpoint_commit_preflight(
                available_commit_bytes=9_999,
                streaming_peak_bytes=4_000,
                reserve_bytes=6_000,
            )

    def test_serialization_state_views_reuse_tensor_storage_without_cpu_clones(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=10)
        source = model.state_dict()
        shared = _select_detached_state(source, lambda name: ".experts." not in name)
        vision = _select_detached_state(source, lambda name: ".experts.vision." in name)
        self.assertTrue(shared)
        self.assertTrue(vision)
        for selected in (shared, vision):
            for name, tensor in selected.items():
                self.assertEqual(tensor.device, source[name].device)
                self.assertEqual(tensor.data_ptr(), source[name].data_ptr())

    def test_preexisting_target_is_refused_before_staging_or_verifier(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint-existing"
            target.mkdir()
            sentinel = target / "sentinel"
            sentinel.write_bytes(b"known-good")
            verifier = Mock()
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=11,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=verifier,
                )
            self.assertEqual(sentinel.read_bytes(), b"known-good")
            self.assertFalse(verifier.called)
            self.assertEqual(list(Path(directory).glob(".*.staging")), [])
    def test_counter_verifier_runs_on_staging_before_atomic_promotion(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=12)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checkpoint-atomic"
            observations: list[tuple[bool, bool, bool, bool, bool]] = []

            def verify(staging: Path, _receipt: dict[str, object]) -> None:
                observations.append((staging.is_dir(), target.exists(), (staging / "checkpoint-manifest.json").is_file(), f".{os.getpid()}." in staging.name, (staging / ".writer-lease.json").is_file()))
                (staging / "parameter-counter-receipt.json").write_text('{"result":"MEASURED"}' + chr(10), encoding="utf-8")

            with patch("checkpoint_artifacts.available_host_commit_bytes", return_value=1024**3):
                receipt = write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=12,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    host_commit_reserve_bytes=128 * 1024**2,
                    pre_publish_verifier=verify,
                )
            self.assertEqual(observations, [(True, False, True, True, True)])
            self.assertTrue(target.joinpath("parameter-counter-receipt.json").is_file())
            self.assertFalse(target.joinpath(".writer-lease.json").exists())
            self.assertEqual(receipt["checkpoint_manifest_sha256"], __import__("hashlib").sha256(target.joinpath("checkpoint-manifest.json").read_bytes()).hexdigest())
            self.assertEqual(receipt["host_commit_preflight"]["available_commit_bytes"], 1024**3)
            self.assertEqual(receipt["host_commit_preflight"]["reserve_bytes"], 128 * 1024**2)

    def test_counter_verifier_failure_removes_staging_without_publishing(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=13)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "checkpoint-failed"
            with self.assertRaisesRegex(RuntimeError, "counter failed"):
                write_checkpoint_artifacts(
                    model, optimizer, target, launch_seed=13,
                    rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
                    data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0},
                    model_config_sha256="c" * 64, contract_sha256="d" * 64,
                    expert_genesis_sha256=model.expert_bank_genesis_hashes(),
                    pre_publish_verifier=lambda _staging, _receipt: (_ for _ in ()).throw(RuntimeError("counter failed")),
                )
            self.assertFalse(target.exists())
            self.assertEqual(list(parent.glob(".*.staging")), [])
            evidence = list((parent / ".checkpoint-quarantine").glob("checkpoint-write-failed-*.json"))
            self.assertEqual(len(evidence), 1)
            payload = __import__("json").loads(evidence[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["error_type"], "RuntimeError")
            self.assertEqual(payload["error_message"], "counter failed")
            self.assertEqual(payload["target"], "checkpoint-failed")
            self.assertRegex(payload["checkpoint_manifest_sha256"], r"^[0-9a-f]{64}$")
            self.assertLess(evidence[0].stat().st_size, 64 * 1024)
            self.assertEqual(
                evidence[0].stem.removeprefix("checkpoint-write-failed-"),
                __import__("hashlib").sha256(evidence[0].read_bytes()).hexdigest(),
            )
    def test_refuses_checkpoint_receipt_without_optimizer_contract(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = write_checkpoint_artifacts(model, optimizer, root, launch_seed=11, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            receipt.pop("optimizer_contract")
            restored = UnifiedDecoder(config, genesis_seed=12)
            with self.assertRaisesRegex(ValueError, "optimizer contract"):
                load_checkpoint_artifacts(restored, optimizer, root, receipt)
    def test_writes_and_restores_hashed_shared_and_four_expert_shards(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            receipt = write_checkpoint_artifacts(model, optimizer, Path(directory) / "checkpoint-0001", launch_seed=11, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            self.assertEqual(receipt["contract_version"], 3)
            self.assertEqual(receipt["architecture_revision"], "ember-sparse-3b-v2")
            restored = UnifiedDecoder(config, genesis_seed=99)
            restore_optimizer = torch.optim.AdamW((parameter for parameter in restored.parameters() if parameter.requires_grad), lr=1e-4)
            load_checkpoint_artifacts(restored, restore_optimizer, Path(directory) / "checkpoint-0001", receipt)
            self.assertEqual(restored.active_expert, "reasoning")
        self.assertEqual(set(receipt["expert_checkpoint_sha256"]), {"vision", "audio", "reasoning", "tool"})
        self.assertEqual(len(receipt["shards"]), 6)
        self.assertEqual(receipt["launch_seed"], 11)
        self.assertIn("optimizer_contract", receipt)
        self.assertRegex(receipt["optimizer_realization"]["optimizer_contract_sha256"], r"^[0-9a-f]{64}$")


    def test_paged_8bit_realization_reads_live_args_not_receipt_fields(self) -> None:
        with warnings.catch_warnings():

            warnings.simplefilter("ignore", DeprecationWarning)

            import bitsandbytes as bnb
        model = UnifiedDecoder(RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64), genesis_seed=11)
        optimizer = bnb.optim.PagedAdamW8bit(model.parameters(), lr=1e-5, weight_decay=0.01, percentile_clipping=100, block_wise=True)
        contract = load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
        realization = _optimizer_realization(optimizer, contract)
        self.assertEqual(realization["implementation"], "bitsandbytes.optim.PagedAdamW8bit")
    def test_writes_and_restores_shared_semantic_checkpoint(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=17)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "semantic-checkpoint"
            receipt = write_checkpoint_artifacts(
                model, optimizer, root, launch_seed=17,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))},
                data_cursor={"shard": "TOKEN-SHARDS-V0:receipt", "record_index": 2, "global_step": 2, "tokens_seen": 2048},
                model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            )
            restored = UnifiedDecoder(config, genesis_seed=18)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
        self.assertEqual(receipt["active_expert_ids"], ["shared"])
        self.assertEqual(restored.active_expert, "shared")
    def test_optimizer_realization_recomputes_runtime_class_source_hyperparameters_and_state_format(self) -> None:
        model = UnifiedDecoder(RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64), genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=0.02)
        contract = _default_optimizer_contract(optimizer)
        self.assertEqual(contract["hyperparameters"], {"param_group_count": 1, "learning_rate": 1e-4, "weight_decay": 0.02})
        realization = _optimizer_realization(optimizer, contract)
        for field, value in (("implementation", "torch.optim.SGD"), ("state_format", "forged-state")):
            tampered = dict(contract); tampered[field] = value
            with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
                _optimizer_realization(optimizer, tampered)
        tampered = {**contract, "hyperparameters": {**contract["hyperparameters"], "learning_rate": 2e-4}}
        with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
            _optimizer_realization(optimizer, tampered)
        forged_source = {**realization, "implementation_source_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
            _validate_runtime_optimizer_realization(optimizer, contract, forged_source)
    def test_restore_rejects_a_runtime_optimizer_that_does_not_realize_the_receipt(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = write_checkpoint_artifacts(model, optimizer, root, launch_seed=11, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes())
            restored = UnifiedDecoder(config, genesis_seed=12)
            wrong_optimizer = torch.optim.SGD(restored.parameters(), lr=1e-4)
            with self.assertRaisesRegex(ValueError, "runtime optimizer realization"):
                load_checkpoint_artifacts(restored, wrong_optimizer, root, receipt)
    def test_architecture_receipt_uses_measured_active_shared_route(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=23)
        model._activate_expert("shared")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            receipt = write_checkpoint_artifacts(
                model, optimizer, Path(directory) / "checkpoint-architecture", launch_seed=23,
                rng_state={"cpu": torch.get_rng_state().clone(), "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8))},
                data_cursor={"shard": "TOKEN-SHARDS-V0:test", "record_index": 1, "global_step": 1, "tokens_seen": 16},
                model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            )
        expected = measure_parameter_counts(model)
        architecture = receipt["architecture"]
        self.assertEqual(architecture["revision"], "ember-sparse-3b-v2")
        for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
            self.assertEqual(architecture[field], expected[field])
        self.assertEqual(architecture["shared_text_ffn"], "always_active_SwiGLU_4H")
if __name__ == "__main__":
    unittest.main()
