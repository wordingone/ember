# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for reusable raw-projector and checkpoint scaffolding."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import RawAudioProjector, RawPatchProjector, RestartDecoderConfig, UnifiedDecoder  # noqa: E402


class RestartDecoderModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        cls.contract_path = ROOT / "configs" / "ember-restart-3b.json"

    def test_genesis_metadata_is_clean_random(self) -> None:
        metadata = self.config.genesis_metadata(seed=17)
        self.assertEqual(metadata["initialization"], "random")
        self.assertIsNone(metadata["parent_checkpoint"])
        self.assertFalse(metadata["borrowed_weights"])
        self.assertFalse(metadata["teacher_outputs"])

    def test_raw_projectors_are_bias_free_trainable_soft_token_maps(self) -> None:
        image = RawPatchProjector(self.config)
        audio = RawAudioProjector(self.config)
        self.assertIsNone(image.linear.bias)
        self.assertIsNone(audio.linear.bias)
        self.assertTrue(image.linear.weight.requires_grad)
        self.assertTrue(audio.linear.weight.requires_grad)
        self.assertEqual(image(torch.randn(1, 48, 48, 3)).shape, (1, self.config.hidden_size))
        self.assertEqual(audio(torch.randn(1, 640)).shape, (1, self.config.hidden_size))

    def test_mixed_raw_image_audio_forward(self) -> None:
        model = UnifiedDecoder(self.config)
        ids = torch.tensor([[1, self.config.image_token_id, 2, self.config.audio_token_id]])
        logits = model(ids, image_patches=torch.randn(1, 48, 48, 3), audio_frames=torch.randn(1, 640), active_expert="audio")
        self.assertEqual(logits.shape, (1, 4, self.config.vocab_size))
        self.assertTrue(torch.isfinite(logits).all())

    def test_gradient_checkpointing_is_training_only(self) -> None:
        model = UnifiedDecoder(self.config)
        ids = torch.randint(0, self.config.vocab_size - 2, (1, 4))
        checkpoint = torch.utils.checkpoint.checkpoint
        model.train()
        with patch("torch.utils.checkpoint.checkpoint", wraps=checkpoint) as spy:
            model(ids, active_expert="reasoning")
        self.assertEqual(spy.call_count, self.config.layers)
        model.eval()
        with patch("torch.utils.checkpoint.checkpoint", wraps=checkpoint) as spy:
            model(ids, active_expert="reasoning")
        self.assertEqual(spy.call_count, 0)

    def test_contract_rejects_lied_sparse_total(self) -> None:
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        contract = copy.deepcopy(contract)
        contract["model"]["total_unique_trainable_parameters"] = 3_000_000_000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-total.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaises(ValueError):
                RestartDecoderConfig.from_contract(path)

    def test_production_materialization_is_guarded_and_meta_is_available(self) -> None:
        config = RestartDecoderConfig.from_contract()
        with self.assertRaises(ValueError):
            UnifiedDecoder(config)
        model = UnifiedDecoder(config, device="meta")
        self.assertEqual(model.token_embedding.weight.device.type, "meta")


if __name__ == "__main__":
    unittest.main()
