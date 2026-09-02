# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_text_fixture.py"


def test_scores_frozen_text_rows_as_non_admissible_selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); fixture = root / "fixture.json"; predictions = root / "predictions.json"; output = root / "output.json"
        fixture.write_text(json.dumps([{"id": "a", "answer": "yes"}, {"id": "b", "answer": "no"}]))
        predictions.write_text(json.dumps({"a": "yes", "b": "wrong"}))
        result = subprocess.run([sys.executable, str(SCRIPT), "--fixture", str(fixture), "--predictions", str(predictions), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text()) == {"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "benchmark_id": "frozen-text-fixture-v1", "rows": [{"id": "a", "correct": True}, {"id": "b", "correct": False}], "correct": 1, "total": 2}
