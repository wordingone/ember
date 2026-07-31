#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed receipt-surface and derived-path custody for issue #672."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

_OWNERSHIP_SCHEMA = "ember-owned-derived-paths-v1"
_REFUSAL_SCHEMA = "ember-receipt-surface-refusal-v1"
_OWNERSHIP_KEYS = {"schema_version", "run_id", "owned_paths"}
_GLOB_CHARS = frozenset("*?[")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RECEIPT_PREFIXES = ("receipts/", "scripts/ember_totality/receipts-totality/")


class ReceiptSurfaceIntegrityError(RuntimeError):
    """Receipt evidence or path ownership is unsafe or unverifiable."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _strict_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptSurfaceIntegrityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(decoded, object_pairs_hook=_strict_object)
    except ReceiptSurfaceIntegrityError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptSurfaceIntegrityError("owned-path manifest is unreadable") from exc
    if not isinstance(value, dict):
        raise ReceiptSurfaceIntegrityError("owned-path manifest must be an object")
    if set(value) != _OWNERSHIP_KEYS:
        raise ReceiptSurfaceIntegrityError("owned-path manifest fields are not closed")
    if value["schema_version"] != _OWNERSHIP_SCHEMA:
        raise ReceiptSurfaceIntegrityError("owned-path manifest schema is unsupported")
    run_id = value["run_id"]
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise ReceiptSurfaceIntegrityError("owned-path manifest run_id is invalid")
    owned_paths = value["owned_paths"]
    if not isinstance(owned_paths, list) or any(
        not isinstance(item, str) for item in owned_paths
    ):
        raise ReceiptSurfaceIntegrityError("owned_paths must be an array of strings")
    if len(owned_paths) != len(set(owned_paths)):
        raise ReceiptSurfaceIntegrityError("owned_paths contains a duplicate")
    return value


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_owned_file(run_root: Path, relative: str) -> Path:
    if (
        not relative
        or "\\" in relative
        or any(char.isspace() or ord(char) < 32 for char in relative)
        or any(char in relative for char in _GLOB_CHARS)
    ):
        raise ReceiptSurfaceIntegrityError("owned path is not a literal safe path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ReceiptSurfaceIntegrityError("owned path escapes or aliases the run tree")
    candidate = run_root.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise ReceiptSurfaceIntegrityError("owned path may not be a symlink")
    resolved = candidate.resolve(strict=False)
    if not _inside(run_root, resolved):
        raise ReceiptSurfaceIntegrityError("owned path escapes the run tree")
    if not candidate.exists() or not candidate.is_file():
        raise ReceiptSurfaceIntegrityError("owned path must name one existing file")
    return candidate


def clear_owned_paths(*, run_root: str | Path, manifest_path: str | Path) -> dict[str, Any]:
    """Delete only exact files declared by a closed manifest inside one run tree."""

    root = Path(run_root).resolve(strict=True)
    manifest = Path(manifest_path)
    if manifest.is_symlink():
        raise ReceiptSurfaceIntegrityError("owned-path manifest may not be a symlink")
    manifest = manifest.resolve(strict=True)
    if not root.is_dir() or not _inside(root, manifest):
        raise ReceiptSurfaceIntegrityError(
            "owned-path manifest must be inside the invoking run tree"
        )
    payload = _read_manifest(manifest)
    targets = [
        (relative, _resolve_owned_file(root, relative))
        for relative in payload["owned_paths"]
    ]
    for _, target in targets:
        target.unlink()
    return {
        "schema_version": _OWNERSHIP_SCHEMA,
        "run_id": payload["run_id"],
        "cleared_paths": [relative for relative, _ in targets],
    }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReceiptSurfaceIntegrityError(
            "TRACKED_RECEIPT_STATUS_UNAVAILABLE"
        ) from exc


def _deleted_tracked_receipt_paths(root: Path) -> list[str]:
    proc = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    deleted: list[str] = []
    records = proc.stdout.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4:
            raise ReceiptSurfaceIntegrityError("TRACKED_RECEIPT_STATUS_MALFORMED")
        try:
            status = record[:2].decode("ascii", errors="strict")
            path = record[3:].decode("utf-8", errors="strict").replace("\\", "/")
        except UnicodeDecodeError as exc:
            raise ReceiptSurfaceIntegrityError(
                "TRACKED_RECEIPT_STATUS_MALFORMED"
            ) from exc
        if "R" in status or "C" in status:
            index += 1
        if "D" in status and path.startswith(_RECEIPT_PREFIXES):
            deleted.append(path)
    return sorted(set(deleted))


def _write_refusal(
    *,
    root: Path,
    refusal_root: Path,
    deleted_paths: list[str],
) -> Path:
    head = _git(root, "rev-parse", "--verify", "HEAD").stdout.decode(
        "ascii", errors="strict"
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReceiptSurfaceIntegrityError("TRACKED_RECEIPT_HEAD_UNAVAILABLE")
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = {
        "schema_version": _REFUSAL_SCHEMA,
        "status": "REFUSED",
        "reason_code": "TRACKED_RECEIPT_DELETION",
        "run_tree_sha": head,
        "deleted_tracked_receipt_paths": deleted_paths,
        "captured_at_utc": timestamp,
        "sha_convention": "canonical JSON excluding evidence_sha256",
    }
    evidence_sha = hashlib.sha256(_canonical_bytes(evidence)).hexdigest()
    payload = dict(evidence)
    payload["evidence_sha256"] = evidence_sha
    encoded = _canonical_bytes(payload)

    refusal_root.mkdir(parents=True, exist_ok=True)
    destination = refusal_root / (
        f"receipt-surface-refusal-{timestamp}-{evidence_sha[:16]}.json"
    )
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=refusal_root,
            prefix=".receipt-surface-refusal-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return destination


def enforce_board_receipt_surface(
    repo_root: str | Path,
    *,
    refusal_root: str | Path,
) -> dict[str, Any]:
    """Refuse a board run before probes/output when tracked receipts are deleted."""

    root = Path(repo_root).resolve(strict=True)
    deleted = _deleted_tracked_receipt_paths(root)
    if deleted:
        receipt = _write_refusal(
            root=root,
            refusal_root=Path(refusal_root).resolve(strict=False),
            deleted_paths=deleted,
        )
        raise ReceiptSurfaceIntegrityError(
            "TRACKED_RECEIPT_DELETION: board render refused; "
            f"durable refusal receipt={receipt.name}"
        )
    return {
        "status": "PASS",
        "deleted_tracked_receipt_paths": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clear only exact manifest-owned derived files inside one run tree."
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--owned-path-manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    result = clear_owned_paths(
        run_root=args.run_root,
        manifest_path=args.owned_path_manifest,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
