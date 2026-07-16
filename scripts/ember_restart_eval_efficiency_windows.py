#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Aggregate raw efficiency windows into non-admissible local metrics."""
import argparse,json,math
from pathlib import Path
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--windows",required=True,type=Path);p.add_argument("--output",required=True,type=Path);a=p.parse_args();
 if a.output.exists():p.error("output must not pre-exist")
 windows=json.loads(a.windows.read_text(encoding="utf-8"))
 if not isinstance(windows,list) or not windows:p.error("windows must be non-empty")
 rates=[];peaks=[]
 for window in windows:
  if not isinstance(window,dict) or isinstance(window.get("tokens"),bool) or not isinstance(window.get("tokens"),int) or window["tokens"]<=0 or not isinstance(window.get("seconds"),(int,float)) or isinstance(window["seconds"],bool) or not math.isfinite(window["seconds"]) or window["seconds"]<=0 or not isinstance(window.get("peak_memory_bytes"),int) or window["peak_memory_bytes"]<0:p.error("invalid efficiency window")
  rates.append(window["tokens"]/window["seconds"]);peaks.append(window["peak_memory_bytes"])
 mean=sum(rates)/len(rates);variance=sum((rate-mean)**2 for rate in rates)/len(rates)
 payload={"result":"SELFTEST","admission":"NOT_ELIGIBLE","window_count":len(windows),"metrics":{"tokens_per_second":mean,"peak_memory_bytes":max(peaks)},"uncertainty":{"method":"population_sd","tokens_per_second_sd":math.sqrt(variance)}}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,sort_keys=True)+"\n",encoding="utf-8");return 0
if __name__=="__main__":raise SystemExit(main())
