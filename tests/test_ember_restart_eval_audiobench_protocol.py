# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_audiobench.py'
def test_derives_passed_criterion_from_pinned_metric_protocol():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);run=root/'run';protocol=root/'protocol';raw=root/'raw';score=root/'score';run.write_text(json.dumps({'suite':'ab/sound-id','run_hash':'a'*64,'headline':{'weighted_recall':.75,'weighted_fpr':.1},'per_mixture':[{'mixture_name':'x'}]}));protocol.write_text(json.dumps({'criterion_id':'ember-3b-audio-capability-v1','thresholds':{'weighted_recall':{'operator':'>=','value':.7},'weighted_fpr':{'operator':'<=','value':.2}}}));r=subprocess.run([sys.executable,str(SCRIPT),'--run-artifact',str(run),'--criterion-protocol',str(protocol),'--raw-predictions',str(raw),'--score-output',str(score)],capture_output=True,text=True);assert r.returncode==0,r.stderr;assert json.loads(score.read_text())['criterion_result']=='PASSED'
