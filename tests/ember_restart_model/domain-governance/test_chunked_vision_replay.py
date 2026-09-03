# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Final-order bounded replay regressions for owned vision records."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOLS))

import build_owned_vision_scenes
import verify_training_data


class _Encoding:
    ids = [1, 2, 3, 4, 5, 6, 7, 8]


class _Tokenizer:
    def encode(self, _text: str) -> _Encoding:
        return _Encoding()


class ChunkedVisionReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tokenizer = _Tokenizer()
        self.image_marker = 31_998
        self.record_count = 528

    def test_ranges_concatenate_to_exact_final_serialized_order_across_511_512(self) -> None:
        full = build_owned_vision_scenes.build_records(
            self.tokenizer,
            count=self.record_count,
            image_marker=self.image_marker,
        )
        replay_plan = build_owned_vision_scenes.build_replay_plan(
            self.tokenizer,
            count=self.record_count,
            image_marker=self.image_marker,
        )
        replayed = [
            *build_owned_vision_scenes.build_records_range(
                self.tokenizer,
                replay_plan=replay_plan,
                start_index=0,
                count=512,
                image_marker=self.image_marker,
            ),
            *build_owned_vision_scenes.build_records_range(
                self.tokenizer,
                replay_plan=replay_plan,
                start_index=512,
                count=16,
                image_marker=self.image_marker,
            ),
        ]
        self.assertEqual(replayed, full)
        self.assertEqual(len(replay_plan.ordered_source_indices), self.record_count)
        self.assertFalse(any(isinstance(value, dict) for value in vars(replay_plan).values()))

    def test_range_entry_rejects_negative_and_non_integer_image_markers(self) -> None:
        replay_plan = build_owned_vision_scenes.build_replay_plan(
            self.tokenizer,
            count=self.record_count,
            image_marker=self.image_marker,
        )
        for invalid_marker in (-1, "31998", None, True):
            with self.subTest(image_marker=invalid_marker):
                with self.assertRaisesRegex(ValueError, "replay marker"):
                    build_owned_vision_scenes.build_records_range(
                        self.tokenizer,
                        replay_plan=replay_plan,
                        start_index=0,
                        count=1,
                        image_marker=invalid_marker,
                    )

    def test_verifier_rejects_omission_duplicate_and_reorder_straddling_511_512(self) -> None:
        records = build_owned_vision_scenes.build_records(
            self.tokenizer,
            count=self.record_count,
            image_marker=self.image_marker,
        )
        mutations = {
            "omission": [*records[:512], *records[513:], records[-1]],
            "duplicate": [*records[:512], records[511], *records[513:]],
            "reorder": [*records[:511], records[512], records[511], *records[513:]],
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                with patch.object(
                    build_owned_vision_scenes,
                    "build_records",
                    side_effect=AssertionError("replay must not allocate a second full record sequence"),
                ):
                    with self.assertRaisesRegex(ValueError, "bound generator replay"):
                        verify_training_data._replay_bound_specialist_records(
                            capability="image",
                            generation={
                                "schema_version": "ember-owned-specialist-generation-v1",
                                "record_count": self.record_count,
                            },
                            generator_path=TOOLS / "build_owned_vision_scenes.py",
                            tokenizer=self.tokenizer,
                            raw_contract={"image_marker": self.image_marker},
                            records=mutated,
                        )


if __name__ == "__main__":
    unittest.main()
