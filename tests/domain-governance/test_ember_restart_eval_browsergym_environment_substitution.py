# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_browsergym.py'
def test_rejects_browser_environment_substitution_before_output():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);manifest=root/'frozen';runs=root/'runs';output=root/'score'
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'browsergym-miniwob','benchmark_version':'1','tasks':[{'task_id':'click-test','task_sha256':'a'*64,'environment_sha256':'b'*64}]}));runs.write_text(json.dumps([{'task_id':'click-test','success':True,'trace_sha256':'c'*64,'environment_sha256':'d'*64}]))
  result=subprocess.run([sys.executable,str(SCRIPT),'--frozen-task-manifest',str(manifest),'--browser-results',str(runs),'--score-output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists()
