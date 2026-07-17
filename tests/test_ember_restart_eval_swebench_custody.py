# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-swebench-custody-v1.json"


def test_swebench_source_audit_records_no_frozen_task_release_or_eligible_runtime():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert custody["goal_id"] == "EMBER-02"
    assert custody["workstream_id"] == "EMBER-02C"
    assert custody["benchmark_id"] == "swe-bench"
    assert custody["source_commit"] == "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
    assert custody["benchmark_version"] == custody["source_commit"]
    assert custody["harness_sha256"] == "6959f0b4e4eaf979771f529b88e3e9df1daa7fe86bc4291feec2e7d320bf7f2e"
    assert custody["license_sha256"] == "2bd2e08df7147f67a69b42c10efae09bd4bf119df397371036187d5dd1b02f57"
    assert custody["protocol_sha256"] == "713f49f4382bead975b4e8e19674142ced799bb14396f8191614b7c81c6b0e2e"
    assert custody["source_only_audit"] == {
        "artifact_sha256": "2a56f54d6b9f2f424e6a45032f5a619580ffd7065de458b046eb988d3257e752",
        "runner_receipt_sha256": "4483c6e296bfd66034330406b72fef671d5ed1765277390b69c95afd82ab268c",
        "claim_status": "SOURCE_ONLY_NO_FROZEN_SWEBENCH_TASK_RELEASE",
    }
    assert custody["external_lite_release_audit"] == {
        "dataset_repository": "SWE-bench/SWE-bench_Lite",
        "upstream_revision": "69611d31007e1c6731db8bd5b5c3f2d33f5bab6e",
        "artifact_bytes": 1218485,
        "license_disposition": "UNDECLARED_IN_EXACT_DATASET_CARD",
        "materialization": "HELD_NO_LICENSE_PROVENANCE",
    }
    assert custody["admission"] == "NOT_EXECUTABLE_UNDECLARED_DATASET_LICENSE_AND_NO_OFFLINE_SANDBOX"
    assert custody["covered_families"] == ["code", "files"]
    assert custody["target_execution_permitted"] is False
