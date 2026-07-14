# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCORER=ROOT/'scripts'/'ember_restart_eval_audiobench.py';PREFLIGHT=ROOT/'scripts'/'ember_restart_eval_execution_preflight.py'
def test_exports_audiobench_per_mixture_records_as_canonical_raw_predictions():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);run=root/'run';scorer_raw=root/'scorer_raw';raw=root/'raw';score=root/'score';checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';out=root/'out';run.write_text(json.dumps({'suite':'ab/sound-id','run_hash':'a'*64,'headline':{'weighted_recall':.75,'weighted_fpr':.1},'per_mixture':[{'mixture_name':'x'}]}))
  for x in(checkpoint,split,harness,protocol):x.write_text(x.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest();s=subprocess.run([sys.executable,str(SCORER),'--run-artifact',str(run),'--raw-predictions',str(scorer_raw),'--score-output',str(score)],capture_output=True,text=True);assert s.returncode==0,s.stderr
  raw.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'b'*64,'tokenizer_sha256':'c'*64,'inference_implementation_sha256':'d'*64,'benchmark':{'id':'audiobench','version':'0fc7fef','capability':'audio','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'x','input_sha256':'e'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'transcript','text':'x'}}]}))
  p=subprocess.run([sys.executable,str(PREFLIGHT),'--capability','audio','--checkpoint-manifest',str(checkpoint),'--benchmark-id','audiobench','--benchmark-version','0fc7fef','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(raw),'--result-artifact',str(score),'--output',str(out)],capture_output=True,text=True);assert p.returncode==0,p.stderr
