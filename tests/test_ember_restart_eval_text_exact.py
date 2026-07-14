# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_text_exact.py"
def test_scores_checkpoint_text_answers_against_frozen_references():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);references=root/"references.jsonl";predictions=root/"predictions.jsonl";manifest=root/'manifest.json';score=root/"score.json"
  references.write_text('{"id":"t1","answer":"yes"}\n{"id":"t2","answer":"no"}\n',encoding="utf-8");predictions.write_text('{"id":"t1","answer":"yes"}\n{"id":"t2","answer":"maybe"}\n',encoding="utf-8")
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'local-text','benchmark_version':'1','references_sha256':hashlib.sha256(references.read_bytes()).hexdigest()}),encoding='utf-8')
  r=subprocess.run([sys.executable,str(SCRIPT),"--frozen-text-manifest",str(manifest),"--references",str(references),"--predictions",str(predictions),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode==0,r.stderr
  payload=json.loads(score.read_text(encoding="utf-8"));assert payload['metrics']=={'exact_match':0.5} and payload['sample_count']==2 and payload['criterion_result']=='FAILED'
