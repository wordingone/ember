# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
from pathlib import Path

from test_admission import test_owned_admission_binds_sufficient_pretraining_evals_and_cli
from test_contract import REPO_ROOT, _write_json


RESOLVER = REPO_ROOT / "scripts" / "ember_restart" / "cli_seat.py"


def _resolve(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            str(manifest),
            "--trusted-verifier-registry",
            str(manifest.parent / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_resolver_derives_owned_identity_from_admitted_bytes(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    result = _resolve(tmp_path / "run.json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    manifest = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    checkpoint_sha256 = manifest["checkpoint"]["sha256"]
    serving = json.loads(
        (tmp_path / manifest["cli"]["serving_manifest_path"]).read_text(encoding="utf-8")
    )
    assert payload == {
        "checkpoint_sha256": checkpoint_sha256,
        "endpoint_url": "http://127.0.0.1:8083",
        "errors": [],
        "identity_url": "http://127.0.0.1:8083/v1/models",
        "launch": {
            "checkpoint_dir": str((tmp_path / manifest["checkpoint"]["manifest_path"]).parent.resolve()),
            "mode": "INTERACTIVE",
            "model_config_path": str((tmp_path / manifest["architecture"]["model_config"]["path"]).resolve()),
            "run_manifest_path": str((tmp_path / "run.json").resolve()),
            "server_path": str((tmp_path / serving["server_implementation"]["path"]).resolve()),
            "tokenizer_path": str((tmp_path / manifest["tokenizer"]["path"]).resolve()),
            "trusted_verifier_registry_path": str((tmp_path / "trusted-verifiers.json").resolve()),
        },
        "model_config_sha256": manifest["architecture"]["model_config"]["sha256"],
        "model_format": "safetensors",
        "model_name": f"ember-owned:{checkpoint_sha256[:12]}",
        "run_id": manifest["run_id"],
        "seat": "OWNED_ADMITTED",
        "server_source_sha256": serving["server_implementation"]["sha256"],
        "tokenizer_sha256": manifest["tokenizer"]["sha256"],
        "valid": True,
    }


def test_resolver_rejects_candidate_and_tampered_serving_bytes(tmp_path: Path):
    test_owned_admission_binds_sufficient_pretraining_evals_and_cli(tmp_path)
    manifest_path = tmp_path / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "CHECKPOINT_CANDIDATE"
    _write_json(manifest_path, manifest)
    candidate = _resolve(manifest_path)
    assert candidate.returncode != 0
    assert json.loads(candidate.stdout)["seat"] is None

    manifest["stage"] = "OWNED_ADMITTED"
    serving_path = tmp_path / manifest["cli"]["serving_manifest_path"]
    serving_path.write_text("{}", encoding="utf-8")
    _write_json(manifest_path, manifest)
    tampered = _resolve(manifest_path)
    assert tampered.returncode != 0
    assert "content hash mismatch" in tampered.stdout
