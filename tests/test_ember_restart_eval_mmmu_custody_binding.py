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
        assert payload["result"] == "SELFTEST"
        assert payload["claim_status"] == "SELFTEST_ONLY_LEGACY_MMMU_CUSTODY"
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

def test_mmmu_rejects_unpinned_scorer_source_even_when_answer_protocol_matches(tmp_path):
    import importlib.util
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("mmmu_scorer_custody", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    root = tmp_path / "mmmu-root"; scorer = root / "mmmu" / "main_eval_only.py"; scorer.parent.mkdir(parents=True); scorer.write_text("print({'Overall': {'num': 1, 'acc': 1.0}})\n", encoding="utf-8")
    answers = tmp_path / "answers.json"; answers.write_text(json.dumps({"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}), encoding="utf-8")
    predictions = tmp_path / "predictions.json"; answer_sha = hashlib.sha256(answers.read_bytes()).hexdigest()
    predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "MMMU", "version": "v", "capability": "image", "split_sha256": answer_sha, "protocol_sha256": hashlib.sha256(f"MMMU:v:{answer_sha}".encode()).hexdigest()}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "validation_math_1", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "A"}}]}), encoding="utf-8")
    custody = tmp_path / "custody.json"; custody.write_text(json.dumps({"schema_version": "ember-restart-benchmark-custody-v1", "benchmark_id": "MMMU", "benchmark_version": "v", "split": {"name": "validation", "answer_dictionary_sha256": answer_sha}}), encoding="utf-8")
    score = tmp_path / "score.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--mmmu-root", str(root), "--answers", str(answers), "--canonical-predictions", str(predictions), "--frozen-mmmu-manifest", str(custody), "--score-output", str(score)], text=True, capture_output=True, check=False)
    assert completed.returncode != 0
    assert "scorer" in completed.stderr or "protocol" in completed.stderr
    assert not score.exists()


def test_mmmu_executes_manifest_selected_scorer_not_mutable_default(tmp_path):
    root = tmp_path / "mmmu-root"; scorer_dir = root / "mmmu"; scorer_dir.mkdir(parents=True)
    answers = tmp_path / "answers.json"; predictions = tmp_path / "predictions.json"; custody = tmp_path / "custody.json"; score = tmp_path / "score.json"
    answers.write_text(json.dumps({"validation_math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}), encoding="utf-8")
    answer_sha = digest(answers)
    selected = scorer_dir / "alternate.py"
    selected.write_text("import argparse; p=argparse.ArgumentParser(); p.add_argument('--output_path'); p.add_argument('--answer_path'); p.parse_args(); print({'Overall': {'num': 1, 'acc': 0.75}})\n", encoding="utf-8")
    (scorer_dir / "main_eval_only.py").write_text("raise SystemExit('default scorer must not execute')\n", encoding="utf-8")
    scorer_sha = digest(selected); license_sha = "e" * 64; upstream_tree = "f" * 40; checkpoint_sha = "a" * 64; config_sha = "b" * 64
    adapter_sha = digest(SCRIPT); protocol_sha = hashlib.sha256(f"MMMU:frozen-v1:{answer_sha}:{scorer_sha}:{license_sha}:{upstream_tree}:{adapter_sha}::{checkpoint_sha}:{config_sha}".encode()).hexdigest()
    prediction = canonical_prediction(answers); prediction["benchmark"]["protocol_sha256"] = protocol_sha
    predictions.write_text(json.dumps(prediction), encoding="utf-8")
    custody.write_text(json.dumps({"schema_version": "ember-restart-benchmark-custody-v1", "benchmark_id": "MMMU", "benchmark_version": "frozen-v1", "upstream_tree_git_sha1": upstream_tree, "split": {"name": "validation", "answer_dictionary_sha256": answer_sha}, "license_sha256": license_sha, "checkpoint_manifest_sha256": checkpoint_sha, "model_config_sha256": config_sha, "scoring_adapter": {"path": "scripts/ember_restart_eval_mmmu.py", "sha256": adapter_sha, "result_disposition": "PREFLIGHT_ONLY_NON_ADMISSIBLE"}, "scorer": {"path": "mmmu/alternate.py", "sha256": scorer_sha}, "protocol_sha256": protocol_sha}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--mmmu-root", str(root), "--answers", str(answers), "--canonical-predictions", str(predictions), "--frozen-mmmu-manifest", str(custody), "--score-output", str(score)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(score.read_text(encoding="utf-8"))["metrics"]["accuracy"] == 0.75