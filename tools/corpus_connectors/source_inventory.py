# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed authorized-source inventory/import boundary for #648.

The inventory is only an index over already receipted bytes.  It does not
fetch, select, rank, or transform data.  Source receipts are the existing
``corpus-connector-receipt-v1`` authority from :mod:`receipt`; this module only
binds those receipts to an immutable raw-byte path for a later importer.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

try:
    from .receipt import L3_STATEMENT, SCHEMA_NAME, sha256_of_manifest
except ImportError:  # direct test/module execution from this connector dir
    from receipt import L3_STATEMENT, SCHEMA_NAME, sha256_of_manifest

SCHEMA = "ember-authorized-source-inventory-v1"
RECEIPT_SCHEMA = SCHEMA_NAME
_INVENTORY_FIELDS = frozenset({"schema_version", "sources"})
_SOURCE_FIELDS = frozenset(
    {"source_id", "domain", "raw_path", "raw_sha256", "receipt_path", "receipt_sha256"}
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "source",
        "source_id",
        "canonical_url",
        "license_evidence",
        "revision",
        "files",
        "total_bytes",
        "sha256_manifest",
        "fetched_at",
        "connector",
        "l3_statement",
        "dest_root",
        "notes",
        "license",
    }
)
_RECEIPT_OPTIONAL_FIELDS = frozenset({"retry_attempts", "retry_events"})
_FILE_FIELDS = frozenset({"path", "bytes", "sha256"})
_ALLOWED_LICENSE_PREFIXES = (
    "PD",
    "CC0",
    "CC-BY",
    "CC-BY-SA",
    "ODC-BY",
    "APACHE",
    "MIT",
    "BSD",
)
_ALLOWED_DOMAINS = frozenset("ABCDEFGHIJK")
_PROVENANCE_PREFIX = "human-provenance:"
_FORBIDDEN_PROVENANCE_MARKERS = (
    "model-generated",
    "model generated",
    "llm-generated",
    "classifier",
    "machine-ranked",
    "machine filtered",
    "synthetic",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _relative_file(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a normalized relative path")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes custody root") from error
    current = root
    for component in Path(value).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"{label} uses a symlink/reparse component")
        try:
            attributes = os.lstat(current).st_file_attributes
        except (AttributeError, FileNotFoundError, OSError):
            attributes = 0
        if attributes & 0x400:
            raise ValueError(f"{label} uses a symlink/reparse component")
    if not candidate.is_file():
        raise ValueError(f"{label} is missing")
    return candidate


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be readable JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _receipt_file_identity(*, root: Path, dest_root: object, file_path: object) -> str:
    """Return the one canonical custody-relative path named by a receipt row."""
    if not isinstance(dest_root, str) or not dest_root:
        raise ValueError("source receipt dest_root is required for path binding")
    if not isinstance(file_path, str) or not file_path or "\\" in file_path:
        raise ValueError("source receipt file path must be normalized")
    destination = Path(dest_root)
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve()
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise ValueError("source receipt dest_root escapes custody root") from error
    candidate = (destination / file_path).resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("source receipt file path escapes custody root") from error
    return relative


def load_authorized_source_inventory(*, manifest_path: Path, custody_root: Path) -> dict[str, Any]:
    """Validate a closed inventory and all receipt/raw-byte bindings."""

    root = custody_root.resolve()
    manifest = _read_json(manifest_path, "source inventory")
    if set(manifest) != _INVENTORY_FIELDS or manifest.get("schema_version") != SCHEMA:
        raise ValueError("source inventory schema is not admitted")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("source inventory must contain at least one source")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
            raise ValueError("source inventory rows have unknown or missing fields")
        source_id = source["source_id"]
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("source inventory source_id must be unique")
        seen.add(source_id)
        if source["domain"] not in _ALLOWED_DOMAINS:
            raise ValueError("source inventory domain is outside the closed A-K charter")
        raw = _relative_file(root, source["raw_path"], "raw_path")
        receipt = _relative_file(root, source["receipt_path"], "receipt_path")
        raw_sha = source["raw_sha256"]
        receipt_sha = source["receipt_sha256"]
        if not _is_sha256(raw_sha) or _sha256(raw) != raw_sha:
            raise ValueError("raw source bytes do not match their hash")
        if not _is_sha256(receipt_sha) or _sha256(receipt) != receipt_sha:
            raise ValueError("source receipt bytes do not match their hash")
        receipt_payload = _read_json(receipt, "source receipt")
        if (
            not _RECEIPT_FIELDS.issubset(receipt_payload)
            or set(receipt_payload) - (_RECEIPT_FIELDS | _RECEIPT_OPTIONAL_FIELDS)
            or receipt_payload.get("schema") != RECEIPT_SCHEMA
        ):
            raise ValueError("source receipt schema is not admitted")
        files = receipt_payload.get("files")
        if not isinstance(files, list) or len(files) != 1:
            raise ValueError("source receipt must bind exactly one inventory file")
        file_rows: list[dict[str, Any]] = []
        for file_row in files:
            if not isinstance(file_row, dict) or set(file_row) != _FILE_FIELDS:
                raise ValueError("source receipt file rows have unknown or missing fields")
            if (
                not isinstance(file_row["path"], str)
                or not file_row["path"]
                or isinstance(file_row["bytes"], bool)
                or not isinstance(file_row["bytes"], int)
                or file_row["bytes"] < 0
                or not _is_sha256(file_row["sha256"])
            ):
                raise ValueError("source receipt file rows are malformed")
            file_rows.append(file_row)
        if receipt_payload.get("sha256_manifest") != sha256_of_manifest([row["sha256"] for row in file_rows]):
            raise ValueError("source receipt manifest hash is not derived from its file rows")
        if receipt_payload.get("total_bytes") != sum(row["bytes"] for row in file_rows):
            raise ValueError("source receipt total bytes are not derived from its file rows")
        if (
            _receipt_file_identity(
                root=root,
                dest_root=receipt_payload.get("dest_root"),
                file_path=file_rows[0]["path"],
            )
            != Path(source["raw_path"]).as_posix()
        ):
            raise ValueError("source receipt file identity does not match inventory raw_path")
        license_value = receipt_payload.get("license")
        normalized_license = license_value.upper() if isinstance(license_value, str) else ""
        notes = receipt_payload.get("notes")
        provenance_text = " ".join(
            str(receipt_payload.get(key, ""))
            for key in ("source", "canonical_url", "license_evidence", "notes")
        ).lower()
        if (
            receipt_payload.get("source_id") != source_id
            or receipt_payload.get("l3_statement") != L3_STATEMENT
            or not isinstance(receipt_payload.get("canonical_url"), str)
            or not receipt_payload["canonical_url"]
            or not isinstance(receipt_payload.get("license_evidence"), str)
            or not receipt_payload["license_evidence"]
            or not isinstance(receipt_payload.get("fetched_at"), str)
            or not receipt_payload["fetched_at"]
            or not isinstance(receipt_payload.get("revision"), (str, type(None)))
            or not isinstance(license_value, str)
            or not license_value
            or not isinstance(notes, str)
            or not notes.startswith(_PROVENANCE_PREFIX)
            or any(marker in provenance_text for marker in _FORBIDDEN_PROVENANCE_MARKERS)
            or normalized_license in {"UNSPECIFIED", "UNVERIFIED", "UNKNOWN"}
            or "-NC" in normalized_license
            or "-ND" in normalized_license
            or not normalized_license.startswith(_ALLOWED_LICENSE_PREFIXES)
            or any(row["bytes"] != raw.stat().st_size or row["sha256"] != raw_sha for row in file_rows)
        ):
            raise ValueError("source receipt license/source identity does not prove these authorized raw bytes")
        normalized.append(source)
    if normalized != sorted(normalized, key=lambda row: row["source_id"]):
        raise ValueError("source inventory rows must be deterministically ordered")
    return manifest


def reopen_authorized_source_inventory(*, manifest_path: Path, custody_root: Path) -> dict[str, Any]:
    """Idempotent reopen entry point used by downstream import consumers."""

    return load_authorized_source_inventory(manifest_path=manifest_path, custody_root=custody_root)
