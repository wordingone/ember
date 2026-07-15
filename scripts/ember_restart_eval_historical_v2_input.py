#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify a custody-pinned v2 bundle as historical input only; never current-rung evidence."""
import argparse,hashlib,json,os,tempfile
from pathlib import Path

ROLES={'shared.pt':'shared_model_and_optimizer','replay-state.pt':'replay_state','expert-vision.pt':'expert_vision','expert-audio.pt':'expert_audio','expert-reasoning.pt':'expert_reasoning','expert-tool.pt':'expert_tool'}
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as handle:
  for block in iter(lambda:handle.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def fail(message):raise ValueError(message)
def verify(manifest_path,custody_path):
 manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'));custody=json.loads(custody_path.read_text(encoding='utf-8-sig'));digest=sha(manifest_path)
 if not isinstance(manifest,dict) or manifest.get('schema_version')!='ember-sparse-checkpoint-v2':fail('historical input requires v2 manifest')
 if not isinstance(custody,dict) or custody.get('schema_version')!='ember-restart-hardlink-custody-v1' or custody.get('result')!='HISTORICAL_ONLY_V2' or custody.get('source_schema_version')!='ember-sparse-checkpoint-v2' or custody.get('checkpoint_manifest_sha256')!=digest:fail('historical custody receipt does not bind v2 manifest')
 records=manifest.get('shards')
 if not isinstance(records,list) or len(records)!=len(ROLES):fail('historical v2 shard set is incomplete')
 seen={}
 for record in records:
  if not isinstance(record,dict) or set(record)!={'path','role','bytes','sha256'}:fail('historical v2 shard schema is invalid')
  name=record['path'];path=manifest_path.parent/name
  if name not in ROLES or record['role']!=ROLES[name] or name in seen or not isinstance(record['bytes'],int) or record['bytes']<=0 or not isinstance(record['sha256'],str):fail('historical v2 shard mapping is invalid')
  if not path.is_file() or path.stat().st_size!=record['bytes'] or sha(path)!=record['sha256']:fail(f'historical v2 shard integrity mismatch: {name}')
  seen[name]=record
 if set(seen)!=set(ROLES):fail('historical v2 shard paths are incomplete')
 files=custody.get('files')
 if not isinstance(files,list):fail('historical custody file index is invalid')
 indexed={item.get('name'):item for item in files if isinstance(item,dict)}
 for name,record in {manifest_path.name:{'sha256':digest,'bytes':manifest_path.stat().st_size},**seen}.items():
  item=indexed.get(name)
  if not isinstance(item,dict) or item.get('sha256')!=record['sha256'] or item.get('bytes')!=record['bytes']:fail(f'historical custody file binding mismatch: {name}')
 return {'goal_id':'EMBER-02','workstream_id':'EMBER-02C','next_executed_outcome':'EMBER-02 first sufficiently pretrained clean-genesis 3B Ember','result':'HISTORICAL_V2_INPUT_ONLY','admission':'NOT_ELIGIBLE','checkpoint_manifest_sha256':digest,'source_schema_version':'ember-sparse-checkpoint-v2','shard_count':len(seen)}
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--custody-receipt',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);arguments=parser.parse_args()
 if arguments.output.exists():parser.error('refusing to overwrite existing output')
 try:payload=verify(arguments.manifest,arguments.custody_receipt)
 except (OSError,UnicodeError,ValueError,json.JSONDecodeError) as error:parser.error(str(error))
 arguments.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=arguments.output.parent,delete=False)as handle:json.dump(payload,handle,sort_keys=True);handle.write('\n');temporary=handle.name
 os.replace(temporary,arguments.output)

if __name__=='__main__':main()
