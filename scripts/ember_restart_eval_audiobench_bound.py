#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score a closed AudioBench run only against canonical audio predictions."""
import argparse,hashlib,json,math,os,sys,tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ember_restart.prediction_contract import ContractError,validate_predictions

def _canonical(value):
 return json.dumps(value,sort_keys=True,separators=(',',':'))

def _finite(value):
 return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

EXPECTED_VERSION="0fc7fef2709c00ac1e2eb2b372ec4c56362bb8c6"
EXPECTED_TREE="4a01fdd3731c70a496993055bbf11499053ea344"
EXPECTED_LICENSE_SHA256="54233ca9f039653155e71f92b7cdf484041bee1fdcd90bafac2b5e21e4c916c9"

def _protocol_sha256(custody):
 identity = {
  "benchmark_id": custody["benchmark_id"],
  "benchmark_version": custody["benchmark_version"],
  "suite": custody["suite"],
  "upstream_tree_git_sha1": custody["upstream_tree_git_sha1"],
  "license_sha256": custody["license_sha256"],
  "scoring_adapter": custody["scoring_adapter"],
 }
 return hashlib.sha256(_canonical(identity).encode()).hexdigest()

def _frozen_custody(data):
 try:
  custody=json.loads(data.decode('utf-8'))
 except (UnicodeError,json.JSONDecodeError) as exc:
  raise ValueError('frozen AudioBench custody invalid') from exc
 if not isinstance(custody, dict):
  raise ValueError('frozen AudioBench custody invalid')
 adapter=custody.get('scoring_adapter') if isinstance(custody,dict) else None
 if custody.get('benchmark_id')!='audiobench' or custody.get('benchmark_version')!=EXPECTED_VERSION or custody.get('upstream_tree_git_sha1')!=EXPECTED_TREE or custody.get('license_sha256')!=EXPECTED_LICENSE_SHA256 or custody.get('suite')!='ab/sound-id' or not isinstance(adapter,dict) or adapter.get('path')!='scripts/ember_restart_eval_audiobench_bound.py' or adapter.get('result_disposition')!='PREFLIGHT_ONLY_NON_ADMISSIBLE' or adapter.get('sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
  raise ValueError('frozen AudioBench custody invalid')
 if custody.get('protocol_sha256') != _protocol_sha256(custody):
  raise ValueError('frozen AudioBench custody invalid')
 return custody

def _closed_run(run):
 if not isinstance(run,dict) or set(run)!={'suite','per_mixture','run_hash','headline'}:
  raise ValueError('closed run schema mismatch')
 if not isinstance(run['suite'],str) or not run['suite'].strip():
  raise ValueError('closed run suite required')
 rows=run['per_mixture']
 if not isinstance(rows,list) or not rows:
  raise ValueError('closed run rows required')
 names=set()
 for row in rows:
  if not isinstance(row,dict) or set(row)!={'mixture_name','weight','recall','fpr','transcript_sha256'}:
   raise ValueError('closed mixture schema mismatch')
  name=row['mixture_name']
  if not isinstance(name,str) or not name or name in names:
   raise ValueError('closed mixture names must be unique and non-empty')
  names.add(name)
  if not _finite(row['weight']) or row['weight']<=0:
   raise ValueError('closed mixture weight invalid')
  if any(not _finite(row[key]) or row[key]<0 or row[key]>1 for key in ('recall','fpr')):
   raise ValueError('closed mixture metrics invalid')
  digest=row['transcript_sha256']
  if not isinstance(digest,str) or len(digest)!=64 or any(char not in '0123456789abcdef' for char in digest):
   raise ValueError('closed mixture transcript hash invalid')
 identity={'suite':run['suite'],'per_mixture':rows}
 if run['run_hash']!=hashlib.sha256(_canonical(identity).encode()).hexdigest():
  raise ValueError('closed run hash mismatch')
 weight=sum(row['weight'] for row in rows)
 metrics={'weighted_recall':sum(row['weight']*row['recall'] for row in rows)/weight,'weighted_fpr':sum(row['weight']*row['fpr'] for row in rows)/weight}
 if not isinstance(run['headline'],dict) or set(run['headline'])!=set(metrics) or any(not _finite(run['headline'][key]) or not math.isclose(run['headline'][key],value,rel_tol=0,abs_tol=1e-12) for key,value in metrics.items()):
  raise ValueError('closed run headline mismatch')
 return rows,metrics

def main():
 p=argparse.ArgumentParser();p.add_argument('--canonical-predictions',required=True,type=Path);p.add_argument('--run-artifact',required=True,type=Path);p.add_argument('--frozen-audiobench-manifest',default=Path(__file__).resolve().parents[1]/'manifests'/'ember-restart-audiobench-custody-v1.json',type=Path);p.add_argument('--score-output',required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error('score output must not pre-exist')
 try:
  prediction_bytes=a.canonical_predictions.read_bytes();run_bytes=a.run_artifact.read_bytes();custody_bytes=a.frozen_audiobench_manifest.read_bytes();custody=_frozen_custody(custody_bytes);envelope=validate_predictions(json.loads(prediction_bytes.decode('utf-8')));run=json.loads(run_bytes.decode('utf-8'));rows,metrics=_closed_run(run)
 except (ContractError,OSError,json.JSONDecodeError,ValueError)as exc:p.error(f'closed AudioBench input invalid: {exc}')
 if envelope['benchmark']['capability']!='audio' or envelope['benchmark']['id']!='audiobench' or envelope['benchmark']['version']!=custody['benchmark_version'] or envelope['benchmark']['protocol_sha256']!=_protocol_sha256(custody) or run['suite']!=custody['suite']:p.error('canonical predictions and closed run must bind frozen AudioBench custody')
 by_id={row['mixture_name']:row for row in rows}
 if len(envelope['rows'])!=len(rows) or {row['id'] for row in envelope['rows']}!=set(by_id):p.error('canonical rows must exactly cover closed mixtures')
 for row in envelope['rows']:
  output=row['output'];runrow=by_id[row['id']]
  if output.get('kind')!='transcript' or hashlib.sha256(output['text'].encode()).hexdigest()!=runrow['transcript_sha256']:
   p.error('canonical transcript does not bind closed mixture evidence')
 payload={'result':'PREFLIGHT_ONLY','claim_status':'NON_ADMISSIBLE_CLOSED_AUDIOBENCH_SCORER','criterion_id':'ember-3b-audio-capability-v1','criterion_result':'FAILED','metrics':metrics,'sample_count':len(rows),'checkpoint_manifest_sha256':envelope['checkpoint_manifest_sha256'],'model_config_sha256':envelope['model_config_sha256'],'benchmark_id':custody['benchmark_id'],'benchmark_version':custody['benchmark_version'],'suite':custody['suite'],'protocol_sha256':_protocol_sha256(custody),'predictions_sha256':hashlib.sha256(prediction_bytes).hexdigest(),'run_artifact_sha256':hashlib.sha256(run_bytes).hexdigest(),'frozen_audiobench_manifest_sha256':hashlib.sha256(custody_bytes).hexdigest(),'upstream':'closed AudioBench rows bound to canonical predictions'}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.score_output.parent,delete=False)as handle:
  handle.write(_canonical(payload)+'\n');temporary=handle.name
 try:
  os.replace(temporary,a.score_output)
 finally:
  Path(temporary).unlink(missing_ok=True)
 return 0

if __name__=='__main__':raise SystemExit(main())
