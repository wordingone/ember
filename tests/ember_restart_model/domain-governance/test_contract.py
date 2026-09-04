# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contract tests for the sparse owned Ember restart 3B run boundary."""

from __future__ import annotations

import json
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))
from src.ember.model.model import RestartDecoderConfig

CONTRACT_PATH = ROOT / "configs" / "ember-restart-3b.json"


class RestartContractTests(unittest.TestCase):
    def test_contract_declares_sparse_clean_random_shape_lineage_and_namespaces(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(contract["architecture_revision"], "ember-sparse-3b-v2")
        self.assertEqual(contract["supersedes"]["contract_version"], 1)
        model = contract["model"]
        self.assertEqual((model["hidden_size"], model["layers"], model["attention_heads"], model["vocab_size"]), (2048, 14, 16, 32000))
        self.assertTrue(model["tied_embeddings"])
        self.assertIn("memory", contract["training"])
        memory = contract["training"]["memory"]
        self.assertEqual(memory["parameter_dtype"], "bfloat16")
        self.assertEqual(memory["parameter_bytes"], 2)
        self.assertEqual(memory["gradient_bytes_per_active_parameter"], 2)
        self.assertEqual(memory["optimizer_state_bytes_per_active_parameter"], 2)
        self.assertEqual(memory["activation_reserve_gib"], 4)
        self.assertEqual(model["expert_routing"]["expert_names"], ["vision", "audio", "reasoning", "tool"])
        self.assertEqual(model["expert_routing"]["active_experts_per_episode_or_batch"], 1)
        self.assertTrue(model["expert_routing"]["inactive_experts_frozen"])
        self.assertFalse(model["expert_routing"]["learned_external_routing"])
        self.assertEqual(model["position_encoding"]["text_audio"], "1d_rope")
        self.assertEqual(model["position_encoding"]["image"], "2d_rope_coordinates")
        self.assertEqual(model["position_encoding"]["attention_modes"], ["causal", "bidirectional"])
        self.assertEqual(model["normalization"]["qk"], "per_head_rmsnorm_before_rope")
        self.assertTrue(model["position_encoding"]["multimodal_span_metadata"])
        self.assertIsNone(contract["lineage"]["parent_checkpoint"])
        self.assertEqual(contract["lineage"]["initialization"], "random")
        roots = {name: entry["root"] for name, entry in contract["namespaces"].items()}
        self.assertEqual(roots["model"], "models/ember-restart-3b")
        self.assertEqual(roots["training"], "src/ember/infrastructure/tools/ember-restart-3b")
        self.assertEqual(roots["checkpoints"], "receipts/ember-restart-3b")
        self.assertEqual(roots["inference"], "inference/ember-restart-3b")
        self.assertEqual(roots["data"], "data/ember-restart-3b")
        self.assertTrue(all(entry["exclusive"] for entry in contract["namespaces"].values()))

    def test_production_contract_rejects_a_shared_text_route_without_declared_nonlinear_ffn(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        del contract["model"]["expert_routing"]["shared_text_ffn"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "shared nonlinear text FFN"):
                RestartDecoderConfig.from_contract(path)
    def test_declared_capacity_is_sparse_total_not_dense_active_claim(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        model = contract["model"]
        self.assertGreaterEqual(model["total_unique_trainable_parameters"], 3_000_000_000)
        self.assertNotIn("active_parameters", model)
        self.assertEqual(contract["authority"]["total_parameters"], model["total_unique_trainable_parameters"])
        formula = model["parameter_formula"]
        self.assertEqual(formula["shared_attention_per_layer"], "4*hidden_size^2")
        self.assertEqual(formula["qk_rmsnorm_per_layer"], "2*(hidden_size/attention_heads)")
        self.assertEqual(formula["four_experts_per_layer"], "4*(12*hidden_size^2)")
        self.assertEqual(formula["shared_text_ffn_per_layer"], "12*hidden_size^2")
        self.assertEqual(model["total_unique_trainable_parameters"], 3_839_161_856)


if __name__ == "__main__":
    unittest.main()
