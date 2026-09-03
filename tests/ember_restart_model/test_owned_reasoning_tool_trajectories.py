# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned non-smoke reasoning and typed-tool trajectory regressions."""

from __future__ import annotations

import base64
import json
import subprocess
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
                expected_ids = list(tokenizer.encode(record["target_text"]).ids)
                self.assertEqual(record["token_ids"], expected_ids[:-1])
                self.assertEqual(record["target_ids"], expected_ids[1:])
                self.assertEqual(verify_record(record)["result"], "PASSED")

    def test_receipt_rejects_transcript_that_disagrees_with_executed_evidence(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "reasoning": 1, "sum": 2, "plus": 3, "equals": 4, **{str(index): index + 5 for index in range(1024)}}, unk_token="<unk>")); tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        record = build_records(tokenizer, count=512, capability="reasoning")[0]
        record["target_text"] = "reasoning sum 1 plus 1 equals 3"
        with self.assertRaisesRegex(ValueError, "transcript"):
            verify_record(record)

    def test_isolated_verifier_accepts_a_batch_of_executed_records(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "reasoning": 1, "sum": 2, "plus": 3, "equals": 4, **{str(index): index + 5 for index in range(1024)}}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, capability="reasoning")[:2]
        payload = base64.b64encode(json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
        completed = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "ember-restart-3b" / "verify_capability_record.py"), "--records-json-base64", payload], text=True, capture_output=True, timeout=15, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["result"], "PASSED")
        self.assertEqual(len(json.loads(completed.stdout)["receipts"]), 2)
    def test_isolated_verifier_accepts_large_record_batch_from_stdin(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "reasoning": 1, "sum": 2, "plus": 3, "equals": 4, **{str(index): index + 5 for index in range(1024)}}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, capability="reasoning")
        completed = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "ember-restart-3b" / "verify_capability_record.py"), "--records-json-stdin"], input=json.dumps(records, sort_keys=True, separators=(",", ":")), text=True, capture_output=True, timeout=15, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(json.loads(completed.stdout)["receipts"]), 512)
if __name__ == "__main__":
    unittest.main()