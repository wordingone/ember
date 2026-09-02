# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,importlib.util,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_execution_preflight.py"
def _load_preflight():
 sys.path.insert(0,str(SCRIPT.parent))
 specification=importlib.util.spec_from_file_location("preflight_single_read",SCRIPT)
 assert specification is not None and specification.loader is not None
 module=importlib.util.module_from_spec(specification)
 specification.loader.exec_module(module)
 return module
def test_shapes_future_evaluation_evidence_fields_without_measured_receipt():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';predictions=root/'predictions';score=root/'score';out=root/'out'
  for path in(checkpoint,split,harness,protocol):path.write_text(path.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'x','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'x'}}]}));score.write_text(json.dumps({'metrics':{'accuracy':1.0},'criterion_id':'ember-3b-text-capability-v1','criterion_result':'PASSED','sample_count':1,'predictions_sha256':h(predictions)}))
  r=subprocess.run([sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(predictions),'--result-artifact',str(score),'--output',str(out)],text=True,capture_output=True);assert r.returncode==0,r.stderr;p=json.loads(out.read_text());assert p['result']=='PREFLIGHT_ONLY' and p['sample_count']==1 and p['criterion_id']=='ember-3b-text-capability-v1'

def test_rejects_existing_preflight_output_and_preserves_it():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';predictions=root/'predictions';score=root/'score';out=root/'out'
  for path in(checkpoint,split,harness,protocol):path.write_text(path.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'x','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'x'}}]}));score.write_text(json.dumps({'metrics':{'accuracy':1.0},'criterion_id':'ember-3b-text-capability-v1','criterion_result':'PASSED','sample_count':1,'predictions_sha256':h(predictions)}));out.write_text('keep')
  r=subprocess.run([sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(predictions),'--result-artifact',str(score),'--output',str(out)],text=True,capture_output=True)
  assert r.returncode!=0 and 'refusing to overwrite existing output' in r.stderr and out.read_text()=='keep'

def test_rejects_malformed_score_json_without_traceback():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';predictions=root/'predictions';score=root/'score';out=root/'out'
  for path in(checkpoint,split,harness,protocol):path.write_text(path.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'x','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'x'}}]}));score.write_text('{not json')
  r=subprocess.run([sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(predictions),'--result-artifact',str(score),'--output',str(out)],text=True,capture_output=True)
  assert r.returncode!=0 and 'invalid evaluator score JSON' in r.stderr and 'Traceback' not in r.stderr

def test_rejects_text_score_bound_to_different_canonical_predictions():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';predictions=root/'predictions';score=root/'score';out=root/'out'
  for path in(checkpoint,split,harness,protocol):path.write_text(path.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'x','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'x'}}]}))
  score.write_text(json.dumps({'metrics':{'accuracy':1.0},'criterion_id':'ember-3b-text-capability-v1','criterion_result':'PASSED','sample_count':1,'predictions_sha256':'0'*64}))
  r=subprocess.run([sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(predictions),'--result-artifact',str(score),'--output',str(out)],text=True,capture_output=True)
  assert r.returncode!=0 and 'score source hashes do not bind supplied evidence' in r.stderr and not out.exists()
def test_rejects_text_score_without_canonical_prediction_binding():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol';predictions=root/'predictions';score=root/'score';out=root/'out'
  for path in(checkpoint,split,harness,protocol):path.write_text(path.name)
  h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'x','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'x'}}]}))
  score.write_text(json.dumps({'metrics':{'accuracy':1.0},'criterion_id':'ember-3b-text-capability-v1','criterion_result':'PASSED','sample_count':1}))
  r=subprocess.run([sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(predictions),'--result-artifact',str(score),'--output',str(out)],text=True,capture_output=True)
  assert r.returncode!=0 and 'score source hashes do not bind supplied evidence' in r.stderr and not out.exists()

def test_text_preflight_reads_canonical_predictions_and_score_once(tmp_path,monkeypatch):
 checkpoint,split,harness,protocol=(tmp_path/name for name in ("checkpoint","split","harness","protocol"))
 for path in (checkpoint,split,harness,protocol):path.write_text(path.name)
 digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
 predictions=tmp_path/"predictions";score=tmp_path/"score";output=tmp_path/"output"
 predictions.write_text(json.dumps({"schema_version":"ember-owned-predictions-v1","claim_status":"NON_ADMISSIBLE_RAW_PREDICTIONS","checkpoint_manifest_sha256":digest(checkpoint),"model_config_sha256":"a"*64,"tokenizer_sha256":"b"*64,"inference_implementation_sha256":"c"*64,"benchmark":{"id":"x","version":"v1","capability":"text","split_sha256":digest(split),"protocol_sha256":digest(protocol)},"decoding":{"strategy":"GREEDY_AUTOREGRESSIVE","teacher_forcing":False,"max_new_tokens":1,"temperature":0,"top_p":1,"stop_token_ids":[1]},"rows":[{"id":"1","input_sha256":"d"*64,"generated_token_ids":[1],"stop_reason":"eos","output":{"kind":"text","text":"x"}}]}))
 score.write_text(json.dumps({"metrics":{"accuracy":1.0},"criterion_id":"ember-3b-text-capability-v1","criterion_result":"FAILED","sample_count":1,"predictions_sha256":digest(predictions)}))
 module=_load_preflight();inputs={predictions,score};reads={path:0 for path in inputs};read_bytes=Path.read_bytes;read_text=Path.read_text
 def track(path,reader,*args,**kwargs):
  if path in inputs:
   reads[path]+=1
   if reads[path]>1:raise AssertionError(f"reopened bound input: {path.name}")
  return reader(path,*args,**kwargs)
 monkeypatch.setattr(Path,"read_bytes",lambda path:track(path,read_bytes))
 monkeypatch.setattr(Path,"read_text",lambda path,*args,**kwargs:track(path,read_text,*args,**kwargs))
 monkeypatch.setattr(sys,"argv",[str(SCRIPT),"--capability","text","--checkpoint-manifest",str(checkpoint),"--benchmark-id","x","--benchmark-version","v1","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(predictions),"--result-artifact",str(score),"--output",str(output)])
 assert module.main() is None
 assert reads=={predictions:1,score:1}