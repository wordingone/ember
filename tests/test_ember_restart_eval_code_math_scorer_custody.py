# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json"


def test_code_and_math_custody_pin_nonadmissible_scorer_bytes():
    custody = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert custody["scoring_adapters"] == [
        {
            "path": "scripts/ember_restart_eval_evalplus_adapter.py",
            "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_evalplus_adapter.py").read_bytes()).hexdigest(),
            "result_disposition": "SELFTEST_ONLY_NON_ADMISSIBLE",
        },
        {
            "path": "scripts/ember_restart_eval_evalplus_result.py",
            "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_evalplus_result.py").read_bytes()).hexdigest(),
            "result_disposition": "SELFTEST_ONLY_NON_ADMISSIBLE",
        },
        {
            "path": "scripts/ember_restart_eval_math_exact.py",
            "sha256": hashlib.sha256((ROOT / "scripts" / "ember_restart_eval_math_exact.py").read_bytes()).hexdigest(),
            "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE",
        },
    ]
