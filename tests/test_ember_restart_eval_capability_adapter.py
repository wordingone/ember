# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftests for all central-contract-shaped evaluator receipt envelopes."""
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_capability_adapter.py"

def test_emits_all_five_central_contract_capabilities() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); checkpoint = "a" * 64; verifier = "b" * 64
        for capability in ("text", "image", "audio", "reasoning", "tool"):
            output = root / f"{capability}.json"
            result = subprocess.run([sys.executable, str(SCRIPT), "--capability", capability, "--checkpoint-sha256", checkpoint, "--verifier-sha256", verifier, "--output", str(output)], text=True, capture_output=True, check=False)
            assert result.returncode == 0, result.stderr
            assert json.loads(output.read_text(encoding="utf-8")) == {"capability": capability, "result": "MEASURED", "subject_checkpoint_sha256": checkpoint, "verifier_sha256": verifier}
