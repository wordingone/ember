# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_terminal_bench.py"


def _frozen(*, image_sha256="b" * 64):
    custody = json.loads((SCRIPT.parents[1] / "manifests" / "ember-restart-terminal-bench-custody-v1.json").read_text(encoding="utf-8"))
    identity = {
        "benchmark_id": "terminal-bench",
        "benchmark_version": "2.0",
        "source_commit": custody["source_commit"],
        "source_tree": custody["source_tree"],
        "license_sha256": custody["license_sha256"],
        "scoring_adapter_path": "scripts/ember_restart_eval_terminal_bench.py",
        "scoring_adapter_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
    }
    return {
        "result": "PREFLIGHT_ONLY",
        "schema_version": "ember-restart-terminal-bench-freeze-v2",
        **identity,
        "protocol_sha256": hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "tasks": [{"task_id": "bounded-task", "task_toml_sha256": "a" * 64, "docker_image_sha256": image_sha256}],
    }


def test_rejects_harbor_outcome_image_that_does_not_match_frozen_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        frozen = root / "frozen.json"
        results = root / "results.json"
        output = root / "score.json"
        frozen.write_text(json.dumps(_frozen()), encoding="utf-8")
        results.write_text(json.dumps([{"task_id": "bounded-task", "status": "passed", "transcript_sha256": "c" * 64, "task_image_sha256": "d" * 64}]), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--harbor-task-results", str(results), "--score-output", str(output)], capture_output=True, text=True)

        assert completed.returncode != 0
        assert not output.exists()


def test_scores_only_harbor_outcome_bound_to_frozen_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        frozen = root / "frozen.json"
        results = root / "results.json"
        output = root / "score.json"
        frozen.write_text(json.dumps(_frozen()), encoding="utf-8")
        results.write_text(json.dumps([{"task_id": "bounded-task", "status": "passed", "transcript_sha256": "c" * 64, "task_image_sha256": "b" * 64}]), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--harbor-task-results", str(results), "--score-output", str(output)], capture_output=True, text=True)

        assert completed.returncode == 0, completed.stderr


def test_rejects_handwritten_legacy_manifest_without_freezer_identity():
    """Terminal-Bench must consume only freezer-produced v2 manifests."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        frozen = root / "frozen.json"
        results = root / "results.json"
        output = root / "score.json"
        legacy = _frozen()
        legacy.pop("schema_version")
        frozen.write_text(json.dumps(legacy), encoding="utf-8")
        results.write_text(json.dumps([{"task_id": "bounded-task", "status": "passed", "transcript_sha256": "c" * 64, "task_image_sha256": "b" * 64}]), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--harbor-task-results", str(results), "--score-output", str(output)], capture_output=True, text=True)

        assert completed.returncode != 0
        assert not output.exists()


def test_terminal_fixture_receipt_is_selftest_and_binds_result_bytes():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        frozen, results, output = root / "frozen.json", root / "results.json", root / "score.json"
        frozen.write_text(json.dumps(_frozen(), separators=(",", ":")), encoding="utf-8")
        results.write_bytes(b'[{"task_id":"bounded-task","status":"passed","transcript_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","task_image_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]')
        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--harbor-task-results", str(results), "--score-output", str(output)], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "SELFTEST"
        assert payload["harbor_task_results_sha256"] == hashlib.sha256(results.read_bytes()).hexdigest()