# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
PRODUCER = REPO_ROOT / "scripts" / "ember_admission" / "produce_candidate.py"


def test_single_ambiguous_registry_role_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output_root = tmp_path / "candidates"
    workspace.mkdir()
    role_names = (
        "artifact_bundle",
        "checkpoint",
        "identity_manifest",
        "receipt_bundle",
        "restart_model_config",
        "restart_run_manifest",
        "tensor_hashes",
        "tensor_manifest",
        "trusted_verifier_registry",
    )
    roles = []
    for index, role in enumerate(role_names):
        source = workspace / f"source-{index}.json"
        content = json.dumps({"role": role}).encode("utf-8")
        source.write_bytes(content)
        roles.append(
            {
                "role": role,
                "path": source.name,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    descriptor = workspace / "admission.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": "ember-owned-admission-input-v1",
                "candidate_id": "candidate-one",
                "roles": roles,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--workspace",
            str(workspace),
            "--descriptor",
            str(descriptor),
            "--output-root",
            str(output_root),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "code": "descriptor.roles",
        "ok": False,
    }
    assert not (output_root / "candidate-one").exists()
