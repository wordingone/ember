# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCORER=ROOT/'scripts'/'ember_restart_eval_text_exact.py';PREFLIGHT=ROOT/'scripts'/'ember_restart_eval_execution_preflight.py'
def test_text_scorer_json_predictions_flow_into_non_admissible_preflight():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);references=root/'references';scorer_predictions=root/'scorer_predictions';predictions=root/'predictions';score=root/'score';checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';out=root/'out';references.write_text(json.dumps([{'id':'t1','answer':'yes'}]));scorer_predictions.write_text(json.dumps([{'id':'t1','answer':'yes'}]))
  for x in(checkpoint,split,harness,protocol):x.write_text(x.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest();score_run=subprocess.run([sys.executable,str(SCORER),'--references',str(references),'--predictions',str(scorer_predictions),'--score-output',str(score)],capture_output=True,text=True);assert score_run.returncode==0,score_run.stderr
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'frozen-text','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'t1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'yes'}}]}))
  p=subprocess.run([sys.executable,str(PREFLIGHT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','frozen-text','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(predictions),'--result-artifact',str(score),'--output',str(out)],capture_output=True,text=True);assert p.returncode==0,p.stderr;assert json.loads(out.read_text())['result']=='PREFLIGHT_ONLY'
