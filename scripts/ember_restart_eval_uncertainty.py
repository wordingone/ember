#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,json,math,tempfile,os
from pathlib import Path
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--rows',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 if a.output.exists():p.error('output must not pre-exist')
 try:rows=json.loads(a.rows.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError)as e:p.error(f'rows must be valid JSON: {e}')
 if not isinstance(rows,list) or not rows or any(not isinstance(x,dict) or not isinstance(x.get('correct'),bool) for x in rows):p.error('rows must be a non-empty list of binary outcomes')
 n=len(rows);correct=sum(x['correct']for x in rows);acc=correct/n;z=1.959963984540054;den=1+z*z/n;center=(acc+z*z/(2*n))/den;half=z*math.sqrt(acc*(1-acc)/n+z*z/(4*n*n))/den
 payload={'result':'SELFTEST','admission':'NOT_ELIGIBLE','sample_count':n,'metrics':{'accuracy':acc},'uncertainty':{'method':'wilson_95','lower':max(0.,center-half),'upper':min(1.,center+half)}}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.output.parent,delete=False)as h:json.dump(payload,h,sort_keys=True);h.write('\n');t=Path(h.name)
 try:
  os.replace(t,a.output)
 finally:
  t.unlink(missing_ok=True)
 return 0
if __name__=='__main__':raise SystemExit(main())
