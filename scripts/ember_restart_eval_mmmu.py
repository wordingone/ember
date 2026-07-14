#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run cached MMMU's local exact scorer; never emits a central receipt."""
import argparse, ast, json, subprocess, sys, tempfile, os
from pathlib import Path

def upstream_predictions(path: Path) -> dict[str,object]:
 value=json.loads(path.read_text(encoding="utf-8"))
 if isinstance(value,dict): return value
 if not isinstance(value,list) or not value: raise ValueError("MMMU predictions must be a non-empty JSON list")
 converted={}
 for row in value:
  if not isinstance(row,dict) or not isinstance(row.get("id"),str) or not row["id"] or "prediction" not in row or row["id"] in converted: raise ValueError("MMMU prediction rows require unique id and prediction")
  converted[row["id"]]=row["prediction"]
 return converted

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--mmmu-root",required=True,type=Path);p.add_argument("--answers",required=True,type=Path);p.add_argument("--predictions",required=True,type=Path);p.add_argument("--score-output",required=True,type=Path);p.add_argument("--timeout-seconds",type=int,default=120);a=p.parse_args()
 if a.score_output.exists():p.error("score output must not pre-exist")
 if not 1<=a.timeout_seconds<=120:p.error("timeout seconds must be between 1 and 120")
 try: answers=json.loads(a.answers.read_text(encoding="utf-8"));converted=upstream_predictions(a.predictions)
 except (OSError,ValueError,json.JSONDecodeError) as exc:p.error(f"invalid MMMU evaluator inputs: {exc}")
 if not isinstance(answers,dict) or not answers or any(not isinstance(v,dict) or v.get("question_type")!="multiple-choice" for v in answers.values()):p.error("MMMU adapter permits multiple-choice answers only")
 if answers.keys()!=converted.keys():p.error("MMMU predictions must exactly cover frozen answer ids")
 scorer=a.mmmu_root/"mmmu"/"main_eval_only.py"
 if not scorer.is_file():p.error("cached MMMU main_eval_only.py is required")
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.predictions.parent,prefix=a.predictions.name+".",suffix=".mmmu.tmp",delete=False)as h:json.dump(converted,h,sort_keys=True);temporary=Path(h.name)
 try: run=subprocess.run([sys.executable,str(scorer),"--output_path",str(temporary),"--answer_path",str(a.answers)],cwd=scorer.parent,text=True,capture_output=True,timeout=a.timeout_seconds,check=False)
 except subprocess.TimeoutExpired:temporary.unlink(missing_ok=True);p.error("MMMU scorer timed out")
 finally: temporary.unlink(missing_ok=True)
 if run.returncode!=0:p.error(f"MMMU scorer failed: {run.stderr.strip()}")
 try: aggregate=ast.literal_eval(run.stdout.strip().splitlines()[-1]);overall=aggregate["Overall"];num=int(overall["num"]);accuracy=float(overall["acc"])
 except (ValueError,SyntaxError,KeyError,IndexError,TypeError):p.error("MMMU scorer returned an invalid aggregate")
 if num<=0 or num!=len(converted):p.error("MMMU scorer did not cover the frozen prediction set")
 payload={"metrics":{"accuracy":accuracy},"sample_count":num,"criterion_id":"ember-3b-image-capability-v1","criterion_result":"FAILED","upstream":"MMMU exact multiple-choice local scorer"}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.score_output.parent,prefix=a.score_output.name+".",suffix=".tmp",delete=False) as h:h.write(json.dumps(payload,sort_keys=True)+"\n");temp=Path(h.name)
 os.replace(temp,a.score_output);return 0
if __name__=="__main__":raise SystemExit(main())
