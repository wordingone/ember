# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Invoke the existing admission consumers on exact published disk bytes."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTITY_VALIDATOR = (
    REPO_ROOT / "scripts" / "ember_01_identity" / "validate_identity.py"
)
RESTART_SEAT_CONSUMER = REPO_ROOT / "scripts" / "ember_restart" / "cli_seat.py"

_IDENTITY_STATIC_EVIDENCE = (
    "manifests/ember-01-identity/schema-v1.json",
    "manifests/ember-01-identity/trusted-verifiers-v1.json",
    "manifests/ember-01-identity/accepted-training-input-authorities-v1.json",
    "manifests/ember-01-custody/benchmark-registry.json",
)
CONSUMER_CLOSURE_RELATIVE_PATHS: Mapping[str, tuple[str, ...]] = {
    "identity": (
        "scripts/ember_01_identity/validate_identity.py",
        *_IDENTITY_STATIC_EVIDENCE,
    ),
    "restart": (
        "src/ember/governance/scripts/ember_restart/cli_seat.py",
        "src/ember/governance/scripts/ember_restart/contract.py",
        "src/ember/governance/scripts/ember_restart/prediction_contract.py",
        "src/ember/governance/scripts/ember_restart/seat_identity_bridge.py",
        "scripts/ember_01_identity/checkpoint_save_load_identity_binding.py",
        "scripts/ember_01_identity/validate_identity.py",
        "tools/ember-restart-3b/parameter_counter.py",
        *_IDENTITY_STATIC_EVIDENCE,
    ),
}
CONSUMER_ENTRYPOINTS = {
    "identity": "scripts/ember_01_identity/validate_identity.py",
    "restart": "src/ember/governance/scripts/ember_restart/cli_seat.py",
}

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
        "src/ember/governance/scripts/ember_restart/cli_seat.py",
        "role:restart_run_manifest",
        "--trusted-verifier-registry",
        "role:restart_trusted_verifier_registry",
    ),
}


@dataclass(frozen=True)
class ConsumerClosureFileSnapshot:
    sha256: str
    content: bytes
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class ConsumerValidatorSnapshot:
    entrypoint: str
    files: Mapping[str, ConsumerClosureFileSnapshot]

    @property
    def sha256(self) -> str:
        return self.files[self.entrypoint].sha256

    @property
    def content(self) -> bytes:
        return self.files[self.entrypoint].content

    @property
    def device(self) -> int:
        return self.files[self.entrypoint].device

    @property
    def inode(self) -> int:
        return self.files[self.entrypoint].inode

    @property
    def size(self) -> int:
        return self.files[self.entrypoint].size

    @property
    def mtime_ns(self) -> int:
        return self.files[self.entrypoint].mtime_ns

    @property
    def ctime_ns(self) -> int:
        return self.files[self.entrypoint].ctime_ns


def _snapshot_file(path: Path) -> ConsumerClosureFileSnapshot:
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
    return ConsumerClosureFileSnapshot(
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        device=before.st_dev,
        inode=before.st_ino,
        size=before.st_size,
        mtime_ns=before.st_mtime_ns,
        ctime_ns=before.st_ctime_ns,
    )


def _valid_closure_relative_path(relative: str) -> bool:
    path = Path(relative)
    return (
        isinstance(relative, str)
        and relative
        and "\\" not in relative
        and not path.is_absolute()
        and relative == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _snapshot_consumer_closure(
    name: str,
    relative_paths: Sequence[str],
) -> ConsumerValidatorSnapshot:
    entrypoint_path = {
        "identity": IDENTITY_VALIDATOR,
        "restart": RESTART_SEAT_CONSUMER,
    }[name]
    try:
        entrypoint = entrypoint_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise ValueError("consumer.validator_location") from exc
    if (
        name not in CONSUMER_ENTRYPOINTS
        or entrypoint != CONSUMER_ENTRYPOINTS[name]
        or len(relative_paths) != len(set(relative_paths))
        or entrypoint not in relative_paths
        or not all(_valid_closure_relative_path(relative) for relative in relative_paths)
    ):
        raise ValueError("consumer.validator_closure")
    files = {
        relative: _snapshot_file(REPO_ROOT / Path(relative))
        for relative in relative_paths
    }
    return ConsumerValidatorSnapshot(entrypoint=entrypoint, files=files)


def snapshot_consumer_validators() -> dict[str, ConsumerValidatorSnapshot]:
    return {
        name: _snapshot_consumer_closure(name, relative_paths)
        for name, relative_paths in CONSUMER_CLOSURE_RELATIVE_PATHS.items()
    }


def _file_matches(relative: str, snapshot: ConsumerClosureFileSnapshot) -> bool:
    try:
        current = _snapshot_file(REPO_ROOT / Path(relative))
    except ValueError:
        return False
    return current == snapshot


def verify_consumer_validators(
    snapshots: Mapping[str, ConsumerValidatorSnapshot],
) -> bool:
    return (
        set(snapshots) == {"identity", "restart"}
        and all(
            snapshot.entrypoint == CONSUMER_ENTRYPOINTS[name]
            and tuple(snapshot.files) == CONSUMER_CLOSURE_RELATIVE_PATHS[name]
            and all(_file_matches(relative, file_snapshot)
                    for relative, file_snapshot in snapshot.files.items())
            for name, snapshot in snapshots.items()
        )
    )


def consumer_validator_closure_identity(
    snapshot: ConsumerValidatorSnapshot,
) -> dict[str, dict[str, object]]:
    return {
        relative: {
            "relative_path": relative,
            "sha256": file_snapshot.sha256,
            "bytes": len(file_snapshot.content),
        }
        for relative, file_snapshot in snapshot.files.items()
    }


def _run_snapshotted_validator(
    snapshot: ConsumerValidatorSnapshot,
    arguments: list[str],
) -> subprocess.CompletedProcess[str]:
    if (
        not _valid_closure_relative_path(snapshot.entrypoint)
        or snapshot.entrypoint not in snapshot.files
        or any(
            not _valid_closure_relative_path(relative)
            or hashlib.sha256(file_snapshot.content).hexdigest()
            != file_snapshot.sha256
            or len(file_snapshot.content) != file_snapshot.size
            for relative, file_snapshot in snapshot.files.items()
        )
    ):
        raise ValueError("consumer.validator_snapshot")
    with tempfile.TemporaryDirectory(prefix="ember-admission-consumer-") as scratch:
        snapshot_root = Path(scratch)
        for relative, file_snapshot in snapshot.files.items():
            destination = snapshot_root / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(file_snapshot.content)
                handle.flush()
                os.fsync(handle.fileno())
        entrypoint = snapshot_root / Path(snapshot.entrypoint)
        command = [sys.executable, str(entrypoint), *arguments]
        completed = subprocess.run(
            command,
            cwd=snapshot_root,
            capture_output=True,
            check=False,
        )
    return subprocess.CompletedProcess(
        args=command,
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="strict"),
        stderr=completed.stderr.decode("utf-8", errors="strict"),
    )





def run_identity_consumer(
    paths: Mapping[str, Path],
    snapshot: ConsumerValidatorSnapshot | None = None,
) -> subprocess.CompletedProcess[str]:
    frozen = snapshot if snapshot is not None else snapshot_consumer_validators()["identity"]
    arguments = [
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
    return _run_snapshotted_validator(frozen, arguments)


def run_restart_consumer(
    paths: Mapping[str, Path],
    snapshot: ConsumerValidatorSnapshot | None = None,
) -> subprocess.CompletedProcess[str]:
    frozen = snapshot if snapshot is not None else snapshot_consumer_validators()["restart"]
    arguments = [
        str(paths["restart_run_manifest"]),
        "--trusted-verifier-registry",
        str(paths["restart_trusted_verifier_registry"]),
    ]
    return _run_snapshotted_validator(frozen, arguments)
