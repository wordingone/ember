# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned non-smoke audio-frame generator regressions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from build_owned_audio_frames import build_records


class OwnedAudioFrameTests(unittest.TestCase):
    def test_records_are_multiframe_raw_pcm_with_derived_distinct_captions(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "audio": 1, "signal": 2, "has": 3, "positive": 4, "negative": 5, "silent": 6, "frames": 7, **{str(index): index + 8 for index in range(32)}}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, audio_marker=31_999)
        self.assertEqual(len(records), 512)
        captions = set()
        for record in records:
            self.assertEqual(record["active_expert"], "audio")
            self.assertEqual(len(record["audio_frames_i16le_base64"]), 4)
            self.assertEqual(record["image_coordinates"], [])
            self.assertEqual(record["multimodal_spans"], [{"start": 0, "length": 4, "modality": "audio", "attention_mode": "causal"}])
            captions.add(record["target_text"])
        self.assertGreaterEqual(len(captions), 12)


    def test_512_owned_audio_episodes_have_nontrivial_raw_diversity(self) -> None:
        from build_owned_audio_frames import build_records
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "audio": 1, "signal": 2, "has": 3, "positive": 4, "negative": 5, "silent": 6, "frames": 7, **{str(index): index + 8 for index in range(16)}}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, audio_marker=31_999)
        raw_episodes = {tuple(record["audio_frames_i16le_base64"]) for record in records}
        self.assertGreaterEqual(len(raw_episodes), 480)
if __name__ == "__main__":
    unittest.main()