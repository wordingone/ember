#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze HellaSwag test bytes without making a capability claim."""
from __future__ import annotations
import argparse,hashlib,json,os,re,tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
COMMIT=re.compile(r"[0-9a-f]{40}");SHA256=re.compile(r"[0-9a-f]{64}");SPLIT=Path('data/test-00000-of-00001.parquet')
def digest(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def main()->int:
 parser=argparse.ArgumentParser();parser.add_argument('--dataset-root',required=True,type=Path);parser.add_argument('--revision',required=True);parser.add_argument('--protocol-sha256',required=True);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
 if args.output.exists():parser.error('output must not pre-exist')
 if not COMMIT.fullmatch(args.revision) or not SHA256.fullmatch(args.protocol_sha256):parser.error('revision and protocol hash must be lowercase content identifiers')
 try:
  card=(args.dataset_root/'README.md').read_bytes();split=(args.dataset_root/SPLIT).read_bytes();card_text=card.decode('utf-8').lower()
  if 'licensing information' not in card_text or 'mit' not in card_text:raise ValueError('HellaSwag card must provide explicit MIT licensing information')
  rows=pq.read_table(pa.BufferReader(split),columns=['ind','source_id','ctx','endings','label']).to_pylist();ids=[(row.get('source_id'),row.get('ind')) if isinstance(row,dict) else None for row in rows]
  def valid(row):
   return isinstance(row,dict) and isinstance(row.get('ind'),int) and isinstance(row.get('source_id'),str) and bool(row['source_id']) and isinstance(row.get('ctx'),str) and bool(row['ctx']) and isinstance(row.get('endings'),list) and bool(row['endings']) and all(isinstance(value,str) and value for value in row['endings']) and isinstance(row.get('label'),str)
  labels=[row['label'] for row in rows if isinstance(row,dict)]
  labels_withheld=bool(labels) and all(label=='' for label in labels)
  labels_complete=bool(labels) and all(label.isdigit() and int(label)<len(row['endings']) for label,row in zip(labels,rows))
  if not rows or len(set(ids))!=len(rows) or any(not valid(row) for row in rows) or not (labels_withheld or labels_complete):raise ValueError('HellaSwag rows require unique ids, nonempty endings, and uniformly withheld or in-range labels')
 except (OSError,UnicodeDecodeError,pa.ArrowException,ValueError) as error:parser.error(str(error))
 payload={'schema_version':'ember-restart-hellaswag-freeze-v1','result':'PREFLIGHT_ONLY','admission':'NOT_EXECUTABLE_NO_FROZEN_LABELS' if labels_withheld else 'NOT_EXECUTABLE_NO_CHECKPOINT_BOUND_PREDICTIONS','claim_status':'FROZEN_HELLASWAG_TEST_INPUTS_NO_FROZEN_LABELS' if labels_withheld else 'FROZEN_HELLASWAG_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS','benchmark_id':'hellaswag','benchmark_version':args.revision,'capability':'reasoning','license':'MIT','license_sha256':digest(card),'references_sha256':digest(split),'split_sha256':digest(split),'protocol_sha256':args.protocol_sha256,'task_count':len(rows)}
 args.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=args.output.parent,prefix=args.output.name+'.',suffix='.tmp',delete=False) as h:h.write(json.dumps(payload,sort_keys=True)+'\n');temporary=Path(h.name)
 os.replace(temporary,args.output);return 0
if __name__=='__main__':raise SystemExit(main())