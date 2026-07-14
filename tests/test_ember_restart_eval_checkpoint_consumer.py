# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from test_ember_restart_eval_checkpoint_consumer_v3_contract import write_v3


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_checkpoint_consumer.py"


def test_verifies_closed_v3_checkpoint_shards_and_emits_identity_receipt():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest, output = write_v3(root), root / "receipt.json"
        completed = subprocess.run([sys.executable, str(SCRIPT), "verify", str(manifest), "--model-config", str(root / "config.json"), "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        receipt = json.loads(output.read_text())
        assert receipt["result"] == "VERIFIED_CHECKPOINT_INPUT"
        assert receipt["checkpoint_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
