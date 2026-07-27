# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded-memory replay regressions for owned specialist generators."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOLS))

import build_owned_audio_frames
import build_owned_reasoning_tool_trajectories
import build_owned_vision_scenes
import verify_training_data


class _Encoding:
    ids = [1, 2, 3, 4, 5, 6, 7, 8]


class _Tokenizer:
    def encode(self, _text: str) -> _Encoding:
        return _Encoding()


class ChunkedSpecialistReplayTests(unittest.TestCase):
    def test_generator_ranges_concatenate_to_unchanged_full_sequence(self) -> None:
        tokenizer = _Tokenizer()
        cases = (
            (build_owned_vision_scenes, {"image_marker": 31_998}),
            (build_owned_audio_frames, {"audio_marker": 31_999}),
            (build_owned_reasoning_tool_trajectories, {"capability": "reasoning"}),
            (build_owned_reasoning_tool_trajectories, {"capability": "tool"}),
        )
        for module, kwargs in cases:
            with self.subTest(module=module.__name__, kwargs=kwargs):
                full = module.build_records(tokenizer, count=512, **kwargs)
                if module is build_owned_vision_scenes:
                    replay_plan = module.build_replay_plan(tokenizer, count=512, **kwargs)
                    chunked = [
                        *module.build_records_range(
                            tokenizer, replay_plan=replay_plan,
                            start_index=0, count=257, **kwargs,
                        ),
                        *module.build_records_range(
                            tokenizer, replay_plan=replay_plan,
                            start_index=257, count=255, **kwargs,
                        ),
                    ]
                else:
                    chunked = [
                        *module.build_records_range(tokenizer, start_index=0, count=257, **kwargs),
                        *module.build_records_range(tokenizer, start_index=257, count=255, **kwargs),
                    ]
                self.assertEqual(chunked, full)

    def test_ranges_reject_boolean_or_negative_indices_and_nonpositive_counts(self) -> None:
        tokenizer = _Tokenizer()
        for start_index, count in ((-1, 1), (True, 1), (0, 0), (0, True)):
            with self.subTest(start_index=start_index, count=count):
                with self.assertRaises(ValueError):
                    build_owned_reasoning_tool_trajectories.build_records_range(
                        tokenizer,
                        start_index=start_index,
                        count=count,
                        capability="reasoning",
                    )

    def test_replay_never_materializes_a_second_full_record_sequence(self) -> None:
        tokenizer = _Tokenizer()
        records = build_owned_reasoning_tool_trajectories.build_records(
            tokenizer, count=1_025, capability="reasoning"
        )
        calls: list[tuple[int, int]] = []
        original = build_owned_reasoning_tool_trajectories.build_records_range

        def observed(tokenizer: object, *, start_index: int, count: int, capability: str):
            calls.append((start_index, count))
            return original(
                tokenizer,
                start_index=start_index,
                count=count,
                capability=capability,
            )

        with patch.object(
            build_owned_reasoning_tool_trajectories,
            "build_records_range",
            side_effect=observed,
        ):
            verify_training_data._replay_bound_specialist_records(
                capability="reasoning",
                generation={
                    "schema_version": "ember-owned-specialist-generation-v1",
                    "record_count": len(records),
                },
                generator_path=TOOLS / "build_owned_reasoning_tool_trajectories.py",
                tokenizer=tokenizer,
                raw_contract=None,
                records=records,
            )

        self.assertEqual(calls, [(0, 512), (512, 512), (1_024, 1)])
        self.assertLess(max(count for _start, count in calls), len(records))

    def test_mutation_in_later_chunk_still_fails_closed(self) -> None:
        tokenizer = _Tokenizer()
        records = build_owned_reasoning_tool_trajectories.build_records(
            tokenizer, count=1_025, capability="reasoning"
        )
        records[900] = {**records[900], "target_text": "mutated after first chunk"}
        with self.assertRaisesRegex(ValueError, "bound generator replay"):
            verify_training_data._replay_bound_specialist_records(
                capability="reasoning",
                generation={
                    "schema_version": "ember-owned-specialist-generation-v1",
                    "record_count": len(records),
                },
                generator_path=TOOLS / "build_owned_reasoning_tool_trajectories.py",
                tokenizer=tokenizer,
                raw_contract=None,
                records=records,
            )


if __name__ == "__main__":
    unittest.main()
