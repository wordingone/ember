#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze GSM8K main/test bytes without making a capability claim."""
from __future__ import annotations
import argparse, hashlib, json, os, re, tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
COMMIT=re.compile(r"[0-9a-f]{40}"); SHA256=re.compile(r"[0-9a-f]{64}"); SPLIT=Path("main/test-00000-of-00001.parquet")
def digest(data: bytes)->str:return hashlib.sha256(data).hexdigest()
def has_mit(card: bytes)->bool:
 text=card.decode("utf-8").replace("\r\n","\n")
 if not text.startswith("---\n"):return False
 end=text.find("\n---",4)
 if end<0:return False
 value=yaml.safe_load(text[4:end])
 if not isinstance(value,dict):return False
 license_value=value.get("license"); values=license_value if isinstance(license_value,list) else [license_value]
 return all(isinstance(item,str) for item in values) and "mit" in values
def main()->int:
 parser=argparse.ArgumentParser();parser.add_argument("--dataset-root",required=True,type=Path);parser.add_argument("--revision",required=True);parser.add_argument("--protocol-sha256",required=True);parser.add_argument("--output",required=True,type=Path);args=parser.parse_args()
 if args.output.exists():parser.error("output must not pre-exist")
 if not COMMIT.fullmatch(args.revision) or not SHA256.fullmatch(args.protocol_sha256):parser.error("revision and protocol hash must be lowercase content identifiers")
 try:
  card=(args.dataset_root/"README.md").read_bytes(); split=(args.dataset_root/SPLIT).read_bytes()
  if not has_mit(card):raise ValueError("GSM8K card must declare MIT license")
  rows=pq.read_table(pa.BufferReader(split),columns=["question","answer"]).to_pylist(); questions=[row.get("question") if isinstance(row,dict) else None for row in rows]
  if not rows or len(set(questions))!=len(rows) or any(not isinstance(row,dict) or not isinstance(row.get("question"),str) or not row["question"] or not isinstance(row.get("answer"),str) or "####" not in row["answer"] for row in rows):raise ValueError("GSM8K rows require unique questions and final answer markers")
 except (OSError,UnicodeDecodeError,pa.ArrowException,ValueError,yaml.YAMLError) as error:parser.error(str(error))
 payload={"schema_version":"ember-restart-gsm8k-freeze-v1","result":"PREFLIGHT_ONLY","claim_status":"FROZEN_GSM8K_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS","benchmark_id":"gsm8k","benchmark_version":args.revision,"capability":"reasoning","license":"MIT","license_sha256":digest(card),"references_sha256":digest(split),"split_sha256":digest(split),"protocol_sha256":args.protocol_sha256,"task_count":len(rows)}
 args.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=args.output.parent,prefix=args.output.name+".",suffix=".tmp",delete=False) as handle:handle.write(json.dumps(payload,sort_keys=True)+"\n"); temporary=Path(handle.name)
 os.replace(temporary,args.output);return 0
if __name__=="__main__":raise SystemExit(main())