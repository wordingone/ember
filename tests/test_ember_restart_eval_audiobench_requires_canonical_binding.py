# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_audiobench.py'
def test_summary_only_run_artifact_cannot_emit_raw_predictions():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);run=root/'run';raw=root/'raw';score=root/'score';rows=[{'mixture_name':'x','weight':1.0,'recall':.5,'fpr':.1,'transcript_sha256':'a'*64}];identity={'suite':'ab/sound-id','per_mixture':rows};run.write_text(json.dumps({**identity,'run_hash':hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'headline':{'weighted_recall':.5,'weighted_fpr':.1}}));r=subprocess.run([sys.executable,str(SCRIPT),'--run-artifact',str(run),'--raw-predictions',str(raw),'--score-output',str(score)],capture_output=True,text=True);assert r.returncode!=0 and not raw.exists()
