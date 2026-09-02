# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file());SCORER=ROOT/'scripts'/'ember_restart_eval_audiobench_bound.py';PREFLIGHT=ROOT/'scripts'/'ember_restart_eval_execution_preflight.py'
def test_audio_preflight_rejects_substituted_closed_run():
 with tempfile.TemporaryDirectory()as tmp:
  r=Path(tmp);c=r/'c';s=r/'s';h=r/'h';p=r/'p';run=r/'run';wrong=r/'wrong';pred=r/'pred';score=r/'score';out=r/'out'
  for x in(c,s,h,p):x.write_text(x.name)
  sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest();text='hello';row={'mixture_name':'m','weight':1.,'recall':.5,'fpr':.1,'transcript_sha256':hashlib.sha256(text.encode()).hexdigest()};identity={'suite':'x','per_mixture':[row]};run.write_text(json.dumps({**identity,'run_hash':hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'headline':{'weighted_recall':.5,'weighted_fpr':.1}}));wrong.write_text(run.read_text()+' ')
  pred.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':sha(c),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'audiobench','version':'v1','capability':'audio','split_sha256':sha(s),'protocol_sha256':sha(p)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'m','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'transcript','text':text}}]}));assert subprocess.run([sys.executable,str(SCORER),'--canonical-predictions',str(pred),'--run-artifact',str(run),'--score-output',str(score)]).returncode==0
  q=subprocess.run([sys.executable,str(PREFLIGHT),'--capability','audio','--checkpoint-manifest',str(c),'--benchmark-id','audiobench','--benchmark-version','v1','--split-artifact',str(s),'--harness-artifact',str(h),'--protocol-artifact',str(p),'--raw-predictions',str(pred),'--closed-run-artifact',str(wrong),'--result-artifact',str(score),'--output',str(out)],capture_output=True,text=True);assert q.returncode!=0 and not out.exists()
