# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_fixture_runner.py"


def test_embedded_actual_values_are_labeled_non_admissible_selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); fixture = root / "fixture.json"; output = root / "output.json"
        fixture.write_text(json.dumps([{"id": c, "capability": c, "expected": "x", "actual": "x"} for c in ("text", "image", "audio", "reasoning", "tool")]))
        result = subprocess.run([sys.executable, str(SCRIPT), "--fixture", str(fixture), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text()) == {"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "correct": 5, "rows": [{"id": c, "capability": c, "correct": True} for c in ("text", "image", "audio", "reasoning", "tool")], "total": 5}
