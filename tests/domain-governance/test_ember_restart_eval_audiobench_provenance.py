# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file());SCORER=ROOT/'scripts'/'ember_restart_eval_audiobench_bound.py'
def test_audio_score_carries_closed_run_and_prediction_byte_hashes():
 with tempfile.TemporaryDirectory()as tmp:
  r=Path(tmp);c=r/'c';s=r/'s';p=r/'p';run=r/'run';pred=r/'pred';score=r/'score'
  for x in(c,s,p):x.write_text(x.name)
  sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest();t='hello';row={'mixture_name':'m','weight':1.,'recall':.5,'fpr':.1,'transcript_sha256':hashlib.sha256(t.encode()).hexdigest()};i={'suite':'x','per_mixture':[row]};run.write_text(json.dumps({**i,'run_hash':hashlib.sha256(json.dumps(i,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'headline':{'weighted_recall':.5,'weighted_fpr':.1}}));pred.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':sha(c),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'audiobench','version':'v1','capability':'audio','split_sha256':sha(s),'protocol_sha256':sha(p)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'m','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'transcript','text':t}}]}));assert subprocess.run([sys.executable,str(SCORER),'--canonical-predictions',str(pred),'--run-artifact',str(run),'--score-output',str(score)]).returncode==0;v=json.loads(score.read_text());assert v['predictions_sha256']==sha(pred) and v['run_artifact_sha256']==sha(run)
