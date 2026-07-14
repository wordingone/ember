#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive a non-admissible audio score from a completed pinned AudioBench run."""
import argparse,json,math,os,re,tempfile
from pathlib import Path
def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def atomic(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+'\n');temp=Path(h.name)
 os.replace(temp,path)
def criterion(protocol_path,metrics):
 if protocol_path is None:return 'FAILED'
 try:protocol=json.loads(protocol_path.read_text())
 except (OSError,json.JSONDecodeError)as exc:raise ValueError(f'invalid criterion protocol: {exc}')
 thresholds=protocol.get('thresholds') if isinstance(protocol,dict) else None
 if protocol.get('criterion_id')!='ember-3b-audio-capability-v1' or not isinstance(thresholds,dict) or not thresholds:raise ValueError('criterion protocol must pin audio criterion and thresholds')
 for name,rule in thresholds.items():
  if name not in metrics or not isinstance(rule,dict) or rule.get('operator') not in ('>=','<=') or not number(rule.get('value')):raise ValueError('criterion protocol has invalid metric threshold')
  if rule['operator']=='>=' and metrics[name]<rule['value']:return 'FAILED'
  if rule['operator']=='<=' and metrics[name]>rule['value']:return 'FAILED'
 return 'PASSED'
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-artifact',required=True,type=Path);p.add_argument('--criterion-protocol',type=Path);p.add_argument('--raw-predictions',required=True,type=Path);p.add_argument('--score-output',required=True,type=Path);a=p.parse_args()
 if a.score_output.exists() or a.raw_predictions.exists():p.error('raw predictions and score output must not pre-exist')
 try:run=json.loads(a.run_artifact.read_text())
 except (OSError,json.JSONDecodeError)as exc:p.error(f'invalid AudioBench run artifact: {exc}')
 headline=run.get('headline') if isinstance(run,dict) else None;mixtures=run.get('per_mixture') if isinstance(run,dict) else None
 names=[x.get('mixture_name') if isinstance(x,dict) else None for x in mixtures] if isinstance(mixtures,list) else []
 if run.get('suite')!='ab/sound-id' or not isinstance(run.get('run_hash'),str) or not re.fullmatch(r'[0-9a-f]{64}',run['run_hash']) or not isinstance(headline,dict) or not isinstance(mixtures,list) or not mixtures or any(not isinstance(x,str) or not x.strip() for x in names) or len(set(names))!=len(names) or not number(headline.get('weighted_recall')) or not number(headline.get('weighted_fpr')):p.error('AudioBench run artifact lacks completed named sound-id evidence')
 metrics={'weighted_fpr':float(headline['weighted_fpr']),'weighted_recall':float(headline['weighted_recall'])}
 try:result=criterion(a.criterion_protocol,metrics)
 except ValueError as exc:p.error(str(exc))
 atomic(a.raw_predictions,mixtures);atomic(a.score_output,{'criterion_id':'ember-3b-audio-capability-v1','criterion_result':result,'metrics':metrics,'sample_count':len(mixtures),'upstream':'pinned local AudioBench run artifact'});return 0
if __name__=='__main__':main()
