# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from test_ember_restart_eval_audiobench_bound import write_bound_custody

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_audiobench_bound.py"


def load_module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("audiobench_read_once", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reads_canonical_predictions_and_closed_run_once_before_hashing(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); predictions = root / "predictions.json"; run = root / "run.json"; custody = root / "custody.json"; score = root / "score.json"
        text = "hello"
        row = {"mixture_name": "m", "weight": 1.0, "recall": 1.0, "fpr": 0.0, "transcript_sha256": hashlib.sha256(text.encode()).hexdigest()}
        identity = {"suite": "ab/sound-id", "per_mixture": [row]}
        run.write_text(json.dumps({**identity, "run_hash": hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "headline": {"weighted_recall": 1.0, "weighted_fpr": 0.0}}), encoding="utf-8")
        write_bound_custody(run, custody)
        predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "audiobench", "version": "0fc7fef2709c00ac1e2eb2b372ec4c56362bb8c6", "capability": "audio", "split_sha256": "e" * 64, "protocol_sha256": "d4db367699931e610459368c9a8aedf16281795b138b09f64351d9ab4c3b7082"}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "m", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "transcript", "text": text}}]}), encoding="utf-8")
        module = load_module(); original_bytes = Path.read_bytes; original_text = Path.read_text; reads = []
        def read_once(path):
            reads.append(path)
            return original_bytes(path)
        def no_text_read(path, *args, **kwargs):
            if path in (predictions, run):
                raise AssertionError("inputs must parse from their one byte snapshot")
            return original_text(path, *args, **kwargs)
        monkeypatch.setattr(Path, "read_bytes", read_once)
        monkeypatch.setattr(Path, "read_text", no_text_read)
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--canonical-predictions", str(predictions), "--run-artifact", str(run), "--frozen-audiobench-manifest", str(custody), "--score-output", str(score)])
        assert module.main() == 0
        assert reads.count(predictions) == 1
        assert reads.count(run) == 1