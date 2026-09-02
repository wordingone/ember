# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_uncertainty.py'
def test_refuses_to_overwrite_existing_uncertainty_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);rows=root/'rows';out=root/'out';rows.write_text(json.dumps([{'correct':True}]));out.write_text('preserve')
  result=subprocess.run([sys.executable,str(SCRIPT),'--rows',str(rows),'--output',str(out)],capture_output=True,text=True)
  assert result.returncode!=0 and out.read_text()=='preserve'
