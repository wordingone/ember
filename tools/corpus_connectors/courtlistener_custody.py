#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind CourtListener's wave-1 bytes to a truthful content disposition.

The existing connector ``manifest.jsonl`` is deliberately kept in its flat
L4 compatibility shape.  This sidecar adds the missing *content* authority:
the source bytes are authenticated against that manifest, a bounded schema
sample is recorded, and metadata exports are excluded from prose-gap yield.
It never downloads or rewrites corpus bytes.
"""
from __future__ import annotations

import argparse
import bz2
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

ANNOTATION_SCHEMA = "corpus-courtlistener-content-annotation-v1"
RESULT = "CONTENT_CLASSIFIED"
PROSE_FIELDS = frozenset(
    {
        "arguments",
        "body",
        "content",
        "disposition",
        "headmatter",
        "headnotes",
        "history",
        "html",
        "summary",
        "syllabus",
        "text",
    }
)
MANIFEST_FIELDS = frozenset(
    {
        "source_url",
        "sha256",
        "bytes",
        "license",
        "human_provenance_basis",
        "fetched_ts",
        "selection_rule",
    }
)
FILE_FIELDS = frozenset(
    {
        "path",
        "source_url",
        "sha256",
        "bytes",
        "selection_rule",
        "content_class",
        "classification_basis",
        "header_sha256",
        "sample_rows",
        "nonempty_prose_cells",
        "prose_gap_eligible",
        "usable_prose_bytes",
    }
)
SAMPLE_LINE_BYTES = 1 << 20
TOP_FIELDS = frozenset(
    {
        "schema_version",
        "result",
        "source_id",
        "manifest_sha256",
        "prose_gap_admission",
        "files",
        "projection",
        "annotation_sha256",
    }
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_without_annotation_hash(annotation: dict) -> bytes:
    payload = {key: value for key, value in annotation.items() if key != "annotation_sha256"}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _read_manifest(path: Path) -> tuple[list[dict], bytes]:
    raw = path.read_bytes()
    rows: list[dict] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"manifest line {line_number} is not UTF-8 JSON") from exc
        if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
            raise ValueError(f"manifest row schema is invalid at line {line_number}")
        rows.append(value)
    if not rows:
        raise ValueError("CourtListener manifest is empty")
    return rows, raw


def _safe_source_path(root: Path, source_url: str) -> tuple[str, Path]:
    if not isinstance(source_url, str) or not source_url:
        raise ValueError("manifest source_url is invalid")
    url_path = urlparse(source_url).path
    if not url_path or "\\" in url_path:
        raise ValueError("manifest source_url does not identify one basename")
    url_parts = PurePosixPath(url_path).parts
    if any(part in {".", ".."} for part in url_parts):
        raise ValueError("manifest source_url does not identify one basename")
    name = url_parts[-1] if url_parts else ""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("manifest source_url does not identify one basename")
    path = (root / name).resolve()
    root_resolved = root.resolve()
    if path.parent != root_resolved:
        raise ValueError("CourtListener source escapes its custody root")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"CourtListener source is not a regular file: {name}")
    return name, path


def _open_text(path: Path):
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", newline="")
    return path.open("rt", encoding="utf-8", newline="")


def _sample_schema(path: Path, sample_rows: int) -> tuple[list[str], int, int]:
    if type(sample_rows) is not int or sample_rows <= 0 or sample_rows > 1024:
        raise ValueError("sample_rows must be an integer in 1..1024")
    with _open_text(path) as stream:
        header_line = stream.readline(SAMPLE_LINE_BYTES)
        if not header_line:
            raise ValueError("CourtListener source has no header")
        if "\n" not in header_line and len(header_line) >= SAMPLE_LINE_BYTES:
            raise ValueError("CourtListener source header exceeds bounded sample")
        try:
            header = next(csv.reader([header_line]))
        except (csv.Error, StopIteration) as exc:
            raise ValueError("CourtListener source header is not valid CSV") from exc
        if not header or any(not isinstance(column, str) for column in header):
            raise ValueError("CourtListener source header is invalid")
        header = [column.strip() for column in header]
        header = [column if column else f"__unnamed_{index}" for index, column in enumerate(header)]
        if len(set(header)) != len(header):
            raise ValueError("CourtListener source header has duplicate columns")
        prose_indexes = [index for index, column in enumerate(header) if column in PROSE_FIELDS]
        nonempty = 0
        observed = 0
        for _ in range(sample_rows):
            line = stream.readline(SAMPLE_LINE_BYTES)
            if not line:
                break
            if "\n" not in line and len(line) >= SAMPLE_LINE_BYTES:
                break
            try:
                row = next(csv.reader([line]))
            except (csv.Error, StopIteration):
                break
            if observed >= sample_rows:
                break
            observed += 1
            for index in prose_indexes:
                if index < len(row) and row[index].strip():
                    nonempty += 1
    return header, observed, nonempty


def build_content_annotation(manifest_path: Path, data_root: Path, *, sample_rows: int = 64) -> dict:
    manifest_path = Path(manifest_path)
    data_root = Path(data_root)
    rows, manifest_bytes = _read_manifest(manifest_path)
    files = []
    seen_paths: set[str] = set()
    raw_bytes = 0
    for row in rows:
        name, path = _safe_source_path(data_root, row["source_url"])
        if name in seen_paths:
            raise ValueError(f"duplicate CourtListener source path: {name}")
        seen_paths.add(name)
        actual_bytes = path.stat().st_size
        if type(row["bytes"]) is not int or row["bytes"] < 0 or actual_bytes != row["bytes"]:
            raise ValueError(f"source byte count mismatch for {name}")
        if not isinstance(row["sha256"], str) or len(row["sha256"]) != 64 or row["sha256"] != row["sha256"].lower():
            raise ValueError(f"source hash is invalid for {name}")
        actual_sha256 = _sha256_file(path)
        if actual_sha256 != row["sha256"]:
            raise ValueError(f"source hash mismatch for {name}")
        header, sampled, nonempty = _sample_schema(path, sample_rows)
        if nonempty:
            content_class = "TEXT_BEARING_REVIEW_REQUIRED"
        elif any(column in PROSE_FIELDS for column in header):
            content_class = "METADATA_ONLY_NO_PROSE_OBSERVED"
        else:
            content_class = "STRUCTURED_METADATA"
        files.append(
            {
                "path": name,
                "source_url": row["source_url"],
                "sha256": row["sha256"],
                "bytes": row["bytes"],
                "selection_rule": row["selection_rule"],
                "content_class": content_class,
                "classification_basis": "header_and_bounded_sample; no model-mediated filter",
                "header_sha256": _sha256_bytes(("\n".join(header) + "\n").encode("utf-8")),
                "sample_rows": sampled,
                "nonempty_prose_cells": nonempty,
                "prose_gap_eligible": False,
                "usable_prose_bytes": 0,
            }
        )
        raw_bytes += row["bytes"]
    files.sort(key=lambda item: item["path"])
    annotation = {
        "schema_version": ANNOTATION_SCHEMA,
        "result": RESULT,
        "source_id": "courtlistener-wave-1",
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "prose_gap_admission": "NOT_ADMITTED",
        "files": files,
        "projection": {
            "raw_bytes": raw_bytes,
            "eligible_prose_bytes": 0,
            "eligible_sources": [],
        },
    }
    annotation["annotation_sha256"] = _sha256_bytes(_canonical_without_annotation_hash(annotation))
    return annotation


def _validate_shape(annotation: dict) -> None:
    if not isinstance(annotation, dict) or set(annotation) != TOP_FIELDS:
        raise ValueError("content annotation schema is invalid")
    if annotation["schema_version"] != ANNOTATION_SCHEMA or annotation["result"] != RESULT:
        raise ValueError("content annotation schema version is invalid")
    if annotation["prose_gap_admission"] != "NOT_ADMITTED":
        raise ValueError("CourtListener prose-gap admission is not fail-closed")
    if not isinstance(annotation["files"], list) or not annotation["files"]:
        raise ValueError("content annotation files are invalid")
    for item in annotation["files"]:
        if not isinstance(item, dict) or set(item) != FILE_FIELDS:
            raise ValueError("content annotation file row schema is invalid")
    if not isinstance(annotation["projection"], dict) or set(annotation["projection"]) != {"raw_bytes", "eligible_prose_bytes", "eligible_sources"}:
        raise ValueError("content annotation projection is invalid")


def validate_content_annotation(annotation_path: Path, manifest_path: Path, data_root: Path) -> dict:
    annotation_path = Path(annotation_path)
    try:
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("content annotation cannot be read") from exc
    _validate_shape(annotation)
    expected_hash = _sha256_bytes(_canonical_without_annotation_hash(annotation))
    if annotation["annotation_sha256"] != expected_hash:
        raise ValueError("content annotation hash mismatch")
    sample_rows = annotation["files"][0].get("sample_rows")
    if type(sample_rows) is not int or sample_rows <= 0 or any(item.get("sample_rows") != sample_rows for item in annotation["files"]):
        raise ValueError("content annotation sample bound is invalid")
    expected = build_content_annotation(Path(manifest_path), Path(data_root), sample_rows=sample_rows)
    if annotation["manifest_sha256"] != expected["manifest_sha256"]:
        raise ValueError("content annotation manifest binding mismatch")
    if annotation["files"] != expected["files"]:
        raise ValueError("content annotation file projection mismatch")
    if annotation["projection"] != expected["projection"]:
        raise ValueError("content annotation projection mismatch")
    return annotation


def prose_gap_projection(annotation: dict) -> dict:
    _validate_shape(annotation)
    projection = annotation["projection"]
    if projection["eligible_prose_bytes"] != 0 or projection["eligible_sources"] != []:
        raise ValueError("CourtListener prose-gap projection is not excluded")
    return {
        "eligible_prose_bytes": projection["eligible_prose_bytes"],
        "eligible_sources": list(projection["eligible_sources"]),
    }


def write_content_annotation(manifest_path: Path, data_root: Path, output_path: Path, *, sample_rows: int = 64) -> Path:
    data_root = Path(data_root).resolve()
    output_path = Path(output_path)
    if output_path.exists():
        raise ValueError(f"content annotation already exists: {output_path.name}")
    if output_path.resolve().parent != data_root:
        raise ValueError("content annotation output must stay inside its custody root")
    annotation = build_content_annotation(manifest_path, data_root, sample_rows=sample_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=output_path.name + ".", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(annotation, indent=2, sort_keys=True) + "\n")
        Path(temp_name).replace(output_path)
    except Exception:
        try:
            Path(temp_name).unlink()
        except OSError:
            pass
        raise
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Annotate CourtListener wave-1 content without downloading or filtering it.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-rows", type=int, default=64)
    args = parser.parse_args(argv)
    try:
        path = write_content_annotation(args.manifest, args.data_root, args.output, sample_rows=args.sample_rows)
    except Exception as exc:
        print(f"BLOCKED {exc}")
        return 1
    print(f"RECEIPT {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
