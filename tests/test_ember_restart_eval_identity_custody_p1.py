# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused regressions for identity and custody invariants."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_result_surface_requires_the_external_registry_anchor(monkeypatch, tmp_path):
    module = _load("scripts/ember_restart_eval_result_surface.py", "p1_result_surface")
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"result":"MEASURED","capability":"text"}'
    receipt.write_bytes(receipt_bytes)
    manifest = tmp_path / "admission.json"
    manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": receipt.name}]}), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": "ember-trusted-verifiers-v1", "verifiers": []}), encoding="utf-8")
    registry_root = tmp_path / "registry-snapshot"
    registry_root.mkdir()
    snapshot = registry_root / "registry.json"
    snapshot.write_bytes(registry.read_bytes())
    monkeypatch.setattr(module, "_pinned_registry_snapshot", lambda _path: (snapshot, registry_root))
    monkeypatch.setattr(module, "_registry_is_pinned", lambda _path: False)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    assert not module._admitted(manifest, registry, receipt_bytes)


def test_claim_renderer_keeps_a_canonical_identity_receipt_body(monkeypatch, tmp_path):
    module = _load("scripts/ember_restart_eval_result_surface.py", "p1_result_identity")
    monkeypatch.setattr(module, "_admitted", lambda *args: True)
    source = tmp_path / "receipt.json"
    output = tmp_path / "surface.md"
    source.write_text(json.dumps({
        "result": "MEASURED", "capability": "text",
        "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64,
        "benchmark_id": "local-text", "benchmark_version": "1", "split_sha256": "c" * 64,
        "harness_sha256": "d" * 64, "protocol_sha256": "e" * 64,
        "predictions_sha256": "f" * 64, "score_artifact_sha256": "1" * 64,
        "criterion_id": "ember-3b-text-capability-v1", "criterion_result": "PASSED",
        "metrics": {"accuracy": 1.0}, "verifier_sha256": "2" * 64,
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(module.__file__), "--input", str(source), "--output", str(output)])
    module.main()
    rendered = output.read_text(encoding="utf-8")
    assert "receipt_json:" in rendered
    assert "checkpoint_manifest_sha256" in rendered
    assert "protocol_sha256" in rendered


def test_audiobench_rejects_a_closed_run_not_hash_bound_by_custody(tmp_path):
    scorer = ROOT / "scripts" / "ember_restart_eval_audiobench_bound.py"
    public_custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    text = "hello"
    row = {"mixture_name": "m", "weight": 1.0, "recall": 0.5, "fpr": 0.1, "transcript_sha256": hashlib.sha256(text.encode()).hexdigest()}
    identity = {"suite": "ab/sound-id", "per_mixture": [row]}
    run = tmp_path / "run.json"
    run.write_text(json.dumps({**identity, "run_hash": hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "headline": {"weighted_recall": 0.5, "weighted_fpr": 0.1}}), encoding="utf-8")
    custody = tmp_path / "custody.json"
    public_custody["closed_run_artifact_sha256"] = "0" * 64
    custody.write_text(json.dumps(public_custody), encoding="utf-8")
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({
        "schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64,
        "benchmark": {"id": "audiobench", "version": public_custody["benchmark_version"], "capability": "audio", "split_sha256": "e" * 64, "protocol_sha256": public_custody["protocol_sha256"]},
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [1]},
        "rows": [{"id": "m", "input_sha256": "f" * 64, "generated_token_ids": [1], "stop_reason": "eos", "output": {"kind": "transcript", "text": text}}],
    }), encoding="utf-8")
    score = tmp_path / "score.json"
    completed = subprocess.run([sys.executable, str(scorer), "--canonical-predictions", str(predictions), "--run-artifact", str(run), "--frozen-audiobench-manifest", str(custody), "--score-output", str(score)], text=True, capture_output=True, check=False)
    assert completed.returncode != 0
    assert "closed run" in completed.stderr.lower() or "custody" in completed.stderr.lower()
    assert not score.exists()


def test_evalplus_rejects_checkpoint_identity_drift_when_frozen_custody_declares_it(tmp_path):
    module = _load("scripts/ember_restart_eval_evalplus_result.py", "p1_evalplus_identity")
    source_manifest = json.loads((ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json").read_text(encoding="utf-8"))
    source_manifest["checkpoint_manifest_sha256"] = "a" * 64
    source_manifest["model_config_sha256"] = "b" * 64
    repo = tmp_path / "repo"
    (repo / "manifests").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    for entry in source_manifest["scoring_adapters"]:
        source = ROOT / entry["path"]
        destination = repo / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        entry["sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    # Recompute the custody protocol after copying the exact adapter bytes.
    source_manifest["protocol_sha256"] = module.evalplus_protocol_sha256(source_manifest, "humanevalplus_v0.1.10", source_manifest["scoring_adapters"])
    manifest = repo / "manifests" / "custody.json"
    manifest.write_text(json.dumps(source_manifest), encoding="utf-8")
    binding = {"checkpoint_manifest_sha256": "c" * 64, "model_config_sha256": "b" * 64, "benchmark_id": "evalplus", "benchmark_version": "v0.1.10", "protocol_sha256": source_manifest["protocol_sha256"], "suite": "humanevalplus_v0.1.10", "task_asset_sha256": source_manifest["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"], "frozen_code_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match="checkpoint"):
        module._load_frozen_code_manifest(manifest, binding, binding["suite"])


def test_spider_canonical_path_does_not_bypass_protocol_for_legacy_schema(tmp_path):
    module = _load("scripts/ember_restart_eval_spider.py", "p1_spider_identity")
    source = tmp_path / "spider"
    source.mkdir()
    evaluator = source / "evaluation.py"
    evaluator.write_text("# evaluator\n", encoding="utf-8")
    gold = tmp_path / "gold.sql"; gold.write_text("select 1\tdb\n", encoding="utf-8")
    tables = tmp_path / "tables.json"; tables.write_text("[]", encoding="utf-8")
    database = tmp_path / "database"; database.mkdir(); (database / "db.sqlite").write_bytes(b"db")
    manifest = tmp_path / "custody.json"
    manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "spider", "benchmark_version": module.SPIDER_VERSION, "gold_sha256": module.sha256_file(gold), "tables_sha256": module.sha256_file(tables), "database_tree_sha256": module.database_tree_sha256(database), "evaluator_sha256": module.sha256_file(evaluator), "source_tree_sha256": module.source_tree_sha256(source), "protocol_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema|protocol"):
        module.verify_frozen_custody(manifest, source, gold, tables, database, include_protocol=True)


def test_mmmu_rejects_checkpoint_identity_drift_when_frozen_manifest_declares_it(tmp_path):
    module = _load("scripts/ember_restart_eval_mmmu.py", "p1_mmmu_identity")
    manifest = {"schema_version": "ember-restart-benchmark-custody-v1", "benchmark_id": "MMMU", "benchmark_version": "v1", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "split": {"name": "validation", "answer_dictionary_sha256": "c" * 64}, "license_sha256": "d" * 64, "scorer": {"path": "score.py", "sha256": "e" * 64}, "upstream_tree_git_sha1": "f" * 40, "scoring_adapter": {"path": "scripts/ember_restart_eval_mmmu.py", "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}, "protocol_sha256": "f" * 64}
    root = tmp_path / "root"; root.mkdir(); (root / "score.py").write_text("", encoding="utf-8")
    manifest["scorer"]["sha256"] = hashlib.sha256((root / "score.py").read_bytes()).hexdigest()
    manifest["protocol_sha256"] = module.sha256(f"MMMU:v1:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc:{manifest['scorer']['sha256']}:{manifest['license_sha256']}:{manifest['upstream_tree_git_sha1']}:{manifest['scoring_adapter']['sha256']}:".encode())
    module.verify_frozen_scorer(manifest, root)
    with pytest.raises(ValueError, match="checkpoint"):
        module.validate_manifest_identity(manifest, {"checkpoint_manifest_sha256": "z" * 64, "model_config_sha256": "b" * 64})
