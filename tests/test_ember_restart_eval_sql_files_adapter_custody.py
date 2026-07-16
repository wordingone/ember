# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sql_and_files_custody_pin_only_their_actual_nonadmissible_components():
    spider = json.loads((ROOT / "manifests" / "ember-restart-spider-custody-v1.json").read_text(encoding="utf-8"))
    swe = json.loads((ROOT / "manifests" / "ember-restart-swebench-custody-v1.json").read_text(encoding="utf-8"))
    assert spider["scoring_adapter"] == {"path": "scripts/ember_restart_eval_spider.py", "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_spider.py").read_bytes()).hexdigest(), "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE"}
    assert swe["source_audit_adapter"] == {"path": "scripts/ember_restart_eval_swebench_source_audit.py", "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_swebench_source_audit.py").read_bytes()).hexdigest(), "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE"}
    assert spider["admission"] == "NOT_EXECUTABLE_NO_FROZEN_GOLD_AND_DATABASE"
    assert swe["admission"] == "NOT_EXECUTABLE_UNDECLARED_DATASET_LICENSE_AND_NO_OFFLINE_SANDBOX"
