# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contract tests for the owned Ember restart 3B run boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "configs" / "ember-restart-3b.json"


class RestartContractTests(unittest.TestCase):
    def test_contract_declares_random_genesis_shape_lineage_and_namespaces(self) -> None:
        with CONTRACT_PATH.open(encoding="utf-8") as handle:
            contract = json.load(handle)

        self.assertGreaterEqual(contract["contract_version"], 1)

        model = contract["model"]
        self.assertEqual(model["hidden_size"], 3072)
        self.assertEqual(model["layers"], 20)
        self.assertEqual(model["attention_heads"], 24)
        self.assertEqual(model["vocab_size"], 32000)
        self.assertTrue(model["tied_embeddings"])
        self.assertEqual(model["image_projection"]["input_shape"], [48, 48, 3])
        self.assertEqual(model["audio_projection"]["frame_samples"], 640)

        self.assertIsNone(contract["lineage"]["parent_checkpoint"])
        self.assertEqual(contract["lineage"]["initialization"], "random")

        namespaces = contract["namespaces"]
        expected_namespaces = {
            "model": "models/ember-restart-3b",
            "training": "tools/ember-restart-3b",
            "checkpoints": "receipts/ember-restart-3b",
            "inference": "inference/ember-restart-3b",
        }
        self.assertEqual(
            {name: entry["root"] for name, entry in namespaces.items()},
            expected_namespaces,
        )
        self.assertTrue(all(entry["exclusive"] for entry in namespaces.values()))
        roots = [entry["root"].rstrip("/") for entry in namespaces.values()]
        self.assertEqual(len(roots), len(set(roots)))
        for root in roots:
            self.assertFalse(any(root.startswith(other + "/") for other in roots if other != root))

        self.assertTrue(contract["training"]["gradient_checkpointing"])
        self.assertEqual(contract["training"]["optimizer"], "paged_8bit_adamw")
        self.assertGreater(contract["checkpoints"]["retention"]["max_count"], 0)

        self.assertIsInstance(contract["sources"]["text"], list)
        self.assertIsInstance(contract["sources"]["image"], list)
        self.assertIsInstance(contract["sources"]["audio"], list)
        self.assertTrue(all(contract["sources"][kind] for kind in ("text", "image", "audio")))

    def test_unique_parameter_count_is_independently_recomputed_and_gated(self) -> None:
        with CONTRACT_PATH.open(encoding="utf-8") as handle:
            contract = json.load(handle)

        model = contract["model"]
        hidden = model["hidden_size"]
        layers = model["layers"]
        vocab = model["vocab_size"]
        image = model["image_projection"]
        audio = model["audio_projection"]
        image_in = image["input_shape"][0] * image["input_shape"][1] * image["input_shape"][2]
        image_out = image["output_size"]
        audio_in = audio["frame_samples"]
        audio_out = audio["output_size"]
        recomputed = (
            vocab * hidden
            + layers * (4 * hidden * hidden + 12 * hidden * hidden)
            + image_in * image_out
            + audio_in * audio_out
        )

        self.assertEqual(model["unique_trainable_parameters"], recomputed)
        self.assertGreaterEqual(
            model["unique_trainable_parameters"],
            model["assertion_minimum_unique_trainable_parameters"],
        )
        self.assertGreaterEqual(model["assertion_minimum_unique_trainable_parameters"], 3_000_000_000)


if __name__ == "__main__":
    unittest.main()
