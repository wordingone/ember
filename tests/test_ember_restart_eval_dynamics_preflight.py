# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_dynamics_preflight.py"
def test_binds_retention_sequence_and_not_applicable_deletion_without_claim():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);manifest=root/"dynamics.json";output=root/"out.json"
  manifest.write_text(json.dumps({"retention":{"slice_sha256":"a"*64,"scorer_sha256":"b"*64,"checkpoints":["c"*64,"d"*64]},"deletion":{"status":"NOT_APPLICABLE_NO_PROMOTED_MECHANISM"}}))
  r=subprocess.run([sys.executable,str(SCRIPT),"--manifest",str(manifest),"--output",str(output)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr
  assert json.loads(output.read_text())=={"result":"PREFLIGHT_ONLY","admission":"NOT_ELIGIBLE","retention_checkpoint_count":2,"deletion_status":"NOT_APPLICABLE_NO_PROMOTED_MECHANISM"}
