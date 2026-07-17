# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Strict MMMU custody must bind the owned checkpoint/config tuple."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-mmmu-validation-custody-v1.json"
ADAPTER = ROOT / "scripts" / "ember_restart_eval_mmmu.py"


def test_strict_mmmu_custody_binds_step2_checkpoint_and_config_in_protocol():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["checkpoint_manifest_sha256"] == "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"
    assert manifest["model_config_sha256"] == "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0"
    scorer = manifest["scorer"]
    adapter = manifest["scoring_adapter"]
    expected = hashlib.sha256(
        f"MMMU:{manifest['benchmark_version']}:{manifest['split']['answer_dictionary_sha256']}:{scorer['sha256']}:{manifest['license_sha256']}:{manifest['upstream_tree_git_sha1']}:{adapter['sha256']}:{manifest['image_input_materialization']['artifact_sha256']}:{manifest['checkpoint_manifest_sha256']}:{manifest['model_config_sha256']}".encode()
    ).hexdigest()
    assert manifest["protocol_sha256"] == expected
