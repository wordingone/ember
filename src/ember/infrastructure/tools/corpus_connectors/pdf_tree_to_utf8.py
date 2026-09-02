#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministically transform one closed connector PDF tree into UTF-8 custody."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

# Direct execution appends the repository root so package imports resolve
# without publishing connector-local bare names or shadowing earlier imports.
_REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from tools.corpus_connectors import pdf_to_utf8  # noqa: E402
from tools.corpus_connectors import receipt as connector_receipt  # noqa: E402


SCHEMA = "ember-pdf-tree-extraction-receipt-v2"
COMPOSITE_AUTHORITY_SCHEMA = "ember-pdf-composite-connector-authority-v1"
COMPOSITE_SPEC_SCHEMA = "ember-pdf-composite-authority-spec-v1"
EXCLUSION_SCHEMA = "ember-pdf-tree-exclusion-set-v1"
DERIVED_CONNECTOR = "_manifests/derived-connector-receipt.json"
TRANSFORM_RECEIPT = "_manifests/pdf-tree-extraction-receipt.json"
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_TOTAL_PAGES = 2_000_000
DEFAULT_MAX_TOTAL_DECODED_CONTENT_BYTES = 1 << 40
DEFAULT_MAX_TOTAL_OUTPUT_BYTES = 1 << 38
_HEX = re.compile(r"^[0-9a-f]{64}$")
_SIDECAR_ROOTS = set(connector_receipt.DEFAULT_EXCLUDE_DIRNAMES)
_SIDECAR_FILES = {"manifest.jsonl"}


class PdfTreeExtractionRefusal(ValueError):
    """The requested tree transform cannot satisfy the closed custody contract."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _normalize_relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PdfTreeExtractionRefusal("connector file path is invalid")
    portable = value.replace("\\", "/")
    pure = PurePosixPath(portable)
    if pure.is_absolute() or re.match(r"^[A-Za-z]:", portable) or any(
        part in {"", ".", ".."} for part in pure.parts
    ):
        raise PdfTreeExtractionRefusal("connector file path is not contained")
    return pure.as_posix()


def _regular_contained(root: Path, relative: str, label: str) -> Path:
    cursor = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError as error:
            raise PdfTreeExtractionRefusal(f"{label} is missing: {relative}") from error
        if _is_reparse_or_symlink(cursor):
            raise PdfTreeExtractionRefusal(f"{label} crosses a symlink or reparse point")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise PdfTreeExtractionRefusal(f"{label} path is malformed")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise PdfTreeExtractionRefusal(f"{label} is not a regular file")
    try:
        cursor.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise PdfTreeExtractionRefusal(f"{label} escapes custody") from error
    return cursor


def _data_paths(root: Path) -> set[str]:
    result: set[str] = set()
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for directory in directories:
            child = current_path / directory
            relative = child.relative_to(root).as_posix()
            if relative.split("/", 1)[0] in _SIDECAR_ROOTS:
                continue
            if _is_reparse_or_symlink(child):
                raise PdfTreeExtractionRefusal("custody contains a symlink or reparse point")
            kept.append(directory)
        directories[:] = kept
        for filename in filenames:
            child = current_path / filename
            relative = child.relative_to(root).as_posix()
            if relative.split("/", 1)[0] in _SIDECAR_ROOTS or relative in _SIDECAR_FILES:
                continue
            if _is_reparse_or_symlink(child) or not child.is_file():
                raise PdfTreeExtractionRefusal("custody contains a non-regular data path")
            result.add(relative)
    return result


def _all_file_paths(root: Path) -> set[str]:
    result: set[str] = set()
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            if _is_reparse_or_symlink(current_path / directory):
                raise PdfTreeExtractionRefusal("custody contains a symlink or reparse point")
        for filename in filenames:
            child = current_path / filename
            if _is_reparse_or_symlink(child) or not child.is_file():
                raise PdfTreeExtractionRefusal("custody contains a non-regular file")
            result.add(child.relative_to(root).as_posix())
    return result


def _all_directory_paths(root: Path) -> set[str]:
    result: set[str] = set()
    for current, directories, _ in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            child = current_path / directory
            if _is_reparse_or_symlink(child):
                raise PdfTreeExtractionRefusal("custody contains a symlink or reparse point")
            result.add(child.relative_to(root).as_posix())
    return result


def _parent_directories(paths: set[str]) -> set[str]:
    result: set[str] = set()
    for relative in paths:
        parts = PurePosixPath(relative).parts[:-1]
        for end in range(1, len(parts) + 1):
            result.add(PurePosixPath(*parts[:end]).as_posix())
    return result


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    if _is_reparse_or_symlink(path) or not path.is_file():
        raise PdfTreeExtractionRefusal(f"{label} must be a regular non-reparse file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PdfTreeExtractionRefusal(f"{label} must be strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise PdfTreeExtractionRefusal(f"{label} must contain one JSON object")
    return raw, value


def _require_outside_custody(path: Path, custody_root: Path, label: str) -> None:
    candidate = path.resolve(strict=True) if path.exists() else path.parent.resolve(strict=True) / path.name
    try:
        candidate.relative_to(custody_root.resolve(strict=True))
    except ValueError:
        return
    raise PdfTreeExtractionRefusal(f"{label} must be outside connector custody")


def _require_outside_custodies(path: Path, custody_roots: tuple[Path, ...], label: str) -> None:
    for custody_root in custody_roots:
        _require_outside_custody(path, custody_root, label)


def _component_rows(receipt_path: Path, receipt_sha256: str) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    raw, payload = _read_json(receipt_path, "composite component receipt")
    if _HEX.fullmatch(receipt_sha256) is None or _sha256(raw) != receipt_sha256:
        raise PdfTreeExtractionRefusal("composite component receipt bytes changed")
    if payload.get("schema") == "corpus-connector-receipt-v1":
        root_value = payload.get("dest_root")
        files = payload.get("files")
    elif payload.get("schema_version") == "issue1581-row2-delta-fetch-v1":
        claimed = payload.get("self_sha256")
        body = dict(payload)
        body.pop("self_sha256", None)
        if claimed != _sha256(_canonical(body)):
            raise PdfTreeExtractionRefusal("composite delta receipt self-hash changed")
        root_value = payload.get("custody")
        files = payload.get("files")
    else:
        raise PdfTreeExtractionRefusal("composite component receipt schema is not admitted")
    if not isinstance(root_value, str) or not root_value or not isinstance(files, list) or not files:
        raise PdfTreeExtractionRefusal("composite component authority is incomplete")
    root = Path(root_value)
    if _is_reparse_or_symlink(root) or not root.is_dir():
        raise PdfTreeExtractionRefusal("composite component custody is unavailable")
    reopened: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise PdfTreeExtractionRefusal("composite component file row is malformed")
        relative = _normalize_relative(item.get("path"))
        size = item.get("bytes")
        digest = item.get("sha256")
        if relative in seen:
            raise PdfTreeExtractionRefusal("composite component contains duplicate paths")
        seen.add(relative)
        path = _regular_contained(root, relative, "composite source PDF")
        if (
            not relative.lower().endswith(".pdf")
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or _HEX.fullmatch(digest) is None
            or path.stat().st_size != size
            or _sha256_file(path) != digest
        ):
            raise PdfTreeExtractionRefusal("composite source PDF identity changed")
        reopened.append({"path": relative, "bytes": size, "sha256": digest, "source_path": path})
    physical_pdfs = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    }
    if physical_pdfs != seen:
        raise PdfTreeExtractionRefusal("composite component PDF set differs from its receipt")
    reopened.sort(key=lambda row: row["path"])
    return payload, root, reopened


def build_composite_connector_authority(*, spec_raw: bytes) -> bytes:
    """Seal a path-bearing multi-custody authority with a path-free file-set identity."""
    try:
        spec = json.loads(spec_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PdfTreeExtractionRefusal("composite authority spec must be strict JSON") from error
    if not isinstance(spec, dict) or set(spec) != {
        "schema_version", "source", "source_id", "canonical_url", "license", "revision", "components"
    } or spec.get("schema_version") != COMPOSITE_SPEC_SCHEMA:
        raise PdfTreeExtractionRefusal("composite authority spec schema is not closed")
    components = spec.get("components")
    if not isinstance(components, list) or len(components) < 2:
        raise PdfTreeExtractionRefusal("composite authority requires at least two components")
    sealed_components: list[dict[str, Any]] = []
    union: dict[str, dict[str, Any]] = {}
    fetched_values: list[str] = []
    for component in components:
        if not isinstance(component, dict) or set(component) != {"receipt_path", "receipt_sha256"}:
            raise PdfTreeExtractionRefusal("composite component binding is malformed")
        receipt_path = Path(component["receipt_path"])
        payload, root, rows = _component_rows(receipt_path, component["receipt_sha256"])
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, str) or not fetched_at:
            raise PdfTreeExtractionRefusal("composite component fetched_at is missing")
        fetched_values.append(fetched_at)
        for row in rows:
            if row["path"] in union:
                raise PdfTreeExtractionRefusal("composite component path sets overlap")
            union[row["path"]] = {key: row[key] for key in ("path", "bytes", "sha256")}
        sealed_components.append({
            "receipt_path": str(receipt_path),
            "receipt_sha256": component["receipt_sha256"],
            "receipt_schema": payload.get("schema") or payload.get("schema_version"),
            "custody_root": str(root),
            "file_count": len(rows),
            "files": [{key: row[key] for key in ("path", "bytes", "sha256")} for row in rows],
        })
    ordered = [union[path] for path in sorted(union)]
    authority: dict[str, Any] = {
        "schema": COMPOSITE_AUTHORITY_SCHEMA,
        "result": "VERIFIED",
        "source": spec["source"],
        "source_id": spec["source_id"],
        "canonical_url": spec["canonical_url"],
        "license": spec["license"],
        "revision": spec["revision"],
        "connector": {"name": "composite_pdf_authority", "version": "v1"},
        "fetched_at": max(fetched_values),
        "components": sealed_components,
        "file_count": len(ordered),
        "total_bytes": sum(row["bytes"] for row in ordered),
        "sha256_manifest": _sha256("\n".join(sorted(row["sha256"] for row in ordered)).encode("utf-8")),
        "path_set_sha256": _sha256(_canonical(ordered)),
    }
    authority["self_sha256"] = _sha256(_canonical(authority))
    return _canonical(authority)


def _canonical_license(value: Any) -> str:
    if value in {
        "CC0-1.0",
        "http://creativecommons.org/publicdomain/zero/1.0/",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    }:
        return "CC0-1.0"
    if value in {
        "CC-BY-4.0",
        "http://creativecommons.org/licenses/by/4.0/",
        "https://creativecommons.org/licenses/by/4.0/",
    }:
        return "CC-BY-4.0"
    raise PdfTreeExtractionRefusal("connector license is not the closed CC-BY-4.0 identity")


def _source_tree(
    connector_receipt: Path,
    connector_receipt_sha256: str,
    *,
    max_files: int,
) -> tuple[dict[str, Any], tuple[Path, ...], list[dict[str, Any]]]:
    if _HEX.fullmatch(connector_receipt_sha256) is None:
        raise PdfTreeExtractionRefusal("connector receipt hash is invalid")
    raw, receipt = _read_json(Path(connector_receipt), "connector receipt")
    if _sha256(raw) != connector_receipt_sha256:
        raise PdfTreeExtractionRefusal("connector receipt bytes do not match the bound hash")
    if receipt.get("schema") == COMPOSITE_AUTHORITY_SCHEMA:
        claimed = receipt.get("self_sha256")
        body = dict(receipt)
        body.pop("self_sha256", None)
        if claimed != _sha256(_canonical(body)) or receipt.get("result") != "VERIFIED":
            raise PdfTreeExtractionRefusal("composite authority self-hash does not rederive")
        components = receipt.get("components")
        if not isinstance(components, list) or len(components) < 2:
            raise PdfTreeExtractionRefusal("composite authority components are incomplete")
        reopened: list[dict[str, Any]] = []
        roots: list[Path] = []
        seen: set[str] = set()
        for component in components:
            if not isinstance(component, dict):
                raise PdfTreeExtractionRefusal("composite authority component is malformed")
            payload, root, rows = _component_rows(
                Path(component.get("receipt_path", "")), component.get("receipt_sha256", "")
            )
            expected = {
                "receipt_path": component.get("receipt_path"),
                "receipt_sha256": component.get("receipt_sha256"),
                "receipt_schema": payload.get("schema") or payload.get("schema_version"),
                "custody_root": str(root),
                "file_count": len(rows),
                "files": [{key: row[key] for key in ("path", "bytes", "sha256")} for row in rows],
            }
            if component != expected:
                raise PdfTreeExtractionRefusal("composite authority component binding changed")
            for row in rows:
                if row["path"] in seen:
                    raise PdfTreeExtractionRefusal("composite component path sets overlap")
                seen.add(row["path"])
                reopened.append(row)
            roots.append(root)
        reopened.sort(key=lambda row: row["path"])
        if len(reopened) > max_files:
            raise PdfTreeExtractionRefusal("connector PDF count exceeds the closed bound")
        public = {
            "schema": "corpus-connector-receipt-v1",
            "source": receipt.get("source"),
            "source_id": receipt.get("source_id"),
            "canonical_url": receipt.get("canonical_url"),
            "license": receipt.get("license"),
            "revision": receipt.get("revision"),
            "connector": receipt.get("connector"),
            "fetched_at": receipt.get("fetched_at"),
            "files": [{key: row[key] for key in ("path", "bytes", "sha256")} for row in reopened],
            "total_bytes": sum(row["bytes"] for row in reopened),
            "sha256_manifest": _sha256("\n".join(sorted(row["sha256"] for row in reopened)).encode("utf-8")),
            "license_evidence": "composite authority binds exact component receipt raw hashes",
            "l3_statement": "deterministic authority union only; no model-mediated selection",
            "notes": f"component_receipt_sha256={','.join(row['receipt_sha256'] for row in components)}",
        }
        if (
            receipt.get("file_count") != len(reopened)
            or receipt.get("total_bytes") != public["total_bytes"]
            or receipt.get("sha256_manifest") != public["sha256_manifest"]
            or receipt.get("path_set_sha256")
            != _sha256(_canonical(public["files"]))
        ):
            raise PdfTreeExtractionRefusal("composite authority union does not rederive")
        return public, tuple(roots), reopened
    if receipt.get("schema") != "corpus-connector-receipt-v1":
        raise PdfTreeExtractionRefusal("connector receipt schema is invalid")
    if not isinstance(max_files, int) or isinstance(max_files, bool) or max_files <= 0:
        raise PdfTreeExtractionRefusal("max_files must be a positive integer")
    files = receipt.get("files")
    if not isinstance(files, list) or not files or len(files) > max_files:
        raise PdfTreeExtractionRefusal("connector PDF count exceeds the closed bound")
    root_value = receipt.get("dest_root")
    if not isinstance(root_value, str) or not root_value:
        raise PdfTreeExtractionRefusal("connector destination root is missing")
    root = Path(root_value)
    if _is_reparse_or_symlink(root) or not root.is_dir():
        raise PdfTreeExtractionRefusal("connector destination root is not a regular directory")
    reopened: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise PdfTreeExtractionRefusal("connector file entry is malformed")
        relative = _normalize_relative(item.get("path"))
        if relative in seen:
            raise PdfTreeExtractionRefusal("connector receipt contains a duplicate path")
        seen.add(relative)
        if not relative.lower().endswith(".pdf"):
            raise PdfTreeExtractionRefusal("connector tree contains a non-PDF file")
        path = _regular_contained(root, relative, "source PDF")
        size = item.get("bytes")
        digest = item.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or _HEX.fullmatch(digest) is None
            or path.stat().st_size != size
            or _sha256_file(path) != digest
        ):
            raise PdfTreeExtractionRefusal("source PDF bytes do not match the connector receipt")
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise PdfTreeExtractionRefusal("source PDF magic is invalid")
        reopened.append({"path": relative, "bytes": size, "sha256": digest, "source_path": path})
    if _data_paths(root) != seen:
        raise PdfTreeExtractionRefusal("connector custody file set differs from its receipt")
    if receipt.get("total_bytes") != sum(item["bytes"] for item in reopened):
        raise PdfTreeExtractionRefusal("connector receipt total bytes do not rederive")
    manifest = _sha256("\n".join(sorted(item["sha256"] for item in reopened)).encode("utf-8"))
    if receipt.get("sha256_manifest") != manifest:
        raise PdfTreeExtractionRefusal("connector receipt manifest does not rederive")
    reopened.sort(key=lambda item: item["path"])
    return receipt, (root,), reopened


def _positive_bound(label: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PdfTreeExtractionRefusal(f"{label} must be a positive integer")
    return value


def _extract_one(
    path: Path,
    *,
    max_pages: int,
    max_decoded_content_bytes: int,
    max_output_bytes: int,
) -> tuple[bytes, int, int, dict[str, Any]]:
    try:
        return pdf_to_utf8._extract_pdf(
            path,
            max_pages=max_pages,
            max_decoded_content_bytes=max_decoded_content_bytes,
            max_output_bytes=max_output_bytes,
        )
    except pdf_to_utf8.PdfExtractionRefusal as error:
        raise PdfTreeExtractionRefusal(str(error)) from error


def _extractor_identity(
    *,
    max_files: int,
    max_pages: int,
    max_decoded_content_bytes: int,
    max_output_bytes: int,
    max_total_pages: int,
    max_total_decoded_content_bytes: int,
    max_total_output_bytes: int,
) -> dict[str, Any]:
    pypdf = pdf_to_utf8._load_pypdf()
    return {
        "normalization": pdf_to_utf8.NORMALIZATION,
        "extractor_semantics_version": pdf_to_utf8.EXTRACTOR_SEMANTICS_VERSION,
        "reader_strict": False,
        "producer_sha256": _sha256_file(Path(__file__).resolve(strict=True)),
        "single_pdf_producer_sha256": _sha256_file(Path(pdf_to_utf8.__file__).resolve(strict=True)),
        "pypdf_version": pdf_to_utf8.PYPDF_VERSION,
        "pypdf_package_tree_sha256": pdf_to_utf8._package_tree_sha256(pypdf),
        "pypdf_wheel_sha256": pdf_to_utf8.PYPDF_WHEEL_SHA256,
        "python_major_minor": pdf_to_utf8.PYTHON_MAJOR_MINOR,
        "python_version": sys.version,
        "max_files": max_files,
        "max_pages": max_pages,
        "max_decoded_content_bytes": max_decoded_content_bytes,
        "max_output_bytes": max_output_bytes,
        "max_total_pages": max_total_pages,
        "max_total_decoded_content_bytes": max_total_decoded_content_bytes,
        "max_total_output_bytes": max_total_output_bytes,
        "zero_fallback": True,
    }


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _receipt_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    return payload


def _validate_transform_shape(receipt: dict[str, Any]) -> None:
    if set(receipt) != {
        "schema",
        "result",
        "claim_boundary",
        "source",
        "extractor",
        "census",
        "exclusions",
        "files",
        "totals",
        "derived_connector",
        "receipt_sha256",
    }:
        raise PdfTreeExtractionRefusal("PDF tree receipt schema is not closed")
    if receipt.get("schema") != SCHEMA or receipt.get("result") != "VERIFIED":
        raise PdfTreeExtractionRefusal("PDF tree receipt result is invalid")
    if receipt.get("receipt_sha256") != _sha256(_canonical(_receipt_payload(receipt))):
        raise PdfTreeExtractionRefusal("PDF tree receipt self-hash does not rederive")


def _load_census_binding(
    *,
    census_report: Path,
    census_report_sha256: str,
    connector_receipt_sha256: str,
    source_files: list[dict[str, Any]],
    expected_extractor: dict[str, Any],
    census_producer_sha256: str | None = None,
    exclusion_set: Path | None = None,
    exclusion_set_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if _HEX.fullmatch(census_report_sha256) is None:
        raise PdfTreeExtractionRefusal("census report hash is invalid")
    raw, report = _read_json(Path(census_report), "PDF tree refusal census")
    if _sha256(raw) != census_report_sha256:
        raise PdfTreeExtractionRefusal("census report bytes do not match the bound hash")
    if set(report) != {
        "schema",
        "result",
        "claim_boundary",
        "started_at",
        "ended_at",
        "elapsed_seconds",
        "source",
        "extractor",
        "files",
        "totals",
        "receipt_sha256",
    } or report.get("schema") != "ember-pdf-tree-refusal-census-v1":
        raise PdfTreeExtractionRefusal("census report schema is not closed")
    embedded = report.get("receipt_sha256")
    if not isinstance(embedded, str) or embedded != _sha256(_canonical(_receipt_payload(report))):
        raise PdfTreeExtractionRefusal("census report self-hash does not rederive")
    source = report.get("source")
    if not isinstance(source, dict) or source.get("connector_receipt_sha256") != connector_receipt_sha256:
        raise PdfTreeExtractionRefusal("census connector receipt identity changed")
    totals = report.get("totals")
    files = report.get("files")
    if not isinstance(files, list) or len(files) != len(source_files):
        raise PdfTreeExtractionRefusal("census file map is incomplete")
    if [row.get("source_path") for row in files if isinstance(row, dict)] != [
        item["path"] for item in source_files
    ]:
        raise PdfTreeExtractionRefusal("census file map order is not canonical")
    refused_rows: list[dict[str, Any]] = []
    included_files: list[dict[str, Any]] = []
    for row, item in zip(files, source_files):
        if not isinstance(row, dict):
            raise PdfTreeExtractionRefusal("census file row is invalid")
        common = {
            "source_path": item["path"],
            "source_bytes": item["bytes"],
            "source_sha256": item["sha256"],
        }
        if any(row.get(key) != value for key, value in common.items()):
            raise PdfTreeExtractionRefusal("census source identity changed")
        if row.get("result") == "PASS":
            if set(row) != {
                *common,
                "result",
                "pages",
                "decoded_content_bytes",
                "output_bytes",
                "output_sha256",
                "extractor_semantics_version",
                "sanitized_pages",
                "pgf_removed_line_count",
                "surrogate_pair_count",
                "escaped_surrogate_count",
            } or _HEX.fullmatch(row.get("output_sha256", "")) is None:
                raise PdfTreeExtractionRefusal("census PASS row is not closed")
            try:
                pdf_to_utf8.validate_extraction_audit(
                    {key: row[key] for key in pdf_to_utf8._AUDIT_KEYS},
                    page_count=row["pages"],
                )
            except (KeyError, pdf_to_utf8.PdfExtractionRefusal) as error:
                raise PdfTreeExtractionRefusal("census PASS extraction audit is invalid") from error
            included_files.append(item)
        elif row.get("result") == "REFUSED":
            allowed = {"source_path", "source_bytes", "source_sha256", "result", "refusal_class", "detail"}
            if "exception_class" in row:
                allowed.add("exception_class")
            if set(row) != allowed or not isinstance(row.get("refusal_class"), str) or not isinstance(row.get("detail"), str):
                raise PdfTreeExtractionRefusal("census refusal row is not closed")
            refused_rows.append(row)
        else:
            raise PdfTreeExtractionRefusal("census file result is invalid")
    expected_totals = {
        "file_count": len(source_files),
        "pass_count": len(included_files),
        "refusal_count": len(refused_rows),
    }
    expected_result = "PASS" if not refused_rows else "REFUSED"
    if totals != expected_totals or report.get("result") != expected_result:
        raise PdfTreeExtractionRefusal("census result does not rederive")
    extractor = report.get("extractor")
    if not isinstance(extractor, dict):
        raise PdfTreeExtractionRefusal("census extractor identity is incomplete")
    identity_keys = {
        "normalization",
        "extractor_semantics_version",
        "reader_strict",
        "producer_sha256",
        "single_pdf_producer_sha256",
        "pypdf_version",
        "pypdf_package_tree_sha256",
        "pypdf_wheel_sha256",
        "python_major_minor",
        "python_version",
        "max_files",
        "max_pages",
        "max_decoded_content_bytes",
        "max_output_bytes",
        "zero_fallback",
    }
    if census_producer_sha256 is not None and _HEX.fullmatch(census_producer_sha256) is None:
        raise PdfTreeExtractionRefusal("census producer hash is invalid")
    expected_census_extractor = {
        key: expected_extractor.get(key)
        for key in identity_keys
    }
    if census_producer_sha256 is not None:
        expected_census_extractor["producer_sha256"] = census_producer_sha256
    if {key: extractor.get(key) for key in identity_keys} != expected_census_extractor:
        raise PdfTreeExtractionRefusal("census extractor identity changed")
    bound_census_producer = extractor["producer_sha256"]
    census_binding = {
        "path": str(Path(census_report).resolve(strict=True)),
        "sha256": census_report_sha256,
        "receipt_sha256": embedded,
        "census_producer_sha256": bound_census_producer,
    }
    if not refused_rows:
        if exclusion_set is not None or exclusion_set_sha256 is not None:
            raise PdfTreeExtractionRefusal("zero-refusal census must not carry an exclusion set")
        return census_binding, {
            "set": None,
            "requested_files": [],
            "census_refusal_rows": [],
        }, included_files
    if exclusion_set is None or exclusion_set_sha256 is None:
        raise PdfTreeExtractionRefusal("refused census requires an explicit exclusion set")
    if _HEX.fullmatch(exclusion_set_sha256) is None:
        raise PdfTreeExtractionRefusal("exclusion set hash is invalid")
    exclusion_raw, exclusion = _read_json(Path(exclusion_set), "PDF tree exclusion set")
    if _sha256(exclusion_raw) != exclusion_set_sha256:
        raise PdfTreeExtractionRefusal("exclusion set bytes do not match the bound hash")
    if set(exclusion) != {"schema", "census_report_sha256", "files", "receipt_sha256"}:
        raise PdfTreeExtractionRefusal("exclusion set schema is not closed")
    if exclusion.get("schema") != EXCLUSION_SCHEMA or exclusion.get("census_report_sha256") != census_report_sha256:
        raise PdfTreeExtractionRefusal("exclusion set census identity changed")
    exclusion_receipt_sha = exclusion.get("receipt_sha256")
    if not isinstance(exclusion_receipt_sha, str) or exclusion_receipt_sha != _sha256(_canonical(_receipt_payload(exclusion))):
        raise PdfTreeExtractionRefusal("exclusion set self-hash does not rederive")
    requested = exclusion.get("files")
    if not isinstance(requested, list) or any(
        not isinstance(row, dict)
        or set(row) != {"source_path", "source_sha256"}
        or not isinstance(row.get("source_path"), str)
        or _HEX.fullmatch(row.get("source_sha256", "")) is None
        for row in requested
    ):
        raise PdfTreeExtractionRefusal("exclusion file set is not closed")
    expected_requested = [
        {"source_path": row["source_path"], "source_sha256": row["source_sha256"]}
        for row in refused_rows
    ]
    if requested != expected_requested:
        raise PdfTreeExtractionRefusal("exclusion set is not exactly equal census refusal set")
    return census_binding, {
        "set": {
            "path": str(Path(exclusion_set).resolve(strict=True)),
            "sha256": exclusion_set_sha256,
            "receipt_sha256": exclusion_receipt_sha,
        },
        "requested_files": requested,
        "census_refusal_rows": refused_rows,
    }, included_files


def _refusal_class(detail: str) -> str:
    categories = (
        ("produced empty text", "EMPTY_TEXT"),
        ("could not be parsed", "PARSE_FAILED"),
        ("page count", "PAGE_BOUND"),
        ("decoded content", "DECODED_CONTENT_FAILED_OR_BOUND"),
        ("text extraction failed", "TEXT_EXTRACTION_FAILED"),
        ("output byte count", "OUTPUT_BOUND"),
    )
    for fragment, category in categories:
        if fragment in detail:
            return category
    return "OTHER_EXTRACTION_REFUSAL"


def census_pdf_tree_refusals(
    *,
    connector_receipt: Path,
    connector_receipt_sha256: str,
    report_path: Path,
    max_files: int = DEFAULT_MAX_FILES,
    max_pages: int = pdf_to_utf8.DEFAULT_MAX_PAGES,
    max_decoded_content_bytes: int = pdf_to_utf8.DEFAULT_MAX_DECODED_CONTENT_BYTES,
    max_output_bytes: int = pdf_to_utf8.DEFAULT_MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Attempt every receipt-listed PDF and write only a closed refusal census."""
    report_path = Path(report_path).absolute()
    if report_path.exists() or report_path.is_symlink():
        raise PdfTreeExtractionRefusal("census report already exists")
    if _is_reparse_or_symlink(report_path.parent) or not report_path.parent.is_dir():
        raise PdfTreeExtractionRefusal("census report parent must be a regular non-reparse directory")
    for label, value in (
        ("max_files", max_files),
        ("max_pages", max_pages),
        ("max_decoded_content_bytes", max_decoded_content_bytes),
        ("max_output_bytes", max_output_bytes),
    ):
        _positive_bound(label, value)
    source, source_root, source_files = _source_tree(
        Path(connector_receipt), connector_receipt_sha256, max_files=max_files
    )
    _require_outside_custodies(report_path, source_root, "census report")
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    for item in source_files:
        try:
            output, pages, decoded, audit = _extract_one(
                item["source_path"],
                max_pages=max_pages,
                max_decoded_content_bytes=max_decoded_content_bytes,
                max_output_bytes=max_output_bytes,
            )
            rows.append({
                "source_path": item["path"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "result": "PASS",
                "pages": pages,
                "decoded_content_bytes": decoded,
                "output_bytes": len(output),
                "output_sha256": _sha256(output),
                **audit,
            })
        except PdfTreeExtractionRefusal as error:
            detail = str(error)
            rows.append({
                "source_path": item["path"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "result": "REFUSED",
                "refusal_class": _refusal_class(detail),
                "detail": detail,
            })
        except MemoryError:
            raise
        except Exception as error:
            # A census exists to enumerate the complete refusal set in one pass.
            # Third-party parser exceptions may escape the adapter's expected
            # refusal type at lazy page-tree access; record that one file and
            # continue. Deliberately do not catch BaseException: interrupts and
            # fatal resource failures must still terminate the census.
            detail = f"{type(error).__name__}: {error!s}"[:320]
            rows.append({
                "source_path": item["path"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "result": "REFUSED",
                "refusal_class": "UNWRAPPED_EXTRACTOR_ERROR",
                "exception_class": type(error).__name__,
                "detail": detail,
            })
    refusal_count = sum(row["result"] == "REFUSED" for row in rows)
    extractor = _extractor_identity(
        max_files=max_files,
        max_pages=max_pages,
        max_decoded_content_bytes=max_decoded_content_bytes,
        max_output_bytes=max_output_bytes,
        max_total_pages=DEFAULT_MAX_TOTAL_PAGES,
        max_total_decoded_content_bytes=DEFAULT_MAX_TOTAL_DECODED_CONTENT_BYTES,
        max_total_output_bytes=DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
    )
    report: dict[str, Any] = {
        "schema": "ember-pdf-tree-refusal-census-v1",
        "result": "PASS" if refusal_count == 0 else "REFUSED",
        "claim_boundary": (
            "read-only extraction refusal census; no derived custody, admission, training, result, "
            "capability, or issue-closure credit"
        ),
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "source": {
            "connector_receipt_sha256": connector_receipt_sha256,
            "source": source.get("source"),
            "source_id": source.get("source_id"),
            "revision": source.get("revision"),
            "license": source.get("license"),
            "file_count": len(source_files),
            "total_bytes": sum(item["bytes"] for item in source_files),
            "manifest_sha256": source.get("sha256_manifest"),
        },
        "extractor": extractor,
        "files": rows,
        "totals": {
            "file_count": len(rows),
            "pass_count": len(rows) - refusal_count,
            "refusal_count": refusal_count,
        },
    }
    report["receipt_sha256"] = _sha256(_canonical(report))
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_exclusive(report_path, raw)
    reopened_raw, reopened = _read_json(report_path, "PDF tree refusal census")
    if reopened != report or _sha256(reopened_raw) != _sha256(raw):
        raise PdfTreeExtractionRefusal("published refusal census changed on reopen")
    return report


def _verify_at(
    *,
    custody_root: Path,
    expected_final_root: Path,
    receipt: dict[str, Any],
    connector_receipt: Path,
    connector_receipt_sha256: str,
) -> None:
    _validate_transform_shape(receipt)
    extractor = receipt.get("extractor")
    if not isinstance(extractor, dict):
        raise PdfTreeExtractionRefusal("PDF tree extractor identity is incomplete")
    expected_extractor = _extractor_identity(
        max_files=extractor.get("max_files"),
        max_pages=extractor.get("max_pages"),
        max_decoded_content_bytes=extractor.get("max_decoded_content_bytes"),
        max_output_bytes=extractor.get("max_output_bytes"),
        max_total_pages=extractor.get("max_total_pages"),
        max_total_decoded_content_bytes=extractor.get("max_total_decoded_content_bytes"),
        max_total_output_bytes=extractor.get("max_total_output_bytes"),
    )
    if extractor != expected_extractor:
        raise PdfTreeExtractionRefusal("PDF tree extractor identity changed")
    source, _, source_files = _source_tree(
        Path(connector_receipt), connector_receipt_sha256, max_files=extractor["max_files"]
    )
    expected_source = {
        "connector_receipt_sha256": connector_receipt_sha256,
        "connector": source.get("connector"),
        "source": source.get("source"),
        "source_id": source.get("source_id"),
        "canonical_url": source.get("canonical_url"),
        "revision": source.get("revision"),
        "license": source.get("license"),
        "license_spdx": _canonical_license(source.get("license")),
        "file_count": len(source_files),
        "total_bytes": sum(item["bytes"] for item in source_files),
        "manifest_sha256": source.get("sha256_manifest"),
    }
    if receipt.get("source") != expected_source:
        raise PdfTreeExtractionRefusal("PDF tree source identity changed")
    census = receipt.get("census")
    if (
        not isinstance(census, dict)
        or set(census) != {"path", "sha256", "receipt_sha256", "census_producer_sha256"}
        or not isinstance(census.get("path"), str)
        or _HEX.fullmatch(census.get("sha256", "")) is None
        or _HEX.fullmatch(census.get("receipt_sha256", "")) is None
        or _HEX.fullmatch(census.get("census_producer_sha256", "")) is None
    ):
        raise PdfTreeExtractionRefusal("PDF tree census binding is not closed")
    exclusions = receipt.get("exclusions")
    if not isinstance(exclusions, dict) or set(exclusions) != {
        "set",
        "requested_files",
        "census_refusal_rows",
    }:
        raise PdfTreeExtractionRefusal("PDF tree exclusion binding is not closed")
    exclusion_binding = exclusions.get("set")
    if exclusion_binding is not None and (
        not isinstance(exclusion_binding, dict)
        or set(exclusion_binding) != {"path", "sha256", "receipt_sha256"}
        or not isinstance(exclusion_binding.get("path"), str)
        or _HEX.fullmatch(exclusion_binding.get("sha256", "")) is None
        or _HEX.fullmatch(exclusion_binding.get("receipt_sha256", "")) is None
    ):
        raise PdfTreeExtractionRefusal("PDF tree exclusion set binding is not closed")
    expected_census, expected_exclusions, included_files = _load_census_binding(
        census_report=Path(census["path"]),
        census_report_sha256=census["sha256"],
        connector_receipt_sha256=connector_receipt_sha256,
        source_files=source_files,
        expected_extractor=expected_extractor,
        census_producer_sha256=census["census_producer_sha256"],
        exclusion_set=Path(exclusion_binding["path"]) if exclusion_binding is not None else None,
        exclusion_set_sha256=exclusion_binding["sha256"] if exclusion_binding is not None else None,
    )
    if census != expected_census or exclusions != expected_exclusions:
        raise PdfTreeExtractionRefusal("PDF tree census partition binding changed")
    claimed_files = receipt.get("files")
    if not isinstance(claimed_files, list) or len(claimed_files) != len(included_files):
        raise PdfTreeExtractionRefusal("PDF tree file map is incomplete")
    if [row.get("source_path") for row in claimed_files if isinstance(row, dict)] != [
        item["path"] for item in included_files
    ]:
        raise PdfTreeExtractionRefusal("PDF tree file map order is not canonical")
    by_source = {row.get("source_path"): row for row in claimed_files if isinstance(row, dict)}
    if len(by_source) != len(included_files):
        raise PdfTreeExtractionRefusal("PDF tree file map contains duplicates")
    actual_output_paths: set[str] = set()
    total_pages = total_decoded = total_output = 0
    for item in included_files:
        claim = by_source.get(item["path"])
        if not isinstance(claim, dict):
            raise PdfTreeExtractionRefusal("PDF tree source file is missing from the map")
        output_path = f"documents/{item['path']}.txt"
        if claim.get("output_path") != output_path:
            raise PdfTreeExtractionRefusal("PDF tree output mapping changed")
        output_bytes, pages, decoded, audit = _extract_one(
            item["source_path"],
            max_pages=extractor["max_pages"],
            max_decoded_content_bytes=extractor["max_decoded_content_bytes"],
            max_output_bytes=extractor["max_output_bytes"],
        )
        expected_claim = {
            "source_path": item["path"],
            "source_bytes": item["bytes"],
            "source_sha256": item["sha256"],
            "output_path": output_path,
            "output_bytes": len(output_bytes),
            "output_sha256": _sha256(output_bytes),
            "pages": pages,
            "decoded_content_bytes": decoded,
            **audit,
        }
        if claim != expected_claim:
            raise PdfTreeExtractionRefusal("PDF tree file receipt differs from re-extraction")
        stored = _regular_contained(custody_root, output_path, "extracted UTF-8 output").read_bytes()
        if stored != output_bytes:
            raise PdfTreeExtractionRefusal("PDF tree output differs from independent re-extraction")
        actual_output_paths.add(output_path)
        total_pages += pages
        total_decoded += decoded
        total_output += len(output_bytes)
    if (
        total_pages > extractor["max_total_pages"]
        or total_decoded > extractor["max_total_decoded_content_bytes"]
        or total_output > extractor["max_total_output_bytes"]
    ):
        raise PdfTreeExtractionRefusal("PDF tree aggregate extraction exceeds the closed bound")
    expected_totals = {
        "source_file_count": len(source_files),
        "file_count": len(included_files),
        "excluded_file_count": len(source_files) - len(included_files),
        "source_bytes": sum(item["bytes"] for item in included_files),
        "excluded_source_bytes": sum(item["bytes"] for item in source_files) - sum(item["bytes"] for item in included_files),
        "output_bytes": total_output,
        "pages": total_pages,
        "decoded_content_bytes": total_decoded,
    }
    if receipt.get("totals") != expected_totals:
        raise PdfTreeExtractionRefusal("PDF tree aggregate totals do not rederive")
    derived_path = custody_root / DERIVED_CONNECTOR
    derived_raw, derived = _read_json(derived_path, "derived connector receipt")
    derived_claim = receipt.get("derived_connector")
    if derived_claim != {
        "path": DERIVED_CONNECTOR,
        "sha256": _sha256(derived_raw),
        "manifest_sha256": derived.get("sha256_manifest"),
    }:
        raise PdfTreeExtractionRefusal("derived connector receipt identity changed")
    expected_derived_files = [
        {"path": row["output_path"], "bytes": row["output_bytes"], "sha256": row["output_sha256"]}
        for row in claimed_files
    ]
    expected_derived_files.sort(key=lambda row: row["path"])
    if (
        derived.get("schema") != "corpus-connector-receipt-v1"
        or derived.get("dest_root") != str(expected_final_root)
        or derived.get("license") != expected_source["license_spdx"]
        or derived.get("files") != expected_derived_files
        or derived.get("total_bytes") != total_output
        or derived.get("sha256_manifest")
        != _sha256("\n".join(sorted(row["sha256"] for row in expected_derived_files)).encode("utf-8"))
    ):
        raise PdfTreeExtractionRefusal("derived connector receipt does not rederive")
    if _data_paths(custody_root) != actual_output_paths:
        raise PdfTreeExtractionRefusal("PDF tree output custody contains missing or extra paths")
    expected_files = actual_output_paths | {DERIVED_CONNECTOR, TRANSFORM_RECEIPT}
    if _all_file_paths(custody_root) != expected_files:
        raise PdfTreeExtractionRefusal("PDF tree output custody contains missing or extra paths")
    if _all_directory_paths(custody_root) != _parent_directories(expected_files):
        raise PdfTreeExtractionRefusal("PDF tree output custody contains missing or extra paths")


def produce_pdf_tree_receipt_one_pass(
    *,
    connector_receipt: Path,
    connector_receipt_sha256: str,
    census_report: Path,
    output_dir: Path,
    workers: int,
    max_files: int = DEFAULT_MAX_FILES,
    max_pages: int = pdf_to_utf8.DEFAULT_MAX_PAGES,
    max_decoded_content_bytes: int = pdf_to_utf8.DEFAULT_MAX_DECODED_CONTENT_BYTES,
    max_output_bytes: int = pdf_to_utf8.DEFAULT_MAX_OUTPUT_BYTES,
    max_total_pages: int = DEFAULT_MAX_TOTAL_PAGES,
    max_total_decoded_content_bytes: int = DEFAULT_MAX_TOTAL_DECODED_CONTENT_BYTES,
    max_total_output_bytes: int = DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Extract once, sealing independently checkable census and transform receipts."""
    output_dir = Path(output_dir).absolute()
    census_report = Path(census_report).absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise PdfTreeExtractionRefusal("output directory already exists")
    if census_report.exists() or census_report.is_symlink():
        raise PdfTreeExtractionRefusal("census report already exists")
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 8:
        raise PdfTreeExtractionRefusal("workers must be an integer from 1 through 8")
    for path, label in ((output_dir.parent, "output parent"), (census_report.parent, "census report parent")):
        if _is_reparse_or_symlink(path) or not path.is_dir():
            raise PdfTreeExtractionRefusal(f"{label} must be a regular non-reparse directory")
    for label, value in (
        ("max_files", max_files),
        ("max_pages", max_pages),
        ("max_decoded_content_bytes", max_decoded_content_bytes),
        ("max_output_bytes", max_output_bytes),
        ("max_total_pages", max_total_pages),
        ("max_total_decoded_content_bytes", max_total_decoded_content_bytes),
        ("max_total_output_bytes", max_total_output_bytes),
    ):
        _positive_bound(label, value)
    source, source_roots, source_files = _source_tree(
        Path(connector_receipt), connector_receipt_sha256, max_files=max_files
    )
    _require_outside_custodies(census_report, source_roots, "census report")
    _require_outside_custodies(output_dir, source_roots, "output directory")
    extractor = _extractor_identity(
        max_files=max_files,
        max_pages=max_pages,
        max_decoded_content_bytes=max_decoded_content_bytes,
        max_output_bytes=max_output_bytes,
        max_total_pages=max_total_pages,
        max_total_decoded_content_bytes=max_total_decoded_content_bytes,
        max_total_output_bytes=max_total_output_bytes,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    staging = output_dir.with_name(f".{output_dir.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir()

    def extract(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            output_bytes, pages, decoded, audit = _extract_one(
                item["source_path"],
                max_pages=max_pages,
                max_decoded_content_bytes=max_decoded_content_bytes,
                max_output_bytes=max_output_bytes,
            )
            output_path = f"documents/{item['path']}.txt"
            _write_exclusive(staging / Path(output_path), output_bytes)
            census_row = {
                "source_path": item["path"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "result": "PASS",
                "pages": pages,
                "decoded_content_bytes": decoded,
                "output_bytes": len(output_bytes),
                "output_sha256": _sha256(output_bytes),
                **audit,
            }
            transform_row = {
                key: value for key, value in census_row.items() if key != "result"
            }
            transform_row["output_path"] = output_path
            return census_row, transform_row
        except PdfTreeExtractionRefusal as error:
            detail = str(error)
            return ({
                "source_path": item["path"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "result": "REFUSED",
                "refusal_class": _refusal_class(detail),
                "detail": detail,
            }, None)
        except MemoryError:
            raise
        except Exception as error:
            detail = f"{type(error).__name__}: {error!s}"[:320]
            return ({
                "source_path": item["path"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "result": "REFUSED",
                "refusal_class": "UNWRAPPED_EXTRACTOR_ERROR",
                "exception_class": type(error).__name__,
                "detail": detail,
            }, None)

    published = False
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-tree") as executor:
            results = list(executor.map(extract, source_files))
        census_rows = [row for row, _ in results]
        transform_rows = [row for _, row in results if row is not None]
        refusal_count = sum(row["result"] == "REFUSED" for row in census_rows)
        census: dict[str, Any] = {
            "schema": "ember-pdf-tree-refusal-census-v1",
            "result": "PASS" if refusal_count == 0 else "REFUSED",
            "claim_boundary": (
                "one-pass extraction refusal census; no admission, training, result, capability, "
                "or issue-closure credit"
            ),
            "started_at": started_at,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - started,
            "source": {
                "connector_receipt_sha256": connector_receipt_sha256,
                "source": source.get("source"),
                "source_id": source.get("source_id"),
                "revision": source.get("revision"),
                "license": source.get("license"),
                "file_count": len(source_files),
                "total_bytes": sum(item["bytes"] for item in source_files),
                "manifest_sha256": source.get("sha256_manifest"),
            },
            "extractor": extractor,
            "files": census_rows,
            "totals": {
                "file_count": len(census_rows),
                "pass_count": len(census_rows) - refusal_count,
                "refusal_count": refusal_count,
            },
        }
        census["receipt_sha256"] = _sha256(_canonical(census))
        census_raw = (json.dumps(census, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        _write_exclusive(census_report, census_raw)
        if refusal_count:
            raise PdfTreeExtractionRefusal("one-pass refusal census is nonzero; transform not published")

        total_pages = sum(row["pages"] for row in transform_rows)
        total_decoded = sum(row["decoded_content_bytes"] for row in transform_rows)
        total_output = sum(row["output_bytes"] for row in transform_rows)
        if (
            total_pages > max_total_pages
            or total_decoded > max_total_decoded_content_bytes
            or total_output > max_total_output_bytes
        ):
            raise PdfTreeExtractionRefusal("PDF tree aggregate extraction exceeds the closed bound")
        census_binding, exclusions, included_files = _load_census_binding(
            census_report=census_report,
            census_report_sha256=_sha256(census_raw),
            connector_receipt_sha256=connector_receipt_sha256,
            source_files=source_files,
            expected_extractor=extractor,
            census_producer_sha256=extractor["producer_sha256"],
        )
        if len(included_files) != len(source_files):
            raise PdfTreeExtractionRefusal("one-pass census partition changed")
        derived_at = datetime.now(timezone.utc).isoformat()
        derived_files = sorted(
            [
                {"path": row["output_path"], "bytes": row["output_bytes"], "sha256": row["output_sha256"]}
                for row in transform_rows
            ],
            key=lambda row: row["path"],
        )
        derived = {
            **source,
            "source": "derived_pdf_text_custody",
            "source_id": f"{source.get('source_id')}+pdf-tree-text-v2",
            "license": _canonical_license(source.get("license")),
            "license_evidence": "deterministic one-pass PDF-to-UTF-8 derivation with bound census",
            "revision": f"{source.get('revision')}+pdf-tree-text-v2",
            "files": derived_files,
            "total_bytes": total_output,
            "sha256_manifest": _sha256("\n".join(sorted(row["sha256"] for row in derived_files)).encode("utf-8")),
            "fetched_at": derived_at,
            "connector": {"name": "pdf_tree_to_utf8", "version": "v2-one-pass"},
            "l3_statement": "deterministic local derivation; no network fetch and no model-mediated selection",
            "dest_root": str(output_dir),
            "notes": f"ONE_PASS original_connector_receipt_sha256={connector_receipt_sha256}; files={len(transform_rows)}",
        }
        derived_raw = (json.dumps(derived, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        _write_exclusive(staging / DERIVED_CONNECTOR, derived_raw)
        receipt: dict[str, Any] = {
            "schema": SCHEMA,
            "result": "VERIFIED",
            "claim_boundary": "deterministic one-pass PDF-tree-to-UTF-8 transform only; no admission, training, result, capability, or issue-closure credit",
            "source": {
                "connector_receipt_sha256": connector_receipt_sha256,
                "connector": source.get("connector"),
                "source": source.get("source"),
                "source_id": source.get("source_id"),
                "canonical_url": source.get("canonical_url"),
                "revision": source.get("revision"),
                "license": source.get("license"),
                "license_spdx": _canonical_license(source.get("license")),
                "file_count": len(source_files),
                "total_bytes": sum(item["bytes"] for item in source_files),
                "manifest_sha256": source.get("sha256_manifest"),
            },
            "extractor": extractor,
            "census": census_binding,
            "exclusions": exclusions,
            "files": transform_rows,
            "totals": {
                "source_file_count": len(source_files),
                "file_count": len(transform_rows),
                "excluded_file_count": 0,
                "source_bytes": sum(item["bytes"] for item in source_files),
                "excluded_source_bytes": 0,
                "output_bytes": total_output,
                "pages": total_pages,
                "decoded_content_bytes": total_decoded,
            },
            "derived_connector": {
                "path": DERIVED_CONNECTOR,
                "sha256": _sha256(derived_raw),
                "manifest_sha256": derived["sha256_manifest"],
            },
        }
        receipt["receipt_sha256"] = _sha256(_canonical(receipt))
        receipt_raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        _write_exclusive(staging / TRANSFORM_RECEIPT, receipt_raw)
        _validate_transform_shape(receipt)
        for row in transform_rows:
            stored = _regular_contained(staging, row["output_path"], "extracted UTF-8 output")
            if stored.stat().st_size != row["output_bytes"] or _sha256_file(stored) != row["output_sha256"]:
                raise PdfTreeExtractionRefusal("one-pass stored output changed before publication")
        os.rename(staging, output_dir)
        published = True
        if _sha256_file(output_dir / TRANSFORM_RECEIPT) != _sha256(receipt_raw):
            raise PdfTreeExtractionRefusal("published one-pass receipt changed on reopen")
        return receipt
    except BaseException:
        shutil.rmtree(output_dir if published else staging, ignore_errors=True)
        raise


def produce_pdf_tree_receipt(
    *,
    connector_receipt: Path,
    connector_receipt_sha256: str,
    census_report: Path,
    census_report_sha256: str,
    exclusion_set: Path | None = None,
    exclusion_set_sha256: str | None = None,
    output_dir: Path,
    census_producer_sha256: str | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_pages: int = pdf_to_utf8.DEFAULT_MAX_PAGES,
    max_decoded_content_bytes: int = pdf_to_utf8.DEFAULT_MAX_DECODED_CONTENT_BYTES,
    max_output_bytes: int = pdf_to_utf8.DEFAULT_MAX_OUTPUT_BYTES,
    max_total_pages: int = DEFAULT_MAX_TOTAL_PAGES,
    max_total_decoded_content_bytes: int = DEFAULT_MAX_TOTAL_DECODED_CONTENT_BYTES,
    max_total_output_bytes: int = DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
) -> dict[str, Any]:
    output_dir = Path(output_dir).absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise PdfTreeExtractionRefusal("output directory already exists")
    if _is_reparse_or_symlink(output_dir.parent) or not output_dir.parent.is_dir():
        raise PdfTreeExtractionRefusal("output parent must be a regular non-reparse directory")
    for label, value in (
        ("max_files", max_files),
        ("max_pages", max_pages),
        ("max_decoded_content_bytes", max_decoded_content_bytes),
        ("max_output_bytes", max_output_bytes),
        ("max_total_pages", max_total_pages),
        ("max_total_decoded_content_bytes", max_total_decoded_content_bytes),
        ("max_total_output_bytes", max_total_output_bytes),
    ):
        _positive_bound(label, value)
    source, source_root, source_files = _source_tree(
        Path(connector_receipt), connector_receipt_sha256, max_files=max_files
    )
    extractor = _extractor_identity(
        max_files=max_files,
        max_pages=max_pages,
        max_decoded_content_bytes=max_decoded_content_bytes,
        max_output_bytes=max_output_bytes,
        max_total_pages=max_total_pages,
        max_total_decoded_content_bytes=max_total_decoded_content_bytes,
        max_total_output_bytes=max_total_output_bytes,
    )
    _require_outside_custodies(Path(census_report), source_root, "census report")
    census, exclusions, included_files = _load_census_binding(
        census_report=Path(census_report),
        census_report_sha256=census_report_sha256,
        connector_receipt_sha256=connector_receipt_sha256,
        source_files=source_files,
        expected_extractor=extractor,
        census_producer_sha256=census_producer_sha256,
        exclusion_set=Path(exclusion_set) if exclusion_set is not None else None,
        exclusion_set_sha256=exclusion_set_sha256,
    )
    staging = output_dir.with_name(f".{output_dir.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir()
    published = False
    try:
        rows: list[dict[str, Any]] = []
        total_pages = total_decoded = total_output = 0
        for item in included_files:
            output_bytes, pages, decoded, audit = _extract_one(
                item["source_path"],
                max_pages=max_pages,
                max_decoded_content_bytes=max_decoded_content_bytes,
                max_output_bytes=max_output_bytes,
            )
            total_pages += pages
            total_decoded += decoded
            total_output += len(output_bytes)
            if (
                total_pages > max_total_pages
                or total_decoded > max_total_decoded_content_bytes
                or total_output > max_total_output_bytes
            ):
                raise PdfTreeExtractionRefusal("PDF tree aggregate extraction exceeds the closed bound")
            output_path = f"documents/{item['path']}.txt"
            _write_exclusive(staging / Path(output_path), output_bytes)
            rows.append({
                "source_path": item["path"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "output_path": output_path,
                "output_bytes": len(output_bytes),
                "output_sha256": _sha256(output_bytes),
                "pages": pages,
                "decoded_content_bytes": decoded,
                **audit,
            })
        derived_at = datetime.now(timezone.utc).isoformat()
        derived_files = [
            {"path": row["output_path"], "bytes": row["output_bytes"], "sha256": row["output_sha256"]}
            for row in rows
        ]
        derived_files.sort(key=lambda row: row["path"])
        derived = {
            **source,
            "source": "derived_pdf_text_custody",
            "source_id": f"{source.get('source_id')}+pdf-tree-text-v2",
            "license": _canonical_license(source.get("license")),
            "license_evidence": (
                "deterministic local PDF-to-UTF-8 derivation; exact original connector and transform "
                "receipts are bound under _manifests"
            ),
            "revision": f"{source.get('revision')}+pdf-tree-text-v2",
            "files": derived_files,
            "total_bytes": total_output,
            "sha256_manifest": _sha256(
                "\n".join(sorted(row["sha256"] for row in derived_files)).encode("utf-8")
            ),
            "fetched_at": derived_at,
            "connector": {"name": "pdf_tree_to_utf8", "version": "v2"},
            "l3_statement": "deterministic local derivation; no network fetch and no model-mediated selection",
            "dest_root": str(output_dir),
            "notes": (
                f"DERIVED_PDF_TEXT original_connector_receipt_sha256={connector_receipt_sha256}; "
                f"transform_receipt={TRANSFORM_RECEIPT}; "
                f"included_files={len(included_files)}; excluded_files={len(source_files) - len(included_files)}"
            ),
        }
        derived_raw = (json.dumps(derived, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        _write_exclusive(staging / DERIVED_CONNECTOR, derived_raw)
        receipt: dict[str, Any] = {
            "schema": SCHEMA,
            "result": "VERIFIED",
            "claim_boundary": (
                "deterministic PDF-tree-to-UTF-8 transform only; no acquisition, admission, training, "
                "result, capability, or issue-closure credit"
            ),
            "source": {
                "connector_receipt_sha256": connector_receipt_sha256,
                "connector": source.get("connector"),
                "source": source.get("source"),
                "source_id": source.get("source_id"),
                "canonical_url": source.get("canonical_url"),
                "revision": source.get("revision"),
                "license": source.get("license"),
                "license_spdx": _canonical_license(source.get("license")),
                "file_count": len(source_files),
                "total_bytes": sum(item["bytes"] for item in source_files),
                "manifest_sha256": source.get("sha256_manifest"),
            },
            "extractor": extractor,
            "census": census,
            "exclusions": exclusions,
            "files": rows,
            "totals": {
                "source_file_count": len(source_files),
                "file_count": len(rows),
                "excluded_file_count": len(source_files) - len(included_files),
                "source_bytes": sum(item["bytes"] for item in included_files),
                "excluded_source_bytes": sum(item["bytes"] for item in source_files)
                - sum(item["bytes"] for item in included_files),
                "output_bytes": total_output,
                "pages": total_pages,
                "decoded_content_bytes": total_decoded,
            },
            "derived_connector": {
                "path": DERIVED_CONNECTOR,
                "sha256": _sha256(derived_raw),
                "manifest_sha256": derived["sha256_manifest"],
            },
        }
        receipt["receipt_sha256"] = _sha256(_canonical(receipt))
        receipt_raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        _write_exclusive(staging / TRANSFORM_RECEIPT, receipt_raw)
        _verify_at(
            custody_root=staging,
            expected_final_root=output_dir,
            receipt=receipt,
            connector_receipt=Path(connector_receipt),
            connector_receipt_sha256=connector_receipt_sha256,
        )
        os.rename(staging, output_dir)
        published = True
        expected_output_paths = {row["output_path"] for row in rows}
        expected_published_files = expected_output_paths | {DERIVED_CONNECTOR, TRANSFORM_RECEIPT}
        if (
            _sha256_file(output_dir / TRANSFORM_RECEIPT) != _sha256(receipt_raw)
            or _sha256_file(output_dir / DERIVED_CONNECTOR) != _sha256(derived_raw)
            or _data_paths(output_dir) != expected_output_paths
            or _all_file_paths(output_dir) != expected_published_files
            or _all_directory_paths(output_dir) != _parent_directories(expected_published_files)
        ):
            raise PdfTreeExtractionRefusal("published PDF tree custody changed on reopen")
        return receipt
    except BaseException:
        shutil.rmtree(output_dir if published else staging, ignore_errors=True)
        raise


def verify_pdf_tree_receipt(
    *,
    receipt_path: Path,
    connector_receipt: Path,
    connector_receipt_sha256: str,
) -> dict[str, Any]:
    receipt_path = Path(receipt_path)
    _, receipt = _read_json(receipt_path, "PDF tree extraction receipt")
    custody_root = receipt_path.parent.parent
    if _is_reparse_or_symlink(custody_root) or not custody_root.is_dir():
        raise PdfTreeExtractionRefusal("PDF tree output custody is not a regular directory")
    _verify_at(
        custody_root=custody_root,
        expected_final_root=custody_root.absolute(),
        receipt=receipt,
        connector_receipt=Path(connector_receipt),
        connector_receipt_sha256=connector_receipt_sha256,
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connector-receipt", type=Path, required=True)
    parser.add_argument("--connector-receipt-sha256", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--census-report", type=Path)
    parser.add_argument("--census-report-sha256")
    parser.add_argument("--census-producer-sha256")
    parser.add_argument("--exclusion-set", type=Path)
    parser.add_argument("--exclusion-set-sha256")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--one-pass", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.one_pass:
        if (
            args.output_dir is None
            or args.census_report is None
            or args.census_report_sha256 is not None
            or args.census_producer_sha256 is not None
            or args.exclusion_set is not None
            or args.exclusion_set_sha256 is not None
            or args.verify
        ):
            parser.error("--one-pass requires only --census-report, --output-dir, and optional --workers")
        receipt = produce_pdf_tree_receipt_one_pass(
            connector_receipt=args.connector_receipt,
            connector_receipt_sha256=args.connector_receipt_sha256,
            census_report=args.census_report,
            output_dir=args.output_dir,
            workers=args.workers,
        )
    elif args.workers != 1:
        parser.error("--workers is only valid with --one-pass")
    elif args.census_report is not None and args.output_dir is None:
        if (
            args.census_report_sha256 is not None
            or args.census_producer_sha256 is not None
            or args.exclusion_set is not None
            or args.exclusion_set_sha256 is not None
            or args.verify
        ):
            parser.error("census generation cannot be combined with transform bindings or --verify")
        receipt = census_pdf_tree_refusals(
            connector_receipt=args.connector_receipt,
            connector_receipt_sha256=args.connector_receipt_sha256,
            report_path=args.census_report,
        )
    elif args.output_dir is None:
        parser.error("--output-dir is required unless --census-report is used")
    elif args.verify:
        if args.census_producer_sha256 is not None:
            parser.error("--census-producer-sha256 is recorded by transform and cannot be supplied to --verify")
        receipt = verify_pdf_tree_receipt(
            receipt_path=args.output_dir / TRANSFORM_RECEIPT,
            connector_receipt=args.connector_receipt,
            connector_receipt_sha256=args.connector_receipt_sha256,
        )
    else:
        if args.census_report is None or args.census_report_sha256 is None:
            parser.error("transform requires --census-report and --census-report-sha256")
        receipt = produce_pdf_tree_receipt(
            connector_receipt=args.connector_receipt,
            connector_receipt_sha256=args.connector_receipt_sha256,
            census_report=args.census_report,
            census_report_sha256=args.census_report_sha256,
            census_producer_sha256=args.census_producer_sha256,
            exclusion_set=args.exclusion_set,
            exclusion_set_sha256=args.exclusion_set_sha256,
            output_dir=args.output_dir,
        )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
