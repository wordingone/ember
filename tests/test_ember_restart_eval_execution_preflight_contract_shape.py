# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_execution_preflight.py"
def test_shapes_future_evaluation_evidence_fields_without_measured_receipt():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); checkpoint=root/"checkpoint.bin";split=root/"split.json";harness=root/"harness.py";protocol=root/"protocol.json";predictions=root/"predictions.json";score=root/"score.json";output=root/"out.json"
  checkpoint.write_bytes(b"checkpoint");split.write_text("[1,2]");harness.write_text("print('score')\n");protocol.write_text('{"version":1}');predictions.write_text('[{"id":"1"}]');score.write_text('{"metrics":{"accuracy":1.0},"criterion_result":"PASSED"}')
  result=subprocess.run([sys.executable,str(SCRIPT),"--capability","text","--checkpoint-manifest",str(checkpoint),"--benchmark-id","frozen-text","--benchmark-version","v1","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(predictions),"--result-artifact",str(score),"--output",str(output)],text=True,capture_output=True,check=False);assert result.returncode==0,result.stderr
  p=json.loads(output.read_text());assert p["result"]=="PREFLIGHT_ONLY" and p["criterion_id"]=="ember-3b-text-capability-v1" and p["criterion_result"]=="PASSED" and p["score_artifact_sha256"]==hashlib.sha256(score.read_bytes()).hexdigest()
