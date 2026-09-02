# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_efficiency_windows.py"
def test_aggregates_raw_efficiency_windows_without_admission():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);windows=root/"windows.json";out=root/"out.json";windows.write_text(json.dumps([{"tokens":100,"seconds":2.0,"peak_memory_bytes":10},{"tokens":120,"seconds":2.0,"peak_memory_bytes":12}]))
  r=subprocess.run([sys.executable,str(SCRIPT),"--windows",str(windows),"--output",str(out)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr
  p=json.loads(out.read_text());assert p["result"]=="SELFTEST" and p["admission"]=="NOT_ELIGIBLE" and p["metrics"]["tokens_per_second"]==55.0 and p["metrics"]["peak_memory_bytes"]==12
