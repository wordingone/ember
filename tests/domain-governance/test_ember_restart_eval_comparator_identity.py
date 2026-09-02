# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_comparator_preflight.py'
def test_rejects_comparator_without_pinned_open_identity_and_size_class():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);t=root/'t';c=root/'c';o=root/'o';shared={'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':'text','benchmark_id':'x','benchmark_version':'v1','split_sha256':'a'*64,'harness_sha256':'b'*64,'protocol_sha256':'c'*64};t.write_text(json.dumps({**shared,'subject_checkpoint_sha256':'d'*64}));c.write_text(json.dumps({**shared,'subject_checkpoint_sha256':'e'*64}));r=subprocess.run([sys.executable,str(SCRIPT),'--target',str(t),'--comparator',str(c),'--output',str(o)],capture_output=True,text=True);assert r.returncode!=0 and not o.exists()
