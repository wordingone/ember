# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_comparator_preflight.py'
def test_rejects_malformed_preflight_without_output_or_traceback():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);target=root/'target';comparator=root/'comparator';output=root/'output';target.write_text('{');comparator.write_text('{}')
  result=subprocess.run([sys.executable,str(SCRIPT),'--target',str(target),'--comparator',str(comparator),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists() and 'invalid preflight JSON' in result.stderr and 'Traceback' not in result.stderr
