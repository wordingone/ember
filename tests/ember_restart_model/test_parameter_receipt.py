# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD checkpoint-bound sparse parameter counter receipt."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import write_parameter_receipt


class ParameterReceiptTests(unittest.TestCase):
    def test_binds_config_counter_checkpoint_and_preupdate_genesis_hashes(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=7)
        optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-4)
        genesis = model.expert_bank_genesis_hashes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            checkpoint = write_checkpoint_artifacts(model, optimizer, root / "checkpoint", launch_seed=7, rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)}, data_cursor={"shard": "owned-test-v1", "record_index": 0, "global_step": 0, "tokens_seen": 0}, model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=genesis)
            receipt = write_parameter_receipt(model, config_path, root / "checkpoint" / "checkpoint-manifest.json", genesis)
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(receipt["active_expert_ids"], ["reasoning"])
        self.assertEqual(receipt["expert_genesis_sha256"], genesis)
        self.assertRegex(receipt["counter_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
