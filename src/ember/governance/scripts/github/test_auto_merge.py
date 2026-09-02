# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest

from src.ember.governance.scripts.github.auto_merge import decide


def meta() -> dict:
    return {
        "number": 7,
        "isDraft": False,
        "autoMergeRequest": None,
        "baseRefName": "master",
        "files": [{"path": "runtime/ember-lab/src/lib.rs"}],
        "changedFiles": 1,
        "labels": [{"name": "merge:auto-approved"}],
    }


class AutoMergeTests(unittest.TestCase):
    def test_authorized_product_change_is_eligible(self) -> None:
        self.assertTrue(decide(meta()).eligible)

    def test_green_without_authority_label_is_not_eligible(self) -> None:
        value = meta()
        value["labels"] = []
        self.assertEqual("authority-label-missing", decide(value).reason)

    def test_manual_required_wins(self) -> None:
        value = meta()
        value["labels"].append({"name": "merge:manual-required"})
        self.assertEqual("manual-required", decide(value).reason)

    def test_truncated_file_list_fails_closed(self) -> None:
        value = meta()
        value["changedFiles"] = 101
        self.assertEqual("files-truncated", decide(value).reason)

    def test_authority_path_requires_manual_merge(self) -> None:
        value = meta()
        value["files"] = [{"path": ".github/workflows/ci-pr.yml"}]
        self.assertTrue(decide(value).reason.startswith("protected-path:"))


if __name__ == "__main__":
    unittest.main()
