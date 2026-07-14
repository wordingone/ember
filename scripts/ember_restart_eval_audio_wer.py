#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score checkpoint transcript predictions against a frozen local reference split."""
import argparse, json, os, tempfile
from pathlib import Path

def read_rows(path: Path) -> dict[str,str]:
 raw=path.read_text(encoding="utf-8")
 try:
  parsed=json.loads(raw);values=parsed if isinstance(parsed,list) else [parsed]
 except json.JSONDecodeError:
  values=[json.loads(line) for line in raw.splitlines() if line.strip()]
 rows={}
 for value in values:
  if not isinstance(value,dict) or not isinstance(value.get("id"),str) or not value["id"] or not isinstance(value.get("transcript"),str) or value["id"] in rows: raise ValueError("each row needs a unique non-empty id and transcript")
  rows[value["id"]]=value["transcript"]
 if not rows: raise ValueError("rows must be non-empty")
 return rows

def distance(reference: list[str], prediction: list[str]) -> int:
 prior=list(range(len(prediction)+1))
 for left,word in enumerate(reference,1):
  current=[left]
  for right,guess in enumerate(prediction,1): current.append(min(prior[right]+1,current[right-1]+1,prior[right-1]+(word!=guess)))
  prior=current
 return prior[-1]

def main() -> int:
 p=argparse.ArgumentParser();p.add_argument("--references",required=True,type=Path);p.add_argument("--predictions",required=True,type=Path);p.add_argument("--score-output",required=True,type=Path);a=p.parse_args()
 if a.score_output.exists(): p.error("score output must not pre-exist")
 try: references=read_rows(a.references);predictions=read_rows(a.predictions)
 except (OSError,ValueError,json.JSONDecodeError) as exc: p.error(f"invalid local transcript artifacts: {exc}")
 if references.keys()!=predictions.keys(): p.error("predictions must exactly cover the frozen reference ids")
 words=sum(len(text.split()) for text in references.values())
 if words<=0: p.error("frozen references must contain at least one word")
 errors=sum(distance(references[key].split(),predictions[key].split()) for key in references)
 payload={"criterion_id":"ember-3b-audio-capability-v1","criterion_result":"FAILED","metrics":{"word_error_rate":errors/words},"sample_count":len(references),"upstream":"deterministic local word-error-rate scorer"}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.score_output.parent,prefix=a.score_output.name+".",suffix=".tmp",delete=False) as handle:
  handle.write(json.dumps(payload,sort_keys=True)+"\n");temporary=Path(handle.name)
 os.replace(temporary,a.score_output);return 0

if __name__=="__main__": raise SystemExit(main())
