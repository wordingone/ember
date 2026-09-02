# goal_id: EMBER-02
# workstream_id: EMBER-02A
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
