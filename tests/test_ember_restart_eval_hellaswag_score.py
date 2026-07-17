# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_hellaswag_score.py"


def envelope(version, split, protocol, checkpoint, config, row_id, text):
    return {
        "schema_version": "ember-owned-predictions-v1",
        "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": checkpoint,
        "model_config_sha256": config,
        "tokenizer_sha256": "c" * 64,
        "inference_implementation_sha256": "d" * 64,
        "benchmark": {"id": "hellaswag", "version": version, "capability": "reasoning", "split_sha256": split, "protocol_sha256": protocol},
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
        "rows": [{"id": row_id, "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": text}}],
    }


def strict_protocol(version: str, split: str, license_sha: str = "f" * 64) -> tuple[str, str]:
    adapter_sha = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    protocol = hashlib.sha256(f"hellaswag:{version}:{split}:{license_sha}:{adapter_sha}".encode()).hexdigest()
    return protocol, adapter_sha


def write_manifest(path: Path, *, version: str, split: str, protocol: str, checkpoint: str, config: str, adapter_sha: str, license_sha: str = "f" * 64) -> None:
    path.write_text(json.dumps({
        "schema_version": "ember-restart-hellaswag-freeze-v2",
        "result": "PREFLIGHT_ONLY",
        "benchmark_id": "hellaswag",
        "benchmark_version": version,
        "capability": "reasoning",
        "references_sha256": split,
        "split_sha256": split,
        "protocol_sha256": protocol,
        "task_count": 1,
        "license_sha256": license_sha,
        "scoring_adapter_path": "scripts/ember_restart_eval_hellaswag_score.py",
        "scoring_adapter_sha256": adapter_sha,
        "checkpoint_manifest_sha256": checkpoint,
        "model_config_sha256": config,
    }), encoding="utf-8")


def test_scores_complete_hellaswag_labels_with_strict_checkpoint_identity(tmp_path):
    references, manifest, predictions, score = (tmp_path / name for name in ("refs.parquet", "manifest.json", "predictions.json", "score.json"))
    version, checkpoint, config = "218ec52e09a7e7462a5400043bb9a69a41d06b76", "a" * 64, "b" * 64
    pq.write_table(pa.table({"source_id": ["s1"], "ind": [0], "ctx": ["context"], "endings": [["a", "b"]], "label": ["1"]}), references)
    split = hashlib.sha256(references.read_bytes()).hexdigest()
    protocol, adapter_sha = strict_protocol(version, split)
    write_manifest(manifest, version=version, split=split, protocol=protocol, checkpoint=checkpoint, config=config, adapter_sha=adapter_sha)
    predictions.write_text(json.dumps(envelope(version, split, protocol, checkpoint, config, "s1:0", "1")), encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    payload = json.loads(score.read_text())
    assert payload["result"] == "PREFLIGHT_ONLY" and payload["criterion_result"] == "FAILED" and payload["metrics"] == {"accuracy": 1.0}


def test_rejects_hellaswag_withheld_labels(tmp_path):
    references, manifest, predictions, score = (tmp_path / name for name in ("refs.parquet", "manifest.json", "predictions.json", "score.json"))
    version, checkpoint, config = "218ec52e09a7e7462a5400043bb9a69a41d06b76", "a" * 64, "b" * 64
    pq.write_table(pa.table({"source_id": ["s1"], "ind": [0], "ctx": ["context"], "endings": [["a", "b"]], "label": [""]}), references)
    split = hashlib.sha256(references.read_bytes()).hexdigest()
    protocol, adapter_sha = strict_protocol(version, split)
    write_manifest(manifest, version=version, split=split, protocol=protocol, checkpoint=checkpoint, config=config, adapter_sha=adapter_sha)
    predictions.write_text(json.dumps(envelope(version, split, protocol, checkpoint, config, "s1:0", "1")), encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode != 0 and not score.exists()


def test_rejects_hellaswag_checkpoint_substitution(tmp_path):
    references, manifest, predictions, score = (tmp_path / name for name in ("refs.parquet", "manifest.json", "predictions.json", "score.json"))
    version, checkpoint, config = "218ec52e09a7e7462a5400043bb9a69a41d06b76", "a" * 64, "b" * 64
    pq.write_table(pa.table({"source_id": ["s1"], "ind": [0], "ctx": ["context"], "endings": [["a", "b"]], "label": ["1"]}), references)
    split = hashlib.sha256(references.read_bytes()).hexdigest()
    protocol, adapter_sha = strict_protocol(version, split)
    write_manifest(manifest, version=version, split=split, protocol=protocol, checkpoint=checkpoint, config=config, adapter_sha=adapter_sha)
    predictions.write_text(json.dumps(envelope(version, split, protocol, "f" * 64, config, "s1:0", "1")), encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode != 0 and not score.exists()


def test_rejects_hellaswag_protocol_substitution(tmp_path):
    references, manifest, predictions, score = (tmp_path / name for name in ("refs.parquet", "manifest.json", "predictions.json", "score.json"))
    version, checkpoint, config = "218ec52e09a7e7462a5400043bb9a69a41d06b76", "a" * 64, "b" * 64
    pq.write_table(pa.table({"source_id": ["s1"], "ind": [0], "ctx": ["context"], "endings": [["a", "b"]], "label": ["1"]}), references)
    split = hashlib.sha256(references.read_bytes()).hexdigest()
    protocol, adapter_sha = strict_protocol(version, split)
    write_manifest(manifest, version=version, split=split, protocol=protocol, checkpoint=checkpoint, config=config, adapter_sha=adapter_sha)
    predictions.write_text(json.dumps(envelope(version, split, "0" * 64, checkpoint, config, "s1:0", "1")), encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode != 0 and not score.exists()