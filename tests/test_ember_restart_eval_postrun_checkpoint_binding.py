# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Post-run checkpoint binding must use the emitted manifest/config bytes."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_postrun_checkpoint_binding.py"


def _fixture(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_bytes(b'{"post_run":true}\n')
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    manifest = tmp_path / "checkpoint-manifest.json"
    manifest.write_text(json.dumps({"schema_version": "ember-sparse-checkpoint-v3", "model_config_sha256": config_sha, "global_step": 3}), encoding="utf-8")
    return manifest, config, config_sha


def test_binds_postrun_manifest_and_config_bytes_without_reusing_prerun_anchor(tmp_path):
    manifest, config, config_sha = _fixture(tmp_path)
    output = tmp_path / "binding.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--checkpoint-manifest", str(manifest), "--model-config", str(config), "--pre-run-manifest-sha256", "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b", "--pre-run-config-sha256", "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0", "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["binding_scope"] == "POST_RUN_EMITTED_CHECKPOINT"
    assert value["checkpoint_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert value["model_config_sha256"] == config_sha
    assert value["model_config_sha256"] != "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0"
    assert value["result"] == "PREFLIGHT_ONLY"


def test_rejects_postrun_manifest_that_self_reports_a_different_config(tmp_path):
    manifest, config, _ = _fixture(tmp_path)
    manifest.write_text(json.dumps({"schema_version": "ember-sparse-checkpoint-v3", "model_config_sha256": "0" * 64}), encoding="utf-8")
    output = tmp_path / "binding.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--checkpoint-manifest", str(manifest), "--model-config", str(config), "--pre-run-manifest-sha256", "a" * 64, "--pre-run-config-sha256", "b" * 64, "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode != 0
    assert not output.exists()
