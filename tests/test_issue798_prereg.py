# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
from pathlib import Path

import pytest

from exp703_prereg import LaunchNotReady, canonical_manifest_sha256, validate_prereg_manifest


def _manifest():
    return {
        "schema": "ember-703-ppm-screen-prereg-v1",
        "issue": 798,
        "order_cap": 8,
        "escape_method": "D",
        "train_target_bytes": 2 * 1024**3,
        "selection": "interleaved",
        "heldout_manifest_sha256": "a" * 64,
        "shard_ids": [{"id": "s0", "sha256": "b" * 64, "bytes": 2 * 1024**3}],
        "lambda_grid": [i / 100 for i in range(1, 100)],
        "seed": 703,
        "raw_byte_custody": {"source_url": "https://example.invalid/raw", "sha256": "c" * 64},
    }


def test_closed_manifest_and_launch_readiness_refuse_unbound_consumer(tmp_path: Path):
    value = _manifest()
    value["manifest_sha256"] = canonical_manifest_sha256(value)
    path = tmp_path / "prereg.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    validated = validate_prereg_manifest(path)
    assert validated["issue"] == 798
    with pytest.raises(LaunchNotReady, match="DECISIVE_CONSUMER_UNBOUND"):
        validated.require_launch_ready()


def test_tampered_manifest_is_rejected(tmp_path: Path):
    value = _manifest()
    value["manifest_sha256"] = canonical_manifest_sha256(value)
    value["shard_ids"][0]["bytes"] += 1
    path = tmp_path / "prereg.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest_sha256"):
        validate_prereg_manifest(path)


def test_unknown_field_and_unbound_consumer_refuse(tmp_path: Path):
    value = _manifest()
    value["manifest_sha256"] = canonical_manifest_sha256(value)
    value["caller_claim"] = "not-authority"
    path = tmp_path / "prereg.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="closed v1 set"):
        validate_prereg_manifest(path)

    value = _manifest()
    value["manifest_sha256"] = canonical_manifest_sha256(value)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    consumer = tmp_path / "consumer.py"
    consumer.write_text("def run_measure(): pass\n", encoding="utf-8")
    validated = validate_prereg_manifest(path)
    with pytest.raises(LaunchNotReady, match="DECISIVE_CONSUMER_UNBOUND"):
        validated.require_launch_ready(consumer)
