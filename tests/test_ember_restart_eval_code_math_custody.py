# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json"


def test_evalplus_source_is_pinned_but_cannot_be_scored_without_frozen_task_assets():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert custody["schema_version"] == "ember-restart-benchmark-custody-v1"
    assert custody["benchmark_id"] == "evalplus"
    assert custody["source_commit"] == "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e"
    assert custody["source_tree"] == "1d0063f35139d70988828fd669aeb365e5030b68"
    assert custody["license"] == "Apache-2.0"
    assert custody["materialization"]["outcome"] == "COMPLETED"
    assert custody["materialization"]["max_b_write_gib"] == 0.25
    assert custody["asset_disposition"] == "SOURCE_ONLY_NO_FROZEN_HUMANEVALPLUS_OR_MBPPPLUS_TASK_ASSETS"
    assert custody["target_execution_permitted"] is False
