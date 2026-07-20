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


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_checkpoint_consumer.py"


def test_requires_exact_config_bytes_and_matching_training_optimizer():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = write_v3(root)
        config = root / "config.json"
        content = json.loads(manifest.read_text())
        config.write_text(json.dumps({"training": {"optimizer": content["optimizer_contract"]}}), encoding="utf-8")
        content["model_config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(content), encoding="utf-8")
        output = root / "receipt.json"
        completed = subprocess.run([sys.executable, str(SCRIPT), "verify", str(manifest), "--model-config", str(config), "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        assert output.exists()
