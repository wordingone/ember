# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned non-smoke vision-scene generator regressions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from build_owned_vision_scenes import build_records
from specialist_semantics import image_caption


class OwnedVisionSceneTests(unittest.TestCase):
    def test_records_are_multisample_raw_scenes_with_derived_distinct_captions(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "image": 1, "scene": 2, "has": 3, "red": 4, "green": 5, "blue": 6, "squares": 7, **{str(index): index + 8 for index in range(32)}}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        self.assertEqual(len(records), 512)
        captions = set()
        for record in records:
            self.assertEqual(record["active_expert"], "vision")
            self.assertEqual(len(record["image_patches_u8_base64"]), 4)
            self.assertEqual(record["image_coordinates"], [[0, 0], [1, 0], [0, 1], [1, 1]])
            self.assertEqual(record["multimodal_spans"], [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}])
            captions.add(record["target_text"])
        self.assertGreaterEqual(len(captions), 16)


    def test_512_owned_scenes_have_nontrivial_raw_diversity(self) -> None:
        from build_owned_vision_scenes import build_records
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "image": 1, "scene": 2, "has": 3, "red": 4, "green": 5, "blue": 6, "squares": 7, **{str(index): index + 8 for index in range(16)}}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        raw_scenes = {tuple(record["image_patches_u8_base64"]) for record in records}
        self.assertGreaterEqual(len(raw_scenes), 480)
if __name__ == "__main__":
    unittest.main()