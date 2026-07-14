# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD checkpoint artifacts for the sparse vertical slice."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import load_checkpoint_artifacts, write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder


class CheckpointArtifactTests(unittest.TestCase):
    def test_writes_and_restores_hashed_shared_and_four_expert_shards(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=11)
        optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            receipt = write_checkpoint_artifacts(model, optimizer, Path(directory), launch_seed=11)
            restored = UnifiedDecoder(config, genesis_seed=99)
            restore_optimizer = torch.optim.AdamW((parameter for parameter in restored.parameters() if parameter.requires_grad), lr=1e-4)
            load_checkpoint_artifacts(restored, restore_optimizer, Path(directory), receipt)
            self.assertEqual(restored.active_expert, "reasoning")
        self.assertEqual(set(receipt["expert_checkpoint_sha256"]), {"vision", "audio", "reasoning", "tool"})
        self.assertEqual(len(receipt["shards"]), 5)
        self.assertEqual(receipt["launch_seed"], 11)


if __name__ == "__main__":
    unittest.main()
