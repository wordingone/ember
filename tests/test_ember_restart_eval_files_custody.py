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
    assert value["asset_disposition"] == "PINNED_SWE_BENCH_SOURCE_NO_LOCAL_TASK_SPLIT_OR_RUNTIME"
    assert value["source_commit"] == "f7bbbb2ccdf479001d6467c9e34af59e44a840f9"
    assert value["source_tree"] == "81083caddb04c76896805b38eaa4e43ca3ce2d63"
    assert value["license"] == "MIT"
    assert value["license_sha256"] == "2bd2e08df7147f67a69b42c10efae09bd4bf119df397371036187d5dd1b02f57"
    assert value["materialization"]["receipt_sha256"] == "b153682746bfcfacbe3f33d8f8749f13f59ea1bd5f17dc937143852c865a8f5c"
    assert value["admission"] == "NOT_EXECUTABLE_NO_FROZEN_FILE_TASK_ASSETS"
    candidate = value['candidate_task_release']
    assert candidate == {'dataset': 'SWE-bench/SWE-bench_Lite', 'revision': '69611d31007e1c6731db8bd5b5c3f2d33f5bab6e', 'config': 'default', 'split': 'test', 'rows': 300, 'parquet_bytes': 1111559, 'license_disposition': 'UNDECLARED_IN_EXACT_DATASET_CARD', 'materialization_permitted': False}
    assert value['verified_candidate'] == {'dataset': 'SWE-bench/SWE-bench_Verified', 'revision': '91aa3ed51b709be6457e12d00300a6a596d4c6a3', 'config': 'default', 'split': 'test', 'rows': 500, 'parquet_bytes': 2096679, 'license_disposition': 'UNDECLARED_IN_EXACT_DATASET_CARD', 'materialization_permitted': False}
    assert value["target_training_access"] == "FORBIDDEN"
    assert "local_path" not in value