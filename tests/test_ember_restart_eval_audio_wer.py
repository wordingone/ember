# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_audio_wer.py'
def test_scores_checkpoint_transcripts_against_frozen_private_references():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);r=root/'references';p=root/'predictions';m=root/'manifest';s=root/'score'
  r.write_text('{"id":"a","transcript":"one two"}\n{"id":"b","transcript":"three"}\n');p.write_text('{"id":"a","transcript":"one too"}\n{"id":"b","transcript":"three"}\n')
  m.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'local-audio-wer','benchmark_version':'1','references_sha256':hashlib.sha256(r.read_bytes()).hexdigest()}))
  q=subprocess.run([sys.executable,str(SCRIPT),'--frozen-audio-manifest',str(m),'--references',str(r),'--predictions',str(p),'--score-output',str(s)],capture_output=True,text=True);assert q.returncode==0,q.stderr
  v=json.loads(s.read_text());assert v['metrics']=={'word_error_rate':1/3} and v['sample_count']==2 and v['criterion_result']=='FAILED'

def test_audio_row_parser_consumes_exact_snapshot_bytes():
 import importlib.util
 spec=importlib.util.spec_from_file_location("audio_wer",SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 payload=b'{"id":"a","transcript":"one"}\n'
 assert module.rows_bytes(payload)=={"a":"one"}
def test_audio_score_replace_failure_cleans_temporary_output(monkeypatch, tmp_path):
 import importlib.util, sys
 spec=importlib.util.spec_from_file_location("audio_wer_cleanup",SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 references=tmp_path/"references";predictions=tmp_path/"predictions";manifest=tmp_path/"manifest";output=tmp_path/"score"
 references.write_text('{"id":"a","transcript":"one"}\n');predictions.write_text('{"id":"a","transcript":"one"}\n');manifest.write_text(json.dumps({"result":"PREFLIGHT_ONLY","benchmark_id":"local-audio-wer","benchmark_version":"1","references_sha256":hashlib.sha256(references.read_bytes()).hexdigest()}))
 monkeypatch.setattr(module.os,"replace",lambda *_: (_ for _ in ()).throw(OSError("replace failed")))
 monkeypatch.setattr(sys,"argv",[str(SCRIPT),"--frozen-audio-manifest",str(manifest),"--references",str(references),"--predictions",str(predictions),"--score-output",str(output)])
 with __import__("pytest").raises(OSError): module.main()
 assert not list(tmp_path.glob("tmp*"))