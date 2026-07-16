#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,hashlib,json,os,re,tempfile
from pathlib import Path
HASH=re.compile(r'[0-9a-f]{64}')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows_bytes(raw):
 out={}
 try:
  parsed=json.loads(raw);values=parsed if isinstance(parsed,list) else [parsed]
 except json.JSONDecodeError:
  values=[json.loads(y) for y in raw.splitlines() if y.strip()]
 for x in values:
  if not isinstance(x,dict) or not isinstance(x.get('id'),str) or not x['id'] or not isinstance(x.get('transcript'),str) or x['id'] in out:raise ValueError('each row needs a unique non-empty id and transcript')
  out[x['id']]=x['transcript']
 if not out:raise ValueError('rows must be non-empty')
 return out
def rows(p):return rows_bytes(p.read_bytes().decode('utf-8'))
def dist(a,b):
 p=list(range(len(b)+1))
 for i,x in enumerate(a,1):
  c=[i]
  for j,y in enumerate(b,1):c.append(min(p[j]+1,c[j-1]+1,p[j-1]+(x!=y)))
  p=c
 return p[-1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--frozen-audio-manifest',required=True,type=Path);p.add_argument('--references',required=True,type=Path);p.add_argument('--predictions',required=True,type=Path);p.add_argument('--score-output',required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error('score output must not pre-exist')
 try:
  manifest_bytes=a.frozen_audio_manifest.read_bytes();reference_bytes=a.references.read_bytes();prediction_bytes=a.predictions.read_bytes();m=json.loads(manifest_bytes.decode('utf-8'));r=rows_bytes(reference_bytes.decode('utf-8'));q=rows_bytes(prediction_bytes.decode('utf-8'));reference_sha256=hashlib.sha256(reference_bytes).hexdigest();manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest()
  if not isinstance(m,dict) or m.get('result')!='PREFLIGHT_ONLY' or m.get('benchmark_id')!='local-audio-wer' or m.get('benchmark_version')!='1' or m.get('references_sha256')!=reference_sha256 or not HASH.fullmatch(m.get('references_sha256','')):raise ValueError('frozen audio manifest does not bind supplied references')
 except (OSError,ValueError,json.JSONDecodeError)as e:p.error(f'invalid local transcript artifacts: {e}')
 if r.keys()!=q.keys():p.error('predictions must exactly cover frozen reference ids')
 words=sum(len(x.split())for x in r.values())
 if words<=0:p.error('frozen references must contain at least one word')
 payload={'result':'SELFTEST','claim_status':'SELFTEST_ONLY_LOCAL_AUDIO_WER','criterion_id':'ember-3b-audio-capability-v1','criterion_result':'FAILED','metrics':{'word_error_rate':sum(dist(r[k].split(),q[k].split())for k in r)/words},'sample_count':len(r),'references_sha256':reference_sha256,'predictions_sha256':hashlib.sha256(prediction_bytes).hexdigest(),'frozen_audio_manifest_sha256':manifest_sha256,'upstream':'deterministic local word-error-rate scorer'}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.score_output.parent,delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+'\n');t=Path(h.name)
 try:
  os.replace(t,a.score_output)
 finally:
  t.unlink(missing_ok=True)
if __name__=='__main__':main()
