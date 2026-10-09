# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_mmmu.py"

def test_converts_central_json_list_predictions_to_private_upstream_shape():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);mmmu=root/"mmmu-root"/"mmmu";mmmu.mkdir(parents=True);answers=root/"answers.json";predictions=root/"predictions.json";score=root/"score.json"
  answers.write_text(json.dumps({"validation_math_1":{"question_type":"multiple-choice","ground_truth":"A"}}),encoding="utf-8");predictions.write_text(json.dumps([{"id":"validation_math_1","prediction":"A"}]),encoding="utf-8")
  (mmmu/"main_eval_only.py").write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--output_path');p.add_argument('--answer_path');a=p.parse_args();assert json.load(open(a.output_path))=={'validation_math_1':'A'};print({'Overall':{'num':1,'acc':1.0}})\n",encoding="utf-8")
  r=subprocess.run([sys.executable,str(SCRIPT),"--mmmu-root",str(root/"mmmu-root"),"--answers",str(answers),"--predictions",str(predictions),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode==0,r.stderr
  assert json.loads(score.read_text(encoding="utf-8"))["sample_count"]==1
