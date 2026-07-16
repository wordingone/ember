# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-eval-browser-tool-custody-v1.json"


def test_browser_tool_custody_pins_fixture_and_static_scorer_bytes():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert custody["scoring_adapters"] == [
        {"path": "scripts/ember_restart_eval_browsergym.py", "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_browsergym.py").read_bytes()).hexdigest(), "result_disposition": "SELFTEST_ONLY_NON_ADMISSIBLE"},
        {"path": "scripts/ember_restart_eval_bfcl_static.py", "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_bfcl_static.py").read_bytes()).hexdigest(), "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE"},
    ]
