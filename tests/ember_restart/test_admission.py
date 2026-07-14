# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
from pathlib import Path

from test_contract import REPO_ROOT, VALIDATOR, _candidate_manifest, _sha256, _write_json


def test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path: Path):
    manifest_path = _candidate_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "OWNED_ADMITTED"
    checkpoint_sha256 = manifest["checkpoint"]["sha256"]

    verifier = tmp_path / "verifiers" / "local-verifier.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text(
        """import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


p = argparse.ArgumentParser()
p.add_argument("--capability", required=True)
p.add_argument("--checkpoint-manifest", required=True)
p.add_argument("--benchmark-id", required=True)
p.add_argument("--benchmark-version", required=True)
p.add_argument("--criterion-id", required=True)
p.add_argument("--split", required=True)
p.add_argument("--harness", required=True)
p.add_argument("--protocol", required=True)
p.add_argument("--predictions", required=True)
p.add_argument("--score-artifact", required=True)
a = p.parse_args()
score = json.loads(Path(a.score_artifact).read_text(encoding="utf-8"))
print(json.dumps({
    "capability": a.capability,
    "result": "MEASURED",
    "subject_checkpoint_sha256": sha256(a.checkpoint_manifest),
    "benchmark_id": a.benchmark_id,
    "benchmark_version": a.benchmark_version,
    "split_sha256": sha256(a.split),
    "harness_sha256": sha256(a.harness),
    "protocol_sha256": sha256(a.protocol),
    "predictions_sha256": sha256(a.predictions),
    "score_artifact_sha256": sha256(a.score_artifact),
    "sample_count": score["rows"],
    "metrics": {"accuracy": 1.0},
    "criterion_id": a.criterion_id,
    "criterion_result": "PASSED",
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    verifier_sha256 = _sha256(verifier)
    sufficient_verifier = tmp_path / "verifiers" / "local-sufficiency-verifier.py"
    sufficient_verifier.write_text(
        """import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


p = argparse.ArgumentParser()
p.add_argument("--checkpoint-manifest", required=True)
p.add_argument("--criterion-id", required=True)
p.add_argument("--training-ledger", required=True)
p.add_argument("--stopping-evaluation", required=True)
p.add_argument("--checkpoint-progression", required=True)
a = p.parse_args()
ledger = json.loads(Path(a.training_ledger).read_text(encoding="utf-8"))
stopping = json.loads(Path(a.stopping_evaluation).read_text(encoding="utf-8"))
print(json.dumps({
    "criterion_id": a.criterion_id,
    "result": "PASSED",
    "subject_checkpoint_sha256": sha256(a.checkpoint_manifest),
    "training_ledger_sha256": sha256(a.training_ledger),
    "stopping_evaluation_sha256": sha256(a.stopping_evaluation),
    "checkpoint_progression_sha256": sha256(a.checkpoint_progression),
    "tokens_seen": ledger["tokens_seen"],
    "gpu_hours": ledger["gpu_hours"],
    "final_loss": stopping["final_loss"],
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    sufficient_verifier_sha256 = _sha256(sufficient_verifier)
    registry = tmp_path / "trusted-verifiers.json"
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    registry_payload["verifiers"].append(
        {
            "path": str(verifier.relative_to(tmp_path)),
            "sha256": verifier_sha256,
            "evidence_classes": ["evaluation"],
            "criterion_ids": [
                "ember-3b-text-capability-v1",
                "ember-3b-image-capability-v1",
                "ember-3b-audio-capability-v1",
                "ember-3b-reasoning-capability-v1",
                "ember-3b-tool-capability-v1",
            ],
        }
    )
    registry_payload["verifiers"].append(
        {
            "path": str(sufficient_verifier.relative_to(tmp_path)),
            "sha256": sufficient_verifier_sha256,
            "evidence_classes": ["sufficient_pretraining"],
            "criterion_ids": ["ember-sufficient-pretraining-v1"],
        }
    )
    _write_json(registry, registry_payload)

    sufficient_evidence = {}
    sufficient_payloads = {
        "training_ledger": {"tokens_seen": 5, "gpu_hours": 0.01},
        "stopping_evaluation": {"final_loss": 1.0, "criterion": "plateau-and-heldout-v1"},
        "checkpoint_progression": {"checkpoints": 2, "monotonic_tokens": True},
    }
    sufficient_hashes = {}
    for evidence_name, evidence_payload in sufficient_payloads.items():
        artifact = tmp_path / "training-evidence" / f"{evidence_name}.json"
        artifact_hash = _write_json(artifact, evidence_payload)
        sufficient_evidence[evidence_name] = {
            "path": str(artifact.relative_to(tmp_path)),
            "sha256": artifact_hash,
        }
        sufficient_hashes[f"{evidence_name}_sha256"] = artifact_hash
    stopping_receipt = tmp_path / "receipts" / "sufficient-pretraining.json"
    stopping_hash = _write_json(
        stopping_receipt,
        {
            "criterion_id": "ember-sufficient-pretraining-v1",
            "result": "PASSED",
            "subject_checkpoint_sha256": checkpoint_sha256,
            "verifier_sha256": sufficient_verifier_sha256,
            **sufficient_hashes,
            "tokens_seen": 5,
            "gpu_hours": 0.01,
            "final_loss": 1.0,
        },
    )
    manifest["training"]["sufficient_pretraining"] = {
        "criterion_id": "ember-sufficient-pretraining-v1",
        "result": "PASSED",
        "receipt_path": str(stopping_receipt.relative_to(tmp_path)),
        "sha256": stopping_hash,
        "evidence": sufficient_evidence,
    }

    evaluations = []
    for capability in ("text", "image", "audio", "reasoning", "tool"):
        benchmark_id = f"owned-{capability}-v1"
        evidence = {}
        evidence_hashes = {}
        for evidence_name in ("split", "harness", "protocol", "predictions", "score_artifact"):
            artifact = tmp_path / "evaluation" / capability / f"{evidence_name}.json"
            artifact_hash = _write_json(
                artifact,
                {"capability": capability, "evidence": evidence_name, "rows": 1},
            )
            evidence[evidence_name] = {
                "path": str(artifact.relative_to(tmp_path)),
                "sha256": artifact_hash,
            }
            evidence_hashes[f"{evidence_name}_sha256"] = artifact_hash
        receipt = tmp_path / "receipts" / f"eval-{capability}.json"
        receipt_hash = _write_json(
            receipt,
            {
                "capability": capability,
                "result": "MEASURED",
                "subject_checkpoint_sha256": checkpoint_sha256,
                "verifier_sha256": verifier_sha256,
                "benchmark_id": benchmark_id,
                "benchmark_version": "frozen-v1",
                **evidence_hashes,
                "sample_count": 1,
                "metrics": {"accuracy": 1.0},
                "criterion_id": f"ember-3b-{capability}-capability-v1",
                "criterion_result": "PASSED",
            },
        )
        evaluations.append(
            {
                "capability": capability,
                "benchmark_id": benchmark_id,
                "receipt_path": str(receipt.relative_to(tmp_path)),
                "sha256": receipt_hash,
                "subject_checkpoint_sha256": checkpoint_sha256,
                "evidence": evidence,
            }
        )
    manifest["evaluations"] = evaluations

    serving_manifest = tmp_path / "serving" / "owned-seat.json"
    serving_hash = _write_json(
        serving_manifest,
        {
            "seat": "OWNED_ADMITTED",
            "checkpoint_sha256": checkpoint_sha256,
            "model_format": "safetensors",
            "endpoint_url": "http://127.0.0.1:8083",
            "protocol": "openai-chat-v1",
            "identity_path": "/v1/models",
        },
    )
    manifest["cli"] = {
        "seat": "OWNED_ADMITTED",
        "serving_manifest_path": str(serving_manifest.relative_to(tmp_path)),
        "sha256": serving_hash,
        "checkpoint_sha256": checkpoint_sha256,
    }
    _write_json(manifest_path, manifest)

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest_path),
            "--trusted-verifier-registry",
            str(registry),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"errors": [], "stage": "OWNED_ADMITTED", "valid": True}

def test_admission_rejects_remote_or_unbound_serving_endpoint(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    serving_path = tmp_path / manifest["cli"]["serving_manifest_path"]
    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    serving["endpoint_url"] = "https://borrowed.example/v1"
    manifest["cli"]["sha256"] = _write_json(serving_path, serving)
    _write_json(manifest_path, manifest)

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest_path),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "cli serving manifest: endpoint_url must be loopback HTTP" in result.stdout

def test_admission_rejects_measurement_envelope_without_executed_evidence(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluation = manifest["evaluations"][0]
    receipt_path = tmp_path / evaluation["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for field in (
        "benchmark_version",
        "split_sha256",
        "harness_sha256",
        "protocol_sha256",
        "predictions_sha256",
        "score_artifact_sha256",
        "sample_count",
        "metrics",
        "criterion_id",
        "criterion_result",
    ):
        receipt.pop(field, None)
    evaluation["sha256"] = _write_json(receipt_path, receipt)
    _write_json(manifest_path, manifest)
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest_path),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert any(
        "executed evidence" in error
        for error in json.loads(result.stdout)["errors"]
    )

def _rerun_admission(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(tmp_path / "run.json"),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_admission_rejects_failed_capability_criterion(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluation = manifest["evaluations"][0]
    receipt_path = tmp_path / evaluation["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["criterion_result"] = "FAILED"
    evaluation["sha256"] = _write_json(receipt_path, receipt)
    _write_json(manifest_path, manifest)
    result = _rerun_admission(tmp_path)
    assert result.returncode == 1
    assert any(
        "capability criterion must be PASSED" in error
        for error in json.loads(result.stdout)["errors"]
    )


def test_admission_rejects_tampered_score_artifact(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    score_ref = manifest["evaluations"][0]["evidence"]["score_artifact"]
    (tmp_path / score_ref["path"]).write_text("tampered score\n", encoding="utf-8")
    result = _rerun_admission(tmp_path)
    assert result.returncode == 1
    assert any(
        "evidence.score_artifact.sha256: content hash mismatch" in error
        for error in json.loads(result.stdout)["errors"]
    )

def test_trusted_evaluation_verifier_must_execute_successfully(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry_path = tmp_path / "trusted-verifiers.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    verifier_entry = next(
        entry for entry in registry["verifiers"] if "evaluation" in entry["evidence_classes"]
    )
    verifier_path = tmp_path / verifier_entry["path"]
    verifier_path.write_text("raise SystemExit(9)\n", encoding="utf-8")
    verifier_sha256 = _sha256(verifier_path)
    verifier_entry["sha256"] = verifier_sha256
    _write_json(registry_path, registry)
    for evaluation in manifest["evaluations"]:
        receipt_path = tmp_path / evaluation["receipt_path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["verifier_sha256"] = verifier_sha256
        evaluation["sha256"] = _write_json(receipt_path, receipt)
    _write_json(manifest_path, manifest)
    result = _rerun_admission(tmp_path)
    assert result.returncode == 1
    assert any(
        "verifier execution" in error
        for error in json.loads(result.stdout)["errors"]
    )

def test_trusted_sufficiency_verifier_must_execute_successfully(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry_path = tmp_path / "trusted-verifiers.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    verifier_entry = next(
        entry
        for entry in registry["verifiers"]
        if "sufficient_pretraining" in entry["evidence_classes"]
    )
    verifier_path = tmp_path / verifier_entry["path"]
    verifier_path.write_text("raise SystemExit(9)\n", encoding="utf-8")
    verifier_sha256 = _sha256(verifier_path)
    verifier_entry["sha256"] = verifier_sha256
    _write_json(registry_path, registry)
    sufficient_ref = manifest["training"]["sufficient_pretraining"]
    sufficient_path = tmp_path / sufficient_ref["receipt_path"]
    sufficient = json.loads(sufficient_path.read_text(encoding="utf-8"))
    sufficient["verifier_sha256"] = verifier_sha256
    sufficient_ref["sha256"] = _write_json(sufficient_path, sufficient)
    _write_json(manifest_path, manifest)
    result = _rerun_admission(tmp_path)
    assert result.returncode == 1
    assert any(
        "sufficiency verifier execution" in error
        for error in json.loads(result.stdout)["errors"]
    )
