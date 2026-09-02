# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_result_surface.py'
def test_renders_preflight_as_non_claim_bearing_not_measured():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);source=root/'source';out=root/'out';source.write_text(json.dumps({'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','capability':'audio'}));r=subprocess.run([sys.executable,str(SCRIPT),'--input',str(source),'--output',str(out)],capture_output=True,text=True);assert r.returncode==0,r.stderr;assert 'NOT CLAIM-BEARING' in out.read_text() and 'MEASURED CAPABILITY' not in out.read_text()
