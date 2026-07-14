#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run cached MMMU's local exact scorer; never emits a central receipt."""
import argparse, ast, json, subprocess, sys, tempfile, os
from pathlib import Path

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--mmmu-root",required=True,type=Path);p.add_argument("--answers",required=True,type=Path);p.add_argument("--predictions",required=True,type=Path);p.add_argument("--score-output",required=True,type=Path);p.add_argument("--timeout-seconds",type=int,default=120);a=p.parse_args()
 if a.score_output.exists():p.error("score output must not pre-exist")
 if not 1<=a.timeout_seconds<=120:p.error("timeout seconds must be between 1 and 120")
 answers=json.loads(a.answers.read_text(encoding="utf-8"))
 if not isinstance(answers,dict) or not answers or any(not isinstance(v,dict) or v.get("question_type")!="multiple-choice" for v in answers.values()):p.error("MMMU adapter permits multiple-choice answers only")
 scorer=a.mmmu_root/"mmmu"/"main_eval_only.py"
 if not scorer.is_file():p.error("cached MMMU main_eval_only.py is required")
 try: run=subprocess.run([sys.executable,str(scorer),"--output_path",str(a.predictions),"--answer_path",str(a.answers)],cwd=scorer.parent,text=True,capture_output=True,timeout=a.timeout_seconds,check=False)
 except subprocess.TimeoutExpired:p.error("MMMU scorer timed out")
 if run.returncode!=0:p.error(f"MMMU scorer failed: {run.stderr.strip()}")
 try: aggregate=ast.literal_eval(run.stdout.strip().splitlines()[-1]);overall=aggregate["Overall"];num=int(overall["num"]);accuracy=float(overall["acc"])
 except (ValueError,SyntaxError,KeyError,IndexError,TypeError):p.error("MMMU scorer returned an invalid aggregate")
 if num<=0:p.error("MMMU scorer evaluated zero items")
 payload={"metrics":{"accuracy":accuracy},"sample_count":num,"criterion_id":"ember-3b-image-capability-v1","criterion_result":"FAILED","upstream":"MMMU exact multiple-choice local scorer"}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.score_output.parent,prefix=a.score_output.name+".",suffix=".tmp",delete=False) as h:h.write(json.dumps(payload,sort_keys=True)+"\n");temp=Path(h.name)
 os.replace(temp,a.score_output);return 0
if __name__=="__main__":raise SystemExit(main())
