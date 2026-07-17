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
    assert value["mutation_policy"] == "FROZEN_NO_ADDITIONS_OR_RENAMES_AFTER_LAUNCH"
    assert [item["name"] for item in value["benchmarks"]] == [
        "MMLU-Pro", "GSM8K", "MATH-500", "ARC-Challenge",
        "HumanEval+", "MBPP", "HellaSwag", "MMMU validation native-image scorer",
    ]
    mmmu = value["benchmarks"][-1]
    assert mmmu["total_records"] == 900
    assert mmmu["eligible_multiple_choice_items"] == 847
    assert set(value["runnability_blockers"]) == {
        "MMLU-Pro license-card hash",
        "owned checkpoint binding",
        "MMMU canonical loader/prediction binding",
    }
    canonical = dict(value)
    digest = canonical.pop("content_sha256")
    assert digest == hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_freezer_rejects_non_sha_evaluator_commit(tmp_path):
    output = tmp_path / "bad.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--evaluator-commit", "not-a-sha", "--output", str(output)], capture_output=True, text=True)
    assert completed.returncode != 0
    assert not output.exists()