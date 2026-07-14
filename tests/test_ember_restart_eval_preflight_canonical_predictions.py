# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_execution_preflight.py'
def test_accepts_checkpoint_bound_canonical_prediction_envelope():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol'
  for x in (checkpoint,split,harness,protocol):x.write_text(x.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest();raw=root/'raw';score=root/'score';out=root/'out'
  raw.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'x','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':3,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'r','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'yes'}}]}));score.write_text(json.dumps({'criterion_id':'ember-3b-text-capability-v1','criterion_result':'FAILED','sample_count':1,'metrics':{'accuracy':0.0}}))
  r=subprocess.run([sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(raw),'--result-artifact',str(score),'--output',str(out)],capture_output=True,text=True);assert r.returncode==0,r.stderr;assert json.loads(out.read_text())['result']=='PREFLIGHT_ONLY'
