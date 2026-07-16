# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-eval-browser-tool-custody-v1.json"


def test_browser_and_structured_tool_protocols_refuse_execution_without_local_runtime_and_frozen_tasks():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert custody["schema_version"] == "ember-restart-benchmark-custody-v1"
    assert custody["browser_ui"] == {
        "benchmark_id": "browsergym-miniwob",
        "source_commit": "9e779f087de9a65668b6974d11f9ce9816026e96",
        "source_tree": "d33e398c18d04d5da742b1c1ec11c4aab8bc010b",
        "license": "Apache-2.0",
        "license_sha256": "b192c58991e8ff585cc574615d40e74185404d4b96c1109d423071ab1367344b",
        "asset_disposition": "NO_LOCAL_PINNED_BROWSERGYM_RUNTIME_OR_FROZEN_MINIWOB_TASKS",
        "target_execution_permitted": False,
    }
    assert custody["structured_tools"] == {
        "benchmark_id": "bfcl",
        "source_commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "source_tree": "8f9c7a04207ca8be448e084dd0802a6aecbd313f",
        "license": "Apache-2.0",
        "license_sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        "materialization": {"max_b_write_gib": 0.5, "outcome": "COMPLETED", "receipt_sha256": "f2aafee550b4252f2b352c92d93224fd0c86e1954fc9ff782bd51d2522b0d622"},
        "frozen_static_non_live": {"categories": ["simple_python", "simple_java", "simple_javascript", "multiple", "parallel", "parallel_multiple", "irrelevance"], "file_count": 7, "tree_sha256": "9d83acb5c37b78d87dd4ad12ccebad360376e3bbdae457c60079aeb6d191424d", "scorable_categories": ["simple_python", "simple_java", "simple_javascript", "multiple", "parallel", "parallel_multiple"], "excluded_categories": {"irrelevance": "NO_LOCAL_POSSIBLE_ANSWER_ORACLE"}, "private_frozen_simple_artifact": {"artifact_sha256": "d04fb5ec83ddf7c21a3c1fea6cfb7992dc88bd773e783ed9c47398eb0b7b5ce8", "disk_receipt_sha256": "3260ce70d7fa0714b62b8323e8d53be709271cd499f84b064a00e3490ada6edf", "split_sha256": "b5397a483dfe48b202c8907622e02276c3a8c33f1009066899cf50c097256aac", "protocol_sha256": "571b4aa3e029a975fdfd512b915fdc85c908063d90fc5e72ac8ef7aa06ce05a4", "task_count": 550, "claim_status": "PREFLIGHT_ONLY"}, "execution_permitted": False},
        "runtime_audit": {"artifact_sha256": "a4ad0d1326773714cbc97674aa964822b6490c91a25ceca0a4b04c94114c06b5", "runner_receipt_sha256": "daf45583d81da37f14e34421de074e03995e0628254d4afa8e0e3f69a430b455", "claim_status": "RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK"},
        "asset_disposition": "PINNED_BFCL_SOURCE_AND_PRIVATE_SIMPLE_TASKS_NO_EXECUTABLE_PINNED_HARNESS_ENVIRONMENT",
        "target_execution_permitted": False,
    }