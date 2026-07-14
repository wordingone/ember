# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_terminal_bench.py"

def test_consumes_exact_frozen_harbor_task_outcomes_with_transcript_hashes():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);tasks=root/"tasks.json";results=root/"results.json";score=root/"score.json"
  tasks.write_text(json.dumps(["task-a","task-b"]),encoding="utf-8")
  results.write_text(json.dumps([{"task_id":"task-a","status":"passed","transcript_sha256":"a"*64,"task_image_sha256":"b"*64},{"task_id":"task-b","status":"failed","transcript_sha256":"c"*64,"task_image_sha256":"d"*64}]),encoding="utf-8")
  run=subprocess.run([sys.executable,str(SCRIPT),"--frozen-task-list",str(tasks),"--harbor-task-results",str(results),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert run.returncode==0,run.stderr
  payload=json.loads(score.read_text(encoding="utf-8"))
  assert payload["metrics"]=={"task_success_rate":0.5}
  assert payload["sample_count"]==2
  assert payload["criterion_id"]=="ember-3b-tool-capability-v1"
  assert payload["criterion_result"]=="FAILED"

def test_rejects_task_outcome_without_a_content_addressed_transcript():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);tasks=root/"tasks.json";results=root/"results.json";score=root/"score.json"
  tasks.write_text('["task-a"]',encoding="utf-8")
  results.write_text('[{"task_id":"task-a","status":"passed","task_image_sha256":"b"}]',encoding="utf-8")
  run=subprocess.run([sys.executable,str(SCRIPT),"--frozen-task-list",str(tasks),"--harbor-task-results",str(results),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert run.returncode!=0 and not score.exists()
