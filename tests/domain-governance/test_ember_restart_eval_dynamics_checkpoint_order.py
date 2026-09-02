# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_dynamics_preflight.py'
def test_rejects_hash_only_retention_sequence_without_checkpoint_steps():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);m=root/'m';o=root/'o';m.write_text(json.dumps({'retention':{'slice_sha256':'a'*64,'scorer_sha256':'b'*64,'checkpoints':['c'*64,'d'*64]},'deletion':{'status':'NOT_APPLICABLE_NO_PROMOTED_MECHANISM'}}));r=subprocess.run([sys.executable,str(SCRIPT),'--manifest',str(m),'--output',str(o)],capture_output=True,text=True);assert r.returncode!=0 and not o.exists()
