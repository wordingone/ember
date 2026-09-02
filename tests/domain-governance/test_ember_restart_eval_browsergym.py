# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_browsergym.py"
def test_shapes_exact_frozen_miniwob_outcomes_with_trace_and_environment_hashes():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);tasks=root/'tasks';runs=root/'runs';out=root/'out'
  tasks.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'browsergym-miniwob','benchmark_version':'1','tasks':[{'task_id':'click-test','task_sha256':'d'*64,'environment_sha256':'b'*64}]}))
  runs.write_text(json.dumps([{'task_id':'click-test','success':True,'trace_sha256':'a'*64,'environment_sha256':'b'*64}]))
  r=subprocess.run([sys.executable,str(SCRIPT),'--frozen-task-manifest',str(tasks),'--browser-results',str(runs),'--score-output',str(out)],capture_output=True,text=True);assert r.returncode==0,r.stderr;p=json.loads(out.read_text());assert p['metrics']=={'task_success_rate':1.0} and p['sample_count']==1 and p['criterion_result']=='FAILED'
