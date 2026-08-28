# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
            "python -B tests/ember_restart_model/test_eval_canary_image.py -v",
            "python -B tests/test_eval_canary_ci_job.py -v",
            "--run-suite",
            "issue1948-eval-canary-terminal.json",
            "ISSUE1948_FROZEN_TIMEOUT_SECONDS: pending-first-green",
        )
        for needle in required:
            self.assertIn(needle, workflow)


if __name__ == "__main__":
    unittest.main()
