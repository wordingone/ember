# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import hashlib
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-arc-challenge-custody-v1.json"


def test_arc_challenge_custody_binds_actual_test_parquet_without_overwriting_inherited_template_pin():
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert value["materialization"] == {
        "upstream_revision": "210d026faf9955653af8916fad021475a3f00453",
        "artifact_sha256": "95135d0a6469b8ae573c3f408cc44c00061b70fc2b8933ab272eab571a269870",
        "runner_receipt_sha256": "d031c6e0de87ecc6eac71a8b3e78a023af024b2c43be5fd637c1313127b78a7b",
        "split_sha256": "62f03257e737aed263f55c6abf87c7bb0028a44a6bdd2a26eb1279eb42c1d1e9",
        "claim_status": "FROZEN_ARC_CHALLENGE_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS",
    }
    assert value["inherited_template_compatibility"] == "HASH_MISMATCH_SEPARATE_NONEXECUTABLE_CUSTODY"
    assert value["target_execution_permitted"] is False
def test_arc_protocol_pins_the_deterministic_scorer_bytes():
    protocol = json.loads((MANIFEST.parent / "ember-restart-arc-challenge-protocol-v1.json").read_text(encoding="utf-8"))
    adapter = protocol["scoring_adapter"]
    assert adapter["path"] == "scripts/ember_restart_eval_arc_challenge.py"
    assert adapter["sha256"] == hashlib.sha256((MANIFEST.parents[1] / adapter["path"]).read_bytes()).hexdigest()
    assert adapter["result_disposition"] == "PREFLIGHT_ONLY_NON_ADMISSIBLE"