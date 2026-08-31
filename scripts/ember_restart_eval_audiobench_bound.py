#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score a closed AudioBench run only against canonical audio predictions."""
import argparse,hashlib,json,math,os,sys,tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
# issue2015 exact-local-import:src/ember/governance/scripts/ember_restart/prediction_contract.py
import importlib.util as _ember_5fe35e3f50d06cc1_importlib
import sys as _ember_5fe35e3f50d06cc1_sys
from pathlib import Path as _ember_5fe35e3f50d06cc1_Path
_ember_5fe35e3f50d06cc1_path = _ember_5fe35e3f50d06cc1_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_restart', 'prediction_contract.py')
if not _ember_5fe35e3f50d06cc1_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_restart/prediction_contract.py')
_ember_5fe35e3f50d06cc1_aliases = ('_ember_issue2015_5fe35e3f50d06cc1', 'ember_restart.prediction_contract', 'prediction_contract', 'scripts.ember_restart.prediction_contract')
_ember_5fe35e3f50d06cc1_existing = []
for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
    _ember_5fe35e3f50d06cc1_candidate = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
    if _ember_5fe35e3f50d06cc1_candidate is not None and all(_ember_5fe35e3f50d06cc1_candidate is not item for item in _ember_5fe35e3f50d06cc1_existing):
        _ember_5fe35e3f50d06cc1_existing.append(_ember_5fe35e3f50d06cc1_candidate)
if len(_ember_5fe35e3f50d06cc1_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
if _ember_5fe35e3f50d06cc1_existing:
    _ember_5fe35e3f50d06cc1_module = _ember_5fe35e3f50d06cc1_existing[0]
    _ember_5fe35e3f50d06cc1_observed = getattr(_ember_5fe35e3f50d06cc1_module, '__file__', None)
    if _ember_5fe35e3f50d06cc1_observed is None or _ember_5fe35e3f50d06cc1_Path(_ember_5fe35e3f50d06cc1_observed).resolve() != _ember_5fe35e3f50d06cc1_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_restart/prediction_contract.py')
else:
    _ember_5fe35e3f50d06cc1_spec = _ember_5fe35e3f50d06cc1_importlib.spec_from_file_location('_ember_issue2015_5fe35e3f50d06cc1', _ember_5fe35e3f50d06cc1_path)
    if _ember_5fe35e3f50d06cc1_spec is None or _ember_5fe35e3f50d06cc1_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_restart/prediction_contract.py')
    _ember_5fe35e3f50d06cc1_module = _ember_5fe35e3f50d06cc1_importlib.module_from_spec(_ember_5fe35e3f50d06cc1_spec)
    for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
        _ember_5fe35e3f50d06cc1_prior = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
        if _ember_5fe35e3f50d06cc1_prior is not None and _ember_5fe35e3f50d06cc1_prior is not _ember_5fe35e3f50d06cc1_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
        _ember_5fe35e3f50d06cc1_sys.modules[_ember_5fe35e3f50d06cc1_alias] = _ember_5fe35e3f50d06cc1_module
    try:
        _ember_5fe35e3f50d06cc1_spec.loader.exec_module(_ember_5fe35e3f50d06cc1_module)
    except BaseException:
        for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
            if _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias) is _ember_5fe35e3f50d06cc1_module:
                _ember_5fe35e3f50d06cc1_sys.modules.pop(_ember_5fe35e3f50d06cc1_alias, None)
        raise
for _ember_5fe35e3f50d06cc1_alias in _ember_5fe35e3f50d06cc1_aliases:
    _ember_5fe35e3f50d06cc1_prior = _ember_5fe35e3f50d06cc1_sys.modules.get(_ember_5fe35e3f50d06cc1_alias)
    if _ember_5fe35e3f50d06cc1_prior is not None and _ember_5fe35e3f50d06cc1_prior is not _ember_5fe35e3f50d06cc1_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/prediction_contract.py')
    _ember_5fe35e3f50d06cc1_sys.modules[_ember_5fe35e3f50d06cc1_alias] = _ember_5fe35e3f50d06cc1_module
ContractError = getattr(_ember_5fe35e3f50d06cc1_module, 'ContractError')
load_predictions = getattr(_ember_5fe35e3f50d06cc1_module, 'load_predictions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/prediction_contract.py

def _canonical(value):
 return json.dumps(value,sort_keys=True,separators=(',',':'))

def _finite(value):
 return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

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
 p=argparse.ArgumentParser();p.add_argument('--canonical-predictions',required=True,type=Path);p.add_argument('--run-artifact',required=True,type=Path);p.add_argument('--score-output',required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error('score output must not pre-exist')
 try:
  envelope=load_predictions(a.canonical_predictions);run=json.loads(a.run_artifact.read_text());rows,metrics=_closed_run(run)
 except (ContractError,OSError,json.JSONDecodeError,ValueError)as exc:p.error(f'closed AudioBench input invalid: {exc}')
 if envelope['benchmark']['capability']!='audio' or envelope['benchmark']['id']!='audiobench':p.error('canonical predictions must bind audio AudioBench')
 by_id={row['mixture_name']:row for row in rows}
 if len(envelope['rows'])!=len(rows) or {row['id'] for row in envelope['rows']}!=set(by_id):p.error('canonical rows must exactly cover closed mixtures')
 for row in envelope['rows']:
  output=row['output'];runrow=by_id[row['id']]
  if output.get('kind')!='transcript' or hashlib.sha256(output['text'].encode()).hexdigest()!=runrow['transcript_sha256']:
   p.error('canonical transcript does not bind closed mixture evidence')
 payload={'criterion_id':'ember-3b-audio-capability-v1','criterion_result':'FAILED','metrics':metrics,'sample_count':len(rows),'predictions_sha256':hashlib.sha256(a.canonical_predictions.read_bytes()).hexdigest(),'run_artifact_sha256':hashlib.sha256(a.run_artifact.read_bytes()).hexdigest(),'upstream':'closed AudioBench rows bound to canonical predictions'}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.score_output.parent,delete=False)as handle:
  handle.write(_canonical(payload)+'\n');temporary=handle.name
 os.replace(temporary,a.score_output)
 return 0

if __name__=='__main__':raise SystemExit(main())
