# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util, json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_browsergym.py'
_BROWSER_SPEC=importlib.util.spec_from_file_location("browsergym_protocol", SCRIPT)
_BROWSER=importlib.util.module_from_spec(_BROWSER_SPEC)
_BROWSER_SPEC.loader.exec_module(_BROWSER)

def frozen_manifest(task_sha, environment_sha):
 d={"schema_version":"ember-restart-browsergym-miniwob-frozen-v1","result":"PREFLIGHT_ONLY","benchmark_id":"browsergym-miniwob","benchmark_version":"1","source_commit":"9e779f087de9a65668b6974d11f9ce9816026e96","source_tree":"d33e398c18d04d5da742b1c1ec11c4aab8bc010b","license_sha256":"b192c58991e8ff585cc574615d40e74185404d4b96c1109d423071ab1367344b","tasks":[{"task_id":"click-test","task_sha256":task_sha,"environment_sha256":environment_sha}]}
 d["protocol_sha256"]=_BROWSER.protocol_sha256(d)
 return d
def test_rejects_browser_environment_substitution_before_output():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);manifest=root/'frozen';runs=root/'runs';output=root/'score'
  manifest.write_text(json.dumps(frozen_manifest("a"*64, "b"*64)));runs.write_text(json.dumps([{'task_id':'click-test','success':True,'trace_sha256':'c'*64,'environment_sha256':'d'*64}]))
  result=subprocess.run([sys.executable,str(SCRIPT),'--frozen-task-manifest',str(manifest),'--browser-results',str(runs),'--score-output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists()
