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
    verifier.write_text("# deterministic local verifier\n", encoding="utf-8")
    verifier_sha256 = _sha256(verifier)
    registry = tmp_path / "trusted-verifiers.json"
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    registry_payload["verifiers"].append(
        {
            "path": str(verifier.relative_to(tmp_path)),
            "sha256": verifier_sha256,
            "evidence_classes": ["sufficient_pretraining", "evaluation"],
            "criterion_ids": [
                "ember-sufficient-pretraining-v1",
                "ember-3b-text-capability-v1",
                "ember-3b-image-capability-v1",
                "ember-3b-audio-capability-v1",
                "ember-3b-reasoning-capability-v1",
                "ember-3b-tool-capability-v1",
            ],
        }
    )
    _write_json(registry, registry_payload)

    stopping_receipt = tmp_path / "receipts" / "sufficient-pretraining.json"
    stopping_hash = _write_json(
        stopping_receipt,
        {
            "criterion_id": "ember-sufficient-pretraining-v1",
            "result": "PASSED",
            "subject_checkpoint_sha256": checkpoint_sha256,
            "verifier_sha256": verifier_sha256,
        },
    )
    manifest["training"]["sufficient_pretraining"] = {
        "criterion_id": "ember-sufficient-pretraining-v1",
        "result": "PASSED",
        "receipt_path": str(stopping_receipt.relative_to(tmp_path)),
        "sha256": stopping_hash,
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
