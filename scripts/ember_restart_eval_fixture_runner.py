#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic exact-match local scorer for frozen evaluator fixtures."""
import argparse, json
from pathlib import Path

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--fixture',required=True,type=Path); p.add_argument('--output',required=True,type=Path); a=p.parse_args()
    rows=json.loads(a.fixture.read_text(encoding='utf-8'))
    if not isinstance(rows,list) or not rows: p.error('fixture must be non-empty list')
    scored=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('capability') not in ('text','image','audio','reasoning','tool') or 'expected' not in row or 'actual' not in row: p.error('invalid frozen fixture row')
        scored.append({'id':row.get('id'),'capability':row['capability'],'correct':row['actual']==row['expected']})
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({'rows':scored,'correct':sum(x['correct'] for x in scored),'total':len(scored)},sort_keys=True)+'\n',encoding='utf-8'); return 0
if __name__=='__main__': raise SystemExit(main())
