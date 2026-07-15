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
    assert custody["source_only_audit"] == {
        "artifact_sha256": "2a56f54d6b9f2f424e6a45032f5a619580ffd7065de458b046eb988d3257e752",
        "runner_receipt_sha256": "f37595272cab74d6bef2df3f800ee152e0260c29b403ab5e87f0440df6afbd99",
        "claim_status": "SOURCE_ONLY_NO_FROZEN_SWEBENCH_TASK_RELEASE",
    }
    assert custody["admission"] == "NOT_EXECUTABLE_NO_FROZEN_TASK_RELEASE_OR_OFFLINE_SANDBOX"
    assert custody["covered_families"] == ["code", "files"]
    assert custody["target_execution_permitted"] is False
