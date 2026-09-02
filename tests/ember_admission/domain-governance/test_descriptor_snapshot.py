# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The producer binds the exact descriptor bytes and file identity."""

from __future__ import annotations

import sys
import time
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

from source_snapshot import snapshot_descriptor, verify_descriptor_snapshot  # noqa: E402


def test_descriptor_swap_then_restore_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    descriptor = workspace / "admission.json"
    original = (
        '{"schema_version":"ember-owned-admission-input-v1",'
        '"candidate_id":"candidate-one","roles":[]}\n'
    ).encode("utf-8")
    descriptor.write_bytes(original)
    snapshot = snapshot_descriptor(workspace, descriptor)

    time.sleep(0.02)
    descriptor.write_bytes(b"{}\n")
    descriptor.write_bytes(original)

    assert snapshot.content == original
    assert not verify_descriptor_snapshot(workspace, snapshot)
