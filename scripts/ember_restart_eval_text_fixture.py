#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run frozen text exact-match rows through a local prediction file."""
import argparse, json
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--predictions',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 rows=json.loads(a.fixture.read_text()); pred=json.loads(a.predictions.read_text()); out=[]
 for row in rows:
  if not isinstance(row,dict) or 'id' not in row or 'answer' not in row: p.error('invalid frozen text row')
  out.append({'id':row['id'],'correct':pred.get(row['id'])==row['answer']})
 a.output.write_text(json.dumps({'benchmark_id':'frozen-text-fixture-v1','rows':out,'correct':sum(x['correct'] for x in out),'total':len(out)},sort_keys=True)+'\n');return 0
if __name__=='__main__':raise SystemExit(main())
