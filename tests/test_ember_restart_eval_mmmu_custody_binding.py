# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_mmmu.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_prediction(answers: Path) -> dict:
    return {
        "schema_version": "ember-owned-predictions-v1",
        "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": "a" * 64,
        "model_config_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64,
        "inference_implementation_sha256": "d" * 64,
        "benchmark": {
            "id": "MMMU",
            "version": "frozen-v1",
            "capability": "image",
            "split_sha256": digest(answers),
            "protocol_sha256": hashlib.sha256(f"MMMU:frozen-v1:{digest(answers)}".encode()).hexdigest(),
        },
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
        "rows": [{"id": "validation_math_1", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "A"}}],
    }


def test_scores_only_canonical_predictions_bound_to_frozen_mmmu_custody():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); mmmu = root / "mmmu-root" / "mmmu"; mmmu.mkdir(parents=True)
        answers = root / "answers.json"; predictions = root / "predictions.json"; custody = root / "custody.json"; score = root / "score.json"
        answers.write_text(json.dumps({"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}), encoding="utf-8")
        predictions.write_text(json.dumps(canonical_prediction(answers)), encoding="utf-8")
        custody.write_text(json.dumps({"benchmark_id": "MMMU", "benchmark_version": "frozen-v1", "admission": "NOT_EXECUTABLE_UNTRAINED_SPECIALIST_NO_CHECKPOINT_BOUND_PREDICTIONS", "split": {"name": "validation", "answer_dictionary_sha256": digest(answers)}}), encoding="utf-8")
        (mmmu / "main_eval_only.py").write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--output_path');p.add_argument('--answer_path');a=p.parse_args();assert json.load(open(a.output_path)) == {'validation_math_1':'A'};print({'Overall':{'num':1,'acc':1.0}})\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--mmmu-root", str(root / "mmmu-root"), "--answers", str(answers), "--canonical-predictions", str(predictions), "--frozen-mmmu-manifest", str(custody), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(score.read_text(encoding="utf-8"))
        assert payload["predictions_sha256"] == digest(predictions)
        assert payload["answers_sha256"] == digest(answers)
        assert payload["frozen_mmmu_manifest_sha256"] == digest(custody)
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "NON_ADMISSIBLE_FROZEN_MMMU_SCORER"
        assert payload["criterion_result"] == "FAILED"


def test_refuses_detached_mmmu_prediction_json():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); answers = root / "answers.json"; predictions = root / "predictions.json"; custody = root / "custody.json"; score = root / "score.json"
        answers.write_text(json.dumps({"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}), encoding="utf-8")
        predictions.write_text(json.dumps({"validation_math_1": "A"}), encoding="utf-8")
        custody.write_text(json.dumps({"benchmark_id": "MMMU", "benchmark_version": "frozen-v1", "admission": "NOT_EXECUTABLE_UNTRAINED_SPECIALIST_NO_CHECKPOINT_BOUND_PREDICTIONS", "split": {"name": "validation", "answer_dictionary_sha256": digest(answers)}}), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--mmmu-root", str(root), "--answers", str(answers), "--canonical-predictions", str(predictions), "--frozen-mmmu-manifest", str(custody), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert "canonical checkpoint predictions are required" in result.stderr
        assert not score.exists()

def test_refuses_mmmu_image_input_receipt_mismatch_before_scorer(tmp_path):
    root = tmp_path; mmmu = root / "mmmu-root" / "mmmu"; mmmu.mkdir(parents=True)
    answers = root / "answers.json"; predictions = root / "predictions.json"; custody = root / "custody.json"; image_inputs = root / "image-inputs.json"; score = root / "score.json"
    answers.write_text(json.dumps({"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}), encoding="utf-8")
    predictions.write_text(json.dumps(canonical_prediction(answers)), encoding="utf-8")
    image_inputs.write_text(json.dumps({"schema_version": "ember-restart-mmmu-image-input-freeze-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "MMMU", "row_count": 1, "rows": [{"id": "validation_math_1", "image_sha256s": ["a" * 64], "input_sha256": "0" * 64}]}), encoding="utf-8")
    custody.write_text(json.dumps({"benchmark_id": "MMMU", "benchmark_version": "frozen-v1", "split": {"name": "validation", "answer_dictionary_sha256": digest(answers)}, "image_input_materialization": {"artifact_sha256": digest(image_inputs)}}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--mmmu-root", str(root / "mmmu-root"), "--answers", str(answers), "--canonical-predictions", str(predictions), "--frozen-mmmu-manifest", str(custody), "--frozen-image-inputs", str(image_inputs), "--score-output", str(score)], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "image input" in result.stderr
    assert not score.exists()

def test_scores_mmmu_when_declared_image_inputs_match_canonical_rows(tmp_path):
    root = tmp_path; mmmu = root / "mmmu-root" / "mmmu"; mmmu.mkdir(parents=True)
    answers = root / "answers.json"; predictions = root / "predictions.json"; custody = root / "custody.json"; image_inputs = root / "image-inputs.json"; score = root / "score.json"
    answers.write_text(json.dumps({"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}), encoding="utf-8")
    prediction = canonical_prediction(answers); prediction["rows"][0]["input_sha256"] = "0" * 64
    predictions.write_text(json.dumps(prediction), encoding="utf-8")
    image_inputs.write_text(json.dumps({"schema_version": "ember-restart-mmmu-image-input-freeze-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "MMMU", "row_count": 1, "rows": [{"id": "validation_math_1", "image_sha256s": ["a" * 64], "input_sha256": "0" * 64}]}), encoding="utf-8")
    custody.write_text(json.dumps({"benchmark_id": "MMMU", "benchmark_version": "frozen-v1", "split": {"name": "validation", "answer_dictionary_sha256": digest(answers)}, "image_input_materialization": {"artifact_sha256": digest(image_inputs)}}), encoding="utf-8")
    (mmmu / "main_eval_only.py").write_text("import argparse; p=argparse.ArgumentParser(); p.add_argument('--output_path'); p.add_argument('--answer_path'); p.parse_args(); print({'Overall': {'num': 1, 'acc': 1.0}})\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--mmmu-root", str(root / "mmmu-root"), "--answers", str(answers), "--canonical-predictions", str(predictions), "--frozen-mmmu-manifest", str(custody), "--frozen-image-inputs", str(image_inputs), "--score-output", str(score)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(score.read_text(encoding="utf-8"))["sample_count"] == 1
