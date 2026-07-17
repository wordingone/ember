# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mmmu_custody_binds_repeatable_runtime_audit():
    manifest = json.loads((ROOT / "manifests" / "ember-restart-mmmu-validation-custody-v1.json").read_text(encoding="utf-8"))
    audit = manifest["runtime_audit"]
    assert audit == {
        "path": "scripts/ember_restart_eval_mmmu_runtime_audit.py",
        "sha256": hashlib.sha256((ROOT / audit["path"]).read_bytes()).hexdigest(),
        "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE",
    }
