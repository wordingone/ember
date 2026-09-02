# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


class LivePullRequestWorkflowIntegrationTests(unittest.TestCase):
    def test_required_guard_uses_base_pinned_live_metadata_gate(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "repo-policy-gate.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.pull_request.base.sha", workflow)
        self.assertIn("gh api --paginate --slurp", workflow)
        self.assertIn("python -m src.ember.governance.scripts.github.live_pr_policy", workflow)
        self.assertIn("--event-base-sha", workflow)
        self.assertIn("--event-head-sha", workflow)
        self.assertIn('--subject-root "${subject}"', workflow)

    def test_ci_pr_bootstraps_exact_head_policy_without_write_authority(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci-pr.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("pull-requests: read", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("Bootstrap exact-head live PR policy (read-only)", workflow)
        self.assertIn("python -m src.ember.governance.scripts.github.live_pr_policy", workflow)
        self.assertIn("--event-base-sha", workflow)
        self.assertIn("--event-head-sha", workflow)
        # Every required job that checks out does so at the exact PR head,
        # never a moving branch ref. The exact roster is a deliberate allowlist:
        # a required checkout job disappearing must fail this integration test.
        checkouts = [
            (name, step.get("with", {}).get("ref"))
            for name, job in yaml.safe_load(workflow)["jobs"].items()
            for step in job.get("steps", [])
            if str(step.get("uses", "")).startswith("actions/checkout@")
        ]
        self.assertEqual(
            {
                "python",
                "rust",
                "rust-linux-test",
                "eval-canary-image",
                "cli",
                "launcher",
                "production-rung-replay",
                "owned-process-posix",
            },
            {name for name, _ in checkouts},
        )
        for name, ref in checkouts:
            self.assertEqual(
                "${{ github.event.pull_request.head.sha || github.sha }}", ref, name
            )

    def test_live_policy_uses_package_safe_module_entrypoint(self) -> None:
        workflows = [
            (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            for name in ("ci-pr.yml", "repo-policy-gate.yml")
        ]
        for workflow in workflows:
            self.assertIn("python -m src.ember.governance.scripts.github.live_pr_policy", workflow)
            self.assertNotIn(
                "python src/ember/governance/scripts/github/live_pr_policy.py",
                workflow,
            )

    def test_dependabot_schema_bypasses_only_human_authority_binding(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "repo-policy-gate.yml"
        ).read_text(encoding="utf-8")
        live_policy = workflow.index("python -m src.ember.governance.scripts.github.live_pr_policy")
        actor_read = workflow.index('["actor_login"]')
        bot_boundary = workflow.index(
            'if [[ "${actor_login}" != "dependabot[bot]" ]]; then'
        )
        authority_binding = workflow.index(
            'python "${kernel}/src/ember/governance/scripts/check_pr_authority_binding.py"'
        )
        self.assertLess(live_policy, actor_read)
        self.assertLess(actor_read, bot_boundary)
        self.assertLess(bot_boundary, authority_binding)
        self.assertIn(
            'echo "trusted narrow Dependabot schema accepted; '
            'human authority binding is not applicable"',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
