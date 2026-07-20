#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,hashlib,json,os,re,tempfile
from pathlib import Path
HASH=re.compile(r'[0-9a-f]{64}')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):
 raw=p.read_text(encoding='utf-8')
 try:v=json.loads(raw);v=v if isinstance(v,list) else [v]
 except json.JSONDecodeError:v=[json.loads(x) for x in raw.splitlines() if x.strip()]
 out={}
 for x in v:
  if not isinstance(x,dict) or not isinstance(x.get('id'),str) or not x['id'] or not isinstance(x.get('answer'),str) or x['id'] in out:raise ValueError('each row needs a unique non-empty id and answer')
  out[x['id']]=x['answer']
 if not out:raise ValueError('rows must be non-empty')
 return out
def main():
 p=argparse.ArgumentParser();p.add_argument('--frozen-reasoning-manifest',required=True,type=Path);p.add_argument('--references',required=True,type=Path);p.add_argument('--predictions',required=True,type=Path);p.add_argument('--score-output',required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error('score output must not pre-exist')
 try:
  m=json.loads(a.frozen_reasoning_manifest.read_text(encoding='utf-8'));r=rows(a.references);q=rows(a.predictions)
  if not isinstance(m,dict) or m.get('result')!='PREFLIGHT_ONLY' or m.get('benchmark_id')!='local-reasoning' or m.get('benchmark_version')!='1' or m.get('references_sha256')!=sha(a.references) or not HASH.fullmatch(m.get('references_sha256','')):raise ValueError('frozen reasoning manifest does not bind supplied references')
 except (OSError,ValueError,json.JSONDecodeError) as e:p.error(f'invalid local answer artifacts: {e}')
 if r.keys()!=q.keys():p.error('predictions must exactly cover frozen reference ids')
 payload={'criterion_id':'ember-3b-reasoning-capability-v1','criterion_result':'FAILED','metrics':{'exact_match':sum(r[k]==q[k] for k in r)/len(r)},'sample_count':len(r),'references_sha256':sha(a.references),'frozen_reasoning_manifest_sha256':sha(a.frozen_reasoning_manifest),'upstream':'deterministic local frozen-answer scorer'}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.score_output.parent,delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+'\n');t=Path(h.name)
 os.replace(t,a.score_output)
if __name__=='__main__':main()
