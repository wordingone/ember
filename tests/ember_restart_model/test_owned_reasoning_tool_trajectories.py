# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned non-smoke reasoning and typed-tool trajectory regressions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from build_owned_reasoning_tool_trajectories import build_records
from verify_capability_record import verify_record


class OwnedReasoningToolTests(unittest.TestCase):
    def test_owned_reasoning_and_tool_records_are_diverse_and_executably_bound(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "reasoning": 1, "tool": 2, "sum": 3, "calculator": 4, "plus": 5, "equals": 6, **{str(index): index + 7 for index in range(1024)}}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        for capability, expert in (("reasoning", "reasoning"), ("tool", "tool")):
            records = build_records(tokenizer, count=512, capability=capability)
            self.assertEqual(len(records), 512)
            self.assertGreaterEqual(len({record["target_text"] for record in records}), 128)
            for record in records:
                self.assertEqual(record["active_expert"], expert)
                self.assertEqual(verify_record(record)["result"], "PASSED")


if __name__ == "__main__":
    unittest.main()