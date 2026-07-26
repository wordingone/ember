# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The closed descriptor itself is workspace-bound."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = REPO_ROOT / "scripts" / "ember_admission" / "produce_candidate.py"
ROLES = (
    "artifact_bundle",
    "checkpoint",
    "identity_manifest",
    "identity_trusted_verifier_registry",
    "receipt_bundle",
    "restart_model_config",
    "restart_run_manifest",
    "restart_trusted_verifier_registry",
    "tensor_hashes",
    "tensor_manifest",
)


def test_descriptor_outside_workspace_is_rejected_before_snapshot(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    rows = []
    for role in ROLES:
        source = workspace / f"{role}.json"
        source.write_bytes(b"{}")
        rows.append(
            {
                "role": role,
                "path": source.name,
                "sha256": hashlib.sha256(b"{}").hexdigest(),
            }
        )
    descriptor = tmp_path / "outside.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": "ember-owned-admission-input-v1",
                "candidate_id": "candidate-one",
                "roles": rows,
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
            str(tmp_path / "candidates"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout) == {"code": "descriptor.location", "ok": False}
