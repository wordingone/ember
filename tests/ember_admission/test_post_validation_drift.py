# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Post-consumer byte drift must invalidate a candidate."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

from source_snapshot import (  # noqa: E402
    snapshot_sources,
    SourceSnapshot,
    verify_published_snapshots,
    verify_source_snapshots,
)


def test_source_drift_after_snapshot_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "checkpoint.bin"
    source.write_bytes(b"original")
    snapshot = SourceSnapshot(
        role="checkpoint",
        relative_path="checkpoint.bin",
        sha256=hashlib.sha256(b"original").hexdigest(),
        content=b"original",
    )

    source.write_bytes(b"changed")

    assert not verify_source_snapshots(workspace, {"checkpoint": snapshot})




def test_source_swap_then_restore_is_still_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "checkpoint.bin"
    original = b"original"
    source.write_bytes(original)
    snapshots = snapshot_sources(
        workspace,
        {
            "roles": [
                {
                    "role": "checkpoint",
                    "path": source.name,
                    "sha256": hashlib.sha256(original).hexdigest(),
                }
            ]
        },
    )

    time.sleep(0.02)
    source.write_bytes(b"changed!")
    source.write_bytes(original)

    assert not verify_source_snapshots(workspace, snapshots)

def test_published_output_drift_is_rejected(tmp_path: Path) -> None:
    published = tmp_path / "candidate" / "checkpoint.bin"
    published.parent.mkdir()
    published.write_bytes(b"original")
    snapshot = SourceSnapshot(
        role="checkpoint",
        relative_path="checkpoint.bin",
        sha256=hashlib.sha256(b"original").hexdigest(),
        content=b"original",
    )
    paths = {"checkpoint": published}

    assert verify_published_snapshots(paths, {"checkpoint": snapshot})
    published.write_bytes(b"changed")
    assert not verify_published_snapshots(paths, {"checkpoint": snapshot})
