# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_mmmu.py"
def test_refuses_non_multiple_choice_answers_before_upstream_execution():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); answers=root/"answers.json"; predictions=root/"predictions.json"; score=root/"score.json"
  answers.write_text(json.dumps({"validation_x_1":{"question_type":"open","ground_truth":"x"}}));predictions.write_text(json.dumps({"validation_x_1":"x"}))
  r=subprocess.run([sys.executable,str(SCRIPT),"--mmmu-root",str(root),"--answers",str(answers),"--predictions",str(predictions),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode!=0 and "multiple-choice" in r.stderr and not score.exists()
