# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_execution_preflight.py"
def invoke(score):
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);checkpoint=root/"checkpoint";split=root/"split";harness=root/"harness";protocol=root/"protocol";predictions=root/"predictions";result=root/"result";output=root/"output"
  for path in(checkpoint,split,harness,protocol):path.write_text(path.name)
  predictions.write_text('[{"id":"1"}]');result.write_text(json.dumps(score))
  return subprocess.run([sys.executable,str(SCRIPT),"--capability","text","--checkpoint-manifest",str(checkpoint),"--benchmark-id","x","--benchmark-version","v1","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(predictions),"--result-artifact",str(result),"--output",str(output)],text=True,capture_output=True,check=False)
def test_requires_evaluator_explicit_criterion_and_exact_integer_sample_count():
 base={"metrics":{"accuracy":1.0},"criterion_id":"ember-3b-text-capability-v1","criterion_result":"PASSED","sample_count":1}
 for changed in ({"criterion_id":None},{"criterion_id":"wrong"},{"sample_count":None},{"sample_count":2},{"sample_count":True}):
  score={**base,**changed};r=invoke(score);assert r.returncode==2, r.stderr
