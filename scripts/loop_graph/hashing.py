# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared content-hashing: the "sha256:<hex>" convention used across the
execution graph (command/inputs/outputs) and provenance receipts."""

from __future__ import annotations

import hashlib
from pathlib import Path


def hash_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def hash_file(path: Path) -> str:
    return hash_bytes(Path(path).read_bytes())
