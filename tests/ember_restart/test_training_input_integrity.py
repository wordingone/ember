# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
from pathlib import Path

from test_contract import REPO_ROOT, VALIDATOR, _candidate_manifest, _write_json


def _run(path: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(path),
            "--trusted-verifier-registry",
            str(path.parent / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def test_candidate_rejects_tokenizer_without_owned_freeze_provenance(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tokenizer"].pop("kind")
    payload["tokenizer"].pop("freeze_receipt")
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert "tokenizer.kind: must equal OWNED_TRAINED" in result["errors"]
    assert "tokenizer.freeze_receipt.path: expected non-empty relative path" in result["errors"]


def test_candidate_rejects_boolean_only_training_data_attestation(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = payload["training_data"][0]
    data_manifest = tmp_path / entry["manifest_path"]
    entry["sha256"] = _write_json(
        data_manifest,
        {"capability": "text", "owned": True, "rows": 1},
    )
    entry.pop("verifier")
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert (
        "training_data[0] manifest.schema_version: "
        "must equal ember-owned-training-data-v1"
    ) in result["errors"]
    assert "training_data[0].verifier: expected object" in result["errors"]


def test_candidate_rejects_unbound_optimizer_declaration(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training"].pop("optimizer")
    payload["training"].pop("optimizer_receipt")
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert "training.optimizer: expected object" in result["errors"]
    assert "training.optimizer_receipt.path: expected non-empty relative path" in result["errors"]

def test_candidate_rejects_training_phase_that_exceeds_bound_data_class(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training"]["input_class"] = "SEMANTIC_PRETRAINING"
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert "training.input_class: does not match bound training data" in result["errors"]

def test_semantic_pretraining_requires_capability_specific_executed_checks(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training"]["input_class"] = "SEMANTIC_PRETRAINING"
    for entry in payload["training_data"]:
        data_path = tmp_path / entry["manifest_path"]
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["data_class"] = "SEMANTIC_PRETRAINING"
        entry["sha256"] = _write_json(data_path, data)
        receipt_path = tmp_path / entry["verification_receipt"]["path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["data_class"] = "SEMANTIC_PRETRAINING"
        receipt["data_manifest_sha256"] = entry["sha256"]
        entry["verification_receipt"]["sha256"] = _write_json(receipt_path, receipt)
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert (
        "training_data[0].verification_receipt.semantic_checks: binding mismatch"
    ) in result["errors"]

def test_candidate_rejects_training_record_byte_tampering(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    data_path = tmp_path / payload["training_data"][0]["manifest_path"]
    data = json.loads(data_path.read_text(encoding="utf-8"))
    records_path = tmp_path / data["records_artifact"]["path"]
    records_path.write_text('{"tampered":true}\n', encoding="utf-8")
    code, result = _run(path)
    assert code == 1
    assert (
        "training_data[0] manifest.records_artifact.sha256: content hash mismatch"
    ) in result["errors"]


def test_candidate_rejects_optimizer_runtime_contract_drift(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training"]["optimizer"]["implementation"] = "paged_8bit_adamw"
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert "training.optimizer: does not match model config" in result["errors"]
    assert "training.optimizer: does not match checkpoint manifest" in result["errors"]
    assert "training.optimizer_receipt.implementation: binding mismatch" in result["errors"]

def test_candidate_rejects_model_mediated_source_hidden_behind_clean_data_envelope(
    tmp_path: Path,
):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = payload["training_data"][0]
    data_path = tmp_path / entry["manifest_path"]
    data = json.loads(data_path.read_text(encoding="utf-8"))
    source_path = tmp_path / data["source_manifest"]["path"]
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["model_mediated"] = True
    source_hash = _write_json(source_path, source)
    data["source_manifest"]["sha256"] = source_hash
    entry["sha256"] = _write_json(data_path, data)
    receipt_path = tmp_path / entry["verification_receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_manifest_sha256"] = source_hash
    receipt["data_manifest_sha256"] = entry["sha256"]
    entry["verification_receipt"]["sha256"] = _write_json(receipt_path, receipt)
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert (
        "training_data[0] source_manifest.model_mediated: must be false"
    ) in result["errors"]

def test_candidate_rejects_tokenizer_without_independently_trusted_verifier(
    tmp_path: Path,
):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tokenizer"].pop("verifier", None)
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert "tokenizer.verifier: expected object" in result["errors"]
    assert "tokenizer.verifier: verifier is not independently trusted" in result["errors"]
