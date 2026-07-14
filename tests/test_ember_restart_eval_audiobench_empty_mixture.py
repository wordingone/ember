# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_audiobench.py'
def test_rejects_empty_per_mixture_rows_as_non_evidence():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);run=root/'run';raw=root/'raw';score=root/'score';run.write_text(json.dumps({'suite':'ab/sound-id','run_hash':'a'*64,'headline':{'weighted_recall':.75,'weighted_fpr':.1},'per_mixture':[{}]}));r=subprocess.run([sys.executable,str(SCRIPT),'--run-artifact',str(run),'--raw-predictions',str(raw),'--score-output',str(score)],capture_output=True,text=True);assert r.returncode!=0 and not raw.exists() and not score.exists()
