# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# goal_id: EMBER-02
# workstream_id: EMBER-02A
"""CPU-only CIA contract tests; no learned model is instantiated."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model.cia_contract import CIA3R1N61, census, history_window


class CIAContractTests(unittest.TestCase):
    def test_corrected_census(self):
        counts = census(CIA3R1N61())
        self.assertEqual(counts.total_unique, 3_082_539_008)
        self.assertEqual(counts.core, 251_383_808)
        self.assertEqual(counts.expert_bundle, 113_246_208)
        self.assertEqual(counts.active_envelope, 364_630_016)
        self.assertEqual(counts.resident_envelope, 477_876_224)

    def test_original_24_expert_design_refused_before_learning(self):
        with self.assertRaisesRegex(ValueError, "3,000,000,000"):
            CIA3R1N61(global_experts=24)

    def test_boolean_and_float_counts_are_not_integer_contracts(self):
        for value in (True, 25.0, "25", 0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CIA3R1N61(global_experts=value)

    def test_residency_cannot_exceed_population(self):
        with self.assertRaises(ValueError):
            CIA3R1N61(resident_experts=26)

    def test_selection_cannot_exceed_residency(self):
        with self.assertRaises(ValueError):
            CIA3R1N61(selected_experts=3)

    def test_first_epoch_has_no_input_history(self):
        self.assertEqual(history_window(position=13, document_start=13, period=1024), (13, 13))
        self.assertEqual(history_window(position=1036, document_start=13, period=1024), (13, 13))

    def test_epoch_uses_only_preceding_epoch_not_current_suffix(self):
        for position in (1037, 1500, 2060):
            self.assertEqual(history_window(position=position, document_start=13, period=1024), (13, 1037))
        self.assertEqual(history_window(position=2061, document_start=13, period=1024), (1037, 2061))

    def test_local_history_resets_at_packed_document_boundary(self):
        self.assertEqual(history_window(position=269, document_start=13, period=256), (13, 269))
        self.assertEqual(history_window(position=270, document_start=270, period=256), (270, 270))

    def test_no_window_can_include_prediction_or_previous_document(self):
        for start in (0, 13, 1025):
            for position in range(start, start + 3000, 37):
                lo, hi = history_window(position=position, document_start=start, period=256)
                self.assertLessEqual(start, lo)
                self.assertLessEqual(lo, hi)
                self.assertLessEqual(hi, position)
                self.assertLessEqual(hi - lo, 256)

    def test_invalid_history_arguments_refused(self):
        for args in ((12, 13, 256), (1, -1, 256), (0, 0, 0), (True, 0, 256), (1, 0, 1.5)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                history_window(position=args[0], document_start=args[1], period=args[2])


if __name__ == "__main__":
    unittest.main()
