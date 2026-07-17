# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""MMLU-Pro license-card identity must be explicit and protocol-bound."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-mmlu-pro-custody-v1.json"
PROTOCOL = ROOT / "manifests" / "ember-restart-mmlu-pro-protocol-v1.json"


def test_mmlu_pro_public_custody_binds_the_pinned_license_card_and_derived_protocol():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert custody["license_card_sha256"] == "4bd710f67da3fa359a33edce1b4b5816b3de416c823c2624ba5e89c2557d2a47"
    assert protocol["license_card_sha256"] == custody["license_card_sha256"]
    assert protocol["protocol_status"] == "FROZEN_LICENSE_CARD_BOUND"
    adapter = hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_mmlu_pro_score.py").read_bytes()).hexdigest()
    expected = hashlib.sha256(f"mmlu-pro:{custody['benchmark_version']}:{custody['references_sha256']}:{custody['license_card_sha256']}:{adapter}".encode()).hexdigest()
    assert protocol["protocol_sha256"] == expected


def test_mmlu_pro_custody_manifest_hash_in_protocol_is_current():
    custody_bytes = MANIFEST.read_bytes()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["custody_manifest_sha256"] == hashlib.sha256(custody_bytes).hexdigest()
