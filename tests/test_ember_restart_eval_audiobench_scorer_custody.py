# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audiobench_custody_pins_only_bound_canonical_scorer():
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    assert custody["scoring_adapter"] == {"path": "scripts/ember_restart_eval_audiobench_bound.py", "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_audiobench_bound.py").read_bytes()).hexdigest(), "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE"}
    assert custody["admission"] == "NOT_EXECUTABLE_UNTRAINED_SPECIALIST_NO_CHECKPOINT_BOUND_PREDICTIONS"
