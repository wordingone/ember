# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_uncertainty.py'
def test_rejects_malformed_rows_without_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);rows=root/'rows';output=root/'out';rows.write_text('{')
  result=subprocess.run([sys.executable,str(SCRIPT),'--rows',str(rows),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists() and 'rows must be valid JSON' in result.stderr
