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
            "criterion_ids": ["ember-sufficient-pretraining-v1"],
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
        receipt = tmp_path / "receipts" / f"eval-{capability}.json"
        receipt_hash = _write_json(
            receipt,
            {
                "capability": capability,
                "result": "MEASURED",
                "subject_checkpoint_sha256": checkpoint_sha256,
                "verifier_sha256": verifier_sha256,
            },
        )
        evaluations.append(
            {
                "capability": capability,
                "benchmark_id": f"owned-{capability}-v1",
                "receipt_path": str(receipt.relative_to(tmp_path)),
                "sha256": receipt_hash,
                "subject_checkpoint_sha256": checkpoint_sha256,
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
