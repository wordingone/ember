#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run a bounded evaluator command, then emit only non-admissible evidence."""
import argparse, subprocess, sys
from pathlib import Path
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--capability",required=True,choices=("text","image","audio","reasoning","tool"));p.add_argument("--checkpoint-manifest",required=True,type=Path);p.add_argument("--benchmark-id",required=True);p.add_argument("--benchmark-version",required=True);p.add_argument("--split-artifact",required=True,type=Path);p.add_argument("--harness-artifact",required=True,type=Path);p.add_argument("--protocol-artifact",required=True,type=Path);p.add_argument("--raw-predictions",required=True,type=Path);p.add_argument("--result-artifact",required=True,type=Path);p.add_argument("--timeout-seconds",type=int,default=120);p.add_argument("--output",required=True,type=Path);p.add_argument("command",nargs=argparse.REMAINDER);a=p.parse_args();command=a.command[1:] if a.command[:1]==["--"] else a.command
 if not command:p.error("evaluator command is required after --")
 if not 1<=a.timeout_seconds<=120:p.error("timeout seconds must be between 1 and 120")
 if a.raw_predictions.exists() or a.result_artifact.exists() or a.output.exists():p.error("evaluator outputs and preflight output must not pre-exist")
 try: completed=subprocess.run(command,text=True,capture_output=True,timeout=a.timeout_seconds,check=False)
 except subprocess.TimeoutExpired:p.error("evaluator command timed out")
 if completed.returncode!=0:p.error(f"evaluator command failed with exit code {completed.returncode}: {completed.stderr.strip()}")
 if not a.raw_predictions.is_file() or not a.result_artifact.is_file():p.error("evaluator command did not create predictions and score artifacts")
 preflight=Path(__file__).with_name("ember_restart_eval_execution_preflight.py")
 command=[sys.executable,str(preflight),"--capability",a.capability,"--checkpoint-manifest",str(a.checkpoint_manifest),"--benchmark-id",a.benchmark_id,"--benchmark-version",a.benchmark_version,"--split-artifact",str(a.split_artifact),"--harness-artifact",str(a.harness_artifact),"--protocol-artifact",str(a.protocol_artifact),"--raw-predictions",str(a.raw_predictions),"--result-artifact",str(a.result_artifact),"--output",str(a.output)]
 return subprocess.run(command,check=False).returncode
if __name__=="__main__":raise SystemExit(main())
