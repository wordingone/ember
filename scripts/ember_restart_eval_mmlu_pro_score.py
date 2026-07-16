#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score canonical MMLU-Pro label predictions against frozen parquet bytes."""
import argparse, hashlib, json, os, tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from ember_restart.prediction_contract import ContractError, validate_predictions

def sha256(data: bytes) -> str:return hashlib.sha256(data).hexdigest()

def expected_answers(data: bytes) -> dict[str, str]:
 try:rows=pq.read_table(pa.BufferReader(data),columns=['question_id','options','answer','answer_index']).to_pylist()
 except pa.ArrowException as error:raise ValueError('frozen MMLU-Pro references must be parquet') from error
 answers={}
 for row in rows:
  identifier=str(row.get('question_id')) if isinstance(row,dict) and isinstance(row.get('question_id'),int) and not isinstance(row.get('question_id'),bool) else None; options=row.get('options') if isinstance(row,dict) else None; answer=row.get('answer') if isinstance(row,dict) else None; index=row.get('answer_index') if isinstance(row,dict) else None
  if not isinstance(identifier,str) or identifier in answers or not isinstance(options,list) or not options or any(not isinstance(option,str) or not option for option in options) or not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(options) or not isinstance(answer,str) or answer!=chr(ord('A')+index):raise ValueError('frozen MMLU-Pro references require unique ids and matching answer indexes')
  answers[identifier]=answer
 if not answers:raise ValueError('frozen MMLU-Pro references must be non-empty')
 return answers

def predicted_answers(data: bytes) -> tuple[dict,dict[str,str]]:
 try:envelope=validate_predictions(json.loads(data.decode('utf-8')))
 except (ContractError,UnicodeDecodeError,json.JSONDecodeError) as error:raise ValueError('canonical checkpoint predictions are required') from error
 rows={}
 for row in envelope['rows']:
  output=row['output']
  if output.get('kind')!='text' or not isinstance(output.get('text'),str) or row['id'] in rows:raise ValueError('canonical MMLU-Pro predictions require unique text outputs')
  rows[row['id']]=output['text'].strip()
 if not rows:raise ValueError('canonical MMLU-Pro predictions must be non-empty')
 return envelope,rows

def atomic_write(path:Path,payload:dict)->None:
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as handle:handle.write(json.dumps(payload,sort_keys=True)+'\n');temporary=Path(handle.name)
 try:os.replace(temporary,path)
 finally:temporary.unlink(missing_ok=True)

def main()->int:
 parser=argparse.ArgumentParser();parser.add_argument('--frozen-manifest',required=True,type=Path);parser.add_argument('--references',required=True,type=Path);parser.add_argument('--predictions',required=True,type=Path);parser.add_argument('--score-output',required=True,type=Path);args=parser.parse_args()
 if args.score_output.exists():parser.error('score output must not pre-exist')
 try:
  manifest_bytes=args.frozen_manifest.read_bytes();reference_bytes=args.references.read_bytes();prediction_bytes=args.predictions.read_bytes();manifest=json.loads(manifest_bytes.decode('utf-8'));references=expected_answers(reference_bytes);envelope,predictions=predicted_answers(prediction_bytes);benchmark=envelope['benchmark']
  fields={'id':'benchmark_id','version':'benchmark_version','split_sha256':'split_sha256','protocol_sha256':'protocol_sha256'}
  if not isinstance(manifest,dict) or manifest.get('result')!='PREFLIGHT_ONLY' or manifest.get('benchmark_id')!='mmlu-pro' or manifest.get('capability')!='reasoning' or manifest.get('references_sha256')!=sha256(reference_bytes) or manifest.get('split_sha256')!=sha256(reference_bytes) or manifest.get('task_count')!=len(references) or any(benchmark.get(field)!=manifest.get(manifest_field) for field,manifest_field in fields.items()):raise ValueError('frozen MMLU-Pro manifest does not bind canonical prediction identity')
  if set(references)!=set(predictions):raise ValueError('canonical MMLU-Pro predictions must exactly cover frozen reference ids')
 except (OSError,UnicodeDecodeError,ValueError,json.JSONDecodeError,pa.ArrowException) as error:parser.error(f'invalid MMLU-Pro scorer inputs: {error}')
 atomic_write(args.score_output,{'result':'PREFLIGHT_ONLY','claim_status':'NON_ADMISSIBLE_FROZEN_MMLU_PRO_SCORER','criterion_id':'ember-3b-reasoning-capability-v1','criterion_result':'FAILED','metrics':{'accuracy':sum(predictions[key]==answer for key,answer in references.items())/len(references)},'sample_count':len(references),'checkpoint_manifest_sha256':envelope['checkpoint_manifest_sha256'],'model_config_sha256':envelope['model_config_sha256'],'references_sha256':sha256(reference_bytes),'predictions_sha256':sha256(prediction_bytes),'frozen_manifest_sha256':sha256(manifest_bytes),'upstream':'deterministic frozen MMLU-Pro exact-label scorer'})
 return 0
if __name__=='__main__':raise SystemExit(main())