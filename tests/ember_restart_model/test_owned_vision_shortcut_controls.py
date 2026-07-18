# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reproducible no-allocation controls for owned spatial vision records."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from build_owned_vision_scenes import build_records
from verify_owned_vision_shortcut_controls import evaluate_shortcut_controls


class OwnedVisionShortcutControlTests(unittest.TestCase):
    def test_control_is_support_preserving_and_declares_uncertainty_and_power(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        report = evaluate_shortcut_controls(build_records(tokenizer, count=512, image_marker=31_998))
        self.assertEqual(report["schema_version"], "ember-owned-vision-shortcut-control-v1")
        self.assertEqual(report["result"], "MEASURED_NONMATERIALIZING_NONDISPATCHABLE")
        self.assertEqual(report["content_only_chance"], 0.25)
        self.assertEqual(report["permutation_support"], {"train": list(range(24)), "validation": list(range(24)), "test": list(range(24))})
        self.assertLessEqual(report["content_only_oracle_accuracy"], 0.25)
        self.assertLess(report["confidence_interval_95"][0], 0.25)
        self.assertGreater(report["confidence_interval_95"][1], 0.25)
        self.assertGreaterEqual(report["power_for_10pp_effect"], 0.8)


if __name__ == "__main__":
    unittest.main()