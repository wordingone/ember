# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from test_contract import REPO_ROOT


RESOLVER = REPO_ROOT / "scripts" / "ember_restart" / "development_cli_seat.py"
RUNTIME_FILES = {
    "configs/ember-restart-3b.json",
    "parameter-evidence/parameter_counter.py",
    "parameter-evidence/step2-realization-receipt.json",
    "parameter-evidence/trusted-verifiers.json",
    "scripts/ember_restart/development_cli_seat.py",
    "src/ember/governance/scripts/ember_restart/prediction_contract.py",
    "scripts/ember_restart_eval_checkpoint_consumer.py",
    "scripts/ember_restart_eval_raw_forward.py",
    "domains/model/tokenizer/tokenizer.json",
    "tools/ember-restart-3b/batch.py",
    "tools/ember-restart-3b/checkpoint_artifacts.py",
    "tools/ember-restart-3b/infer.py",
    "tools/ember-restart-3b/model.py",
    "tools/ember-restart-3b/parameter_counter.py",
    "tools/ember-restart-3b/serve_owned_openai.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _fixture(
    tmp_path: Path, *, checkpoint_schema_version: object = "ember-sparse-checkpoint-v3"
) -> Path:
    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir(parents=True)
    model_config = tmp_path / "configs" / "ember-restart-3b.json"
    tokenizer = tmp_path / "domains" / "model" / "tokenizer" / "tokenizer.json"
    server = tmp_path / "tools" / "ember-restart-3b" / "serve_owned_openai.py"
    counter = tmp_path / "parameter-evidence" / "parameter_counter.py"
    receipt = tmp_path / "parameter-evidence" / "step2-realization-receipt.json"
    registry = tmp_path / "parameter-evidence" / "trusted-verifiers.json"
    for path, content in (
        (model_config, b'{"architecture":"owned"}'),
        (tokenizer, b'{"tokenizer":"owned"}'),
        (server, b"# owned server\n"),
        (counter, b"# owned counter\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    generated = {
        "configs/ember-restart-3b.json",
        "domains/model/tokenizer/tokenizer.json",
        "tools/ember-restart-3b/serve_owned_openai.py",
        "parameter-evidence/parameter_counter.py",
        "parameter-evidence/step2-realization-receipt.json",
        "parameter-evidence/trusted-verifiers.json",
    }
    for relative in sorted(RUNTIME_FILES - generated):
        runtime_file = tmp_path / relative
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text(f"# fixture {relative}\n", encoding="utf-8")

    config_hash = _sha256(model_config)
    tokenizer_hash = _sha256(tokenizer)
    counter_hash = _sha256(counter)
    checkpoint_manifest = checkpoint_dir / "checkpoint-manifest.json"
    _write_json(
        checkpoint_manifest,
        {
            "schema_version": checkpoint_schema_version,
            "architecture_revision": "ember-sparse-3b-v2",
            "model_config_sha256": config_hash,
            "architecture": {
                "allocated_parameters": 3_839_161_856,
                "active_parameters": 1_020_589_568,
            },
            "data_cursor": {
                "tokens_seen": 2048,
                "tokenizer_sha256": tokenizer_hash,
            },
        },
    )
    checkpoint_hash = _sha256(checkpoint_manifest)
    _write_json(
        receipt,
        {
            "schema_version": "ember-sparse-realization-receipt-v1",
            "result": "MEASURED",
            "verification_boundary": "VERIFIED_MEASURED",
            "subject_checkpoint_sha256": checkpoint_hash,
            "model_config_sha256": config_hash,
            "counter_sha256": counter_hash,
            "allocated_parameters": 3_839_161_856,
            "active_parameters": 1_020_589_568,
        },
    )
    receipt_hash = _sha256(receipt)
    _write_json(
        registry,
        {
            "schema_version": "ember-trusted-verifiers-v1",
            "verifiers": [{"path": counter.name, "sha256": counter_hash, "criterion_ids": ["ember-sparse-step2-realization-v1"], "evidence_classes": ["parameter_realization"]}],
            "realization_receipts": [
                {
                    "path": receipt.name,
                    "sha256": receipt_hash,
                    "subject_checkpoint_sha256": checkpoint_hash,
                    "model_config_sha256": config_hash,
                    "counter_sha256": counter_hash,
                    "active_expert": "shared",
                }
            ],
        },
    )
    runtime_index = tmp_path / "runtime-bundle-index.json"
    _write_json(
        runtime_index,
        {
            "schema_version": "ember-owned-runtime-bundle-v1",
            "source_commit": "a" * 40,
            "files": {
                relative: {
                    "sha256": _sha256(tmp_path / relative),
                    "bytes": (tmp_path / relative).stat().st_size,
                }
                for relative in sorted(RUNTIME_FILES)
            },
        },
    )
    manifest = tmp_path / "development.json"
    _write_json(
        manifest,
        {
            "schema_version": "ember-owned-development-seat-v1",
            "seat": "OWNED_DEVELOPMENT",
            "claim_status": "NON_ADMISSIBLE",
            "endpoint_url": "http://127.0.0.1:8083",
            "checkpoint": {"manifest_path": "checkpoint/checkpoint-manifest.json", "sha256": checkpoint_hash},
            "model_config": {"path": "configs/ember-restart-3b.json", "sha256": config_hash},
            "tokenizer": {"path": "domains/model/tokenizer/tokenizer.json", "sha256": tokenizer_hash},
            "server": {"path": "tools/ember-restart-3b/serve_owned_openai.py", "sha256": _sha256(server)},
            "runtime_bundle": {"index_path": runtime_index.name, "sha256": _sha256(runtime_index)},
            "parameter_evidence": {
                "counter_path": "parameter-evidence/parameter_counter.py",
                "counter_sha256": counter_hash,
                "receipt_path": "parameter-evidence/step2-realization-receipt.json",
                "receipt_sha256": receipt_hash,
                "registry_path": "parameter-evidence/trusted-verifiers.json",
                "registry_sha256": _sha256(registry),
                "allocated_parameters": 3_839_161_856,
                "active_parameters": 1_020_589_568,
            },
            "training": {"tokens_seen": 2048},
        },
    )
    return manifest


def _resolve(manifest: Path) -> subprocess.CompletedProcess[str]:
    source = json.loads(manifest.read_text(encoding="utf-8"))
    runtime_index = manifest.parent / source["runtime_bundle"]["index_path"]
    return subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            str(manifest),
            "--expected-manifest-sha256",
            _sha256(manifest),
            "--expected-runtime-index-sha256",
            _sha256(runtime_index),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_development_resolver_binds_exact_non_claiming_checkpoint(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    result = _resolve(manifest)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    source = json.loads(manifest.read_text(encoding="utf-8"))
    checkpoint = source["checkpoint"]["sha256"]
    assert payload["valid"] is True
    assert payload["seat"] == "OWNED_DEVELOPMENT"
    assert payload["claim_status"] == "NON_ADMISSIBLE"
    assert payload["tokens_seen"] == 2048
    assert payload["checkpoint_sha256"] == checkpoint
    assert payload["model_name"] == f"ember-owned-development:{checkpoint[:12]}"
    assert payload["launch"]["development_manifest_path"] == str(manifest.resolve())
    assert payload["launch"]["model_config_path"] == str(
        (manifest.parent / source["model_config"]["path"]).resolve()
    )
    assert payload["launch"]["mode"] == "INTERACTIVE"


def test_development_resolver_accepts_bound_warm_checkpoint_v5(tmp_path: Path) -> None:
    manifest = _fixture(
        tmp_path, checkpoint_schema_version="ember-sparse-checkpoint-v5"
    )
    result = _resolve(manifest)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["claim_status"] == "NON_ADMISSIBLE"
    assert payload["tokens_seen"] == 2048


def test_development_resolver_rejects_unapproved_checkpoint_schemas(
    tmp_path: Path,
) -> None:
    for name, schema_version in (
        ("v4", "ember-sparse-checkpoint-v4"),
        ("v6", "ember-sparse-checkpoint-v6"),
        ("malformed", {"name": "ember-sparse-checkpoint-v5"}),
    ):
        manifest = _fixture(
            tmp_path / name, checkpoint_schema_version=schema_version
        )
        result = _resolve(manifest)
        assert result.returncode == 1
        assert "checkpoint schema_version is not supported" in result.stdout


def test_development_resolver_rejects_tamper_claim_upgrade_and_count_drift(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    source = json.loads(manifest.read_text(encoding="utf-8"))
    tokenizer_path = manifest.parent / source["tokenizer"]["path"]
    tokenizer_bytes = tokenizer_path.read_bytes()
    tokenizer_path.write_bytes(bytes([tokenizer_bytes[0] ^ 1]) + tokenizer_bytes[1:])
    result = _resolve(manifest)
    assert result.returncode == 1
    assert "content hash mismatch" in result.stdout

    manifest = _fixture(tmp_path / "claim")
    source = json.loads(manifest.read_text(encoding="utf-8"))
    source["claim_status"] = "VERIFIED"
    _write_json(manifest, source)
    result = _resolve(manifest)
    assert result.returncode == 1
    assert "claim_status must be NON_ADMISSIBLE" in result.stdout

    manifest = _fixture(tmp_path / "count")
    source = json.loads(manifest.read_text(encoding="utf-8"))
    source["parameter_evidence"]["allocated_parameters"] += 1
    _write_json(manifest, source)
    result = _resolve(manifest)
    assert result.returncode == 1
    assert "allocated_parameters does not match checkpoint manifest" in result.stdout


def test_development_resolver_rejects_drift_in_imported_runtime_source(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    imported = tmp_path / "tools" / "ember-restart-3b" / "infer.py"
    imported_bytes = imported.read_bytes()
    imported.write_bytes(bytes([imported_bytes[0] ^ 1]) + imported_bytes[1:])
    result = _resolve(manifest)
    assert result.returncode == 1
    assert "runtime file tools/ember-restart-3b/infer.py" in result.stdout
    assert "content hash mismatch" in result.stdout
