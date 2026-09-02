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
      - run: python -B src/ember/governance/scripts/github/labels.py apply
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
      - run: python -B src/ember/governance/scripts/github/labels.py apply
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
      - run: python -B src/ember/governance/scripts/github/labels.py apply
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

    def test_expression_cancel_in_progress_permits_metadata_types(self) -> None:
        path = self._write(
            """
name: fine
on:
  pull_request:
    branches: [master]
    types: [opened, synchronize, labeled, edited]
permissions:
  contents: read
concurrency:
  group: fine-${{ github.event.pull_request.number }}
  cancel-in-progress: ${{ github.event.action == 'synchronize' }}
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
"""
        )
        self.assertEqual([], workflow_policy.validate_workflow(path))

    def test_live_pr_reader_without_covering_trigger_is_rejected(self) -> None:
        path = self._write(
            """
name: bad
on:
  pull_request:
    branches: [master]
    types: [opened, synchronize, reopened]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: python -m src.ember.governance.scripts.github.live_pr_policy --root .
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(any("could never re-validate" in error for error in errors), errors)
        self.assertTrue(any("'edited'" in error and "'labeled'" in error for error in errors), errors)

    def test_omitted_types_do_not_silently_satisfy_coverage(self) -> None:
        path = self._write(
            """
name: bad
on:
  pull_request:
    branches: [master]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: python src/ember/governance/scripts/check_pr_authority_binding.py --body-file body.txt
"""
        )
        errors = workflow_policy.validate_workflow(path)
        self.assertTrue(any("could never re-validate" in error for error in errors), errors)

    def test_body_reader_covered_by_edited_passes(self) -> None:
        path = self._write(
            """
name: fine
on:
  pull_request_target:
    branches: [master]
    types: [opened, synchronize, reopened, edited]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: python src/ember/governance/scripts/check_pr_authority_binding.py --body-file body.txt
"""
        )
        self.assertEqual([], workflow_policy.validate_workflow(path))

    def test_required_pr_workflows_keep_their_live_input_cure_path(self) -> None:
        """ci-pr and repo-policy-gate both run live_pr_policy, which reads the
        live title, body, labels and milestone. Each must stay triggered on the
        activity that changes those inputs, and must not cancel unconditionally,
        or a body/label/milestone fix has no path back to green (#1375)."""
        root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
        readers_required = workflow_policy.LIVE_PR_INPUT_READERS["live_pr_policy"][1]
        for name in ("ci-pr.yml", "repo-policy-gate.yml"):
            path = root / ".github" / "workflows" / name
            with self.subTest(workflow=name):
                self.assertEqual([], workflow_policy.validate_workflow(path))
                workflow = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
                if True in workflow and "on" not in workflow:
                    workflow["on"] = workflow.pop(True)
                subscribed = workflow_policy._subscribed_pr_types(workflow["on"])
                covered = frozenset().union(*subscribed.values())
                self.assertEqual(frozenset(), readers_required - covered)
                self.assertFalse(
                    workflow_policy._cancels_in_progress(workflow["concurrency"])
                )

    def test_ci_pr_bootstrap_passes_subject_root(self) -> None:
        """ci-pr.yml's live_pr_policy bootstrap must pass --subject-root
        alongside --root, or the stale-base-only escape hatch
        (pinned_base_covers_live_base / pinned_head_covers_live_head) is
        permanently dead code: main() only builds policy_roots when
        args.subject_root is not None (#46)."""
        root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
        path = root / ".github" / "workflows" / "ci-pr.yml"
        text = path.read_text(encoding="utf-8", errors="strict")
        workflow = yaml.safe_load(text)
        if True in workflow and "on" not in workflow:
            workflow["on"] = workflow.pop(True)
        bootstrap_runs = [
            step["run"]
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if step.get("name") == "Bootstrap exact-head live PR policy (read-only)"
        ]
        self.assertTrue(bootstrap_runs, "bootstrap step not found in ci-pr.yml")
        for run in bootstrap_runs:
            self.assertIn("src.ember.governance.scripts.github.live_pr_policy", run)
            self.assertIn("--root .", run)
            self.assertIn("--subject-root .", run)

    def test_pr_policy_reads_no_live_state_and_stays_stripped(self) -> None:
        """pr-policy validates in-tree sources only, so it is the one required
        PR workflow that may drop every metadata trigger outright."""
        root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
        path = root / ".github" / "workflows" / "pr-policy.yml"
        self.assertEqual([], workflow_policy.validate_workflow(path))
        workflow = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
        if True in workflow and "on" not in workflow:
            workflow["on"] = workflow.pop(True)
        self.assertEqual({}, workflow_policy._live_pr_input_readers(workflow["jobs"]))
        self.assertEqual({}, workflow_policy._metadata_only_pr_types(workflow["on"]))

    def test_labels_sync_confines_write_authority_to_trusted_master_apply(self) -> None:
        root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
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
