# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The trusted parameter counter must inspect checkpoint realization under -I."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder


class CounterCliTests(unittest.TestCase):
    def test_isolated_cli_rejects_corrupt_realization_and_reports_measurement(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=7)
        optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_payload = {
                "architecture_revision": "ember-sparse-3b-v1",
                "model": {
                    "hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                    "tied_embeddings": True,
                    "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                    "audio_projection": {"frame_samples": 640, "output_size": 32},
                    "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                },
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
            write_checkpoint_artifacts(
                model, optimizer, root / "checkpoint", launch_seed=7,
                rng_state_sha256={"cpu": "a" * 64, "cuda": "b" * 64},
                data_cursor={"shard": "owned-bootstrap-v1", "record": 0},
                model_config_sha256=config_sha256, contract_sha256="d" * 64, expert_genesis_sha256=model.expert_bank_genesis_hashes(),
            )
            command = [
                sys.executable, "-I", str(ROOT / "tools" / "ember-restart-3b" / "parameter_counter.py"),
                "--model-config", str(config_path),
                "--checkpoint-manifest", str(root / "checkpoint" / "checkpoint-manifest.json"),
                "--active-expert", "reasoning",
            ]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            measured = json.loads(completed.stdout)
            self.assertEqual(measured["result"], "MEASURED")
            self.assertEqual(measured["active_expert_ids"], ["reasoning"])
            self.assertRegex(measured["counter_sha256"], r"^[0-9a-f]{64}$")
            (root / "checkpoint" / "expert-tool.pt").write_bytes(b"corrupt")
            rejected = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("mismatch", rejected.stderr)


if __name__ == "__main__":
    unittest.main()