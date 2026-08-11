# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Validate and atomically publish launch-authority bytes outside the repo.

The tracked ``receipts/ember-02-launch-authority`` tree is an immutable
historical record.  This publisher accepts an already-minted four-file packet,
reopens it through the canonical certified consumer, and promotes it into a
run-scoped external custody directory.  It does not execute training.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid
from collections.abc import Callable
from typing import Any


SCHEMA = "ember-launch-authority-external-custody-v1"
FILES = (
    "certificate.json",
    "declaration-ledger.jsonl",
    "run-spec.json",
    "sha-binding-map.json",
)
SHA_BINDING_KEYS = frozenset(
    {
        "benchmark_registry_sha256",
        "board_receipt_sha256",
        "checkout_sha256",
        "cli_binary_sha256",
        "config_sha256",
        "failure_class_ledger_sha256",
        "input_authority_sha256",
        "launch_packet_sha256",
        "root_summary_sha256",
        "seat_sha256",
        "subject_manifest_sha256",
        "tokenizer_sha256",
    }
)
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PublicationRefusal(ValueError):
    """A fail-closed refusal raised before live custody is changed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_no_reparse_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if not current.exists():
            continue
        stat = current.lstat()
        if current.is_symlink() or bool(
            getattr(stat, "st_file_attributes", 0) & 0x400
        ):
            raise PublicationRefusal(f"{label.upper()}_REPARSE_COMPONENT")


def _regular_source(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise PublicationRefusal(f"{label.upper()}_PATH_NOT_ABSOLUTE")
    _assert_no_reparse_components(path, label)
    if path.is_symlink() or not path.is_file():
        raise PublicationRefusal(f"{label.upper()}_NOT_REGULAR_FILE")
    return path.resolve(strict=True)


def _validate_sha_binding_map_bytes(raw: bytes) -> None:
    """Reopen the required disclosure map as a closed, nonempty schema.

    The certificate carries the authoritative digest values; this sidecar records the
    source identity from which each digest was derived. Publishing arbitrary bytes under
    its governed filename would make the four-file packet self-contradictory even though
    the three-file certified consumer remained green.
    """
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise PublicationRefusal("SHA_BINDING_MAP_DUPLICATE_KEY")
            payload[key] = value
        return payload

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationRefusal("SHA_BINDING_MAP_INVALID") from error
    if not isinstance(payload, dict) or set(payload) != SHA_BINDING_KEYS:
        raise PublicationRefusal("SHA_BINDING_MAP_SCHEMA_MISMATCH")
    if any(not isinstance(value, str) or not value.strip() for value in payload.values()):
        raise PublicationRefusal("SHA_BINDING_MAP_SOURCE_IDENTITY_INVALID")


def _external_root(repo_root: Path, custody_root: Path) -> tuple[Path, Path]:
    repo = repo_root.resolve(strict=True)
    if not custody_root.is_absolute():
        raise PublicationRefusal("CUSTODY_ROOT_NOT_ABSOLUTE")
    _assert_no_reparse_components(custody_root, "custody_root")
    custody = custody_root.resolve(strict=True)
    try:
        custody.relative_to(repo)
    except ValueError:
        return repo, custody
    raise PublicationRefusal("CUSTODY_ROOT_INSIDE_REPOSITORY")


def _historical_hashes(repo: Path) -> dict[str, str]:
    root = repo / "receipts" / "ember-02-launch-authority"
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _canonical_validator(repo: Path) -> Callable[[Path, Path, Path], Any]:
    module_path = repo / "tools" / "ember-restart-3b" / "certified_train_launch.py"
    spec = importlib.util.spec_from_file_location("ember_certified_train_launch", module_path)
    if spec is None or spec.loader is None:
        raise PublicationRefusal("CERTIFIED_CONSUMER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)

    def validate(certificate: Path, ledger: Path, run_spec: Path) -> Any:
        return module.validate_certified_request(repo, certificate, ledger, run_spec)

    return validate


def publish_launch_authority(
    *,
    repo_root: Path,
    custody_root: Path,
    run_id: str,
    certificate: Path,
    declaration_ledger: Path,
    run_spec: Path,
    sha_binding_map: Path,
    validator: Callable[[Path, Path, Path], Any] | None = None,
) -> dict[str, Any]:
    """Validate, atomically publish, reopen, and receipt one authority packet."""

    repo, custody = _external_root(repo_root, custody_root)
    if RUN_ID.fullmatch(run_id) is None:
        raise PublicationRefusal("RUN_ID_INVALID")
    source_paths = {
        "certificate.json": _regular_source(certificate, "certificate"),
        "declaration-ledger.jsonl": _regular_source(
            declaration_ledger, "declaration_ledger"
        ),
        "run-spec.json": _regular_source(run_spec, "run_spec"),
        "sha-binding-map.json": _regular_source(sha_binding_map, "sha_binding_map"),
    }
    try:
        source_bytes = {name: path.read_bytes() for name, path in source_paths.items()}
    except OSError as error:
        raise PublicationRefusal("SOURCE_READ_FAILED") from error
    _validate_sha_binding_map_bytes(source_bytes["sha-binding-map.json"])
    destination_parent = custody / run_id
    destination = destination_parent / "launch-authority"
    if destination.exists():
        raise PublicationRefusal("DESTINATION_ALREADY_EXISTS")

    historical_before = _historical_hashes(repo)
    staging = custody / f".issue1506-{run_id}-{uuid.uuid4().hex}.staging"
    published = False
    staging.mkdir(mode=0o700)
    try:
        for name in FILES:
            (staging / name).write_bytes(source_bytes[name])

        (validator or _canonical_validator(repo))(
            staging / "certificate.json",
            staging / "declaration-ledger.jsonl",
            staging / "run-spec.json",
        )
        source_hashes = {name: _sha256(staging / name) for name in FILES}
        receipt = {
            "schema_version": SCHEMA,
            "run_id": run_id,
            "custody_kind": "external-run-scoped",
            "training_executed": False,
            "files": source_hashes,
        }
        receipt_bytes = (
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        (staging / "launch-authority-custody.json").write_bytes(receipt_bytes)

        destination_parent.mkdir(mode=0o700)
        os.replace(staging, destination)
        published = True
        reopened = {name: _sha256(destination / name) for name in FILES}
        if reopened != source_hashes:
            raise PublicationRefusal("PUBLISHED_BYTES_CHANGED")
        if _historical_hashes(repo) != historical_before:
            raise PublicationRefusal("HISTORICAL_RECORD_CHANGED")
        return {
            **receipt,
            "custody_root": str(destination),
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if published:
            shutil.rmtree(destination, ignore_errors=True)
        if destination_parent.is_dir() and not any(destination_parent.iterdir()):
            destination_parent.rmdir()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--custody-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--declaration-ledger", required=True, type=Path)
    parser.add_argument("--run-spec", required=True, type=Path)
    parser.add_argument("--sha-binding-map", required=True, type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="publish after canonical validation; without this flag no files are written",
    )
    args = parser.parse_args(argv)
    if not args.execute:
        print(
            json.dumps(
                {
                    "outcome": "DRY_RUN",
                    "destination": str(
                        args.custody_root / args.run_id / "launch-authority"
                    ),
                    "training_executed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    try:
        receipt = publish_launch_authority(
            repo_root=args.repo_root,
            custody_root=args.custody_root,
            run_id=args.run_id,
            certificate=args.certificate,
            declaration_ledger=args.declaration_ledger,
            run_spec=args.run_spec,
            sha_binding_map=args.sha_binding_map,
        )
    except (OSError, PublicationRefusal, ValueError) as error:
        print(json.dumps({"outcome": "REFUSED", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps({"outcome": "PUBLISHED", **receipt}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
