# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
from pathlib import Path

from test_contract import REPO_ROOT, VALIDATOR, _candidate_manifest, _write_json


def _run(manifest: Path, *, with_registry: bool = True) -> tuple[int, dict]:
    command = [sys.executable, str(VALIDATOR), "validate", str(manifest)]
    if with_registry:
        command.extend(
            ["--trusted-verifier-registry", str(manifest.parent / "trusted-verifiers.json")]
        )
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def test_candidate_rejects_borrowed_weight_lineage(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["lineage"]["borrowed_weights"] = True
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert "lineage.borrowed_weights: must be false" in result["errors"]


def test_candidate_rejects_zero_audio_exposure(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["training"]["modality_tokens"]["audio"] = 0
    _write_json(path, payload)
    code, result = _run(path)
    assert code == 1
    assert "training.modality_tokens.audio: must be positive" in result["errors"]


def test_candidate_rejects_checkpoint_shard_tampering(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    shard = tmp_path / "checkpoint" / "model-00001.safetensors"
    shard.write_bytes(b"tampered")
    code, result = _run(path)
    assert code == 1
    assert "checkpoint.shards[0].sha256: content hash mismatch" in result["errors"]


def test_owned_admission_rejects_self_attestation_without_external_registry(tmp_path: Path):
    path = _candidate_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "OWNED_ADMITTED"
    _write_json(path, payload)
    code, result = _run(path, with_registry=False)
    assert code == 1
    assert "trusted_verifier_registry: required for checkpoint claims" in result["errors"]
