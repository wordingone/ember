# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD checkpoint artifacts for the sparse vertical slice."""

from __future__ import annotations

import sys
import tempfile
import warnings
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import _default_optimizer_contract, _optimizer_realization, _validate_runtime_optimizer_realization, load_checkpoint_artifacts, write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder
from run_vertical_slice import load_optimizer_contract


class CheckpointArtifactTests(unittest.TestCase):
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
        optimizer = bnb.optim.PagedAdamW8bit(model.parameters(), lr=1e-5, weight_decay=0.01, percentile_clipping=5, block_wise=True)
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
if __name__ == "__main__":
    unittest.main()
