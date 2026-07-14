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
        self.assertEqual(batch["image_patches"].shape, (1, 1, 48, 48, 3))
        self.assertEqual(batch["audio_frames"].shape, (1, 1, 640))
        self.assertEqual(batch["active_expert"], "reasoning")


    def test_decoded_record_forwards_patch_frame_sequences_coordinates_and_span(self) -> None:
        record = self._record()
        image_a = bytes(index % 251 for index in range(48 * 48 * 3))
        image_b = bytes((index + 7) % 251 for index in range(48 * 48 * 3))
        audio_a = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        audio_b = (torch.arange(640, dtype=torch.int16) - 120).numpy().tobytes()
        record.update({
            "token_ids": [1, self.config.image_token_id, self.config.image_token_id, self.config.audio_token_id, self.config.audio_token_id, 2],
            "target_ids": [2, 3, 4, 5, 6, 7],
            "image_patches_u8_base64": [base64.b64encode(image_a).decode("ascii"), base64.b64encode(image_b).decode("ascii")],
            "audio_frames_i16le_base64": [base64.b64encode(audio_a).decode("ascii"), base64.b64encode(audio_b).decode("ascii")],
            "image_coordinates": [[0, 0], [1, 0]],
            "multimodal_spans": [
                {"start": 1, "length": 2, "modality": "image", "attention_mode": "isolated"},
                {"start": 3, "length": 2, "modality": "audio", "attention_mode": "causal"},
            ],
        })
        batch = decode_owned_batch(record, self.config, device=torch.device("cpu"))
        self.assertEqual(batch["image_patches"].shape, (1, 2, 48, 48, 3))
        self.assertEqual(batch["audio_frames"].shape, (1, 2, 640))
        self.assertTrue(torch.equal(batch["image_coordinates"], torch.tensor([[0, 0], [1, 0]])))
        self.assertEqual([(span.start, span.length, span.modality) for span in batch["spans"]], [(1, 2, "image"), (3, 2, "audio")])
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
