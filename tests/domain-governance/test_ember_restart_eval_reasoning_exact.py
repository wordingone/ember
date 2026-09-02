# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_reasoning_exact.py"
def test_scores_checkpoint_answers_against_frozen_reasoning_references():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);references=root/'references';predictions=root/'predictions';manifest=root/'manifest';score=root/'score'
  references.write_text('{"id":"r1","answer":"42"}\n{"id":"r2","answer":"red"}\n');predictions.write_text('{"id":"r1","answer":"42"}\n{"id":"r2","answer":"blue"}\n')
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'local-reasoning','benchmark_version':'1','references_sha256':hashlib.sha256(references.read_bytes()).hexdigest()}))
  r=subprocess.run([sys.executable,str(SCRIPT),'--frozen-reasoning-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(score)],text=True,capture_output=True);assert r.returncode==0,r.stderr
  payload=json.loads(score.read_text());assert payload['metrics']=={'exact_match':.5} and payload['sample_count']==2 and payload['criterion_result']=='FAILED'
