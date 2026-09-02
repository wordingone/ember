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

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from specialist_semantics import IMAGE_BYTES, PALETTE, spatial_relation_caption, structural_scene_sha256, verify_image_supervision


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
    def test_raw_image_relation_recomputes_frozen_tokenizer_target_and_rejects_raw_swap(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        patches = [_patch([("red", 10, 10)]), _patch([("green", 10, 10)]), _patch([]), _patch([])]
        coordinates = [[0, 0], [1, 0], [0, 1], [1, 1]]
        caption = spatial_relation_caption(patches, coordinates)
        encoded = list(tokenizer.encode(caption).ids)
        record = {
            "token_ids": [31_998, 31_998, 31_998, 31_998, *encoded[:-1]],
            "target_ids": [31_998, 31_998, 31_998, *encoded],
            "target_text": caption,
            "image_coordinates": coordinates,
            "capability_evidence": {"image": {
                "target_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
                "scene_sha256": structural_scene_sha256(patches, coordinates),
                "derivation": "raw_image_spatial_relation_execution",
            }},
        }
        verify_image_supervision(record, patches=patches, tokenizer=tokenizer, image_marker=31_998)
        with self.assertRaisesRegex(ValueError, "locally derived"):
            verify_image_supervision(record, patches=[patches[1], patches[0], patches[2], patches[3]], tokenizer=tokenizer, image_marker=31_998)

    def test_raw_audio_frames_require_locally_derived_signal_caption(self) -> None:
        from specialist_semantics import audio_caption, verify_audio_supervision
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "audio": 1, "signal": 2, "has": 3, "positive": 4, "negative": 5, "silent": 6, "frames": 7, "0": 8, "1": 9, "2": 10}, unk_token="<unk>")); tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        frame = b"".join(int(value).to_bytes(2, "little", signed=True) for value in ([100, -100, 100, -100] * 160)); frames = [frame, frame]
        caption = audio_caption(frames); encoded = list(tokenizer.encode(caption).ids)
        record = {"token_ids": [31_999, 31_999, *encoded[:-1]], "target_ids": [31_999, *encoded], "target_text": caption, "capability_evidence": {"audio": {"caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(), "derivation": "raw_audio_signal_execution"}}}
        verify_audio_supervision(record, frames=frames, tokenizer=tokenizer, audio_marker=31_999)
        record["capability_evidence"]["audio"]["caption_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "locally derived"):
            verify_audio_supervision(record, frames=frames, tokenizer=tokenizer, audio_marker=31_999)

if __name__ == "__main__":
    unittest.main()