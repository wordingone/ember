# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_terminal_bench.py"


def _frozen(tasks):
 custody=json.loads((SCRIPT.parents[1]/"manifests"/"ember-restart-terminal-bench-custody-v1.json").read_text(encoding="utf-8"))
 identity={"benchmark_id":"terminal-bench","benchmark_version":"2.0","source_commit":custody["source_commit"],"source_tree":custody["source_tree"],"license_sha256":custody["license_sha256"],"scoring_adapter_path":"scripts/ember_restart_eval_terminal_bench.py","scoring_adapter_sha256":hashlib.sha256(SCRIPT.read_bytes()).hexdigest()}
 return {"schema_version":"ember-restart-terminal-bench-freeze-v2","result":"PREFLIGHT_ONLY",**identity,"protocol_sha256":hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest(),"tasks":tasks}


def test_consumes_exact_frozen_harbor_task_outcomes_with_transcript_hashes():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);tasks=root/"tasks.json";results=root/"results.json";score=root/"score.json"
  tasks.write_text(json.dumps(_frozen([{"task_id":"task-a","task_toml_sha256":"e"*64,"docker_image_sha256":"b"*64},{"task_id":"task-b","task_toml_sha256":"f"*64,"docker_image_sha256":"d"*64}])),encoding="utf-8")
  results.write_text(json.dumps([{"task_id":"task-a","status":"passed","transcript_sha256":"a"*64,"task_image_sha256":"b"*64},{"task_id":"task-b","status":"failed","transcript_sha256":"c"*64,"task_image_sha256":"d"*64}]),encoding="utf-8")
  run=subprocess.run([sys.executable,str(SCRIPT),"--frozen-task-manifest",str(tasks),"--harbor-task-results",str(results),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert run.returncode==0,run.stderr
  payload=json.loads(score.read_text(encoding="utf-8"))
  assert payload["metrics"]=={"task_success_rate":0.5}
  assert payload["result"]=="SELFTEST"
  assert payload["admission"]=="NOT_ELIGIBLE"
  assert payload["claim_status"]=="SELFTEST_ONLY_FIXTURE_HARBOR_OUTCOMES"
  assert payload["sample_count"]==2
  assert payload["criterion_id"]=="ember-3b-tool-capability-v1"
  assert payload["criterion_result"]=="FAILED"


def test_rejects_task_outcome_without_a_content_addressed_transcript():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);tasks=root/"tasks.json";results=root/"results.json";score=root/"score.json"
  tasks.write_text("[\"task-a\"]",encoding="utf-8")
  results.write_text("[{\"task_id\":\"task-a\",\"status\":\"passed\",\"task_image_sha256\":\"b\"}]",encoding="utf-8")
  run=subprocess.run([sys.executable,str(SCRIPT),"--frozen-task-list",str(tasks),"--harbor-task-results",str(results),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert run.returncode!=0 and not score.exists()


def test_terminal_bench_score_replace_failure_cleans_real_cli_temporary_output(monkeypatch, tmp_path):
 import importlib.util, pytest
 spec=importlib.util.spec_from_file_location("terminal_cleanup", SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 tasks=tmp_path/"tasks.json";results=tmp_path/"results.json";score=tmp_path/"score.json"
 tasks.write_text(json.dumps(_frozen([{"task_id":"task-a","task_toml_sha256":"e"*64,"docker_image_sha256":"b"*64}])),encoding="utf-8")
 results.write_text(json.dumps([{"task_id":"task-a","status":"passed","transcript_sha256":"a"*64,"task_image_sha256":"b"*64}]),encoding="utf-8")
 monkeypatch.setattr(sys,"argv",[str(SCRIPT),"--frozen-task-manifest",str(tasks),"--harbor-task-results",str(results),"--score-output",str(score)])
 monkeypatch.setattr(module.os,"replace",lambda *_: (_ for _ in ()).throw(OSError("replace denied")))
 with pytest.raises(OSError,match="replace denied"):
  module.main()
 assert not score.exists()
 assert not list(tmp_path.glob("tmp*"))


def test_strict_terminal_manifest_cannot_omit_derived_protocol_identity():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);tasks=root/'tasks.json';results=root/'results.json';score=root/'score.json'
  tasks.write_text(json.dumps({'schema_version':'ember-restart-terminal-bench-freeze-v2','result':'PREFLIGHT_ONLY','benchmark_id':'terminal-bench','benchmark_version':'2.0','source_commit':'a'*40,'source_tree':'b'*40,'license_sha256':'c'*64,'tasks':[{'task_id':'task-a','task_toml_sha256':'e'*64,'docker_image_sha256':'b'*64}]}),encoding='utf-8')
  results.write_text(json.dumps([{'task_id':'task-a','status':'passed','transcript_sha256':'a'*64,'task_image_sha256':'b'*64}]),encoding='utf-8')
  run=subprocess.run([sys.executable,str(SCRIPT),'--frozen-task-manifest',str(tasks),'--harbor-task-results',str(results),'--score-output',str(score)],text=True,capture_output=True,check=False)
  assert run.returncode!=0 and not score.exists()