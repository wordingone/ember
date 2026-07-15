# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_comparator_preflight.py"
def test_accepts_only_identically_pinned_target_and_comparator_preflights():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);target=root/"target.json";comparator=root/"comparator.json";out=root/"out.json";shared={"result":"PREFLIGHT_ONLY","admission":"NOT_ELIGIBLE","capability":"image","benchmark_id":"MMMU","benchmark_version":"v1","split_sha256":"a"*64,"harness_sha256":"b"*64,"protocol_sha256":"c"*64}
  target.write_text(json.dumps({**shared,"subject_checkpoint_sha256":"d"*64}));comparator.write_text(json.dumps({**shared,"subject_checkpoint_sha256":"e"*64,"subject_kind":"open_comparator","comparator_model_id":"example/comparator-3b","comparator_revision":"f"*40,"comparator_size_class":"open_3b"}))
  r=subprocess.run([sys.executable,str(SCRIPT),"--target",str(target),"--comparator",str(comparator),"--output",str(out)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr
  payload=json.loads(out.read_text());assert all(payload[key]==value for key,value in {"result":"COMPARISON_PREFLIGHT","admission":"NOT_ELIGIBLE","capability":"image","benchmark_id":"MMMU","benchmark_version":"v1","comparator_model_id":"example/comparator-3b"}.items())


def test_comparator_preflight_receipt_binds_exact_input_bytes():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);target=root/'target';comparator=root/'comparator';output=root/'output';shared={'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':'text','benchmark_id':'x','benchmark_version':'1','split_sha256':'a'*64,'harness_sha256':'b'*64,'protocol_sha256':'c'*64}
  target.write_bytes(json.dumps({**shared,'subject_checkpoint_sha256':'d'*64}).encode())
  comparator.write_bytes(json.dumps({**shared,'subject_checkpoint_sha256':'e'*64,'subject_kind':'open_comparator','comparator_model_id':'example/comparator-3b','comparator_revision':'f'*40,'comparator_size_class':'open_3b'}).encode())
  run=subprocess.run([sys.executable,str(SCRIPT),'--target',str(target),'--comparator',str(comparator),'--output',str(output)],capture_output=True,text=True);assert run.returncode==0,run.stderr
  import hashlib
  payload=json.loads(output.read_text());assert payload['target_preflight_sha256']==hashlib.sha256(target.read_bytes()).hexdigest() and payload['comparator_preflight_sha256']==hashlib.sha256(comparator.read_bytes()).hexdigest()
def test_comparator_preflight_emits_full_shared_evaluator_tuple():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);target=root/'target';comparator=root/'comparator';output=root/'output';shared={'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':'text','benchmark_id':'x','benchmark_version':'1','split_sha256':'a'*64,'harness_sha256':'b'*64,'protocol_sha256':'c'*64};target.write_text(json.dumps({**shared,'subject_checkpoint_sha256':'d'*64}));comparator.write_text(json.dumps({**shared,'subject_checkpoint_sha256':'e'*64,'subject_kind':'open_comparator','comparator_model_id':'example/comparator-3b','comparator_revision':'f'*40,'comparator_size_class':'open_3b'}));run=subprocess.run([sys.executable,str(SCRIPT),'--target',str(target),'--comparator',str(comparator),'--output',str(output)],capture_output=True,text=True);assert run.returncode==0,run.stderr;payload=json.loads(output.read_text());assert {key:payload[key] for key in ('split_sha256','harness_sha256','protocol_sha256')}=={key:shared[key] for key in ('split_sha256','harness_sha256','protocol_sha256')}