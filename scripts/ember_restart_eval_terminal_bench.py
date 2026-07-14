#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shape frozen Harbor task outcomes for non-admissible evaluator preflight."""
import argparse,json,os,re,tempfile
from pathlib import Path

HASH=re.compile(r"[0-9a-f]{64}")
def atomic(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,prefix=path.name+".",suffix=".tmp",delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+"\n");tmp=Path(h.name)
 os.replace(tmp,path)
def load(path,label):
 try:return json.loads(path.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError)as exc:raise ValueError(f"invalid {label}: {exc}")
def main():
 p=argparse.ArgumentParser();p.add_argument("--frozen-task-list",required=True,type=Path);p.add_argument("--harbor-task-results",required=True,type=Path);p.add_argument("--score-output",required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error("score output must not pre-exist")
 try:
  tasks=load(a.frozen_task_list,"frozen task list");results=load(a.harbor_task_results,"Harbor task results")
  if not isinstance(tasks,list) or not tasks or any(not isinstance(x,str) or not x for x in tasks) or len(set(tasks))!=len(tasks):raise ValueError("frozen task list must be a non-empty unique string list")
  if not isinstance(results,list) or len(results)!=len(tasks):raise ValueError("Harbor results must exactly cover frozen task count")
  observed=[];passed=0
  for item in results:
   if not isinstance(item,dict) or not isinstance(item.get("task_id"),str) or item.get("status") not in ("passed","failed") or not isinstance(item.get("transcript_sha256"),str) or not HASH.fullmatch(item["transcript_sha256"]) or not isinstance(item.get("task_image_sha256"),str) or not HASH.fullmatch(item["task_image_sha256"]):raise ValueError("each Harbor result requires task id, pass/fail, transcript hash, and image hash")
   observed.append(item["task_id"]);passed+=item["status"]=="passed"
  if observed!=tasks:raise ValueError("Harbor results must preserve the exact frozen task order")
 except ValueError as exc:p.error(str(exc))
 atomic(a.score_output,{"metrics":{"task_success_rate":passed/len(tasks)},"sample_count":len(tasks),"criterion_id":"ember-3b-tool-capability-v1","criterion_result":"FAILED","upstream":"pinned local Harbor task-outcome records"});return 0
if __name__=="__main__":raise SystemExit(main())
