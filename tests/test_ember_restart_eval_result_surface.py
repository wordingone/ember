# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_result_surface.py'
def test_renders_preflight_as_non_claim_bearing_not_measured():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);source=root/'source';out=root/'out';source.write_text(json.dumps({'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':'audio'}));r=subprocess.run([sys.executable,str(SCRIPT),'--input',str(source),'--output',str(out)],capture_output=True,text=True);assert r.returncode==0,r.stderr;assert 'NOT CLAIM-BEARING' in out.read_text() and 'MEASURED CAPABILITY' not in out.read_text()


def test_renders_verified_non_claim_raw_forward_without_capability_credit():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);source=root/'raw-forward.json';out=root/'surface.md'
  source.write_text(json.dumps({'result':'VERIFIED_NON_CLAIM_RAW_FORWARD','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','output':{'decoded_text':'lev'},'truth_boundary':{'capability_proven':False,'sufficient_pretraining_proven':False}}))
  run=subprocess.run([sys.executable,str(SCRIPT),'--input',str(source),'--output',str(out)],capture_output=True,text=True);assert run.returncode==0,run.stderr
  rendered=out.read_text();assert 'VERIFIED NON-CLAIM RAW FORWARD' in rendered and 'NOT CLAIM-BEARING' in rendered and 'MEASURED CAPABILITY' not in rendered