# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD acceptance for decoded, domain-routed raw multimodal batches."""

from __future__ import annotations

import base64
import copy
import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import batch
from batch import decode_owned_batch, run_one_batch
from parameter_counter import measure_parameter_counts
from run_vertical_slice import _counter_expected_counts
from model import RestartDecoderConfig, UnifiedDecoder


class VerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)

    def _record(self, expert: str = "vision") -> dict[str, object]:
        image = bytes(index % 251 for index in range(48 * 48 * 3))
        audio = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes()
        if expert == "vision":
            return {"schema_version": "ember-owned-bootstrap-batch-v1", "sample_id": "owned-vision-0001", "token_ids": [1, self.config.image_token_id, 2], "target_ids": [2, 3, 4], "image_patches_u8_base64": [base64.b64encode(image).decode("ascii")], "image_coordinates": [[0, 0]], "multimodal_spans": [{"start": 1, "length": 1, "modality": "image", "attention_mode": "isolated"}], "active_expert": "vision"}
        return {"schema_version": "ember-owned-bootstrap-batch-v1", "sample_id": "owned-audio-0001", "token_ids": [1, self.config.audio_token_id, 2], "target_ids": [2, 3, 4], "audio_frames_i16le_base64": [base64.b64encode(audio).decode("ascii")], "image_coordinates": [], "multimodal_spans": [{"start": 1, "length": 1, "modality": "audio", "attention_mode": "causal"}], "active_expert": "audio"}

    def test_decoded_domain_records_retain_only_their_raw_modality(self) -> None:
        vision = decode_owned_batch(self._record("vision"), self.config, device=torch.device("cpu"))
        audio = decode_owned_batch(self._record("audio"), self.config, device=torch.device("cpu"))
        self.assertEqual(vision["image_patches"].shape, (1, 1, 48, 48, 3))
        self.assertIsNone(vision["audio_frames"])
        self.assertIsNone(audio["image_patches"])
        self.assertEqual(audio["audio_frames"].shape, (1, 1, 640))
        self.assertEqual((vision["active_expert"], audio["active_expert"]), ("vision", "audio"))

    def test_verified_specialist_schema_reaches_its_declared_route(self) -> None:
        record = self._record("vision")
        record["schema_version"] = "ember-owned-semantic-record-v1"
        decoded = decode_owned_batch(record, self.config, device=torch.device("cpu"))
        self.assertEqual(decoded["active_expert"], "vision")
        self.assertEqual(decoded["image_patches"].shape, (1, 1, 48, 48, 3))
    def test_audio_frame_bytes_decode_as_explicit_little_endian_i16(self) -> None:
        raw = bytes((0x00, 0x80, 0xFF, 0xFF, 0x00, 0x00, 0xFF, 0x7F))
        self.assertTrue(hasattr(batch, "_decode_i16le"))
        self.assertEqual(batch._decode_i16le(raw), [-32768, -1, 0, 32767])
        full_frame = raw + (b"\x00" * ((640 * 2) - len(raw)))
        record = self._record("audio")
        record["audio_frames_i16le_base64"] = [base64.b64encode(full_frame).decode("ascii")]
        decoded = decode_owned_batch(record, self.config, device=torch.device("cpu"))
        expected = torch.tensor([-1.0, -1.0 / 32768.0, 0.0, 32767.0 / 32768.0])
        self.assertTrue(torch.allclose(decoded["audio_frames"][0, 0, :4], expected))

    def test_multi_patch_coordinates_and_multi_frame_temporal_order_reach_decoder(self) -> None:
        vision = self._record("vision")
        image_a = bytes(index % 251 for index in range(48 * 48 * 3))
        image_b = bytes((index + 7) % 251 for index in range(48 * 48 * 3))
        vision.update({"token_ids": [1, self.config.image_token_id, self.config.image_token_id, 2], "target_ids": [2, 3, 4, 5], "image_patches_u8_base64": [base64.b64encode(image_a).decode("ascii"), base64.b64encode(image_b).decode("ascii")], "image_coordinates": [[0, 0], [1, 0]], "multimodal_spans": [{"start": 1, "length": 2, "modality": "image", "attention_mode": "isolated"}]})
        model = UnifiedDecoder(self.config, genesis_seed=79).eval()
        batch = decode_owned_batch(vision, self.config, device=torch.device("cpu"))
        baseline = model(batch["input_ids"], image_patches=batch["image_patches"], image_coordinates=batch["image_coordinates"], spans=batch["spans"], active_expert="vision")
        shifted = copy.deepcopy(vision); shifted["image_coordinates"] = [[1, 0], [0, 0]]
        shifted_batch = decode_owned_batch(shifted, self.config, device=torch.device("cpu"))
        self.assertFalse(torch.equal(baseline, model(shifted_batch["input_ids"], image_patches=shifted_batch["image_patches"], image_coordinates=shifted_batch["image_coordinates"], spans=shifted_batch["spans"], active_expert="vision")))
        audio = self._record("audio")
        audio_a = (torch.arange(640, dtype=torch.int16) - 320).numpy().tobytes(); audio_b = (torch.arange(640, dtype=torch.int16) - 120).numpy().tobytes()
        audio.update({"token_ids": [1, self.config.audio_token_id, self.config.audio_token_id, 2], "target_ids": [2, 3, 4, 5], "audio_frames_i16le_base64": [base64.b64encode(audio_a).decode("ascii"), base64.b64encode(audio_b).decode("ascii")], "multimodal_spans": [{"start": 1, "length": 2, "modality": "audio", "attention_mode": "causal"}]})
        audio_batch = decode_owned_batch(audio, self.config, device=torch.device("cpu"))
        temporal = model(audio_batch["input_ids"], audio_frames=audio_batch["audio_frames"], image_coordinates=audio_batch["image_coordinates"], spans=audio_batch["spans"], active_expert="audio")
        reversed_audio = copy.deepcopy(audio); reversed_audio["audio_frames_i16le_base64"].reverse()
        reversed_batch = decode_owned_batch(reversed_audio, self.config, device=torch.device("cpu"))
        self.assertFalse(torch.allclose(temporal, model(reversed_batch["input_ids"], audio_frames=reversed_batch["audio_frames"], image_coordinates=reversed_batch["image_coordinates"], spans=reversed_batch["spans"], active_expert="audio")))

    def test_rejects_marker_value_coordinate_span_and_expert_domain_mismatches(self) -> None:
        missing_value = self._record("vision"); missing_value["token_ids"] = [1, self.config.image_token_id, self.config.image_token_id, 2]; missing_value["target_ids"] = [2, 3, 4, 5]
        with self.assertRaisesRegex(ValueError, "marker count"):
            decode_owned_batch(missing_value, self.config, device=torch.device("cpu"))
        wrong_coordinates = self._record("vision"); wrong_coordinates["image_coordinates"] = []
        with self.assertRaisesRegex(ValueError, "image_coordinates"):
            decode_owned_batch(wrong_coordinates, self.config, device=torch.device("cpu"))
        wrong_span = self._record("vision"); wrong_span["multimodal_spans"] = []
        with self.assertRaisesRegex(ValueError, "cover exactly"):
            decode_owned_batch(wrong_span, self.config, device=torch.device("cpu"))
        wrong_domain = self._record("vision"); wrong_domain["active_expert"] = "reasoning"
        with self.assertRaisesRegex(ValueError, "routed raw modalities"):
            decode_owned_batch(wrong_domain, self.config, device=torch.device("cpu"))

    def test_production_batch_rejects_omitted_coordinates_or_spans(self) -> None:
        missing_coordinates = self._record("vision"); del missing_coordinates["image_coordinates"]
        with self.assertRaisesRegex(ValueError, "image_coordinates"):
            decode_owned_batch(missing_coordinates, self.config, device=torch.device("cpu"))
        missing_spans = self._record("vision"); del missing_spans["multimodal_spans"]
        with self.assertRaisesRegex(ValueError, "multimodal_spans"):
            decode_owned_batch(missing_spans, self.config, device=torch.device("cpu"))

    def test_counter_emits_total_and_single_expert_fields(self) -> None:
        model = UnifiedDecoder(self.config)
        counts = measure_parameter_counts(model)
        self.assertEqual(counts["unique_parameters"], model.count_unique_trainable_parameters(include_frozen=True))
        self.assertEqual(counts["active_parameters"], model.count_unique_trainable_parameters())
        self.assertLess(counts["active_parameters"], counts["unique_parameters"])
        self.assertEqual(counts["active_expert_ids"], ["reasoning"])

    def test_counter_expectations_follow_the_routed_expert_at_publication(self) -> None:
        model = UnifiedDecoder(self.config)
        model._activate_expert("vision")
        counts = _counter_expected_counts(model)
        self.assertEqual(counts["active_expert_ids"], ["vision"])
        self.assertEqual(counts["active_parameters"], model.count_unique_trainable_parameters())
    def test_one_real_small_domain_batch_updates_only_selected_expert(self) -> None:
        result = run_one_batch(self._record("vision"), self.config, device=torch.device("cpu"))
        self.assertTrue(torch.isfinite(torch.tensor(result["loss"])))
        self.assertEqual(result["active_expert"], "vision")
        self.assertLess(result["episode_trainable_parameters"], result["total_unique_parameters"])


    def test_decoded_image_patch_preserves_raw_u8_endpoints_for_projector(self) -> None:
        record = self._record("vision")
        raw = bytes([0, 255, 0]) * (48 * 48)
        record["image_patches_u8_base64"] = [base64.b64encode(raw).decode("ascii")]
        batch = decode_owned_batch(record, self.config, device=torch.device("cpu"))
        self.assertEqual(batch["image_patches"][0, 0, 0, 0].tolist(), [0.0, 255.0, 0.0])


if __name__ == "__main__":
    unittest.main()