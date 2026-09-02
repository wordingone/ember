# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import subprocess,sys,tempfile
from pathlib import Path
from test_ember_restart_eval_runner_hardening import base
def test_failed_runner_never_publishes_preflight_even_if_it_leaves_raw_residue():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);pred=root/'p';score=root/'s';out=root/'o';child=root/'child.py';child.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('partial')\nraise SystemExit(1)\n")
  command,*_=base(root,pred,score,out);result=subprocess.run(command+['--',sys.executable,str(child),str(pred)],capture_output=True,text=True)
  assert result.returncode!=0 and pred.exists() and not score.exists() and not out.exists()
