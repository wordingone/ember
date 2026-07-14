# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed checkpoint publication and restore tests."""

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


class CheckpointIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        self.model = UnifiedDecoder(self.config, genesis_seed=7)
        self.optimizer = torch.optim.AdamW((p for p in self.model.parameters() if p.requires_grad), lr=1e-4)

    def _write(self, root: Path) -> dict[str, object]:
        return write_checkpoint_artifacts(
            self.model, self.optimizer, root, launch_seed=7,
            rng_state_sha256={"cpu": "a" * 64, "cuda": "b" * 64},
            data_cursor={"shard": "owned-bootstrap-v1", "record": 0},
            model_config_sha256="c" * 64, contract_sha256="d" * 64, expert_genesis_sha256=self.model.expert_bank_genesis_hashes(),
        )

    def test_manifest_is_newline_terminated_and_binds_replay_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self._write(root)
            raw_manifest = (root / "checkpoint-manifest.json").read_bytes()
        self.assertTrue(raw_manifest.endswith(b"\n"))
        self.assertEqual(receipt["rng_state_sha256"]["cpu"], "a" * 64)
        self.assertEqual(receipt["data_cursor"]["record"], 0)
        self.assertEqual(receipt["model_config_sha256"], "c" * 64)
        self.assertEqual(receipt["contract_sha256"], "d" * 64)
        self.assertRegex(receipt["checkpoint_manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(receipt["shards"]), 5)

    def test_restore_does_not_mutate_model_when_any_shard_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self._write(root)
            (root / "expert-tool.pt").write_bytes(b"corrupted")
            restored = UnifiedDecoder(self.config, genesis_seed=99)
            before = next(restored.parameters()).detach().clone()
            restore_optimizer = torch.optim.AdamW((p for p in restored.parameters() if p.requires_grad), lr=1e-4)
            with self.assertRaisesRegex(ValueError, "expert shard hash mismatch: tool"):
                load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
            self.assertTrue(torch.equal(before, next(restored.parameters()).detach()))


if __name__ == "__main__":
    unittest.main()