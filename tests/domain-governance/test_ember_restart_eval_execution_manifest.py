# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for a materialized evaluator-input manifest."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_execution_manifest.py"


def test_validates_content_addressed_materialized_execution_inputs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = {name: root / name for name in ("split.json", "harness.py", "protocol.json")}
        for name, path in paths.items(): path.write_text(name)
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"capability": "tool", "benchmark_id": "bfcl", "benchmark_version": "v3", "artifacts": {key: {"path": value.name, "sha256": hashlib.sha256(value.read_bytes()).hexdigest()} for key, value in {"split": paths["split.json"], "harness": paths["harness.py"], "protocol": paths["protocol.json"]}.items()}}))
        result = subprocess.run([sys.executable, str(SCRIPT), str(manifest)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"valid": True, "capability": "tool", "benchmark_id": "bfcl", "benchmark_version": "v3", "artifact_sha256": {"split_sha256": hashlib.sha256(paths["split.json"].read_bytes()).hexdigest(), "harness_sha256": hashlib.sha256(paths["harness.py"].read_bytes()).hexdigest(), "protocol_sha256": hashlib.sha256(paths["protocol.json"].read_bytes()).hexdigest()}}
