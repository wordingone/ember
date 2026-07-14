# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_execution_runner.py"


def test_runs_evaluator_before_emitting_non_admissible_evidence_bundle():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); checkpoint = root / "checkpoint"; split = root / "split"; harness = root / "harness"; protocol = root / "protocol"; predictions = root / "predictions.json"; score = root / "score.json"; result = root / "result.json"; runner = root / "runner.py"
        for path in (checkpoint, split, harness, protocol): path.write_bytes(path.name.encode())
        runner.write_text("import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps([{'id':'1'}]))\nPath(sys.argv[2]).write_text(json.dumps({'accuracy':1.0}))\n")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--capability", "text", "--checkpoint", str(checkpoint), "--benchmark-id", "unit", "--benchmark-version", "v1", "--split-artifact", str(split), "--harness-artifact", str(harness), "--protocol-artifact", str(protocol), "--raw-predictions", str(predictions), "--result-artifact", str(score), "--criterion-result", "PASSED", "--output", str(result), "--", sys.executable, str(runner), str(predictions), str(score)], text=True, capture_output=True, check=False)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(result.read_text())
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["admission"] == "NOT_ELIGIBLE"
        assert payload["sample_count"] == 1
