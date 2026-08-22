# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for reusable raw-projector and checkpoint scaffolding."""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import RMSNorm, RawAudioProjector, RawPatchProjector, RestartDecoderConfig, UnifiedDecoder  # noqa: E402


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

    def test_capture_static_marker_indices_avoid_tensor_to_host_sync_and_match_eager(self) -> None:
        model = UnifiedDecoder(self.config)
        model.eval()
        ids = torch.tensor([[
            1, self.config.image_token_id, 2, self.config.audio_token_id,
        ]])
        image = torch.randn(1, 48, 48, 3)
        audio = torch.randn(1, 640)
        with torch.no_grad():
            eager = model(
                ids,
                image_patches=image,
                audio_frames=audio,
                active_expert="audio",
            )
            with patch.object(
                torch.Tensor,
                "item",
                side_effect=AssertionError("capture-static forward synchronized to host"),
            ):
                capture_static = model(
                    ids,
                    image_patches=image,
                    audio_frames=audio,
                    active_expert="audio",
                    static_image_marker_indices=torch.tensor([1]),
                    static_audio_marker_indices=torch.tensor([3]),
                )
        torch.testing.assert_close(capture_static, eager, rtol=0.0, atol=0.0)

    def test_forward_is_total_over_text_only_input_colliding_with_modality_markers(self) -> None:
        # image_token_id/audio_token_id are ordinary emittable vocab ids, not reserved
        # out-of-band markers (issue #1725). A text-only forward (no image_patches, no
        # audio_frames) must complete even when a token in input_ids happens to equal
        # one of them by coincidence.
        model = UnifiedDecoder(self.config)
        ids = torch.tensor([[1, self.config.image_token_id, self.config.audio_token_id, 2]])
        logits = model(ids, active_expert="reasoning")
        self.assertEqual(logits.shape, (1, 4, self.config.vocab_size))
        self.assertTrue(torch.isfinite(logits).all())

    def test_text_only_collision_does_not_inject_modality_embedding(self) -> None:
        # A colliding marker id with no raw modality tensor supplied must be embedded
        # as an ordinary token, not silently treated as a zero/garbage modality slot.
        model = UnifiedDecoder(self.config)
        model.eval()
        ids = torch.tensor([[1, self.config.image_token_id, 2]])
        with torch.no_grad():
            hidden_states = model.token_embedding(ids)
            injected, image_mask = model._inject_modality(
                hidden_states,
                ids,
                marker_id=self.config.image_token_id,
                raw_values=None,
                projector=model.image_projector,
                name="image",
            )
        self.assertTrue(torch.equal(injected, hidden_states))
        self.assertFalse(bool(image_mask.any()))

    def test_raw_modality_values_without_marker_still_raise(self) -> None:
        # The genuine caller-error case (raw tensor supplied but no marker present)
        # must still be rejected -- only the text-only-collision case is tolerated.
        model = UnifiedDecoder(self.config)
        ids = torch.tensor([[1, 2, 3]])
        with self.assertRaises(ValueError):
            model(ids, image_patches=torch.randn(1, 48, 48, 3))

    def test_gradient_checkpointing_is_training_only(self) -> None:
        model = UnifiedDecoder(self.config)
        ids = torch.randint(0, self.config.vocab_size - 2, (1, 4))
        checkpoint = torch.utils.checkpoint.checkpoint
        model.train()
        with patch("torch.utils.checkpoint.checkpoint", wraps=checkpoint) as spy:
            model(ids, active_expert="reasoning")
        self.assertEqual(spy.call_count, self.config.layers)
        self.assertTrue(all(call.kwargs.get("preserve_rng_state") is True for call in spy.call_args_list))
        self.assertTrue(all(call.kwargs.get("use_reentrant") is False for call in spy.call_args_list))
        model.eval()
        with patch("torch.utils.checkpoint.checkpoint", wraps=checkpoint) as spy:
            model(ids, active_expert="reasoning")
        self.assertEqual(spy.call_count, 0)

    def test_gradient_checkpointing_matches_uncheckpointed_logits_and_every_gradient(self) -> None:
        seed = 314159
        ids = torch.tensor([[1, 2, 3, 4], [4, 3, 2, 1]])
        torch.manual_seed(seed)
        without_checkpointing = UnifiedDecoder(dataclasses.replace(self.config, gradient_checkpointing=False))
        torch.manual_seed(seed)
        with_checkpointing = UnifiedDecoder(dataclasses.replace(self.config, gradient_checkpointing=True))
        without_checkpointing.train()
        with_checkpointing.train()

        logits_without = without_checkpointing(ids, active_expert="reasoning")
        logits_with = with_checkpointing(ids, active_expert="reasoning")
        torch.testing.assert_close(logits_with, logits_without, rtol=1e-6, atol=1e-6)
        logits_without.square().mean().backward()
        logits_with.square().mean().backward()

        gradients_without = dict(without_checkpointing.named_parameters())
        gradients_with = dict(with_checkpointing.named_parameters())
        self.assertEqual(set(gradients_with), set(gradients_without))
        for name in gradients_without:
            left = gradients_without[name].grad
            right = gradients_with[name].grad
            self.assertEqual(left is None, right is None, name)
            if left is not None and right is not None:
                torch.testing.assert_close(right, left, rtol=1e-6, atol=1e-6, msg=name)
    def test_contract_rejects_lied_sparse_total(self) -> None:
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        contract = copy.deepcopy(contract)
        contract["model"]["total_unique_trainable_parameters"] = 3_000_000_000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-total.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaises(ValueError):
                RestartDecoderConfig.from_contract(path)

    def test_production_contract_requires_explicit_per_head_qk_rmsnorm(self) -> None:
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        contract = copy.deepcopy(contract)
        contract["model"]["normalization"]["qk"] = "disabled"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-qk-norm.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Q/K RMSNorm"):
                RestartDecoderConfig.from_contract(path)

    def test_attention_applies_trainable_per_head_qk_rmsnorm_before_rope(self) -> None:
        model = UnifiedDecoder(self.config)
        attention = model.layers[0].attention
        self.assertIsInstance(attention.q_norm, RMSNorm)
        self.assertIsInstance(attention.k_norm, RMSNorm)
        self.assertEqual(attention.q_norm.weight.numel(), self.config.hidden_size // self.config.attention_heads)
        values = torch.randn(1, attention.heads, 3, attention.head_dim) * 100
        self.assertTrue(torch.allclose(attention.q_norm(values).square().mean(dim=-1), torch.ones(1, attention.heads, 3), rtol=1e-4, atol=1e-4))

    def test_production_materialization_is_guarded_and_meta_is_available(self) -> None:
        config = RestartDecoderConfig.from_contract()
        with self.assertRaises(ValueError):
            UnifiedDecoder(config)
        model = UnifiedDecoder(config, device="meta")
        self.assertEqual(model.token_embedding.weight.device.type, "meta")


    def test_text_and_audio_coordinates_rotate_both_rotary_half_widths(self) -> None:
        model = UnifiedDecoder(self.config)
        input_ids = torch.tensor([[1, 2, self.config.audio_token_id]])
        image_mask = torch.zeros_like(input_ids, dtype=torch.bool)
        coordinates = model._coordinates(input_ids, image_mask, torch.empty((0, 2), dtype=torch.long), torch.tensor([[0, 3, 7]]))
        self.assertTrue(torch.equal(coordinates[0, 1], torch.tensor([3, 3])))
        self.assertTrue(torch.equal(coordinates[0, 2], torch.tensor([7, 7])))


if __name__ == "__main__":
    unittest.main()
