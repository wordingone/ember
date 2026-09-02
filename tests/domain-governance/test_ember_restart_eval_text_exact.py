# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_text_exact.py"
def test_scores_checkpoint_text_answers_against_frozen_references():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);references=root/"references.jsonl";predictions=root/"predictions.json";manifest=root/'manifest.json';score=root/"score.json"
  references.write_text('{"id":"t1","answer":"yes"}\n{"id":"t2","answer":"no"}\n',encoding="utf-8")
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'local-text','benchmark_version':'1','references_sha256':hashlib.sha256(references.read_bytes()).hexdigest(),'checkpoint_manifest_sha256':'a'*64,'model_config_sha256':'b'*64,'split_sha256':'e'*64,'protocol_sha256':'f'*64}),encoding='utf-8')
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':'a'*64,'model_config_sha256':'b'*64,'tokenizer_sha256':'c'*64,'inference_implementation_sha256':'d'*64,'benchmark':{'id':'local-text','version':'1','capability':'text','split_sha256':'e'*64,'protocol_sha256':'f'*64},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[2]},'rows':[{'id':'t1','input_sha256':'0'*64,'generated_token_ids':[2],'stop_reason':'eos','output':{'kind':'text','text':'yes'}},{'id':'t2','input_sha256':'1'*64,'generated_token_ids':[2],'stop_reason':'eos','output':{'kind':'text','text':'maybe'}}]}),encoding='utf-8')
  r=subprocess.run([sys.executable,str(SCRIPT),"--frozen-text-manifest",str(manifest),"--references",str(references),"--predictions",str(predictions),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode==0,r.stderr
  payload=json.loads(score.read_text(encoding="utf-8"));assert payload['metrics']=={'exact_match':0.5} and payload['sample_count']==2 and payload['criterion_result']=='FAILED' and payload['predictions_sha256']==hashlib.sha256(predictions.read_bytes()).hexdigest()