# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import subprocess
import sys
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
                "production-rung-replay-retry",
                "owned-process-posix",
                "owned-process-posix-retry",
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


    def _aggregate_verdict(self, results: dict[str, str]) -> tuple[int, str]:
        """Run the ci-pr aggregate's inline python on crafted `needs` results; return (exit code, stdout)."""
        job = yaml.safe_load((ROOT / ".github" / "workflows" / "ci-pr.yml").read_text(encoding="utf-8"))["jobs"]["ci-pr"]
        run = next(step["run"] for step in job["steps"] if step.get("name") == "Stable aggregate verdict")
        lines = run.splitlines()
        start = next(i for i, line in enumerate(lines) if line.strip() == "python - <<'PY'") + 1
        end = next(i for i in range(start, len(lines)) if lines[i].strip() == "PY")
        needs = {name: {"result": result} for name, result in results.items()}
        done = subprocess.run(
            [sys.executable, "-B", "-c", chr(10).join(lines[start:end])],
            capture_output=True, text=True, env=dict(os.environ, NEEDS_JSON=json.dumps(needs)),
        )
        self.assertEqual("", done.stderr)
        return done.returncode, done.stdout

    def _needs_names(self) -> list[str]:
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci-pr.yml").read_text(encoding="utf-8"))
        return list(workflow["jobs"]["ci-pr"]["needs"])

    def _all(self, **overrides: str) -> dict[str, str]:
        results = {name: "success" for name in self._needs_names()}
        for name in ("owned-process-posix-retry", "production-rung-replay-retry"):
            results[name] = "skipped"
        for key, value in overrides.items():
            self.assertIn(key.replace("_", "-"), results)
            results[key.replace("_", "-")] = value
        return results

    def test_aggregate_passes_when_every_job_succeeds_or_a_retry_is_skipped(self) -> None:
        code, out = self._aggregate_verdict(self._all())
        self.assertEqual(0, code)
        self.assertNotIn("::warning::", out)

    def test_aggregate_passes_a_failed_first_attempt_whose_retry_succeeded_and_says_so(self) -> None:
        for first in ("failure", "cancelled", "skipped"):
            code, out = self._aggregate_verdict(self._all(owned_process_posix=first, owned_process_posix_retry="success"))
            self.assertEqual(0, code, first)
            self.assertIn("::warning::owned-process-posix first attempt was " + first, out)
        code, out = self._aggregate_verdict(self._all(production_rung_replay="failure", production_rung_replay_retry="success"))
        self.assertEqual(0, code)
        self.assertIn("::warning::production-rung-replay first attempt was failure", out)

    def test_aggregate_fails_when_the_retry_also_fails_or_never_ran(self) -> None:
        for retry in ("failure", "cancelled", "skipped"):
            code, _ = self._aggregate_verdict(self._all(owned_process_posix="failure", owned_process_posix_retry=retry))
            self.assertEqual(1, code, retry)
        code, _ = self._aggregate_verdict(self._all(production_rung_replay="cancelled", production_rung_replay_retry="failure"))
        self.assertEqual(1, code)

    def test_aggregate_does_not_forgive_a_job_that_has_no_retry(self) -> None:
        for name in self._needs_names():
            if name.endswith("-retry") or name + "-retry" in self._needs_names():
                continue
            code, _ = self._aggregate_verdict(self._all(**{name.replace("-", "_"): "failure"}))
            self.assertEqual(1, code, name)

    def test_a_retry_job_runs_only_after_a_first_attempt_that_did_not_succeed(self) -> None:
        jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "ci-pr.yml").read_text(encoding="utf-8"))["jobs"]
        for base in ("owned-process-posix", "production-rung-replay"):
            retry = jobs[base + "-retry"]
            self.assertEqual(base, retry["needs"])
            self.assertIn("!cancelled()", retry["if"])
            self.assertIn("needs.%s.result != 'success'" % base, retry["if"])
            self.assertNotIn(base + "-retry", jobs[base].get("needs", []))
            first_steps = [{k: v for k, v in step.items() if k != "name"} for step in jobs[base]["steps"]]
            retry_steps = [{k: v for k, v in step.items() if k != "name"} for step in retry["steps"]]
            self.assertEqual(first_steps, retry_steps, base + ": the retry must run the same steps as the first attempt")


if __name__ == "__main__":
    unittest.main()
