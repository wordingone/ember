# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_comparator_preflight.py"
def test_accepts_only_identically_pinned_target_and_comparator_preflights():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);target=root/"target.json";comparator=root/"comparator.json";out=root/"out.json";shared={"result":"PREFLIGHT_ONLY","admission":"NOT_ELIGIBLE","capability":"image","benchmark_id":"MMMU","benchmark_version":"v1","split_sha256":"a"*64,"harness_sha256":"b"*64,"protocol_sha256":"c"*64}
  target.write_text(json.dumps({**shared,"subject_checkpoint_sha256":"d"*64}));comparator.write_text(json.dumps({**shared,"subject_checkpoint_sha256":"e"*64,"subject_kind":"open_comparator","comparator_revision":"f"*40,"comparator_size_class":"open_3b"}))
  r=subprocess.run([sys.executable,str(SCRIPT),"--target",str(target),"--comparator",str(comparator),"--output",str(out)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr
  assert json.loads(out.read_text())=={"result":"COMPARISON_PREFLIGHT","admission":"NOT_ELIGIBLE","capability":"image","benchmark_id":"MMMU","benchmark_version":"v1"}
