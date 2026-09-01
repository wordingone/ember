# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = REPO_ROOT / "scripts" / "ember_admission" / "produce_candidate.py"
REQUIRED_ROLES = (
    "artifact_bundle",
    "checkpoint",
    "identity_trusted_verifier_registry",
    "identity_manifest",
    "receipt_bundle",
    "restart_model_config",
    "restart_run_manifest",
    "tensor_hashes",
    "tensor_manifest",
    "restart_trusted_verifier_registry",
    "restart_trusted_verifier_registry_approval",
)


def test_wrong_source_hash_refuses_before_candidate_publication(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    output_root = tmp_path / "candidates"
    workspace.mkdir()
    source = workspace / "source.json"
    source.write_bytes(b"{}")
    digest = hashlib.sha256(b"{}").hexdigest()
    roles = [
        {"role": role, "path": "source.json", "sha256": digest}
        for role in REQUIRED_ROLES
    ]
    roles[0]["sha256"] = "0" * 64
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
        "code": "source.hash",
        "ok": False,
    }
    assert not output_root.exists()
