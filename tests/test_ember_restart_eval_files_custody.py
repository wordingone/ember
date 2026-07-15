# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-files-custody-v1.json"


def test_files_family_is_explicitly_held_without_pinned_tasks_or_runtime():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["benchmark_id"] == "swe-bench-lite"
    assert value["target_execution_permitted"] is False
    assert value["asset_disposition"] == "NO_LOCAL_PINNED_SWE_BENCH_TASKS_OR_RUNTIME"
    assert value["admission"] == "NOT_EXECUTABLE_NO_FROZEN_FILE_TASK_ASSETS"
    assert value["target_training_access"] == "FORBIDDEN"
    assert "local_path" not in value
