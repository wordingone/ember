# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for locally derived raw specialist supervision."""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from specialist_semantics import IMAGE_BYTES, PALETTE, image_caption, verify_image_supervision


def _patch(rectangles: list[tuple[str, int, int]]) -> bytes:
    pixels = bytearray(IMAGE_BYTES)
    for color, x, y in rectangles:
        rgb = PALETTE[color]
        for row in range(y, y + 4):
            for column in range(x, x + 4):
                offset = (row * 48 + column) * 3
                pixels[offset : offset + 3] = bytes(rgb)
    return bytes(pixels)


class SpecialistSemanticTests(unittest.TestCase):
    def test_raw_image_components_recompute_frozen_tokenizer_target(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "image": 1, "scene": 2, "has": 3, "red": 4, "green": 5, "blue": 6, "squares": 7, "0": 8, "1": 9, "2": 10, "3": 11}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        patches = [_patch([("red", 2, 2)]), _patch([("red", 10, 10), ("blue", 20, 20)]), _patch([("green", 30, 30)]), _patch([])]
        caption = image_caption(patches)
        encoded = list(tokenizer.encode(caption).ids)
        record = {
            "token_ids": [31_998, 31_998, 31_998, 31_998, *encoded[:-1]],
            "target_ids": [31_998, 31_998, 31_998, *encoded],
            "target_text": caption,
            "capability_evidence": {"image": {"caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(), "derivation": "raw_image_property_execution"}},
        }
        verify_image_supervision(record, patches=patches, tokenizer=tokenizer, image_marker=31_998)
        record["target_text"] = "fabricated label"
        with self.assertRaisesRegex(ValueError, "locally derived"):
            verify_image_supervision(record, patches=patches, tokenizer=tokenizer, image_marker=31_998)


if __name__ == "__main__":
    unittest.main()