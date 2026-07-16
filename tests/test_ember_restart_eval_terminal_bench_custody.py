# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-terminal-bench-custody-v1.json"


def test_terminal_bench_cache_is_explicitly_nonexecutable_without_digest_pinned_offline_tasks():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert custody["schema_version"] == "ember-restart-benchmark-custody-v1"
    assert custody["benchmark_id"] == "terminal-bench"
    assert custody["source_commit"] == "2fd12b88aafdd04a52c298e3940bcb189f9766d6"
    assert custody["source_tree"] == "ec7c02c7f0b59ce8ed2f7c88d1e70cda7427edfa"
    assert custody["asset_disposition"] == "PREFLIGHT_ONLY_NO_ELIGIBLE_OFFLINE_DIGEST_PINNED_TASK"
    assert custody["eligibility"] == {
        "task_count": 89,
        "digest_pinned_image_task_count": 0,
        "network_disabled_task_count": 0,
        "eligible_task_count": 0,
    }
    assert custody["target_execution_permitted"] is False
