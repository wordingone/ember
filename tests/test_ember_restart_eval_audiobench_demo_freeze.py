# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_audiobench_demo_freeze.py"


def test_freezes_bundled_audiobench_demo_protocol_bytes(tmp_path):
    root = tmp_path / "audiobench"
    data = root / "src" / "audiobench" / "data" / "sound_id"
    (data / "packs").mkdir(parents=True)
    (root / "src" / "audiobench" / "suites").mkdir(parents=True)
    (data / "packs" / "demo.json").write_text(json.dumps({"id": "demo", "source": "procedural (bundled)", "license": "bundled", "labels": ["siren"], "mixture_counts": {"solo": 1}, "clip_resolver": "procedural"}), encoding="utf-8")
    (data / "prompts.yaml").write_text("version: yesno-v1\n", encoding="utf-8")
    (data / "procedural.py").write_text("DEMO_SAMPLE_RATE = 16000\n", encoding="utf-8")
    (root / "src" / "audiobench" / "suites" / "sound_id.py").write_text("SUITE_ID = 'ab/sound-id'\n", encoding="utf-8")
    output = tmp_path / "frozen.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--audiobench-root", str(root), "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["result"] == "PREFLIGHT_ONLY"
    assert value["benchmark_id"] == "audiobench-demo-procedural"
    assert value["capability"] == "audio"
    assert value["task_count"] == 1
    assert value["claim_status"] == "SELFTEST_ONLY_PROCEDURAL_AUDIO"
    expected_protocol = hashlib.sha256(f"audiobench-demo-procedural:0fc7fef2709c00ac1e2eb2b372ec4c56362bb8c6:{value['split_sha256']}".encode("ascii")).hexdigest()
    assert value["protocol_sha256"] == expected_protocol
    assert value["split_sha256"] == hashlib.sha256(b"demo_pack\0" + (data / "packs" / "demo.json").read_bytes() + b"\nprompts\0" + (data / "prompts.yaml").read_bytes() + b"\nprocedural\0" + (data / "procedural.py").read_bytes() + b"\nsuite\0" + (root / "src" / "audiobench" / "suites" / "sound_id.py").read_bytes()).hexdigest()


def test_demo_freezer_protocol_is_not_caller_attested(tmp_path):
    root = tmp_path / "audiobench"
    data = root / "src" / "audiobench" / "data" / "sound_id"
    (data / "packs").mkdir(parents=True)
    (root / "src" / "audiobench" / "suites").mkdir(parents=True)
    (data / "packs" / "demo.json").write_text(json.dumps({"id": "demo", "source": "procedural (bundled)", "license": "bundled", "labels": ["siren"], "mixture_counts": {"solo": 1}, "clip_resolver": "procedural"}), encoding="utf-8")
    (data / "prompts.yaml").write_text("version: yesno-v1\n", encoding="utf-8")
    (data / "procedural.py").write_text("DEMO_SAMPLE_RATE = 16000\n", encoding="utf-8")
    (root / "src" / "audiobench" / "suites" / "sound_id.py").write_text("SUITE_ID = 'ab/sound-id'\n", encoding="utf-8")
    outputs = []
    for supplied in ("a" * 64, "b" * 64, None):
        output = tmp_path / f"frozen-{supplied[0] if supplied else 'omitted'}.json"
        command = [sys.executable, str(SCRIPT), "--audiobench-root", str(root)]
        if supplied is not None:
            command.extend(["--protocol-sha256", supplied])
        command.extend(["--output", str(output)])
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        outputs.append(json.loads(output.read_text(encoding="utf-8"))["protocol_sha256"])
    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[0] not in {"a" * 64, "b" * 64}
