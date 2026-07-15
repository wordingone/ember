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
        "asset_disposition": "NO_LOCAL_PINNED_BROWSERGYM_RUNTIME_OR_FROZEN_MINIWOB_TASKS",
        "target_execution_permitted": False,
    }
    assert custody["structured_tools"] == {
        "benchmark_id": "bfcl",
        "source_commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "asset_disposition": "NO_LOCAL_PINNED_BFCL_RUNTIME_OR_FROZEN_TASKS",
        "target_execution_permitted": False,
    }
