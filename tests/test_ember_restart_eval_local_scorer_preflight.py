# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCORER=ROOT/"scripts"/"ember_restart_eval_text_exact.py"
PREFLIGHT=ROOT/"scripts"/"ember_restart_eval_execution_preflight.py"

def test_text_scorer_json_predictions_flow_into_non_admissible_preflight():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);references=root/"references.json";predictions=root/"predictions.json";score=root/"score.json";checkpoint=root/"checkpoint";split=root/"split";harness=root/"harness";protocol=root/"protocol";out=root/"out.json"
  references.write_text(json.dumps([{"id":"t1","answer":"yes"}]),encoding="utf-8");predictions.write_text(json.dumps([{"id":"t1","answer":"yes"}]),encoding="utf-8")
  for value in(checkpoint,split,harness,protocol):value.write_text(value.name,encoding="utf-8")
  score_run=subprocess.run([sys.executable,str(SCORER),"--references",str(references),"--predictions",str(predictions),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert score_run.returncode==0,score_run.stderr
  preflight=subprocess.run([sys.executable,str(PREFLIGHT),"--capability","text","--checkpoint-manifest",str(checkpoint),"--benchmark-id","frozen-text","--benchmark-version","v1","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(predictions),"--result-artifact",str(score),"--output",str(out)],text=True,capture_output=True,check=False)
  assert preflight.returncode==0,preflight.stderr
  assert json.loads(out.read_text(encoding="utf-8"))["result"]=="PREFLIGHT_ONLY"
