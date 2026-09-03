# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


class EvalCanaryCiJobTests(unittest.TestCase):
    """Break caught: the canary job or its self-check drifts from the bound CPU route."""

    def test_pinned_cpu_ci_job_is_dedicated_measurement_ready_and_self_checked(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci-pr.yml").read_text(encoding="utf-8")
        required = (
            "eval-canary-image:",
            'python-version: "3.10.11"',
            "torch==2.10.0+cpu",
            "https://download.pytorch.org/whl/cpu",
            "tokenizers==0.22.2",
            "TORCH_WHEEL_FILENAME",
            "TORCH_WHEEL_SHA256",
            'python -B "$(test -f tests/ember_restart_model/domain-governance/test_eval_canary_image.py && echo tests/ember_restart_model/domain-governance || echo tests/ember_restart_model)/test_eval_canary_image.py" -v',
            "python -B tests/domain-governance/test_eval_canary_ci_job.py -v",
            "--run-suite",
            "issue1948-eval-canary-terminal.json",
            "ISSUE1948_FROZEN_TIMEOUT_SECONDS: 12",
            "ISSUE1948_MEASURING_RUN_URL: https://github.com/wordingone/ember/actions/runs/33279094639",
            "torch-2.10.0+cpu-cp310-cp310-manylinux_2_28_x86_64.whl",
            "a280ffaea7b9c828e0c1b9b3bd502d9b6a649dc9416997b69b84544bd469f215",
            'test "$(git rev-parse HEAD)" = "${{ github.event.pull_request.head.sha || github.sha }}"',
            'GITHUB_SHA="$(git rev-parse HEAD)" timeout 12s python -B',
        )
        for needle in required:
            self.assertIn(needle, workflow)


if __name__ == "__main__":
    unittest.main()
