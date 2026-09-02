# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_uncertainty.py"
def test_aggregates_binary_rows_with_wilson_interval():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);rows=root/"rows.json";out=root/"out.json";rows.write_text(json.dumps([{"id":"a","correct":True},{"id":"b","correct":False},{"id":"c","correct":True},{"id":"d","correct":True}]))
  r=subprocess.run([sys.executable,str(SCRIPT),"--rows",str(rows),"--output",str(out)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr
  p=json.loads(out.read_text());assert p["result"]=="SELFTEST" and p["admission"]=="NOT_ELIGIBLE" and p["sample_count"]==4 and p["metrics"]["accuracy"]==0.75 and p["uncertainty"]["method"]=="wilson_95"
