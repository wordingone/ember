#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze MMMU row/image input digests from already pinned validation bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-root", required=True, type=Path)
    parser.add_argument("--validation-freeze", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    try:
        freeze_bytes = arguments.validation_freeze.read_bytes()
        freeze = json.loads(freeze_bytes.decode("utf-8"))
        if not isinstance(freeze, dict) or freeze.get("schema_version") != "ember-restart-mmmu-validation-freeze-v1" or freeze.get("benchmark_id") != "MMMU" or not isinstance(freeze.get("upstream_revision"), str) or len(freeze["upstream_revision"]) != 40:
            raise ValueError("invalid MMMU validation freeze")
        expected_files = freeze.get("validation_parquet_files")
        expected_rows = freeze.get("validation_row_count")
        if not isinstance(expected_files, list) or not expected_files or not isinstance(expected_rows, int) or expected_rows <= 0:
            raise ValueError("MMMU validation freeze lacks file or row evidence")
        observed_files = sorted(arguments.validation_root.glob("*/validation-*.parquet"))
        expected_paths = [entry.get("path") for entry in expected_files if isinstance(entry, dict)]
        if len(expected_paths) != len(expected_files) or expected_paths != sorted(expected_paths) or [path.relative_to(arguments.validation_root).as_posix() for path in observed_files] != expected_paths:
            raise ValueError("MMMU validation parquet paths do not match frozen file index")
        rows = []
        for path, expected in zip(observed_files, expected_files):
            data = path.read_bytes()
            if expected.get("sha256") != sha256(data):
                raise ValueError("MMMU validation parquet bytes do not match frozen file index")
            table = pq.read_table(pa.BufferReader(data))
            image_columns = sorted((name for name in table.column_names if name.startswith("image_")), key=lambda name: int(name.split("_", 1)[1]))
            if not image_columns or any(name not in table.column_names for name in ("id", "question", "options")):
                raise ValueError("MMMU validation parquet lacks canonical image inputs")
            for row in table.select(["id", "question", "options", *image_columns]).to_pylist():
                identifier, question, options = row.get("id"), row.get("question"), row.get("options")
                if not all(isinstance(value, str) and value for value in (identifier, question, options)):
                    raise ValueError("MMMU rows require nonempty id, question, and options")
                image_hashes = []
                for column in image_columns:
                    image = row.get(column)
                    if image is None:
                        continue
                    if not isinstance(image, dict) or not isinstance(image.get("bytes"), bytes) or not image["bytes"]:
                        raise ValueError("MMMU image payload must be nonempty bytes")
                    image_hashes.append(sha256(image["bytes"]))
                if not image_hashes:
                    raise ValueError("MMMU row has no image payload")
                rows.append({"id": identifier, "image_sha256s": image_hashes, "input_sha256": canonical_digest({"id": identifier, "question": question, "options": options, "image_sha256s": image_hashes})})
        if len(rows) != expected_rows or len({row["id"] for row in rows}) != len(rows):
            raise ValueError("MMMU row count or identifiers do not match frozen validation set")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, pa.ArrowException, ValueError) as error:
        parser.error(str(error))
    payload = {"schema_version": "ember-restart-mmmu-image-input-freeze-v1", "result": "PREFLIGHT_ONLY", "claim_status": "FROZEN_MMMU_IMAGE_INPUTS_NO_CHECKPOINT_BOUND_PREDICTIONS", "benchmark_id": "MMMU", "upstream_revision": freeze["upstream_revision"], "validation_freeze_sha256": sha256(freeze_bytes), "row_count": len(rows), "rows": rows}
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, prefix=arguments.output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())