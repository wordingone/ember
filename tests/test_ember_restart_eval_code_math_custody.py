# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json"


def test_evalplus_source_and_frozen_code_task_assets_are_pinned_without_checkpoint_predictions():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert custody["schema_version"] == "ember-restart-benchmark-custody-v1"
    assert custody["benchmark_id"] == "evalplus"
    assert custody["source_commit"] == "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e"
    assert custody["source_tree"] == "1d0063f35139d70988828fd669aeb365e5030b68"
    assert custody["license"] == "Apache-2.0"
    assert custody["materialization"]["outcome"] == "COMPLETED"
    assert custody["materialization"]["max_b_write_gib"] == 0.25
    assert custody["frozen_task_assets"] == {
        "humanevalplus_v0.1.10": {"rows": 164, "sha256": "272720b90ac375502c8ed23cd791c2a93dfb22a911641a494da74a426c09f101", "receipt_sha256": "2edba3d347adfa753356bd0f132eff884192db4a92deeb9fe4df2b1943b698f7"},
        "mbppplus_v0.2.0": {"rows": 378, "sha256": "af43697e8791c4c149bdfd6b489d8b5412507551ac20e28a439f650b8225db63", "receipt_sha256": "28029857489e2633bd5646693e574a5d01b5ca2a15c57e30fd1c1018de8ed3b5"},
    }
    assert custody["asset_disposition"] == "FROZEN_HUMANEVALPLUS_AND_MBPPPLUS_TASK_ASSETS_NO_CHECKPOINT_BOUND_PREDICTIONS"
    assert custody["target_execution_permitted"] is False
