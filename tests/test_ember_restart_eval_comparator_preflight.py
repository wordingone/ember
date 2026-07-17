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
  payload=json.loads(out.read_text())
  assert payload["result"]=="COMPARISON_PREFLIGHT" and payload["admission"]=="NOT_ELIGIBLE"
  assert all(payload[field]==shared[field] for field in ("capability","benchmark_id","benchmark_version","split_sha256","harness_sha256","protocol_sha256"))
  assert payload["target_subject_checkpoint_sha256"]=="d"*64 and payload["comparator_subject_checkpoint_sha256"]=="e"*64
  assert payload["comparator_revision"]=="f"*40 and payload["comparator_size_class"]=="open_3b"

def test_comparator_preflight_receipt_preserves_full_identity_for_distinct_pairs():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);target=root/"target.json";comparator=root/"comparator.json";out=root/"out.json"
  shared={"result":"PREFLIGHT_ONLY","admission":"NOT_ELIGIBLE","capability":"tool","benchmark_id":"BFCL","benchmark_version":"v2","split_sha256":"1"*64,"harness_sha256":"2"*64,"protocol_sha256":"3"*64}
  target.write_text(json.dumps({**shared,"subject_checkpoint_sha256":"4"*64}))
  comparator.write_text(json.dumps({**shared,"subject_checkpoint_sha256":"5"*64,"subject_kind":"open_comparator","comparator_revision":"6"*40,"comparator_size_class":"open_27b_or_31b"}))
  run=subprocess.run([sys.executable,str(SCRIPT),"--target",str(target),"--comparator",str(comparator),"--output",str(out)],text=True,capture_output=True,check=False)
  assert run.returncode==0,run.stderr
  payload=json.loads(out.read_text())
  assert payload["admission"]=="NOT_ELIGIBLE"
  assert payload["split_sha256"]==shared["split_sha256"] and payload["harness_sha256"]==shared["harness_sha256"] and payload["protocol_sha256"]==shared["protocol_sha256"]
  assert payload["target_subject_checkpoint_sha256"]=="4"*64 and payload["comparator_subject_checkpoint_sha256"]=="5"*64
  assert payload["comparator_revision"]=="6"*40 and payload["comparator_size_class"]=="open_27b_or_31b"
