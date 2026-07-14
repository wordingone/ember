# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCORER=ROOT/"scripts"/"ember_restart_eval_audiobench.py"
PREFLIGHT=ROOT/"scripts"/"ember_restart_eval_execution_preflight.py"

def test_exports_audiobench_per_mixture_records_as_central_raw_predictions():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);run=root/"run.json";raw=root/"raw.json";score=root/"score.json";checkpoint=root/"checkpoint";split=root/"split";harness=root/"harness";protocol=root/"protocol";out=root/"out.json"
  run.write_text(json.dumps({"suite":"ab/sound-id","run_hash":"a"*64,"headline":{"weighted_recall":0.75,"weighted_fpr":0.1},"per_mixture":[{"mixture_name":"x"}]}),encoding="utf-8")
  for item in(checkpoint,split,harness,protocol):item.write_text(item.name,encoding="utf-8")
  s=subprocess.run([sys.executable,str(SCORER),"--run-artifact",str(run),"--raw-predictions",str(raw),"--score-output",str(score)],text=True,capture_output=True,check=False);assert s.returncode==0,s.stderr
  p=subprocess.run([sys.executable,str(PREFLIGHT),"--capability","audio","--checkpoint-manifest",str(checkpoint),"--benchmark-id","audiobench","--benchmark-version","0fc7fef","--split-artifact",str(split),"--harness-artifact",str(harness),"--protocol-artifact",str(protocol),"--raw-predictions",str(raw),"--result-artifact",str(score),"--output",str(out)],text=True,capture_output=True,check=False);assert p.returncode==0,p.stderr
