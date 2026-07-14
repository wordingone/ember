#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive a non-admissible audio score from a completed pinned AudioBench run."""
import argparse,json,math,os,re,tempfile
from pathlib import Path
def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--run-artifact",required=True,type=Path);p.add_argument("--score-output",required=True,type=Path);a=p.parse_args()
 if a.score_output.exists():p.error("score output must not pre-exist")
 try:run=json.loads(a.run_artifact.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError)as exc:p.error(f"invalid AudioBench run artifact: {exc}")
 headline=run.get("headline") if isinstance(run,dict) else None;mixtures=run.get("per_mixture") if isinstance(run,dict) else None
 if run.get("suite")!="ab/sound-id" or not isinstance(run.get("run_hash"),str) or not re.fullmatch(r"[0-9a-f]{64}",run["run_hash"]) or not isinstance(headline,dict) or not isinstance(mixtures,list) or not mixtures or not number(headline.get("weighted_recall")) or not number(headline.get("weighted_fpr")):p.error("AudioBench run artifact lacks completed sound-id evidence")
 payload={"criterion_id":"ember-3b-audio-capability-v1","criterion_result":"FAILED","metrics":{"weighted_fpr":float(headline["weighted_fpr"]),"weighted_recall":float(headline["weighted_recall"])},"sample_count":len(mixtures),"upstream":"pinned local AudioBench run artifact"}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.score_output.parent,prefix=a.score_output.name+".",suffix=".tmp",delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+"\n");temp=Path(h.name)
 os.replace(temp,a.score_output);return 0
if __name__=="__main__":raise SystemExit(main())
