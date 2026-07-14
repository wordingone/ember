# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_execution_runner.py'
def base(root,predictions,score,out):
 checkpoint=root/'checkpoint';split=root/'split';harness=root/'harness';protocol=root/'protocol'
 for x in(checkpoint,split,harness,protocol):x.write_text(x.name)
 return [sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(checkpoint),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(split),'--harness-artifact',str(harness),'--protocol-artifact',str(protocol),'--raw-predictions',str(predictions),'--result-artifact',str(score),'--output',str(out)],checkpoint,split,protocol
def test_derives_criterion_from_canonical_evaluator_score_envelope():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);pred=root/'p';score=root/'s';out=root/'o';runner=root/'r.py';runner.write_text("import hashlib,json,sys\nfrom pathlib import Path\nh=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()\np,s,c,split,protocol=sys.argv[1:]\nPath(p).write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':h(c),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'x','version':'v1','capability':'text','split_sha256':h(split),'protocol_sha256':h(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'1','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'text','text':'x'}}]}))\nPath(s).write_text(json.dumps({'metrics':{'accuracy':1.0},'criterion_id':'ember-3b-text-capability-v1','criterion_result':'PASSED','sample_count':1}))\n")
  command,checkpoint,split,protocol=base(root,pred,score,out);r=subprocess.run(command+['--',sys.executable,str(runner),str(pred),str(score),str(checkpoint),str(split),str(protocol)],text=True,capture_output=True);assert r.returncode==0,r.stderr;assert json.loads(out.read_text())['criterion_result']=='PASSED'
def test_timeout_fails_closed_without_publishing_output():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);pred=root/'p';score=root/'s';out=root/'o';runner=root/'r.py';runner.write_text('import time\ntime.sleep(2)\n');command,*_=base(root,pred,score,out);r=subprocess.run(command+['--timeout-seconds','1','--',sys.executable,str(runner)],text=True,capture_output=True);assert r.returncode!=0 and not out.exists()
