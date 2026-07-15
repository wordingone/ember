# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_materialized_multimodal_and_audio_custody_names_current_prediction_boundary():
    for name in (
        "ember-restart-mmmu-validation-custody-v1.json",
        "ember-restart-audiobench-custody-v1.json",
    ):
        custody = json.loads((ROOT / "manifests" / name).read_text(encoding="utf-8"))

        assert custody["admission"] == "NOT_EXECUTABLE_UNTRAINED_SPECIALIST_NO_CHECKPOINT_BOUND_PREDICTIONS"
        if name == "ember-restart-audiobench-custody-v1.json":
            assert custody["procedural_demo"] == {"artifact_sha256": "bd91917edb4ef4258624ea242fc4573364f18c8cae99423966002b6871cdcdf3", "disk_receipt_sha256": "41a06044333342cc998eefa2ed87bda34ae40647eca4b1bb4200eb8c35bdcb4f", "claim_status": "SELFTEST_ONLY_PROCEDURAL_AUDIO"}
        assert custody["target_training_access"] == "FORBIDDEN"


def test_spider_retains_its_separate_frozen_gold_and_database_boundary():
    custody = json.loads((ROOT / "manifests" / "ember-restart-spider-custody-v1.json").read_text(encoding="utf-8"))

    assert custody["admission"] == "NOT_EXECUTABLE_NO_FROZEN_GOLD_AND_DATABASE"


def test_mmmu_pinned_validation_materialization_is_source_compatible_not_a_score():
    custody = json.loads((ROOT / "manifests" / "ember-restart-mmmu-validation-custody-v1.json").read_text(encoding="utf-8"))
    assert custody["validation_parquet_materialization"] == {
        "upstream_revision": "f87afafe4afe71650b99ef5236d7b5bb3f6345c7",
        "artifact_sha256": "2f1f5ab0e961e8eb3f7082277dc354f0d503f775fb177a385585444ccd5110b4",
        "runner_receipt_sha256": "0302a0db75c07830ca0265c096379b0f5dd994e6c11c2699194d685f76bf4bfb",
        "claim_status": "FROZEN_SOURCE_COMPATIBILITY_ONLY",
    }

def test_spider_source_only_audit_binds_the_absent_asset_boundary():
    custody = json.loads((ROOT / "manifests" / "ember-restart-spider-custody-v1.json").read_text(encoding="utf-8"))
    assert custody["source_only_audit"] == {
        "artifact_sha256": "ac3f513e8e6a2436379b5db85269c86568f81285e7dd9603aa66c2d244895e31",
        "runner_receipt_sha256": "fd3c3af5f5300c4c288a2ef8181c0bc08d40beee5a5d7c1254a79d4ee8fbfd71",
        "claim_status": "SOURCE_ONLY_NO_FROZEN_SQL_EVALUATION_ASSETS",
    }

def test_spider_validation_pair_freeze_is_custody_only_without_databases():
    custody = json.loads((ROOT / "manifests" / "ember-restart-spider-custody-v1.json").read_text(encoding="utf-8"))
    assert custody["validation_pairs_materialization"] == {
        "upstream_revision": "0c350918f3f29ec754f1181c65cdce76cd6c133c",
        "artifact_sha256": "6fa91248385896a6e74dff55a01fdc8df9fc7854bd007bd092a75c663631c6de",
        "runner_receipt_sha256": "76e04b0d5a79e928f8344514fd1a31f3e9ec1dc836abc429b7d7321157a403c5",
        "claim_status": "FROZEN_SPIDER_VALIDATION_PAIRS_NO_DATABASE_EXECUTION",
    }