#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,json,os,re,tempfile
from pathlib import Path
HASH=re.compile(r'[0-9a-f]{64}')
def main():
 p=argparse.ArgumentParser();p.add_argument('--frozen-task-list',required=True,type=Path);p.add_argument('--browser-results',required=True,type=Path);p.add_argument('--score-output',required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error('score output must not pre-exist')
 try:
  tasks=json.loads(a.frozen_task_list.read_text());runs=json.loads(a.browser_results.read_text())
  if not isinstance(tasks,list) or not tasks or len(tasks)!=len(set(tasks)) or not isinstance(runs,list) or len(runs)!=len(tasks):raise ValueError()
  if [x.get('task_id') if isinstance(x,dict) else None for x in runs]!=tasks or any(not isinstance(x.get('success'),bool) or not all(isinstance(x.get(k),str) and HASH.fullmatch(x[k]) for k in ('trace_sha256','environment_sha256')) for x in runs):raise ValueError()
 except Exception:p.error('results must exactly cover frozen tasks with boolean success and content-addressed trace/environment hashes')
 payload={'metrics':{'task_success_rate':sum(x['success'] for x in runs)/len(tasks)},'sample_count':len(tasks),'criterion_id':'ember-3b-tool-capability-v1','criterion_result':'FAILED','upstream':'pinned local BrowserGym MiniWoB task outcomes'}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.score_output.parent,delete=False)as h:json.dump(payload,h,sort_keys=True);name=h.name
 os.replace(name,a.score_output)
if __name__=='__main__':main()
