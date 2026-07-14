# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD proof for a real decoded raw multimodal training batch."""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from batch import decode_owned_batch, run_one_batch  # noqa: E402
from parameter_counter import measure_parameter_counts  # noqa: E402
from model import RestartDecoderConfig  # noqa: E402


class VerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)

    def _record(self) -> dict[str, object]:
        image = bytes((index % 251 for index in range(48 * 48 * 3)))
        audio = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        return {
            "schema_version": "ember-owned-bootstrap-batch-v1",
            "sample_id": "owned-bootstrap-0001",
            "token_ids": [1, self.config.image_token_id, 2, self.config.audio_token_id],
            "target_ids": [2, 3, 4, 5],
            "image_u8_base64": base64.b64encode(image).decode("ascii"),
            "audio_i16le_base64": base64.b64encode(audio).decode("ascii"),
            "active_expert": "reasoning",
        }

    def test_decoded_record_retains_raw_modalities_and_declared_expert(self) -> None:
        batch = decode_owned_batch(self._record(), self.config, device=torch.device("cpu"))
        self.assertEqual(batch["input_ids"].shape, (1, 4))
        self.assertEqual(batch["image_patches"].shape, (1, 48, 48, 3))
        self.assertEqual(batch["audio_frames"].shape, (1, 640))
        self.assertEqual(batch["active_expert"], "reasoning")

    def test_counter_emits_total_and_single_expert_fields(self) -> None:
        from model import UnifiedDecoder
        model = UnifiedDecoder(self.config)
        counts = measure_parameter_counts(model)
        self.assertEqual(counts["unique_parameters"], model.count_unique_trainable_parameters(include_frozen=True))
        self.assertEqual(counts["active_parameters"], model.count_unique_trainable_parameters())
        self.assertEqual(counts["episode_trainable_parameters"], counts["active_parameters"])
        self.assertLess(counts["active_parameters"], counts["unique_parameters"])
        self.assertEqual(counts["active_expert_ids"], ["reasoning"])

    def test_one_real_small_batch_updates_only_one_expert_path(self) -> None:
        result = run_one_batch(self._record(), self.config, device=torch.device("cpu"))
        self.assertTrue(torch.isfinite(torch.tensor(result["loss"])))
        self.assertEqual(result["active_expert"], "reasoning")
        self.assertLess(result["episode_trainable_parameters"], result["total_unique_parameters"])
        self.assertGreater(result["episode_trainable_parameters"], 0)


if __name__ == "__main__":
    unittest.main()
