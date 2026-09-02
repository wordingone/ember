# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"


def test_cli_accepts_shared_as_a_manifest_bound_route(tmp_path):
    completed = subprocess.run([sys.executable, str(SCRIPT), "--tokenizer", str(tmp_path / "missing-tokenizer.json"), "--checkpoint-manifest", str(tmp_path / "missing-manifest.json"), "--checkpoint-sha256", "a" * 64, "--model-config", str(tmp_path / "missing-config.json"), "--model-config-sha256", "b" * 64, "--output", str(tmp_path / "receipt.json"), "--active-expert", "shared"], capture_output=True, text=True)

    assert completed.returncode != 0
    assert "invalid choice" not in completed.stderr
