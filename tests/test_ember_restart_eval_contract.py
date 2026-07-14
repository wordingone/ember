# goal_id: EMBER-01
# workstream_id: EMBER-01A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contract tests for the checkpoint-bound Ember restart evaluation interface."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ember_restart_eval_contract.py"


def manifest() -> dict:
    families = ["text", "reasoning", "mathematics", "coding", "sql", "browser_ui", "terminal", "image", "audio", "structured_tools", "efficiency", "retention", "deletion_ablation"]
    return {
        "schema_version": "ember-restart-eval/v1",
        "target": {"kind": "owned_checkpoint", "checkpoint_sha256": "a" * 64, "lineage_manifest": "receipts/lineage.json"},
        "comparators": [{"role": "comparison_only", "revision": "b" * 40}],
        "suites": [{"family": family, "dataset_revision": "c" * 40, "split_sha256": "d" * 64, "harness_commit": "e" * 40, "prompt_protocol_sha256": "f" * 64, "scoring_protocol_sha256": "0" * 64} for family in families],
        "execution": {"runner": "disk_budget_runner.py", "receipt_namespace": "receipts/ember-restart-evaluation"},
    }


def run(value: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manifest.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(path)], cwd=REPO, text=True, capture_output=True, check=False)


def test_accepts_complete_checkpoint_bound_manifest() -> None:
    result = run(manifest())
    assert result.returncode == 0, result.stderr
    assert "EMBER_RESTART_EVAL_CONTRACT: VALID" in result.stdout


def test_rejects_missing_audio_suite() -> None:
    value = manifest()
    value["suites"] = [suite for suite in value["suites"] if suite["family"] != "audio"]
    result = run(value)
    assert result.returncode == 2
    assert "MISSING_FAMILIES: audio" in result.stderr
