# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Test-first regressions for the four #862 identity/custody P1s.

These tests are deliberately independent of the broader evaluator graph.  They
exercise the public boundaries that must remain bound to the external trust
anchor, preserve claim identity, and refuse caller-substituted benchmark
evidence.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _audio_run(text: str) -> bytes:
    row = {
        "mixture_name": "m",
        "weight": 1.0,
        "recall": 0.5,
        "fpr": 0.1,
        "transcript_sha256": _sha_bytes(text.encode()),
    }
    identity = {"suite": "ab/sound-id", "per_mixture": [row]}
    payload = {
        **identity,
        "run_hash": _sha_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()),
        "headline": {"weighted_recall": 0.5, "weighted_fpr": 0.1},
    }
    return json.dumps(payload, sort_keys=True).encode() + b"\n"


def _audio_predictions(module, custody: dict, text: str) -> dict:
    return {
        "schema_version": "ember-owned-predictions-v1",
        "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": "a" * 64,
        "model_config_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64,
        "inference_implementation_sha256": "d" * 64,
        "benchmark": {
            "id": "audiobench",
            "version": custody["benchmark_version"],
            "capability": "audio",
            "split_sha256": "e" * 64,
            "protocol_sha256": module._protocol_sha256(custody),
        },
        "decoding": {
            "strategy": "GREEDY_AUTOREGRESSIVE",
            "teacher_forcing": False,
            "max_new_tokens": 1,
            "temperature": 0,
            "top_p": 1,
            "stop_token_ids": [1],
        },
        "rows": [{
            "id": "m",
            "input_sha256": "f" * 64,
            "generated_token_ids": [1],
            "stop_reason": "eos",
            "output": {"kind": "transcript", "text": text},
        }],
    }


def test_result_surface_rejects_an_internally_consistent_registry_without_the_pinned_hash(tmp_path, monkeypatch):
    module = _load("scripts/ember_restart_eval_result_surface.py", "four_p1_surface_anchor")
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"result":"MEASURED","capability":"text"}'
    receipt.write_bytes(receipt_bytes)
    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": receipt.name}]}), encoding="utf-8")
    registry = tmp_path / "trusted-verifiers.json"
    registry_bytes = b'{"schema_version":"ember-trusted-verifiers-v1","verifiers":[]}'
    registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": _sha_bytes(b"other-registry")}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    output = tmp_path / "surface.md"
    monkeypatch.setattr(sys, "argv", [str(module.__file__), "--input", str(receipt), "--admission-manifest", str(admission), "--trusted-verifier-registry", str(registry), "--output", str(output)])
    module.main()
    assert "NOT CLAIM-BEARING" in output.read_text(encoding="utf-8")


def test_claim_renderer_serializes_every_identity_field_so_admitted_receipts_cannot_collide(tmp_path, monkeypatch):
    module = _load("scripts/ember_restart_eval_result_surface.py", "four_p1_surface_identity")
    monkeypatch.setattr(module, "_admitted", lambda *args: True)
    base = {
        "result": "MEASURED",
        "capability": "text",
        "model_config_sha256": "b" * 64,
        "benchmark_id": "local-text",
        "benchmark_version": "1",
        "split_sha256": "c" * 64,
        "harness_sha256": "d" * 64,
        "protocol_sha256": "e" * 64,
        "predictions_sha256": "f" * 64,
        "score_artifact_sha256": "1" * 64,
        "criterion_id": "ember-3b-text-capability-v1",
        "criterion_result": "PASSED",
        "metrics": {"accuracy": 1.0},
        "verifier_sha256": "2" * 64,
    }
    rendered = []
    for marker in ("a", "9"):
        source = tmp_path / f"receipt-{marker}.json"
        source.write_text(json.dumps({**base, "checkpoint_manifest_sha256": marker * 64}), encoding="utf-8")
        output = tmp_path / f"surface-{marker}.md"
        monkeypatch.setattr(sys, "argv", [str(module.__file__), "--input", str(source), "--output", str(output)])
        module.main()
        rendered.append(output.read_text(encoding="utf-8"))
    assert rendered[0] != rendered[1]
    assert '"checkpoint_manifest_sha256":"aaaaaaaa' in rendered[0]
    assert '"checkpoint_manifest_sha256":"99999999' in rendered[1]
    for field in module.IDENTITY_FIELDS:
        assert f"{field}:" in rendered[0]


def test_audiobench_rejects_a_valid_foreign_closed_run_even_when_predictions_are_well_formed(tmp_path):
    module = _load("scripts/ember_restart_eval_audiobench_bound.py", "four_p1_audio_custody")
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    bound_run = _audio_run("bound")
    foreign_run = _audio_run("foreign")
    custody["closed_run_artifact_sha256"] = _sha_bytes(bound_run)
    custody_path = tmp_path / "custody.json"
    custody_path.write_text(json.dumps(custody, sort_keys=True), encoding="utf-8")
    run_path = tmp_path / "run.json"
    run_path.write_bytes(foreign_run)
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps(_audio_predictions(module, custody, "foreign"), sort_keys=True), encoding="utf-8")
    output = tmp_path / "score.json"
    completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "ember_restart_eval_audiobench_bound.py"), "--canonical-predictions", str(predictions_path), "--run-artifact", str(run_path), "--frozen-audiobench-manifest", str(custody_path), "--score-output", str(output)], capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert "closed run" in completed.stderr.lower() or "custody" in completed.stderr.lower()
    assert not output.exists()



def test_audiobench_non_admissible_receipt_preserves_frozen_benchmark_identity(tmp_path):
    module = _load("scripts/ember_restart_eval_audiobench_bound.py", "four_p1_audio_receipt")
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    run_bytes = _audio_run("bound")
    custody["closed_run_artifact_sha256"] = _sha_bytes(run_bytes)
    custody["scoring_adapter"]["sha256"] = _sha(Path(module.__file__))
    custody["protocol_sha256"] = module._protocol_sha256(custody)
    custody_path = tmp_path / "custody.json"
    custody_path.write_text(json.dumps(custody, sort_keys=True), encoding="utf-8")
    run_path = tmp_path / "run.json"
    run_path.write_bytes(run_bytes)
    predictions = _audio_predictions(module, custody, "bound")
    prediction_path = tmp_path / "predictions.json"
    prediction_path.write_text(json.dumps(predictions, sort_keys=True), encoding="utf-8")
    output = tmp_path / "score.json"
    completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "ember_restart_eval_audiobench_bound.py"), "--canonical-predictions", str(prediction_path), "--run-artifact", str(run_path), "--frozen-audiobench-manifest", str(custody_path), "--score-output", str(output)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["result"] == "PREFLIGHT_ONLY"
    assert payload["benchmark_id"] == "audiobench"
    assert payload["benchmark_version"] == custody["benchmark_version"]
    assert payload["split_sha256"] == predictions["benchmark"]["split_sha256"]
    assert payload["protocol_sha256"] == predictions["benchmark"]["protocol_sha256"]
    assert payload["checkpoint_manifest_sha256"] == predictions["checkpoint_manifest_sha256"]
    assert payload["model_config_sha256"] == predictions["model_config_sha256"]
def test_evalplus_spider_and_mmmu_reject_checkpoint_or_protocol_identity_drift():
    evalplus = _load("scripts/ember_restart_eval_evalplus_result.py", "four_p1_evalplus")
    manifest = json.loads((ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json").read_text(encoding="utf-8"))
    manifest["checkpoint_manifest_sha256"] = "a" * 64
    manifest["model_config_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="checkpoint/config"):
        evalplus.evalplus_protocol_sha256({key: value for key, value in manifest.items() if key not in {"checkpoint_manifest_sha256", "model_config_sha256"}}, "humanevalplus_v0.1.10", manifest["scoring_adapters"])

    spider = _load("scripts/ember_restart_eval_spider.py", "four_p1_spider")
    with pytest.raises(ValueError, match="checkpoint_manifest_sha256"):
        spider.require_canonical_identity({"schema_version": "ember-restart-benchmark-custody-v1", "protocol_sha256": "a" * 64})

    mmmu = _load("scripts/ember_restart_eval_mmmu.py", "four_p1_mmmu")
    with pytest.raises(ValueError, match="checkpoint"):
        mmmu.validate_manifest_identity({"schema_version": "ember-restart-benchmark-custody-v1", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64}, {"checkpoint_manifest_sha256": "9" * 64, "model_config_sha256": "b" * 64})
