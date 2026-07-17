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
        "runner_receipt_sha256": "daf45583d81da37f14e34421de074e03995e0628254d4afa8e0e3f69a430b455",
        "claim_status": "RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK",
        "path": "scripts/ember_restart_eval_bfcl_runtime_audit.py",
        "sha256": "205bf667dc3b27e964a08266c0e39a07726ffad433a293f43ce2286dad2ffc36",
        "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE",
    }
    assert custody["structured_tools"]["target_execution_permitted"] is False
