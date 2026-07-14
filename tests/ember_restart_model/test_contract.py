# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contract tests for the sparse owned Ember restart 3B run boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "configs" / "ember-restart-3b.json"


class RestartContractTests(unittest.TestCase):
    def test_contract_declares_sparse_clean_random_shape_lineage_and_namespaces(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(contract["supersedes"]["contract_version"], 1)
        model = contract["model"]
        self.assertEqual((model["hidden_size"], model["layers"], model["attention_heads"], model["vocab_size"]), (2048, 14, 16, 32000))
        self.assertTrue(model["tied_embeddings"])
        self.assertEqual(model["expert_routing"]["expert_names"], ["vision", "audio", "reasoning", "tool"])
        self.assertEqual(model["expert_routing"]["active_experts_per_episode_or_batch"], 1)
        self.assertTrue(model["expert_routing"]["inactive_experts_frozen"])
        self.assertFalse(model["expert_routing"]["learned_external_routing"])
        self.assertEqual(model["position_encoding"]["text_audio"], "1d_rope")
        self.assertEqual(model["position_encoding"]["image"], "2d_rope_coordinates")
        self.assertTrue(model["position_encoding"]["multimodal_span_metadata"])
        self.assertIsNone(contract["lineage"]["parent_checkpoint"])
        self.assertEqual(contract["lineage"]["initialization"], "random")
        roots = {name: entry["root"] for name, entry in contract["namespaces"].items()}
        self.assertEqual(roots["model"], "models/ember-restart-3b")
        self.assertEqual(roots["training"], "tools/ember-restart-3b")
        self.assertEqual(roots["checkpoints"], "receipts/ember-restart-3b")
        self.assertEqual(roots["inference"], "inference/ember-restart-3b")
        self.assertEqual(roots["data"], "data/ember-restart-3b")
        self.assertTrue(all(entry["exclusive"] for entry in contract["namespaces"].values()))

    def test_declared_capacity_is_sparse_total_not_dense_active_claim(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        model = contract["model"]
        self.assertGreaterEqual(model["total_unique_trainable_parameters"], 3_000_000_000)
        self.assertNotIn("active_parameters", model)
        self.assertEqual(contract["authority"]["total_parameters"], model["total_unique_trainable_parameters"])
        formula = model["parameter_formula"]
        self.assertEqual(formula["shared_attention_per_layer"], "4*hidden_size^2")
        self.assertEqual(formula["four_experts_per_layer"], "4*(12*hidden_size^2)")


if __name__ == "__main__":
    unittest.main()
