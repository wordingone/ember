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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir(parents=True)
    model_config = tmp_path / "model-config.json"
    tokenizer = tmp_path / "tokenizer.json"
    server = tmp_path / "serve_owned.py"
    counter = tmp_path / "parameter_counter.py"
    receipt = tmp_path / "realization-receipt.json"
    registry = tmp_path / "trusted-verifiers.json"
    for path, content in (
        (model_config, b'{"architecture":"owned"}'),
        (tokenizer, b'{"tokenizer":"owned"}'),
        (server, b"# owned server\n"),
        (counter, b"# owned counter\n"),
    ):
        path.write_bytes(content)

    config_hash = _sha256(model_config)
    tokenizer_hash = _sha256(tokenizer)
    counter_hash = _sha256(counter)
    checkpoint_manifest = checkpoint_dir / "checkpoint-manifest.json"
    _write_json(
        checkpoint_manifest,
        {
            "schema_version": "ember-sparse-checkpoint-v3",
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
    manifest = tmp_path / "development.json"
    _write_json(
        manifest,
        {
            "schema_version": "ember-owned-development-seat-v1",
            "seat": "OWNED_DEVELOPMENT",
            "claim_status": "NON_ADMISSIBLE",
            "endpoint_url": "http://127.0.0.1:8083",
            "checkpoint": {"manifest_path": str(checkpoint_manifest), "sha256": checkpoint_hash},
            "model_config": {"path": str(model_config), "sha256": config_hash},
            "tokenizer": {"path": str(tokenizer), "sha256": tokenizer_hash},
            "server": {"path": str(server), "sha256": _sha256(server)},
            "parameter_evidence": {
                "counter_path": str(counter),
                "counter_sha256": counter_hash,
                "receipt_path": str(receipt),
                "receipt_sha256": receipt_hash,
                "registry_path": str(registry),
                "registry_sha256": _sha256(registry),
                "allocated_parameters": 3_839_161_856,
                "active_parameters": 1_020_589_568,
            },
            "training": {"tokens_seen": 2048},
        },
    )
    return manifest


def _resolve(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RESOLVER), str(manifest)],
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
    assert payload["launch"]["mode"] == "INTERACTIVE"


def test_development_resolver_rejects_tamper_claim_upgrade_and_count_drift(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    source = json.loads(manifest.read_text(encoding="utf-8"))
    Path(source["tokenizer"]["path"]).write_text("tampered", encoding="utf-8")
    result = _resolve(manifest)
