# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "scripts" / "ember_totality" / "test_c_auto.py"


class CAutonomyClaimIntegrityTests(unittest.TestCase):
    def _run_probe(self, root: Path) -> str:
        env = os.environ.copy()
        env["EMBER_TOTALITY_ROOT"] = str(root)
        completed = subprocess.run(
            [sys.executable, "-B", str(PROBE)],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def test_rejects_stub_forged_r0_claim(self) -> None:
        """Removing claim-content validation must make this exact exploit GREEN."""
        with tempfile.TemporaryDirectory(prefix="c-auto-stub-forgery-") as raw_root:
            root = Path(raw_root)
            contract = root / "docs" / "spec" / "autonomy-relinquishment-ladder-v1.md"
            contract.parent.mkdir(parents=True)
            contract.write_text("# fixture contract\n", encoding="utf-8")

            window_names = []
            receipts = root / "receipts" / "autonomy-ladder"
            receipts.mkdir(parents=True)
            for number in range(1, 6):
                name = f"R0-window-{number}.json"
                window_names.append(name)
                (receipts / name).write_text(
                    json.dumps({"ts": number}) + "\n",
                    encoding="utf-8",
                )
            (receipts / "R0-claim-forged.json").write_text("{}\n", encoding="utf-8")

            state = {
                "schema": "autonomy-ladder-state-v1",
                "contract": "docs/spec/autonomy-relinquishment-ladder-v1.md",
                "current_rung": "R0",
                "rungs": {
                    "R0": {
                        "status": "CLAIMED",
                        "claimed": True,
                        "windows": window_names,
                    }
                },
                "reversion_log": [],
                "promotion_rule": "K=5 consecutive clean receipted windows",
                "safety_floor": (
                    "operator escalation set + governor caps + kill-discipline NEVER transfer"
                ),
            }
            (root / "autonomy-ladder-state.json").write_text(
                json.dumps(state) + "\n",
                encoding="utf-8",
            )

            output = self._run_probe(root)
            self.assertTrue(output.startswith("RED "), output)
            self.assertIn("invalid_autonomy_claim_evidence", output)


if __name__ == "__main__":
    unittest.main()
