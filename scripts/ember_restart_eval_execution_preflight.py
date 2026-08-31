#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,hashlib,json,math,os,tempfile,sys
from pathlib import Path
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
validate_predictions = getattr(_ember_5fe35e3f50d06cc1_module, 'validate_predictions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/prediction_contract.py
CAPABILITIES=("text","image","audio","reasoning","tool")
def sha256(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--capability',required=True,choices=CAPABILITIES);p.add_argument('--checkpoint-manifest',required=True,type=Path);p.add_argument('--benchmark-id',required=True);p.add_argument('--benchmark-version',required=True);p.add_argument('--split-artifact',required=True,type=Path);p.add_argument('--harness-artifact',required=True,type=Path);p.add_argument('--protocol-artifact',required=True,type=Path);p.add_argument('--raw-predictions',required=True,type=Path);p.add_argument('--closed-run-artifact',type=Path);p.add_argument('--result-artifact',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 if not a.benchmark_id.strip() or not a.benchmark_version.strip():p.error('benchmark id and version must be non-empty')
 if a.output.exists():p.error('refusing to overwrite existing output')
 try:
  prediction_bytes=a.raw_predictions.read_bytes();predictions_sha256=hashlib.sha256(prediction_bytes).hexdigest();envelope=validate_predictions(json.loads(prediction_bytes.decode('utf-8')))
 except (ContractError,OSError,UnicodeError,json.JSONDecodeError) as e:p.error(f'canonical prediction envelope required: {e}')
 try:
  score_bytes=a.result_artifact.read_bytes();score_artifact_sha256=hashlib.sha256(score_bytes).hexdigest();score=json.loads(score_bytes.decode('utf-8'))
 except (OSError,UnicodeError,json.JSONDecodeError):p.error('invalid evaluator score JSON')
 benchmark=envelope['benchmark'];checkpoint=sha256(a.checkpoint_manifest);split=sha256(a.split_artifact);protocol=sha256(a.protocol_artifact)
 if envelope['checkpoint_manifest_sha256']!=checkpoint or benchmark['capability']!=a.capability or benchmark['id']!=a.benchmark_id or benchmark['version']!=a.benchmark_version or benchmark['split_sha256']!=split or benchmark['protocol_sha256']!=protocol:p.error('canonical prediction envelope does not bind supplied evaluation inputs')
 expected=f'ember-3b-{a.capability}-capability-v1';rows=envelope['rows']
 if not isinstance(score,dict) or score.get('criterion_id')!=expected or score.get('criterion_result') not in ('PASSED','FAILED'):p.error('evaluator score artifact must explicitly provide the pinned criterion')
 if a.capability=='text' and score.get('predictions_sha256')!=predictions_sha256:p.error('text score source hashes do not bind supplied evidence')
 if a.benchmark_id=='audiobench':
  if a.closed_run_artifact is None:p.error('AudioBench preflight requires closed run artifact')
  if score.get('predictions_sha256')!=predictions_sha256 or score.get('run_artifact_sha256')!=sha256(a.closed_run_artifact):p.error('AudioBench score source hashes do not bind supplied evidence')
 count=score.get('sample_count')
 if not isinstance(count,int) or isinstance(count,bool) or count!=len(rows):p.error('evaluator sample_count must be an exact integer match for canonical rows')
 metrics=score.get('metrics')
 if not isinstance(metrics,dict) or not metrics or any(isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)for v in metrics.values()):p.error('score artifact must contain non-empty finite numeric metrics')
 payload={'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':a.capability,'subject_checkpoint_sha256':checkpoint,'benchmark_id':a.benchmark_id,'benchmark_version':a.benchmark_version,'split_sha256':split,'harness_sha256':sha256(a.harness_artifact),'protocol_sha256':protocol,'predictions_sha256':predictions_sha256,'score_artifact_sha256':score_artifact_sha256,'sample_count':count,'metrics':metrics,'criterion_id':expected,'criterion_result':score['criterion_result']}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.output.parent,delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+'\n');tmp=h.name
 os.replace(tmp,a.output)
if __name__=='__main__':main()