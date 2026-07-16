# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_mmlu_pro_score.py'

def test_scores_mmlu_pro_canonical_choice_labels_against_frozen_parquet():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);references=root/'mmlu.parquet';manifest=root/'manifest.json';predictions=root/'predictions.json';score=root/'score.json';version='b189ec765aa7ed75c8acfea42df31fdae71f97be';protocol='e'*64
  pq.write_table(pa.table({'question_id':[1,2],'question':['q1','q2'],'options':[['a','b'],['c','d']],'answer':['A','B'],'answer_index':[0,1]}),references);digest=hashlib.sha256(references.read_bytes()).hexdigest()
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'mmlu-pro','benchmark_version':version,'capability':'reasoning','references_sha256':digest,'split_sha256':digest,'protocol_sha256':protocol,'task_count':2}),encoding='utf-8')
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':'a'*64,'model_config_sha256':'b'*64,'tokenizer_sha256':'c'*64,'inference_implementation_sha256':'d'*64,'benchmark':{'id':'mmlu-pro','version':version,'capability':'reasoning','split_sha256':digest,'protocol_sha256':protocol},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[2]},'rows':[{'id':'1','input_sha256':'0'*64,'generated_token_ids':[2],'stop_reason':'eos','output':{'kind':'text','text':'A'}},{'id':'2','input_sha256':'1'*64,'generated_token_ids':[2],'stop_reason':'eos','output':{'kind':'text','text':'A'}}]}),encoding='utf-8')
  completed=subprocess.run([sys.executable,str(SCRIPT),'--frozen-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(score)],capture_output=True,text=True)
  assert completed.returncode==0,completed.stderr
  payload=json.loads(score.read_text(encoding='utf-8'));assert payload['result']=='PREFLIGHT_ONLY' and payload['claim_status']=='NON_ADMISSIBLE_FROZEN_MMLU_PRO_SCORER' and payload['metrics']=={'accuracy':0.5} and payload['sample_count']==2

def test_rejects_mmlu_pro_predictions_with_incomplete_frozen_row_coverage():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);references=root/'mmlu.parquet';manifest=root/'manifest.json';predictions=root/'predictions.json';score=root/'score.json';version='b189ec765aa7ed75c8acfea42df31fdae71f97be';protocol='e'*64
  pq.write_table(pa.table({'question_id':[1],'question':['q1'],'options':[['a','b']],'answer':['A'],'answer_index':[0]}),references);digest=hashlib.sha256(references.read_bytes()).hexdigest();manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'mmlu-pro','benchmark_version':version,'capability':'reasoning','references_sha256':digest,'split_sha256':digest,'protocol_sha256':protocol,'task_count':1}),encoding='utf-8')
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':'a'*64,'model_config_sha256':'b'*64,'tokenizer_sha256':'c'*64,'inference_implementation_sha256':'d'*64,'benchmark':{'id':'mmlu-pro','version':version,'capability':'reasoning','split_sha256':digest,'protocol_sha256':protocol},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[2]},'rows':[{'id':'other','input_sha256':'0'*64,'generated_token_ids':[2],'stop_reason':'eos','output':{'kind':'text','text':'A'}}]}),encoding='utf-8')
  completed=subprocess.run([sys.executable,str(SCRIPT),'--frozen-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(score)],capture_output=True,text=True)
  assert completed.returncode!=0 and not score.exists()

def test_rejects_valid_hex_mmlu_pro_protocol_not_derived_from_scorer_custody(tmp_path):
    root = tmp_path; references = root / "mmlu.parquet"; manifest = root / "manifest.json"; predictions = root / "predictions.json"; score = root / "score.json"
    pq.write_table(pa.table({"question_id": [1], "question": ["q1"], "options": [["a", "b"]], "answer": ["A"], "answer_index": [0]}), references)
    reference_sha = hashlib.sha256(references.read_bytes()).hexdigest(); version = "b189ec765aa7ed75c8c2f453518a537a8b2117bd137e7714d4ef1565e9ba06c1ecb9ad8"
    adapter_sha = hashlib.sha256(SCRIPT.read_bytes()).hexdigest(); license_sha = "f" * 64
    manifest.write_text(json.dumps({"schema_version": "ember-restart-mmlu-pro-freeze-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "mmlu-pro", "benchmark_version": version, "capability": "reasoning", "license_sha256": license_sha, "scoring_adapter_sha256": adapter_sha, "references_sha256": reference_sha, "split_sha256": reference_sha, "protocol_sha256": "0" * 64, "task_count": 1}), encoding="utf-8")
    predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "mmlu-pro", "version": version, "capability": "reasoning", "split_sha256": reference_sha, "protocol_sha256": "0" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "1", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "A"}}]}), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert completed.returncode != 0
    assert not score.exists()