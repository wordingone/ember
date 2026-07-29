# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.github import workflow_policy


class WorkflowPolicyTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "workflow.yml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_unpinned_action_is_rejected(self) -> None:
        path = self._write(
            """
name: bad
on: pull_request
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(any("unpinned action" in error for error in errors))

    def test_privileged_subject_checkout_is_rejected(self) -> None:
        path = self._write(
            """
name: bad
on: pull_request_target
permissions:
  pull-requests: write
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          ref: ${{ github.event.pull_request.head.sha }}
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(any("checks out pull-request subject" in e for e in errors))

    def test_privileged_repository_tool_execution_is_rejected(self) -> None:
        path = self._write(
            """
name: bad
on: pull_request_target
permissions:
  issues: write
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: python -m pytest
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(any("repository-authored code" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
