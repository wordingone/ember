#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score a closed AudioBench run only against canonical audio predictions."""
import argparse,hashlib,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ember_restart.prediction_contract import ContractError,load_predictions
def main():
 p=argparse.ArgumentParser();p.add_argument('--canonical-predictions',required=True,type=Path);p.add_argument('--run-artifact',required=True,type=Path);p.add_argument('--score-output',required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error('score output must not pre-exist')
 try: envelope=load_predictions(a.canonical_predictions);run=json.loads(a.run_artifact.read_text())
 except (ContractError,OSError,json.JSONDecodeError)as e:p.error(f'canonical AudioBench input invalid: {e}')
 if envelope['benchmark']['capability']!='audio' or envelope['benchmark']['id']!='audiobench':p.error('canonical predictions must bind audio AudioBench')
 rows=run.get('per_mixture') if isinstance(run,dict) else None
 if not isinstance(rows,list) or not rows:p.error('closed run rows required')
 by_id={x.get('mixture_name'):x for x in rows if isinstance(x,dict)}
 if len(by_id)!=len(rows) or len(envelope['rows'])!=len(rows):p.error('canonical rows must exactly cover closed mixtures')
 for row in envelope['rows']:
  runrow=by_id.get(row['id']);output=row['output']
  if not runrow or output.get('kind')!='transcript' or hashlib.sha256(output['text'].encode()).hexdigest()!=runrow.get('transcript_sha256'):p.error('canonical transcript does not bind closed mixture evidence')
 try:
  weight=sum(x['weight'] for x in rows);metrics={'weighted_recall':sum(x['weight']*x['recall'] for x in rows)/weight,'weighted_fpr':sum(x['weight']*x['fpr'] for x in rows)/weight}
  if weight<=0 or any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) for x in metrics.values()):raise ValueError()
 except (KeyError,TypeError,ValueError):p.error('closed rows have invalid metrics')
 a.score_output.write_text(json.dumps({'criterion_id':'ember-3b-audio-capability-v1','criterion_result':'FAILED','metrics':metrics,'sample_count':len(rows),'upstream':'closed AudioBench rows bound to canonical predictions'},sort_keys=True)+'\n');return 0
if __name__=='__main__':main()
