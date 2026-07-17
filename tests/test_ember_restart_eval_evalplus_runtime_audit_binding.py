# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_evalplus_custody_binds_the_repeatable_runtime_audit():
    manifest = json.loads((ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json").read_text(encoding="utf-8"))
    audit = manifest["runtime_audit"]
    assert audit == {
        "artifact_sha256": "f2bf6444a47103ed1ecdb9ccf7e97ee984fa10925ce8f7e673da1bd296e43a45",
        "runner_receipt_sha256": "b192a9e35220bec690440c24774401c70256523d5e9d84f9bd3015db50c4afd4",
        "claim_status": "RUNTIME_HELD_MUTABLE_CONTAINER_BUILD",
        "path": "scripts/ember_restart_eval_evalplus_runtime_audit.py",
        "sha256": hashlib.sha256((ROOT / "scripts/ember_restart_eval_evalplus_runtime_audit.py").read_bytes()).hexdigest(),
        "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE",
    }