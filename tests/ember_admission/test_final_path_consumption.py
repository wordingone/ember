# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The real consumer boundary receives only final candidate paths."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

import produce_candidate  # noqa: E402


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


def test_consumers_receive_only_final_candidate_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    output_root = tmp_path / "candidates"
    destination = output_root / "candidate-one"
    workspace.mkdir()
    roles = []
    for role in REQUIRED_ROLES:
        relative = f"inputs/{role}.json"
        content = (json.dumps({"role": role}, sort_keys=True) + "\n").encode()
        source = workspace / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        roles.append(
            {
                "role": role,
                "path": relative,
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

    observed_roots: list[set[Path]] = []

    def accept(paths, _snapshot):
        observed_roots.append(
            {path.parents[1] for path in paths.values()}
        )
        return subprocess.CompletedProcess([], 0, "{}\n", "")

    monkeypatch.setattr(produce_candidate, "run_identity_consumer", accept)
    monkeypatch.setattr(produce_candidate, "run_restart_consumer", accept)
    monkeypatch.setattr(
        produce_candidate,
        "verify_consumer_validators",
        lambda _snapshots: True,
    )

    result = produce_candidate.main(
        [
            "--workspace",
            str(workspace),
            "--descriptor",
            str(descriptor),
            "--output-root",
            str(output_root),
        ]
    )

    assert result == 0
    assert observed_roots == [{destination}, {destination}]
