# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path

ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCORER=ROOT/'scripts'/'ember_restart_eval_audiobench_bound.py'

def _sha(path):
 return hashlib.sha256(path.read_bytes()).hexdigest()

def _predictions(root,text='hello'):
 checkpoint=root/'checkpoint';split=root/'split';protocol=root/'protocol'
 for path in(checkpoint,split,protocol):path.write_text(path.name)
 payload={'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':_sha(checkpoint),'model_config_sha256':'a'*64,'tokenizer_sha256':'b'*64,'inference_implementation_sha256':'c'*64,'benchmark':{'id':'audiobench','version':'v1','capability':'audio','split_sha256':_sha(split),'protocol_sha256':_sha(protocol)},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[1]},'rows':[{'id':'m','input_sha256':'d'*64,'generated_token_ids':[1],'stop_reason':'eos','output':{'kind':'transcript','text':text}}]}
 path=root/'predictions.json';path.write_text(json.dumps(payload));return path

def _run(root,pred,payload):
 run=root/'run.json';score=root/'score.json';run.write_text(json.dumps(payload))
 return subprocess.run([sys.executable,str(SCORER),'--canonical-predictions',str(pred),'--run-artifact',str(run),'--score-output',str(score)],capture_output=True,text=True),score

def test_rejects_a_perfect_headline_or_run_hash_not_derived_from_closed_rows():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);text='hello';pred=_predictions(root,text);row={'mixture_name':'m','weight':1.0,'recall':.5,'fpr':.1,'transcript_sha256':hashlib.sha256(text.encode()).hexdigest()}
  result,score=_run(root,pred,{'suite':'ab/sound-id','per_mixture':[row],'run_hash':'f'*64,'headline':{'weighted_recall':1.0,'weighted_fpr':0.0}})
  assert result.returncode!=0 and not score.exists()

def test_rejects_empty_duplicate_and_nonfinite_closed_mixtures():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);pred=_predictions(root);row={'mixture_name':'m','weight':1.0,'recall':.5,'fpr':.1,'transcript_sha256':hashlib.sha256(b'hello').hexdigest()}
  cases=[{'suite':'ab/sound-id','per_mixture':[],'run_hash':'0'*64,'headline':{}},{'suite':'ab/sound-id','per_mixture':[row,row],'run_hash':'0'*64,'headline':{}},{'suite':'ab/sound-id','per_mixture':[dict(row,recall=float('nan'))],'run_hash':'0'*64,'headline':{}}]
  for number,payload in enumerate(cases):
   run=root/f'run-{number}.json';score=root/f'score-{number}.json';run.write_text(json.dumps(payload))
   result=subprocess.run([sys.executable,str(SCORER),'--canonical-predictions',str(pred),'--run-artifact',str(run),'--score-output',str(score)],capture_output=True,text=True)
   assert result.returncode!=0 and not score.exists()
