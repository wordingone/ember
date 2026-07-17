# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util, json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_browsergym.py"
_BROWSER_SPEC=importlib.util.spec_from_file_location("browsergym_protocol", SCRIPT)
_BROWSER=importlib.util.module_from_spec(_BROWSER_SPEC)
_BROWSER_SPEC.loader.exec_module(_BROWSER)

def frozen_manifest(task_sha, environment_sha):
 d={"schema_version":"ember-restart-browsergym-miniwob-frozen-v1","result":"PREFLIGHT_ONLY","benchmark_id":"browsergym-miniwob","benchmark_version":"1","source_commit":"9e779f087de9a65668b6974d11f9ce9816026e96","source_tree":"d33e398c18d04d5da742b1c1ec11c4aab8bc010b","license_sha256":"b192c58991e8ff585cc574615d40e74185404d4b96c1109d423071ab1367344b","tasks":[{"task_id":"click-test","task_sha256":task_sha,"environment_sha256":environment_sha}]}
 d["protocol_sha256"]=_BROWSER.protocol_sha256(d)
 return d
def test_shapes_exact_frozen_miniwob_outcomes_with_trace_and_environment_hashes():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);tasks=root/'tasks';runs=root/'runs';out=root/'out'
  tasks.write_text(json.dumps(frozen_manifest("d"*64, "b"*64)))
  runs.write_text(json.dumps([{'task_id':'click-test','success':True,'trace_sha256':'a'*64,'environment_sha256':'b'*64}]))
  r=subprocess.run([sys.executable,str(SCRIPT),'--frozen-task-manifest',str(tasks),'--browser-results',str(runs),'--score-output',str(out)],capture_output=True,text=True);assert r.returncode==0,r.stderr;p=json.loads(out.read_text());assert p['result']=='SELFTEST' and p['admission']=='NOT_ELIGIBLE' and p['claim_status']=='SELFTEST_ONLY_FIXTURE_BROWSER_OUTCOMES' and p['metrics']=={'task_success_rate':1.0} and p['sample_count']==1 and p['criterion_result']=='FAILED'

def test_browsergym_score_replace_failure_cleans_real_cli_temporary_output(monkeypatch, tmp_path):
 import importlib.util, pytest
 spec=importlib.util.spec_from_file_location("browser_cleanup",SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 tasks=tmp_path/"tasks";runs=tmp_path/"runs";score=tmp_path/"score"
 tasks.write_text(json.dumps(frozen_manifest("d"*64, "b"*64)),encoding="utf-8")
 runs.write_text(json.dumps([{"task_id":"click-test","success":True,"trace_sha256":"a"*64,"environment_sha256":"b"*64}]),encoding="utf-8")
 monkeypatch.setattr(sys,"argv",[str(SCRIPT),"--frozen-task-manifest",str(tasks),"--browser-results",str(runs),"--score-output",str(score)])
 monkeypatch.setattr(module.os,"replace",lambda *_: (_ for _ in ()).throw(OSError("replace denied")))
 with pytest.raises(OSError,match="replace denied"):
  module.main()
 assert not score.exists()
 assert not list(tmp_path.glob("tmp*"))
