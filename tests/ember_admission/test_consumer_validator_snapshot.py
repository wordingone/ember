# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Consumer validator identities must be frozen before execution."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

import consumers  # noqa: E402


def test_consumer_validator_snapshot_binds_bytes_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = tmp_path / "identity.py"
    restart = tmp_path / "restart.py"
    identity.write_bytes(b"identity-v1")
    restart.write_bytes(b"restart-v1")
    monkeypatch.setattr(consumers, "IDENTITY_VALIDATOR", identity)
    monkeypatch.setattr(consumers, "RESTART_SEAT_CONSUMER", restart)

    snapshots = consumers.snapshot_consumer_validators()

    assert snapshots["identity"].sha256 == hashlib.sha256(b"identity-v1").hexdigest()
    assert snapshots["restart"].sha256 == hashlib.sha256(b"restart-v1").hexdigest()
    assert consumers.verify_consumer_validators(snapshots)

    time.sleep(0.02)
    identity.write_bytes(b"identity-v2")
    identity.write_bytes(b"identity-v1")

    assert not consumers.verify_consumer_validators(snapshots)
