# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_vision_battery_freeze.py"


def test_freezes_exact_vision_v4_battery_and_current_blockers(tmp_path):
    output = tmp_path / "vision-v4-battery.json"
    head = "9" * 40
    completed = subprocess.run([sys.executable, str(SCRIPT), "--evaluator-commit", head, "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["schema_version"] == "ember-restart-vision-v4-eval-battery-v1"
    assert value["evaluator_commit"] == head
    assert value["checkpoint_manifest_sha256"] == "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"
    assert value["model_config_sha256"] == "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0"
    assert value["mutation_policy"] == "FROZEN_NO_ADDITIONS_OR_RENAMES_AFTER_LAUNCH"
    assert [item["name"] for item in value["benchmarks"]] == [
        "MMLU-Pro", "GSM8K", "MATH-500", "ARC-Challenge",
        "HumanEval+", "MBPP", "HellaSwag", "MMMU validation native-image scorer",
    ]
    mmmu = value["benchmarks"][-1]
    assert mmmu["total_records"] == 900
    assert mmmu["eligible_multiple_choice_items"] == 847
    assert value["runnability_blockers"] == ["no checkpoint-bound predictions"]
    canonical = dict(value)
    digest = canonical.pop("content_sha256")
    assert digest == hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_freezer_rejects_non_sha_evaluator_commit(tmp_path):
    output = tmp_path / "bad.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--evaluator-commit", "not-a-sha", "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode != 0
    assert not output.exists()
