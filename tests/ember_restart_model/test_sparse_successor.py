# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD acceptance tests for the sparse clean-genesis Ember successor."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import (  # noqa: E402
    EXPERT_NAMES,
    MultimodalSpan,
    RestartDecoderConfig,
    UnifiedDecoder,
    count_unique_trainable_parameters,
)


class SparseSuccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=2, attention_heads=4, vocab_size=64
        )

    def test_text_rope_is_position_sensitive(self) -> None:
        model = UnifiedDecoder(self.config).eval()
        tokens = torch.tensor([[4, 5]])
        first = model(tokens, position_ids=torch.tensor([[0, 1]]))
        second = model(tokens, position_ids=torch.tensor([[0, 3]]))
        self.assertFalse(torch.allclose(first[:, -1], second[:, -1]))

    def test_image_2d_rope_coordinates_are_position_sensitive(self) -> None:
        model = UnifiedDecoder(self.config).eval()
        tokens = torch.tensor([[4, self.config.image_token_id]])
        patch = torch.randn(1, 48, 48, 3)
        first = model(tokens, image_patches=patch, image_coordinates=torch.tensor([[0, 1]]))
        second = model(tokens, image_patches=patch, image_coordinates=torch.tensor([[1, 0]]))
        self.assertFalse(torch.allclose(first[:, -1], second[:, -1]))

    def test_isolated_multimodal_span_blocks_cross_span_attention(self) -> None:
        model = UnifiedDecoder(self.config)
        spans = [MultimodalSpan(start=1, length=1, modality="image", attention_mode="isolated")]
        allowed = model.build_attention_mask(batch_size=1, sequence_length=3, spans=spans, device=torch.device("cpu"))
        self.assertTrue(allowed[0, 1, 1])
        self.assertFalse(allowed[0, 2, 1])
        self.assertFalse(allowed[0, 1, 0])

    def test_four_expert_banks_are_distinct_and_named(self) -> None:
        model = UnifiedDecoder(self.config)
        self.assertEqual(tuple(model.layers[0].experts.keys()), EXPERT_NAMES)
        weights = [model.layers[0].experts[name].up_gate.weight for name in EXPERT_NAMES]
        self.assertEqual(len({id(weight) for weight in weights}), 4)

    def test_explicit_genesis_seed_replays_and_diverges(self) -> None:
        torch.manual_seed(41)
        first = UnifiedDecoder(self.config, genesis_seed=41)
        torch.manual_seed(41)
        second = UnifiedDecoder(self.config, genesis_seed=41)
        torch.manual_seed(42)
        third = UnifiedDecoder(self.config, genesis_seed=42)
        self.assertEqual(first.genesis_metadata["seed"], 41)
        self.assertEqual(first.expert_bank_genesis_hashes(), second.expert_bank_genesis_hashes())
        self.assertNotEqual(first.expert_bank_genesis_hashes(), third.expert_bank_genesis_hashes())

    def test_clean_genesis_uses_transformer_scale_for_tied_embeddings(self) -> None:
        model = UnifiedDecoder(self.config, genesis_seed=43)
        self.assertAlmostEqual(float(model.token_embedding.weight.detach().std()), 0.02, delta=0.003)
        self.assertTrue(torch.equal(model.token_embedding.weight, model.lm_head.weight))


    def test_omitted_nonproduction_seed_is_explicitly_unknown(self) -> None:
        model = UnifiedDecoder(self.config)
        self.assertIsNone(model.genesis_metadata["seed"])
    def test_expert_bank_genesis_hashes_are_distinct(self) -> None:
        model = UnifiedDecoder(self.config)
        hashes = model.expert_bank_genesis_hashes()
        self.assertEqual(set(hashes), set(EXPERT_NAMES))
        self.assertEqual(len(set(hashes.values())), 4)

    def test_single_expert_activation_isolates_inactive_gradients(self) -> None:
        model = UnifiedDecoder(self.config)
        tokens = torch.randint(0, self.config.vocab_size - 2, (1, 4))
        model.train()
        output = model(tokens, active_expert="reasoning")
        output.sum().backward()
        for layer in model.layers:
            for name, expert in layer.experts.items():
                grads = [parameter.grad for parameter in expert.parameters()]
                if name == "reasoning":
                    self.assertTrue(all(parameter.requires_grad for parameter in expert.parameters()))
                    self.assertTrue(any(grad is not None for grad in grads))
                else:
                    self.assertTrue(all(not parameter.requires_grad for parameter in expert.parameters()))
                    self.assertTrue(all(grad is None for grad in grads))

    def test_only_selected_expert_executes_per_layer(self) -> None:
        model = UnifiedDecoder(self.config)
        calls: list[str] = []
        for layer in model.layers:
            for name, expert in layer.experts.items():
                original = expert.forward
                def observed(hidden, *, _name=name, _original=original):
                    calls.append(_name)
                    return _original(hidden)
                expert.forward = observed  # type: ignore[method-assign]
        model(torch.randint(0, self.config.vocab_size - 2, (1, 3)), active_expert="tool")
        self.assertEqual(calls, ["tool"] * self.config.layers)


    def test_checkpointed_layers_match_noncheckpointed_logits_and_gradients(self) -> None:
        checkpointed = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64, gradient_checkpointing=True)
        direct = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64, gradient_checkpointing=False)
        torch.manual_seed(73)
        with_checkpoint = UnifiedDecoder(checkpointed, genesis_seed=73).train()
        torch.manual_seed(73)
        without_checkpoint = UnifiedDecoder(direct, genesis_seed=73).train()
        tokens = torch.tensor([[4, 5, 6]])
        with_logits = with_checkpoint(tokens, active_expert="reasoning")
        without_logits = without_checkpoint(tokens, active_expert="reasoning")
        with_logits.sum().backward()
        without_logits.sum().backward()
        self.assertTrue(torch.allclose(with_logits, without_logits))
        for (name, first), (_, second) in zip(with_checkpoint.named_parameters(), without_checkpoint.named_parameters()):
            if first.requires_grad:
                self.assertEqual(first.grad is None, second.grad is None, name)
                if first.grad is not None:
                    self.assertTrue(torch.allclose(first.grad, second.grad), name)
    def test_meta_production_count_is_exact_and_at_least_three_billion(self) -> None:
        config = RestartDecoderConfig.from_contract()
        model = UnifiedDecoder(config, device="meta")
        measured = count_unique_trainable_parameters(model, include_frozen=True)
        self.assertEqual(measured, config.total_unique_trainable_parameters)
        self.assertGreaterEqual(measured, 3_000_000_000)


if __name__ == "__main__":
    unittest.main()
