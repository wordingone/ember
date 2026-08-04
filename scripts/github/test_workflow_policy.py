# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

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
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
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

    def test_pull_request_write_job_cannot_execute_checked_out_subject(self) -> None:
        path = self._write(
            """
name: same-repository-pr-is-still-untrusted
on: pull_request
permissions:
  contents: read
jobs:
  apply:
    permissions:
      contents: read
      issues: write
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - run: python -B scripts/github/labels.py apply
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("write-capable PR job executes pull-request code" in e for e in errors),
            errors,
        )

    def test_pull_request_write_job_cannot_execute_foreign_master_checkout(self) -> None:
        path = self._write(
            """
name: foreign-repository-master-is-not-trusted
on: pull_request
permissions:
  issues: write
jobs:
  apply:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: attacker/controlled
          ref: master
      - run: python -B scripts/github/labels.py apply
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("write-capable PR job executes pull-request code" in e for e in errors),
            errors,
        )

    def test_pull_request_write_job_cannot_run_inline_code_with_trusted_checkout(
        self,
    ) -> None:
        path = self._write(
            """
name: pull-request-controls-workflow-source
on: pull_request
permissions:
  contents: read
jobs:
  apply:
    permissions:
      contents: read
      issues: write
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: wordingone/ember
          ref: master
      - run: echo attacker-controlled-workflow-source
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("pull_request workflow source cannot hold write authority" in e for e in errors),
            errors,
        )

    def test_pull_request_write_job_cannot_run_arbitrary_pinned_remote_action(
        self,
    ) -> None:
        path = self._write(
            """
name: pinned-is-not-trusted
on: pull_request
permissions:
  contents: read
  issues: write
jobs:
  apply:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: attacker/controlled@0123456789abcdef0123456789abcdef01234567
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("pull_request workflow source cannot hold write authority" in e for e in errors),
            errors,
        )

    def test_codeql_write_exception_rejects_untrusted_action(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "security-codeql.yml"
        path.write_text(
            """
name: security-codeql
on: pull_request
permissions:
  contents: read
  security-events: write
jobs:
  codeql:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: attacker/controlled@0123456789abcdef0123456789abcdef01234567
""",
            encoding="utf-8",
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("pull_request workflow source cannot hold write authority" in e for e in errors),
            errors,
        )

    def test_codeql_write_exception_rejects_environment_injection(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "security-codeql.yml"
        path.write_text(
            """
name: security-codeql
on: pull_request
permissions:
  contents: read
  security-events: write
jobs:
  codeql:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        language: [python, javascript-typescript]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - uses: github/codeql-action/init@3b0bd1d116c0bde30213346b22d4f634d96a2fb0
        env:
          NODE_OPTIONS: --require ./attacker.js
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/analyze@3b0bd1d116c0bde30213346b22d4f634d96a2fb0
""",
            encoding="utf-8",
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("pull_request workflow source cannot hold write authority" in e for e in errors),
            errors,
        )

    def test_codeql_write_exception_rejects_workflow_environment_injection(
        self,
    ) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "security-codeql.yml"
        path.write_text(
            """
name: security-codeql
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]
  schedule:
    - cron: "47 10 * * 2"
env:
  NODE_OPTIONS: --require ./attacker.js
permissions:
  contents: read
  security-events: write
jobs:
  codeql:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        language: [python, javascript-typescript]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - uses: github/codeql-action/init@3b0bd1d116c0bde30213346b22d4f634d96a2fb0
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/analyze@3b0bd1d116c0bde30213346b22d4f634d96a2fb0
""",
            encoding="utf-8",
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("pull_request workflow source cannot hold write authority" in e for e in errors),
            errors,
        )

    def test_dependabot_or_fork_token_reduction_is_not_a_safety_proof(self) -> None:
        path = self._write(
            """
name: actor-filter-does-not-cure-authority-mixing
on: pull_request
permissions:
  issues: write
jobs:
  apply:
    if: github.actor == 'dependabot[bot]' || github.event.pull_request.head.repo.fork
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - run: python -B scripts/github/labels.py apply
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("write-capable PR job executes pull-request code" in e for e in errors),
            errors,
        )

    def test_metadata_only_pr_types_under_cancellation_are_rejected(self) -> None:
        path = self._write(
            """
name: bad
on:
  pull_request:
    branches: [master]
    types: [opened, synchronize, labeled, edited]
permissions:
  contents: read
concurrency:
  group: bad-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("metadata-only activity" in error for error in errors), errors
        )
        self.assertTrue(any("'edited'" in error and "'labeled'" in error for error in errors), errors)

    def test_metadata_only_pr_types_are_allowed_without_cancellation(self) -> None:
        path = self._write(
            """
name: fine
on:
  pull_request_target:
    branches: [master]
    types: [opened, synchronize, labeled, unlabeled]
permissions:
  contents: read
concurrency:
  group: fine-${{ github.event.pull_request.number }}
  cancel-in-progress: false
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertEqual([], errors)

    def test_job_level_cancellation_also_rejects_metadata_only_types(self) -> None:
        path = self._write(
            """
name: bad
on:
  pull_request:
    branches: [master]
    types: [opened, milestoned]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    concurrency:
      group: bad-${{ github.event.pull_request.number }}
      cancel-in-progress: true
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(
            any("metadata-only activity" in error for error in errors), errors
        )

    def test_required_pr_workflows_do_not_subscribe_to_metadata_only_types(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for name in ("ci-pr.yml", "pr-policy.yml", "repo-policy-gate.yml"):
            path = root / ".github" / "workflows" / name
            with self.subTest(workflow=name):
                self.assertEqual([], workflow_policy.validate_workflow(path))
                workflow = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
                if True in workflow and "on" not in workflow:
                    workflow["on"] = workflow.pop(True)
                self.assertEqual({}, workflow_policy._metadata_only_pr_types(workflow["on"]))

    def test_labels_sync_confines_write_authority_to_trusted_master_apply(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / ".github" / "workflows" / "labels-sync.yml"
        errors = workflow_policy.validate_workflow(path)
        self.assertEqual([], errors)

        workflow = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
        if True in workflow and "on" not in workflow:
            workflow["on"] = workflow.pop(True)
        self.assertNotIn("pull_request", workflow["on"])
        self.assertFalse(workflow_policy._permission_writes(workflow["permissions"]))

        validate = workflow["jobs"]["validate"]
        apply = workflow["jobs"]["apply"]
        self.assertFalse(workflow_policy._permission_writes(validate.get("permissions")))
        self.assertTrue(workflow_policy._permission_writes(apply["permissions"]))
        self.assertIn("github.event_name == 'workflow_dispatch'", apply["if"])
        self.assertIn("github.ref_protected == true", apply["if"])
        checkout = next(step for step in apply["steps"] if "uses" in step)
        self.assertEqual("${{ github.sha }}", checkout["with"]["ref"])
        self.assertFalse(checkout["with"]["persist-credentials"])


if __name__ == "__main__":
    unittest.main()
