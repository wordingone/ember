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
        self.assertEqual(report["schema_version"], "ember-owned-vision-shortcut-control-v3")
        self.assertEqual(report["result"], "MEASURED_NONMATERIALIZING_NONDISPATCHABLE")
        self.assertEqual(report["content_only_chance"], 0.25)
        self.assertEqual(report["permutation_support"], {"train": list(range(24)), "validation": list(range(24)), "test": list(range(24))})
        self.assertEqual(report["declared_split_ratio"], {"train": 0.5, "validation": 0.25, "test": 0.25})
        self.assertEqual(report["per_split_record_counts"], {"train": 256, "validation": 128, "test": 128})
        for split in ("train", "validation", "test"):
            self.assertEqual(report["per_split_content_only_oracle_accuracy"][split], 0.25)
            self.assertEqual(report["per_split_ordered_patch_mean_oracle_accuracy"][split], 0.25)
            self.assertLess(report["per_split_confidence_interval_95"][split][0], 0.25)
            self.assertGreater(report["per_split_confidence_interval_95"][split][1], 0.25)

    def test_control_rejects_counterfactual_group_split_across_partitions(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        records[0] = dict(records[0], scene_split="validation")
        with self.assertRaisesRegex(ValueError, "counterfactual group"):
            evaluate_shortcut_controls(records)


    def test_control_rejects_serialized_position_and_previous_label_order_leaks(self) -> None:
        """The controls must inspect final serialized order, not hidden sample metadata."""
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        leaked = sorted(records, key=lambda record: int(str(record["sample_id"]).rsplit("-", 1)[1]))
        with self.assertRaisesRegex(ValueError, "position-mod-4"):
            evaluate_shortcut_controls(leaked)

    def test_control_preregisters_and_gates_serialized_order_predictors(self) -> None:
        """Position and predecessor label predictors must stay under their split-specific chance limits."""
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        report = evaluate_shortcut_controls(build_records(tokenizer, count=512, image_marker=31_998))
        self.assertEqual(report["serialized_order_schema_version"], "ember-owned-vision-order-v1")
        self.assertTrue(report["wilson_and_power_report_only"])
        for split in ("train", "validation", "test"):
            bound = report["per_split_order_leak_acceptance_bound"][split]
            self.assertLessEqual(report["per_split_position_mod_4_oracle_accuracy"][split], bound)
            self.assertLessEqual(report["per_split_previous_label_oracle_accuracy"][split], bound)
if __name__ == "__main__":
    unittest.main()