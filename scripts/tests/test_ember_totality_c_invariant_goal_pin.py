#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ember_totality import test_c_invariant as target


class GoalInvariantPinTests(unittest.TestCase):
    def check_text(self, text: str) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as tmp:
            goal = Path(tmp) / "GOAL.md"
            goal.write_text(text, encoding="utf-8")
            with patch.object(target, "GOAL_FILE", goal):
                return target.check_goal_pin()

    def test_accepts_current_json_contract_pin(self) -> None:
        ok, reason = self.check_text(
            '{\n'
            '  "schema_version": "ember-goal/v3",\n'
            f'  "invariant_sha256": "{target.INVARIANT_SHA256.upper()}",\n'
            '  "status": "ACTIVE"\n'
            '}\n'
        )
        self.assertTrue(ok, reason)

    def test_accepts_legacy_unquoted_contract_pin(self) -> None:
        ok, reason = self.check_text(
            f"invariant_sha256: {target.INVARIANT_SHA256}\n"
        )
        self.assertTrue(ok, reason)

    def test_rejects_wrong_hash(self) -> None:
        ok, _ = self.check_text(f'"invariant_sha256": "{"0" * 64}"\n')
        self.assertFalse(ok)

    def test_rejects_duplicate_pin_lines(self) -> None:
        ok, _ = self.check_text(
            f"invariant_sha256: {target.INVARIANT_SHA256}\n"
            f'"invariant_sha256": "{target.INVARIANT_SHA256}"\n'
        )
        self.assertFalse(ok)

    def test_does_not_accept_prose_mention(self) -> None:
        ok, _ = self.check_text(
            f"The invariant_sha256 is {target.INVARIANT_SHA256}.\n"
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
