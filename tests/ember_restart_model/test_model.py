# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU-small tests for the owned Ember restart decoder."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch


ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = ROOT / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOL_ROOT))

from model import (  # noqa: E402
    RawAudioProjector,
    RawPatchProjector,
    RestartDecoderConfig,
    UnifiedDecoder,
    count_unique_trainable_parameters,
)


class RestartDecoderModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = RestartDecoderConfig.small_for_tests(
            hidden_size=32,
            layers=2,
            attention_heads=4,
            vocab_size=64,
        )
        cls.contract_path = ROOT / "configs" / "ember-restart-3b.json"

    def test_genesis_metadata_is_deterministic_and_clean_random(self) -> None:
        first = self.config.genesis_metadata(seed=17)
        second = self.config.genesis_metadata(seed=17)

        self.assertEqual(first, second)
        self.assertEqual(first["initialization"], "random")
        self.assertIsNone(first["parent_checkpoint"])
        self.assertFalse(first["borrowed_weights"])
        self.assertFalse(first["teacher_outputs"])
        self.assertFalse(first["model_derived_data"])
        self.assertFalse(first["external_judges"])

    def test_small_text_forward_returns_decoder_logits(self) -> None:
        model = UnifiedDecoder(self.config)
        input_ids = torch.randint(0, self.config.vocab_size - 2, (2, 5))

        logits = model(input_ids)

        self.assertEqual(logits.shape, (2, 5, self.config.vocab_size))

    def test_raw_projectors_are_bias_free_trainable_soft_token_maps(self) -> None:
        patch_projector = RawPatchProjector(self.config)
        audio_projector = RawAudioProjector(self.config)

        self.assertIsNone(patch_projector.linear.bias)
        self.assertIsNone(audio_projector.linear.bias)
        self.assertTrue(patch_projector.linear.weight.requires_grad)
        self.assertTrue(audio_projector.linear.weight.requires_grad)
        self.assertEqual(
            patch_projector(torch.randn(1, 48, 48, 3)).shape,
            (1, self.config.hidden_size),
        )
        self.assertEqual(
            audio_projector(torch.randn(1, 640)).shape,
            (1, self.config.hidden_size),
        )

    def test_mixed_text_image_audio_markers_forward(self) -> None:
        model = UnifiedDecoder(self.config)
        image_id = self.config.image_token_id
        audio_id = self.config.audio_token_id
        input_ids = torch.tensor([[1, image_id, 2, audio_id, 3]])

        logits = model(
            input_ids,
            image_patches=torch.randn(1, 48, 48, 3),
            audio_frames=torch.randn(1, 640),
        )

        self.assertEqual(logits.shape, (1, 5, self.config.vocab_size))
        self.assertTrue(torch.isfinite(logits).all())

    def test_raw_marker_replacement_reaches_decoder_positions(self) -> None:
        model = UnifiedDecoder(self.config)
        image_id = self.config.image_token_id
        audio_id = self.config.audio_token_id
        input_ids = torch.tensor([[4, image_id, 5, audio_id]])
        hidden = model.token_embedding(input_ids)
        patch = torch.randn(1, 48, 48, 3)
        audio = torch.randn(1, 640)

        injected = model._inject_modality(
            hidden,
            input_ids,
            marker_id=image_id,
            raw_values=patch,
            projector=model.image_projector,
            name="image",
        )
        injected = model._inject_modality(
            injected,
            input_ids,
            marker_id=audio_id,
            raw_values=audio,
            projector=model.audio_projector,
            name="audio",
        )

        self.assertTrue(torch.allclose(injected[0, 1], model.image_projector(patch)[0]))
        self.assertTrue(torch.allclose(injected[0, 3], model.audio_projector(audio)[0]))

    def test_checkpoint_runs_per_layer_only_during_training(self) -> None:
        model = UnifiedDecoder(self.config)
        input_ids = torch.randint(0, self.config.vocab_size - 2, (1, 4))
        checkpoint = torch.utils.checkpoint.checkpoint

        model.train()
        with patch("torch.utils.checkpoint.checkpoint", wraps=checkpoint) as spy:
            model(input_ids)
        self.assertEqual(spy.call_count, self.config.layers)

        model.eval()
        with patch("torch.utils.checkpoint.checkpoint", wraps=checkpoint) as spy:
            model(input_ids)
        self.assertEqual(spy.call_count, 0)

    def test_production_contract_path_is_independent_of_cwd(self) -> None:
        old_cwd = Path.cwd()
        try:
            os.chdir(tempfile.gettempdir())
            config = RestartDecoderConfig.from_contract()
        finally:
            os.chdir(old_cwd)
        self.assertEqual(config.contract_name, "ember-restart-3b")
        self.assertGreaterEqual(config.parameter_count(), 3_000_000_000)

    def test_production_count_and_compatibility_api(self) -> None:
        config = RestartDecoderConfig.from_contract(self.contract_path)

        self.assertGreaterEqual(config.parameter_count(), 3_000_000_000)
        self.assertEqual(
            config.parameter_count(),
            config.calculate_unique_trainable_parameters(),
        )
        self.assertEqual(count_unique_trainable_parameters(config), config.parameter_count())

    def test_lied_downward_assertion_minimum_cannot_admit_sub_3b_contract(self) -> None:
        with self.contract_path.open(encoding="utf-8") as handle:
            contract = json.load(handle)
        contract = copy.deepcopy(contract)
        model = contract["model"]
        model["hidden_size"] = 32
        model["layers"] = 1
        model["attention_heads"] = 4
        model["vocab_size"] = 64
        model["image_projection"]["output_size"] = 32
        model["audio_projection"]["output_size"] = 32
        model["unique_trainable_parameters"] = (
            64 * 32 + (4 * 32 * 32 + 12 * 32 * 32) + (48 * 48 * 3) * 32 + 640 * 32
        )
        model["assertion_minimum_unique_trainable_parameters"] = 0

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lied-contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaises(ValueError):
                RestartDecoderConfig.from_contract(path)

    def test_contract_requires_tied_embeddings(self) -> None:
        with self.contract_path.open(encoding="utf-8") as handle:
            contract = json.load(handle)
        contract["model"]["tied_embeddings"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "untied.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaises(ValueError):
                RestartDecoderConfig.from_contract(path)

    def test_marker_ids_are_distinct_nonnegative_and_in_vocab(self) -> None:
        kwargs = dict(hidden_size=32, layers=1, attention_heads=4, vocab_size=64)
        with self.assertRaises(ValueError):
            RestartDecoderConfig(**kwargs, image_token_id=-1, audio_token_id=63)
        with self.assertRaises(ValueError):
            RestartDecoderConfig(**kwargs, image_token_id=64, audio_token_id=63)
        with self.assertRaises(ValueError):
            RestartDecoderConfig(**kwargs, image_token_id=62, audio_token_id=62)

    def test_production_materialization_is_guarded(self) -> None:
        config = RestartDecoderConfig.from_contract()

        with self.assertRaises(ValueError):
            UnifiedDecoder(config)

        model = UnifiedDecoder(config, device="meta")
        self.assertEqual(model.token_embedding.weight.device.type, "meta")


if __name__ == "__main__":
    unittest.main()
