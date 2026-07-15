#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,hashlib,json,math,os,tempfile,sys
from pathlib import Path
from ember_restart.prediction_contract import ContractError,load_predictions
CAPABILITIES=("text","image","audio","reasoning","tool")
def sha256(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--capability',required=True,choices=CAPABILITIES);p.add_argument('--checkpoint-manifest',required=True,type=Path);p.add_argument('--benchmark-id',required=True);p.add_argument('--benchmark-version',required=True);p.add_argument('--split-artifact',required=True,type=Path);p.add_argument('--harness-artifact',required=True,type=Path);p.add_argument('--protocol-artifact',required=True,type=Path);p.add_argument('--raw-predictions',required=True,type=Path);p.add_argument('--closed-run-artifact',type=Path);p.add_argument('--result-artifact',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 if not a.benchmark_id.strip() or not a.benchmark_version.strip():p.error('benchmark id and version must be non-empty')
 if a.output.exists():p.error('refusing to overwrite existing output')
 try:envelope=load_predictions(a.raw_predictions)
 except ContractError as e:p.error(f'canonical prediction envelope required: {e}')
 benchmark=envelope['benchmark'];checkpoint=sha256(a.checkpoint_manifest);split=sha256(a.split_artifact);protocol=sha256(a.protocol_artifact)
 if envelope['checkpoint_manifest_sha256']!=checkpoint or benchmark['capability']!=a.capability or benchmark['id']!=a.benchmark_id or benchmark['version']!=a.benchmark_version or benchmark['split_sha256']!=split or benchmark['protocol_sha256']!=protocol:p.error('canonical prediction envelope does not bind supplied evaluation inputs')
 try:score=json.loads(a.result_artifact.read_text())
 except (OSError,json.JSONDecodeError):p.error('invalid evaluator score JSON')
 expected=f'ember-3b-{a.capability}-capability-v1';rows=envelope['rows']
 if not isinstance(score,dict) or score.get('criterion_id')!=expected or score.get('criterion_result') not in ('PASSED','FAILED'):p.error('evaluator score artifact must explicitly provide the pinned criterion')
 if a.capability=='text' and score.get('predictions_sha256')!=sha256(a.raw_predictions):p.error('text score source hashes do not bind supplied evidence')
 if a.benchmark_id=='audiobench':
  if a.closed_run_artifact is None:p.error('AudioBench preflight requires closed run artifact')
  if score.get('predictions_sha256')!=sha256(a.raw_predictions) or score.get('run_artifact_sha256')!=sha256(a.closed_run_artifact):p.error('AudioBench score source hashes do not bind supplied evidence')
 count=score.get('sample_count')
 if not isinstance(count,int) or isinstance(count,bool) or count!=len(rows):p.error('evaluator sample_count must be an exact integer match for canonical rows')
 metrics=score.get('metrics')
 if not isinstance(metrics,dict) or not metrics or any(isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)for v in metrics.values()):p.error('score artifact must contain non-empty finite numeric metrics')
 payload={'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':a.capability,'subject_checkpoint_sha256':checkpoint,'benchmark_id':a.benchmark_id,'benchmark_version':a.benchmark_version,'split_sha256':split,'harness_sha256':sha256(a.harness_artifact),'protocol_sha256':protocol,'predictions_sha256':sha256(a.raw_predictions),'score_artifact_sha256':sha256(a.result_artifact),'sample_count':count,'metrics':metrics,'criterion_id':expected,'criterion_result':score['criterion_result']}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.output.parent,delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+'\n');tmp=h.name
 os.replace(tmp,a.output)
if __name__=='__main__':main()
