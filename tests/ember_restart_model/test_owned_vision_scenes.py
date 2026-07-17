# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned non-smoke vision-scene generator regressions."""

from __future__ import annotations

import base64
from collections import Counter
import sys
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from build_owned_vision_scenes import build_records, spatial_relation_caption, structural_scene_sha256


class OwnedVisionSceneTests(unittest.TestCase):
    def test_records_are_multisample_raw_scenes_with_derived_spatial_targets(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        self.assertEqual(len(records), 512)
        captions = set()
        for record in records:
            self.assertEqual(record["active_expert"], "vision")
            self.assertEqual(len(record["image_patches_u8_base64"]), 4)
            self.assertEqual(record["image_coordinates"], [[0, 0], [1, 0], [0, 1], [1, 1]])
            self.assertEqual(record["multimodal_spans"], [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}])
            self.assertEqual(record["capability_evidence"]["image"]["derivation"], "raw_image_spatial_relation_execution")
            captions.add(record["target_text"])
        self.assertEqual(captions, {"red is left of green", "red is right of green", "red is above green", "red is below green"})
    def test_512_owned_scenes_have_nontrivial_raw_diversity(self) -> None:
        from build_owned_vision_scenes import build_records, spatial_relation_caption, structural_scene_sha256
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        raw_scenes = {tuple(record["image_patches_u8_base64"]) for record in records}
        self.assertGreaterEqual(len(raw_scenes), 480)
    def test_spatial_records_balance_relations_preserve_histograms_and_require_coordinate_binding(self) -> None:
        """Owned vision labels must be raw-spatial, balanced, structurally unique, and coordinate-sensitive."""
        vocabulary = {"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}
        tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        targets = Counter(record["target_text"] for record in records)
        self.assertEqual(targets, Counter({
            "red is left of green": 128,
            "red is right of green": 128,
            "red is above green": 128,
            "red is below green": 128,
        }))
        histograms = set()
        structures = set()
        shuffled_targets = []
        for record in records:
            patches = [base64.b64decode(value, validate=True) for value in record["image_patches_u8_base64"]]
            coordinates = record["image_coordinates"]
            self.assertEqual(spatial_relation_caption(patches, coordinates), record["target_text"])
            histograms.add(tuple(sorted(Counter(byte for patch in patches for byte in patch).items())))
            structures.add(structural_scene_sha256(patches, coordinates))
            permutation = (3, 2, 1, 0)
            shuffled_patches = [patches[index] for index in permutation]
            shuffled_targets.append(spatial_relation_caption(shuffled_patches, coordinates))
            paired_coordinates = [coordinates[index] for index in permutation]
            self.assertEqual(spatial_relation_caption(shuffled_patches, paired_coordinates), record["target_text"])
        self.assertEqual(len(histograms), 1)
        self.assertEqual(len(structures), len(records))
        self.assertTrue(all(shuffled != record["target_text"] for shuffled, record in zip(shuffled_targets, records)))
    def test_spatial_scene_splits_are_deterministic_relation_balanced_and_structurally_disjoint(self) -> None:
        """The generator assigns whole counterfactual relation groups to one split without scene overlap."""
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        split_hashes = {"train": set(), "validation": set(), "test": set()}
        split_targets = {name: Counter() for name in split_hashes}
        for record in records:
            split = record["scene_split"]
            scene_sha256 = record["capability_evidence"]["image"]["scene_sha256"]
            split_hashes[split].add(scene_sha256)
            split_targets[split][record["target_text"]] += 1
        self.assertEqual(sum(len(values) for values in split_hashes.values()), len(records))
        self.assertTrue(all(len(values) > 0 for values in split_hashes.values()))
        self.assertTrue(all(len(targets) == 4 and len(set(targets.values())) == 1 for targets in split_targets.values()))
if __name__ == "__main__":
    unittest.main()