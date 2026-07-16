# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_mmmu.py"


def load_module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("mmmu_answer_snapshot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_mmmu_scorer_receives_hashed_answer_snapshot(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); mmmu = root / "mmmu"; mmmu.mkdir(); answers = root / "answers.json"; predictions = root / "predictions.json"; custody = root / "custody.json"; score = root / "score.json"
        original = {"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}
        answers.write_text(json.dumps(original), encoding="utf-8")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "MMMU", "version": "v", "capability": "image", "split_sha256": digest(answers), "protocol_sha256": hashlib.sha256(f"MMMU:v:{digest(answers)}".encode()).hexdigest()}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "validation_math_1", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "A"}}]}), encoding="utf-8")
        custody.write_text(json.dumps({"benchmark_id": "MMMU", "benchmark_version": "v", "split": {"name": "validation", "answer_dictionary_sha256": digest(answers)}}), encoding="utf-8")
        (mmmu / "main_eval_only.py").write_text("# test placeholder", encoding="utf-8")
        module = load_module()
        def fake_run(command, **_):
            answers.write_text(json.dumps({"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "B"}}), encoding="utf-8")
            assert json.loads(Path(command[-1]).read_text(encoding="utf-8")) == original
            return subprocess.CompletedProcess(command, 0, "{'Overall': {'num': 1, 'acc': 1.0}}\n", "")
        monkeypatch.setattr(module.subprocess, "run", fake_run)
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--mmmu-root", str(root), "--answers", str(answers), "--canonical-predictions", str(predictions), "--frozen-mmmu-manifest", str(custody), "--score-output", str(score)])
        assert module.main() == 0
