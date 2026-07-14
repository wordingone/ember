#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed byte verifier for an owned sparse checkpoint manifest."""
import argparse,hashlib,json,os,tempfile
from pathlib import Path
def _sha256(path):
 d=hashlib.sha256()
 with path.open('rb')as f:
  for b in iter(lambda:f.read(1024*1024),b''):d.update(b)
 return d.hexdigest()
def _verify(m):
 p=json.loads(m.read_text(encoding='utf-8'))
 if not isinstance(p,dict) or p.get('schema_version')!='ember-sparse-checkpoint-v2':raise ValueError('unsupported checkpoint manifest')
 if not isinstance(p.get('model_config_sha256'),str) or len(p['model_config_sha256'])!=64 or not isinstance(p.get('shards'),list) or not p['shards']:raise ValueError('checkpoint manifest missing model or shards')
 for e in p['shards']:
  if not isinstance(e,dict) or set(e)!={'path','role','bytes','sha256'}:raise ValueError('checkpoint shard schema mismatch')
  q=m.parent/e['path']
  if not q.is_file() or q.stat().st_size!=e['bytes'] or _sha256(q)!=e['sha256']:raise ValueError('checkpoint shard integrity mismatch')
 return {'goal_id':'EMBER-02','workstream_id':'EMBER-02C','next_executed_outcome':'EMBER-02 first sufficiently pretrained clean-genesis 3B Ember','checkpoint_manifest_sha256':_sha256(m),'model_config_sha256':p['model_config_sha256'],'result':'VERIFIED_CHECKPOINT_INPUT','shard_count':len(p['shards'])}
def main():
 a=argparse.ArgumentParser();s=a.add_subparsers(dest='c',required=True);v=s.add_parser('verify');v.add_argument('manifest',type=Path);v.add_argument('--output',required=True,type=Path);x=a.parse_args()
 try:r=_verify(x.manifest)
 except (OSError,UnicodeError,json.JSONDecodeError,ValueError)as e:a.error(str(e))
 x.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=x.output.parent,delete=False)as h:json.dump(r,h,sort_keys=True,separators=(',',':'));h.write('\n');n=h.name
 os.replace(n,x.output)
if __name__=='__main__':main()
