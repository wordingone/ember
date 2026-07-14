# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_execution_preflight.py"
def test_accepts_checkpoint_manifest_named_like_central_verifier_contract():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);checkpoint=root/"checkpoint-manifest.json";split=root/"split";harness=root/"harness";protocol=root/"protocol";predictions=root/"predictions";score=root/"score";output=root/"output"
  for path in(checkpoint,split,harness,protocol):path.write_text(path.name)
  predictions.write_text('[{"id":"1"}]');score.write_text('{"metrics":{"accuracy":1.0},"criterion_result":"PASSED"}')
  r=subprocess.run([sys.executable,str(SCRIPT),"--capability","text","--checkpoint-manifest",str(checkpoint),"--benchmark-id","x","--benchmark-version","v1","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(predictions),"--result-artifact",str(score),"--output",str(output)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr;assert json.loads(output.read_text())["result"]=="PREFLIGHT_ONLY"
