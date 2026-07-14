# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the deterministic text evaluation receipt adapter."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_text_adapter.py"


def test_emits_central_contract_shaped_text_receipt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "text-receipt.json"
        checkpoint = "a" * 64
        verifier = "b" * 64
        result = subprocess.run([sys.executable, str(SCRIPT), "--checkpoint-sha256", checkpoint, "--verifier-sha256", verifier, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {"capability": "text", "result": "MEASURED", "subject_checkpoint_sha256": checkpoint, "verifier_sha256": verifier}
