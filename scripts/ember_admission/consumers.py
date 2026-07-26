# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Invoke the existing admission consumers on exact published disk bytes."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTITY_VALIDATOR = (
    REPO_ROOT / "scripts" / "ember_01_identity" / "validate_identity.py"
)
RESTART_SEAT_CONSUMER = REPO_ROOT / "scripts" / "ember_restart" / "cli_seat.py"

CONSUMER_COMMAND_CONTRACTS = {
    "identity": (
        "python",
        "scripts/ember_01_identity/validate_identity.py",
        "role:identity_manifest",
        "--checkpoint",
        "role:checkpoint",
        "--tensor-hashes",
        "role:tensor_hashes",
        "--tensor-manifest",
        "role:tensor_manifest",
        "--artifact-bundle",
        "role:artifact_bundle",
        "--receipt-bundle",
        "role:receipt_bundle",
        "--trusted-verifier-registry",
        "role:identity_trusted_verifier_registry",
        "--require-resolved",
    ),
    "restart": (
        "python",
        "scripts/ember_restart/cli_seat.py",
        "role:restart_run_manifest",
        "--trusted-verifier-registry",
        "role:restart_trusted_verifier_registry",
    ),
}


@dataclass(frozen=True)
class ConsumerValidatorSnapshot:
    sha256: str
    content: bytes
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _snapshot_validator(path: Path) -> ConsumerValidatorSnapshot:
    try:
        before = path.stat(follow_symlinks=False)
        content = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError("consumer.validator_unavailable") from exc
    if (
        not path.is_file()
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
        or before.st_size != len(content)
    ):
        raise ValueError("consumer.validator_drift")
    return ConsumerValidatorSnapshot(
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        device=before.st_dev,
        inode=before.st_ino,
        size=before.st_size,
        mtime_ns=before.st_mtime_ns,
        ctime_ns=before.st_ctime_ns,
    )


def snapshot_consumer_validators() -> dict[str, ConsumerValidatorSnapshot]:
    return {
        "identity": _snapshot_validator(IDENTITY_VALIDATOR),
        "restart": _snapshot_validator(RESTART_SEAT_CONSUMER),
    }


def _validator_matches(path: Path, snapshot: ConsumerValidatorSnapshot) -> bool:
    try:
        current = _snapshot_validator(path)
    except ValueError:
        return False
    return (
        current.sha256 == snapshot.sha256
        and current.content == snapshot.content
        and current.device == snapshot.device
        and current.inode == snapshot.inode
        and current.size == snapshot.size
        and current.mtime_ns == snapshot.mtime_ns
        and current.ctime_ns == snapshot.ctime_ns
    )


def verify_consumer_validators(
    snapshots: Mapping[str, ConsumerValidatorSnapshot],
) -> bool:
    return set(snapshots) == {"identity", "restart"} and (
        _validator_matches(IDENTITY_VALIDATOR, snapshots["identity"])
        and _validator_matches(RESTART_SEAT_CONSUMER, snapshots["restart"])
    )





def run_identity_consumer(paths: Mapping[str, Path]) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(IDENTITY_VALIDATOR),
        str(paths["identity_manifest"]),
        "--checkpoint",
        str(paths["checkpoint"]),
        "--tensor-hashes",
        str(paths["tensor_hashes"]),
        "--tensor-manifest",
        str(paths["tensor_manifest"]),
        "--artifact-bundle",
        str(paths["artifact_bundle"]),
        "--receipt-bundle",
        str(paths["receipt_bundle"]),
        "--trusted-verifier-registry",
        str(paths["identity_trusted_verifier_registry"]),
        "--require-resolved",
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_restart_consumer(paths: Mapping[str, Path]) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(RESTART_SEAT_CONSUMER),
        str(paths["restart_run_manifest"]),
        "--trusted-verifier-registry",
        str(paths["restart_trusted_verifier_registry"]),
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
