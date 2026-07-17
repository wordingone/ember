# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_bfcl_simple_freeze.py"


def test_freezes_aligned_bfcl_simple_prompt_and_oracle_pairs(tmp_path):
    data = tmp_path / "data"; answers = data / "possible_answer"; answers.mkdir(parents=True)
    for category in ("simple_python", "simple_java", "simple_javascript"):
        (data / f"BFCL_v4_{category}.json").write_text(json.dumps({"id": f"{category}_0", "function": [], "question": []}) + "\n", encoding="utf-8")
        (answers / f"BFCL_v4_{category}.json").write_text(json.dumps({"id": f"{category}_0", "ground_truth": [{"lookup": {"city": ["Paris"]}}]}) + "\n", encoding="utf-8")
    output = tmp_path / "frozen.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--data-root", str(data), "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["result"] == "PREFLIGHT_ONLY"
    assert value["benchmark_id"] == "bfcl-static-simple"
    assert value["task_count"] == 3
    assert [item["id"] for item in value["tasks"]] == ["simple_python_0", "simple_java_0", "simple_javascript_0"]
    assert value["tasks"][0]["functions"] == []
    assert value["tasks"][0]["category"] == "simple_python"
    assert value["tasks"][0]["question"] == []


def test_refuses_misaligned_bfcl_simple_oracle(tmp_path):
    data = tmp_path / "data"; answers = data / "possible_answer"; answers.mkdir(parents=True)
    for category in ("simple_python", "simple_java", "simple_javascript"):
        (data / f"BFCL_v4_{category}.json").write_text(json.dumps({"id": f"{category}_0", "function": [], "question": []}) + "\n", encoding="utf-8")
        (answers / f"BFCL_v4_{category}.json").write_text(json.dumps({"id": "wrong", "ground_truth": [{"lookup": {}}]}) + "\n", encoding="utf-8")
    output = tmp_path / "frozen.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--data-root", str(data), "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert not output.exists()

def test_refuses_bfcl_simple_prompt_without_function_declarations(tmp_path):
    data = tmp_path / "data"; answers = data / "possible_answer"; answers.mkdir(parents=True)
    for category in ("simple_python", "simple_java", "simple_javascript"):
        prompt = {"id": f"{category}_0", "question": []}
        if category != "simple_python":
            prompt["function"] = []
        (data / f"BFCL_v4_{category}.json").write_text(json.dumps(prompt) + "\n", encoding="utf-8")
        (answers / f"BFCL_v4_{category}.json").write_text(json.dumps({"id": f"{category}_0", "ground_truth": [{"lookup": {}}]}) + "\n", encoding="utf-8")
    output = tmp_path / "frozen.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--data-root", str(data), "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert not output.exists()

def test_bfcl_protocol_is_not_caller_attested(tmp_path):
    data = tmp_path / "data"
    answers = data / "possible_answer"
    answers.mkdir(parents=True)
    for category in ("simple_python", "simple_java", "simple_javascript"):
        (data / f"BFCL_v4_{category}.json").write_text(json.dumps({"id": f"{category}_0", "function": [], "question": []}) + "\n", encoding="utf-8")
        (answers / f"BFCL_v4_{category}.json").write_text(json.dumps({"id": f"{category}_0", "ground_truth": [{"lookup": {"city": ["Paris"]}}]}) + "\n", encoding="utf-8")
    protocols = []
    for supplied in ("a" * 64, "b" * 64):
        output = tmp_path / f"frozen-{supplied[0]}.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-root", str(data), "--protocol-sha256", supplied, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        protocols.append(json.loads(output.read_text(encoding="utf-8"))["protocol_sha256"])
    assert protocols[0] == protocols[1]
    assert protocols[0] not in {"a" * 64, "b" * 64}
