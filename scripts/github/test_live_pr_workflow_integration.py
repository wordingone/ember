# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class LivePullRequestWorkflowIntegrationTests(unittest.TestCase):
    def test_required_guard_uses_base_pinned_live_metadata_gate(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "repo-policy-gate.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.pull_request.base.sha", workflow)
        self.assertIn("gh api --paginate --slurp", workflow)
        self.assertIn("python -m scripts.github.live_pr_policy", workflow)
        self.assertIn("--event-base-sha", workflow)
        self.assertIn("--event-head-sha", workflow)

    def test_ci_pr_bootstraps_exact_head_policy_without_write_authority(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci-pr.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("pull-requests: read", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("Bootstrap exact-head live PR policy (read-only)", workflow)
        self.assertIn("python -m scripts.github.live_pr_policy", workflow)
        self.assertIn("--event-base-sha", workflow)
        self.assertIn("--event-head-sha", workflow)
        self.assertEqual(
            3, workflow.count("ref: ${{ github.event.pull_request.head.sha || github.sha }}")
        )

    def test_live_policy_uses_package_safe_module_entrypoint(self) -> None:
        workflows = [
            (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            for name in ("ci-pr.yml", "repo-policy-gate.yml")
        ]
        for workflow in workflows:
            self.assertIn("python -m scripts.github.live_pr_policy", workflow)
            self.assertNotIn(
                "python scripts/github/live_pr_policy.py",
                workflow,
            )


if __name__ == "__main__":
    unittest.main()
