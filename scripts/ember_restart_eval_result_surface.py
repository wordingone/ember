#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,json,os,tempfile
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 try:r=json.loads(a.input.read_text())
 except Exception:p.error('input must be JSON')
 if not isinstance(r,dict):p.error('input must be an object')
 measured=r.get('result')=='MEASURED' and r.get('admission')=='ADMITTED' and r.get('checkpoint_status')!='NON_CLAIM_BOOTSTRAP'
 label='MEASURED CAPABILITY' if measured else 'NOT CLAIM-BEARING'
 text=f'# Ember evaluation result\n\nStatus: {label}\n\nCapability: {r.get("capability","unknown")}\n'
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.output.parent,delete=False)as h:h.write(text);name=h.name
 os.replace(name,a.output)
if __name__=='__main__':main()
