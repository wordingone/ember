# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_execution_preflight.py'
def test_non_audiobench_audio_does_not_require_closed_run_artifact():
 with tempfile.TemporaryDirectory()as tmp:
  r=Path(tmp);c=r/'c';s=r/'s';h=r/'h';p=r/'p';raw=r/'raw';score=r/'score';out=r/'out'
  for x in(c,s,h,p):x.write_text(x.name)
  sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest();raw.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':sha(c),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'librispeech-wer','version':'v1','capability':'audio','split_sha256':sha(s),'protocol_sha256':sha(p)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'transcript','text':'x'}}]}));score.write_text(json.dumps({'criterion_id':'ember-3b-audio-capability-v1','criterion_result':'FAILED','sample_count':1,'metrics':{'wer':1.0}}));x=subprocess.run([sys.executable,str(SCRIPT),'--capability','audio','--checkpoint-manifest',str(c),'--benchmark-id','librispeech-wer','--benchmark-version','v1','--split-artifact',str(s),'--harness-artifact',str(h),'--protocol-artifact',str(p),'--raw-predictions',str(raw),'--result-artifact',str(score),'--output',str(out)],capture_output=True,text=True);assert x.returncode==0,x.stderr
