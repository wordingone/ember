# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_checkpoint_consumer.py"


def test_rejects_legacy_v2_checkpoint_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        shard = root / "shared.pt"
        manifest = root / "checkpoint-manifest.json"
        output = root / "receipt.json"
        shard.write_bytes(b"legacy")
        manifest.write_text(json.dumps({"schema_version": "ember-sparse-checkpoint-v2", "model_config_sha256": "a" * 64, "shards": [{"path": shard.name, "role": "shared_model_and_optimizer", "bytes": shard.stat().st_size, "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()}]}), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "verify", str(manifest), "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode != 0
        assert not output.exists()
