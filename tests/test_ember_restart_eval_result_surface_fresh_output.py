# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_result_surface.py'
def test_refuses_to_overwrite_existing_result_surface():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);source=root/'source';output=root/'output';source.write_text(json.dumps({'result':'PREFLIGHT_ONLY'}));output.write_text('preserve')
  result=subprocess.run([sys.executable,str(SCRIPT),'--input',str(source),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and output.read_text()=='preserve'
