# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green selftests for non-admissible reasoning and tool fixture scoring."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_structured_fixture.py"


def test_scores_reasoning_predictions_as_non_admissible_selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); fixture = root / "reasoning.json"; predictions = root / "predictions.json"; output = root / "output.json"
        fixture.write_text(json.dumps([{"id": "r1", "answer": "42"}, {"id": "r2", "answer": "blue"}]))
        predictions.write_text(json.dumps({"r1": "42", "r2": "red"}))
        result = subprocess.run([sys.executable, str(SCRIPT), "--capability", "reasoning", "--fixture", str(fixture), "--predictions", str(predictions), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text()) == {"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "capability": "reasoning", "rows": [{"id": "r1", "correct": True}, {"id": "r2", "correct": False}], "correct": 1, "total": 2}


def test_compares_tool_calls_canonically_as_non_admissible_selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); fixture = root / "tool.json"; predictions = root / "predictions.json"; output = root / "output.json"
        fixture.write_text(json.dumps([{"id": "t1", "expected_call": {"name": "lookup", "arguments": {"city": "Paris", "units": "metric"}}}, {"id": "t2", "expected_call": {"name": "search", "arguments": {"q": "ember"}}}]))
        predictions.write_text(json.dumps({"t1": {"arguments": {"units": "metric", "city": "Paris"}, "name": "lookup"}, "t2": {"name": "search", "arguments": {"q": "wrong"}}}))
        result = subprocess.run([sys.executable, str(SCRIPT), "--capability", "tool", "--fixture", str(fixture), "--predictions", str(predictions), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text()) == {"result": "SELFTEST", "admission": "NOT_ELIGIBLE", "capability": "tool", "rows": [{"id": "t1", "correct": True}, {"id": "t2", "correct": False}], "correct": 1, "total": 2}
