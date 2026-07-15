# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib, importlib.util, json, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SCORER=ROOT/'scripts'/'ember_restart_eval_text_exact.py';PREFLIGHT=ROOT/'scripts'/'ember_restart_eval_execution_preflight.py'
def _load_text_scorer():
    sys.path.insert(0, str(SCORER.parent))
    specification = importlib.util.spec_from_file_location("text_scorer_single_read", SCORER)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module
def test_text_scorer_consumes_checkpoint_bound_canonical_predictions(tmp_path):
    references, manifest, predictions, score = (tmp_path / name for name in ("references.json", "manifest.json", "predictions.json", "score.json"))
    references.write_text(json.dumps([{"id": "t1", "answer": "yes"}]), encoding="utf-8")
    manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "local-text", "benchmark_version": "1", "references_sha256": hashlib.sha256(references.read_bytes()).hexdigest(), "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "split_sha256": "e" * 64, "protocol_sha256": "f" * 64}), encoding="utf-8")
    predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "local-text", "version": "1", "capability": "text", "split_sha256": "e" * 64, "protocol_sha256": "f" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "t1", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "yes"}}]}), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(SCORER), "--frozen-text-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(score.read_text(encoding="utf-8"))
    assert payload["sample_count"] == 1
    assert payload["predictions_sha256"] == hashlib.sha256(predictions.read_bytes()).hexdigest()
def test_text_scorer_rejects_synthetic_answer_rows(tmp_path):
    references, manifest, predictions, score = (tmp_path / name for name in ("references.json", "manifest.json", "predictions.json", "score.json"))
    references.write_text(json.dumps([{"id": "t1", "answer": "yes"}]), encoding="utf-8")
    manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "local-text", "benchmark_version": "1", "references_sha256": hashlib.sha256(references.read_bytes()).hexdigest(), "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "split_sha256": "e" * 64, "protocol_sha256": "f" * 64}), encoding="utf-8")
    predictions.write_text(json.dumps([{"id": "t1", "answer": "yes"}]), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(SCORER), "--frozen-text-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert completed.returncode != 0
    assert "canonical checkpoint predictions" in completed.stderr
    assert not score.exists()

def _write_checkpoint_bound_text_inputs(tmp_path, *, frozen_updates=None, prediction_updates=None):
    references, manifest, predictions, score = (tmp_path / name for name in ("references.json", "manifest.json", "predictions.json", "score.json"))
    references.write_text(json.dumps([{"id": "t1", "answer": "yes"}]), encoding="utf-8")
    frozen = {
        "result": "PREFLIGHT_ONLY",
        "benchmark_id": "local-text",
        "benchmark_version": "1",
        "references_sha256": hashlib.sha256(references.read_bytes()).hexdigest(),
        "checkpoint_manifest_sha256": "a" * 64,
        "model_config_sha256": "b" * 64,
        "split_sha256": "e" * 64,
        "protocol_sha256": "f" * 64,
    }
    if frozen_updates:
        frozen.update(frozen_updates)
    manifest.write_text(json.dumps(frozen), encoding="utf-8")
    prediction = {
        "schema_version": "ember-owned-predictions-v1",
        "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": "a" * 64,
        "model_config_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64,
        "inference_implementation_sha256": "d" * 64,
        "benchmark": {"id": "local-text", "version": "1", "capability": "text", "split_sha256": "e" * 64, "protocol_sha256": "f" * 64},
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
        "rows": [{"id": "t1", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "yes"}}],
    }
    if prediction_updates:
        for key, value in prediction_updates.items():
            if key == "benchmark":
                prediction["benchmark"].update(value)
            else:
                prediction[key] = value
    predictions.write_text(json.dumps(prediction), encoding="utf-8")
    return references, manifest, predictions, score


def _score_text(manifest, references, predictions, score):
    return subprocess.run([sys.executable, str(SCORER), "--frozen-text-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)


def test_text_scorer_rejects_missing_frozen_checkpoint_binding(tmp_path):
    references, manifest, predictions, score = _write_checkpoint_bound_text_inputs(tmp_path, frozen_updates={"checkpoint_manifest_sha256": None})
    completed = _score_text(manifest, references, predictions, score)
    assert completed.returncode != 0
    assert "canonical prediction identity" in completed.stderr
    assert not score.exists()


def test_text_scorer_rejects_wrong_frozen_checkpoint_binding(tmp_path):
    references, manifest, predictions, score = _write_checkpoint_bound_text_inputs(tmp_path, frozen_updates={"checkpoint_manifest_sha256": "9" * 64})
    completed = _score_text(manifest, references, predictions, score)
    assert completed.returncode != 0
    assert "canonical prediction identity" in completed.stderr
    assert not score.exists()


def test_text_scorer_rejects_missing_or_wrong_frozen_model_binding(tmp_path):
    for value in (None, "9" * 64):
        case = tmp_path / ("missing" if value is None else "wrong")
        case.mkdir()
        references, manifest, predictions, score = _write_checkpoint_bound_text_inputs(case, frozen_updates={"model_config_sha256": value})
        completed = _score_text(manifest, references, predictions, score)
        assert completed.returncode != 0
        assert "canonical prediction identity" in completed.stderr
        assert not score.exists()


def test_text_scorer_rejects_canonical_benchmark_identity_drift(tmp_path):
    for key, value in (("id", "other-text"), ("version", "2"), ("split_sha256", "9" * 64), ("protocol_sha256", "8" * 64)):
        case = tmp_path / key
        case.mkdir()
        references, manifest, predictions, score = _write_checkpoint_bound_text_inputs(case, prediction_updates={"benchmark": {key: value}})
        completed = _score_text(manifest, references, predictions, score)
        assert completed.returncode != 0
        assert "canonical prediction identity" in completed.stderr
        assert not score.exists()

def test_text_scorer_reads_each_bound_input_once(tmp_path, monkeypatch):
    references, manifest, predictions, score = _write_checkpoint_bound_text_inputs(tmp_path)
    module = _load_text_scorer()
    inputs = {references, manifest, predictions}
    reads = {path: 0 for path in inputs}
    original = Path.read_bytes

    def read_once(path):
        if path in inputs:
            reads[path] += 1
            if reads[path] > 1:
                raise AssertionError(f"reopened bound input: {path.name}")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_once)
    monkeypatch.setattr(sys, "argv", [str(SCORER), "--frozen-text-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)])

    assert module.main() == 0
    assert reads == {references: 1, manifest: 1, predictions: 1}