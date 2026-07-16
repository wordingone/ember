# goal_id: EMBER-02
# workstream_id: EMBER-02C
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
  payload=json.loads(score.read_text());assert payload['claim_status']=='SELFTEST_ONLY_FIXTURE_REASONING_ANSWERS' and payload['metrics']=={'exact_match':.5} and payload['sample_count']==2 and payload['criterion_result']=='FAILED' and payload['result']=='SELFTEST' and payload['predictions_sha256']==hashlib.sha256(predictions.read_bytes()).hexdigest()

def test_reasoning_score_replace_failure_cleans_temporary_output(monkeypatch, tmp_path):
 import importlib.util,sys,pytest
 spec=importlib.util.spec_from_file_location("reasoning_cleanup",SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 references=tmp_path/"references";predictions=tmp_path/"predictions";manifest=tmp_path/"manifest";output=tmp_path/"score"
 references.write_text('{"id":"a","answer":"one"}\n');predictions.write_text('{"id":"a","answer":"one"}\n');manifest.write_text(json.dumps({"result":"PREFLIGHT_ONLY","benchmark_id":"local-reasoning","benchmark_version":"1","references_sha256":hashlib.sha256(references.read_bytes()).hexdigest()}))
 monkeypatch.setattr(module.os,"replace",lambda *_: (_ for _ in ()).throw(OSError("replace failed")));monkeypatch.setattr(sys,"argv",[str(SCRIPT),"--frozen-reasoning-manifest",str(manifest),"--references",str(references),"--predictions",str(predictions),"--score-output",str(output)])
 with pytest.raises(OSError): module.main()
 assert not list(tmp_path.glob("tmp*"))