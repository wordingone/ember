#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze MMLU-Pro test bytes without a checkpoint capability claim."""
from __future__ import annotations
import argparse,hashlib,json,os,re,tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
COMMIT=re.compile(r'[0-9a-f]{40}');SHA256=re.compile(r'[0-9a-f]{64}');SPLIT=Path('data/test-00000-of-00001.parquet')
def digest(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def has_mit(card:bytes)->bool:
 text=card.decode('utf-8').replace('\r\n','\n')
 if not text.startswith('---\n'):return False
 end=text.find('\n---',4)
 if end<0:return False
 value=yaml.safe_load(text[4:end]);return isinstance(value,dict) and value.get('license')=='mit'
def main()->int:
 parser=argparse.ArgumentParser();parser.add_argument('--dataset-root',required=True,type=Path);parser.add_argument('--revision',required=True);parser.add_argument('--protocol-sha256',required=True);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
 if args.output.exists():parser.error('output must not pre-exist')
 if not COMMIT.fullmatch(args.revision) or not SHA256.fullmatch(args.protocol_sha256):parser.error('revision and protocol hash must be lowercase content identifiers')
 try:
  card=(args.dataset_root/'README.md').read_bytes();split=(args.dataset_root/SPLIT).read_bytes()
  if not has_mit(card):raise ValueError('MMLU-Pro card must declare MIT license')
  rows=pq.read_table(pa.BufferReader(split),columns=['question_id','question','options','answer','answer_index']).to_pylist();ids=[r.get('question_id') if isinstance(r,dict) else None for r in rows]
  def valid(r):return isinstance(r,dict) and isinstance(r.get('question_id'),int) and isinstance(r.get('question'),str) and bool(r['question']) and isinstance(r.get('options'),list) and bool(r['options']) and all(isinstance(x,str) and x for x in r['options']) and isinstance(r.get('answer'),str) and r['answer'] and isinstance(r.get('answer_index'),int) and 0<=r['answer_index']<len(r['options']) and r['answer']==chr(ord('A')+r['answer_index'])
  if not rows or len(set(ids))!=len(rows) or any(not valid(r) for r in rows):raise ValueError('MMLU-Pro rows require unique ids, nonempty options, and matching answer indexes')
 except (OSError,UnicodeDecodeError,pa.ArrowException,ValueError,yaml.YAMLError) as error:parser.error(str(error))
 payload={'schema_version':'ember-restart-mmlu-pro-freeze-v1','result':'PREFLIGHT_ONLY','claim_status':'FROZEN_MMLU_PRO_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS','benchmark_id':'mmlu-pro','benchmark_version':args.revision,'capability':'reasoning','license':'MIT','license_sha256':digest(card),'references_sha256':digest(split),'split_sha256':digest(split),'protocol_sha256':args.protocol_sha256,'task_count':len(rows)}
 args.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=args.output.parent,prefix=args.output.name+'.',suffix='.tmp',delete=False) as h:h.write(json.dumps(payload,sort_keys=True)+'\n');temporary=Path(h.name)
 try:
  os.replace(temporary,args.output)
 finally:
  temporary.unlink(missing_ok=True)
 return 0
if __name__=='__main__':raise SystemExit(main())