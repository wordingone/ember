# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_audiobench.py"

def test_derives_passed_criterion_from_pinned_metric_protocol():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);run=root/"run.json";protocol=root/"protocol.json";raw=root/"raw.json";score=root/"score.json"
  run.write_text(json.dumps({"suite":"ab/sound-id","run_hash":"a"*64,"headline":{"weighted_recall":0.75,"weighted_fpr":0.1},"per_mixture":[{}]}),encoding="utf-8")
  protocol.write_text(json.dumps({"criterion_id":"ember-3b-audio-capability-v1","thresholds":{"weighted_recall":{"operator":">=","value":0.7},"weighted_fpr":{"operator":"<=","value":0.2}}}),encoding="utf-8")
  result=subprocess.run([sys.executable,str(SCRIPT),"--run-artifact",str(run),"--criterion-protocol",str(protocol),"--raw-predictions",str(raw),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert result.returncode==0,result.stderr
  assert json.loads(score.read_text(encoding="utf-8"))["criterion_result"]=="PASSED"
