# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-browser-tool-custody-v1.json"


def test_bfcl_custody_binds_runtime_audit_and_keeps_unpinned_live_tool_runtime_ineligible():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))
    runtime = custody["structured_tools"]["runtime_audit"]
    assert runtime == {
        "artifact_sha256": "a4ad0d1326773714cbc97674aa964822b6490c91a25ceca0a4b04c94114c06b5",
        "runner_receipt_sha256": "3e3d7fb9859725ed4badcdb5a2ce9bb66303d92ede40f845a636a3066ea759f5",
        "claim_status": "RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK",
    }
    assert custody["structured_tools"]["target_execution_permitted"] is False
