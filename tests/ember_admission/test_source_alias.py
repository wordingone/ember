# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Distinct paths to one mutable file identity are terminal."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ember_admission"))

from source_snapshot import snapshot_sources  # noqa: E402


def test_hardlinked_source_roles_are_rejected_as_aliases(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = workspace / "first.bin"
    second = workspace / "second.bin"
    content = b"shared mutable file"
    first.write_bytes(content)
    os.link(first, second)
    digest = hashlib.sha256(content).hexdigest()
    descriptor = {
        "roles": [
            {
                "role": "checkpoint",
                "path": first.name,
                "sha256": digest,
            },
            {
                "role": "tensor_hashes",
                "path": second.name,
                "sha256": digest,
            },
        ]
    }

    try:
        snapshot_sources(workspace, descriptor)
    except ValueError as exc:
        assert str(exc) == "source.alias"
    else:
        raise AssertionError("hardlinked role aliases were accepted")
