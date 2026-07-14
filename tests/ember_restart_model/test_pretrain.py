# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU-small acceptance for a real resumable Ember pretraining segment."""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import RestartDecoderConfig, UnifiedDecoder
from pretrain import run_pretraining_segment


class PretrainingSegmentTests(unittest.TestCase):
    def _record(self, config: RestartDecoderConfig) -> dict[str, object]:
        image = bytes(index % 251 for index in range(48 * 48 * 3))
        audio = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        return {
            "schema_version": "ember-owned-bootstrap-batch-v1",
            "sample_id": "owned-pretrain-0001",
            "token_ids": [1, config.image_token_id, 2, config.audio_token_id],
            "target_ids": [2, 3, 4, 5],
            "image_u8_base64": base64.b64encode(image).decode("ascii"),
            "audio_i16le_base64": base64.b64encode(audio).decode("ascii"),
            "active_expert": "reasoning",
        }

    def test_segment_updates_real_model_and_emits_checkpoint_cadence(self) -> None:
        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=17)
        optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-4)
        checkpoints: list[int] = []
        result = run_pretraining_segment(
            model=model,
            optimizer=optimizer,
            records=[self._record(config), self._record(config)],
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=1,
            checkpoint_callback=lambda step, _result: checkpoints.append(step),
        )
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["tokens_seen"], 8)
        self.assertEqual(result["modality_examples"], {"text": 2, "image": 2, "audio": 2})
        self.assertEqual(checkpoints, [1, 2])
        self.assertTrue(all(torch.isfinite(torch.tensor(value)) for value in result["losses"]))


if __name__ == "__main__":
    unittest.main()