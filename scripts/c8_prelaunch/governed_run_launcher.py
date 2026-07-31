#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Canonical fail-closed launcher for C8 governed-run commands.

The launcher consumes one closed, repository-confined manifest, hashes the
exact config and admissibility-receipt bytes, appends the public O5 run-ledger
row, and only then creates the child process. A manifest, evidence, or ledger
failure creates no child. The child receives private snapshots of the exact
hashed evidence through mandatory arguments; it cannot silently consume
different config or admissibility bytes.

This is a launch mechanism, not a claim that any C8 arm has run or passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

try:
    from .run_ledger import ARMS, assert_launch_recorded
except ImportError:  # pragma: no cover - direct script execution
    from run_ledger import ARMS, assert_launch_recorded


SCHEMA_VERSION = "ember-c8-governed-launch-v1"
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "arm",
        "config_path",
        "admissibility_receipt_path",
        "python_script_path",
        "argv",
    }
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RESERVED_CHILD_ARGUMENTS = (
    "--config",
    "--admissibility-receipt",
    "--run-id",
    "--arm",
)


class GovernedLaunchError(ValueError):
    """The contract is malformed or does not bind real repository bytes."""


@dataclass(frozen=True)
class LaunchManifest:
    run_id: str
    arm: str
    config_path: Path
    admissibility_receipt_path: Path
    python_script_path: Path
    argv: tuple[str, ...]


@dataclass(frozen=True)
class GovernedLaunchResult:
    returncode: int
    argv: tuple[str, ...]
    run_id: str
    arm: str
    config_sha256: str
    admissibility_receipt_sha256: str
    python_script_sha256: str


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GovernedLaunchError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GovernedLaunchError(f"cannot read launch manifest: {exc}") from exc
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GovernedLaunchError("launch manifest must be strict UTF-8") from exc
    try:
        value = json.loads(decoded, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, GovernedLaunchError) as exc:
        raise GovernedLaunchError(f"invalid launch manifest JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise GovernedLaunchError("launch manifest must be a JSON object")
    return value


def _confined_file(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise GovernedLaunchError(f"{field} must be a nonempty repo-relative path")
    if "\\" in value or "\x00" in value:
        raise GovernedLaunchError(f"{field} must use canonical forward slashes")
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.as_posix() != value:
        raise GovernedLaunchError(f"{field} must be a canonical repo-relative path")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise GovernedLaunchError(f"{field} contains an unsafe path component")

    candidate = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise GovernedLaunchError(f"{field} may not traverse a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise GovernedLaunchError(f"{field} is missing or escapes the repository") from exc
    if not resolved.is_file():
        raise GovernedLaunchError(f"{field} must name a regular file")
    return resolved


def _manifest_file(root: Path, manifest_path: Path) -> Path:
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    try:
        resolved = manifest_path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise GovernedLaunchError("launch manifest must be a repository-confined file") from exc
    if manifest_path.is_symlink() or not resolved.is_file():
        raise GovernedLaunchError("launch manifest must be a non-symlink regular file")
    return resolved


def load_launch_manifest(repo_root: Path | str, manifest_path: Path | str) -> LaunchManifest:
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise GovernedLaunchError("repo_root must be a directory")
    manifest_file = _manifest_file(root, Path(manifest_path))
    payload = _read_json_object(manifest_file)
    if set(payload) != MANIFEST_FIELDS:
        missing = sorted(MANIFEST_FIELDS - set(payload))
        extra = sorted(set(payload) - MANIFEST_FIELDS)
        raise GovernedLaunchError(
            f"closed manifest schema mismatch: missing={missing} extra={extra}"
        )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise GovernedLaunchError(f"schema_version must be {SCHEMA_VERSION}")

    run_id = payload["run_id"]
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise GovernedLaunchError("run_id must be a nonempty canonical identifier")
    arm = payload["arm"]
    if arm not in ARMS:
        raise GovernedLaunchError(f"arm must be one of {sorted(ARMS)}")
    argv = payload["argv"]
    if not isinstance(argv, list) or not all(
        isinstance(item, str) and item and "\x00" not in item for item in argv
    ):
        raise GovernedLaunchError("argv must be a list of nonempty strings")
    if any(
        item == reserved or item.startswith(f"{reserved}=")
        for item in argv
        for reserved in RESERVED_CHILD_ARGUMENTS
    ):
        raise GovernedLaunchError("argv may not override launcher-owned arguments")

    config_path = _confined_file(root, payload["config_path"], "config_path")
    receipt_path = _confined_file(
        root, payload["admissibility_receipt_path"], "admissibility_receipt_path"
    )
    script_path = _confined_file(root, payload["python_script_path"], "python_script_path")
    relative_script = script_path.relative_to(root)
    if (
        not relative_script.parts
        or relative_script.parts[0] != "scripts"
        or script_path.suffix != ".py"
    ):
        raise GovernedLaunchError("python_script_path must name a repository scripts/*.py file")

    return LaunchManifest(
        run_id=run_id,
        arm=arm,
        config_path=config_path,
        admissibility_receipt_path=receipt_path,
        python_script_path=script_path,
        argv=tuple(argv),
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_governed_launch(
    *,
    repo_root: Path | str,
    manifest_path: Path | str,
    record_launch: Callable[..., Mapping[str, Any]] = assert_launch_recorded,
    run_process: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    now: Callable[[], str] = _utc_now,
) -> GovernedLaunchResult:
    root = Path(repo_root).resolve(strict=True)
    manifest = load_launch_manifest(root, manifest_path)

    config_bytes = manifest.config_path.read_bytes()
    receipt_bytes = manifest.admissibility_receipt_path.read_bytes()
    script_bytes = manifest.python_script_path.read_bytes()
    config_sha = _sha256(config_bytes)
    receipt_sha = _sha256(receipt_bytes)
    script_sha = _sha256(script_bytes)

    ledger_path = root / "state" / "c8-run-ledger.jsonl"
    completed: subprocess.CompletedProcess[Any]
    argv: tuple[str, ...]
    with tempfile.TemporaryDirectory(prefix=f"ember-c8-{manifest.run_id}-") as temporary:
        snapshot_root = Path(temporary)
        config_snapshot = snapshot_root / "config.json"
        receipt_snapshot = snapshot_root / "admissibility-receipt.json"
        script_snapshot = snapshot_root / "governed-child.py"
        config_snapshot.write_bytes(config_bytes)
        receipt_snapshot.write_bytes(receipt_bytes)
        script_snapshot.write_bytes(script_bytes)
        if (
            _sha256(config_snapshot.read_bytes()) != config_sha
            or _sha256(receipt_snapshot.read_bytes()) != receipt_sha
            or _sha256(script_snapshot.read_bytes()) != script_sha
        ):
            raise GovernedLaunchError("private launch snapshot hash mismatch")

        # Admission is the last operation before process creation. Any failure
        # refuses the launch; the child can consume only the already-snapshotted
        # bytes recorded here.
        record_launch(
            ledger_path=str(ledger_path),
            run_id=manifest.run_id,
            arm=manifest.arm,
            launch_ts=now(),
            config_sha=config_sha,
            admissibility_commit_sha=receipt_sha,
        )

        argv = (
            sys.executable,
            "-B",
            str(script_snapshot),
            *manifest.argv,
            "--config",
            str(config_snapshot),
            "--admissibility-receipt",
            str(receipt_snapshot),
            "--run-id",
            manifest.run_id,
            "--arm",
            manifest.arm,
        )
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(root)
            if not existing_pythonpath
            else os.pathsep.join((str(root), existing_pythonpath))
        )
        completed = run_process(
            list(argv), cwd=str(root), env=environment, check=False
        )

    return GovernedLaunchResult(
        returncode=int(completed.returncode),
        argv=tuple(argv),
        run_id=manifest.run_id,
        arm=manifest.arm,
        config_sha256=config_sha,
        admissibility_receipt_sha256=receipt_sha,
        python_script_sha256=script_sha,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_governed_launch(repo_root=args.repo_root, manifest_path=args.manifest)
    except (GovernedLaunchError, OSError) as exc:
        print(f"C8_GOVERNED_LAUNCH_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "schema_version": "ember-c8-governed-launch-result-v1",
                "run_id": result.run_id,
                "arm": result.arm,
                "returncode": result.returncode,
                "config_sha256": result.config_sha256,
                "admissibility_receipt_sha256": result.admissibility_receipt_sha256,
                "python_script_sha256": result.python_script_sha256,
            },
            sort_keys=True,
        )
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
