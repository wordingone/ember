# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""No-replace candidate publication coverage."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
PRODUCER = REPO_ROOT / "scripts" / "ember_admission" / "produce_candidate.py"
REQUIRED_ROLES = (
    "artifact_bundle",
    "checkpoint",
    "identity_trusted_verifier_registry",
    "identity_manifest",
    "receipt_bundle",
    "restart_model_config",
    "restart_run_manifest",
    "restart_trusted_verifier_registry",
    "restart_trusted_verifier_registry_approval",
    "tensor_hashes",
    "tensor_manifest",
)


def test_preexisting_candidate_is_never_overwritten(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output_root = tmp_path / "candidates"
    existing = output_root / "candidate-one"
    workspace.mkdir()
    existing.mkdir(parents=True)
    sentinel = existing / "sentinel"
    sentinel.write_bytes(b"preserve")
    roles = []
    for role in REQUIRED_ROLES:
        source = workspace / f"{role}.json"
        content = json.dumps({"role": role}).encode()
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
    assert json.loads(result.stdout) == {"code": "candidate.exists", "ok": False}
    assert sentinel.read_bytes() == b"preserve"
