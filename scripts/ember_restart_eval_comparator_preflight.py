#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail closed unless target and pinned open comparator share evaluator pins."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


FIELDS = ("capability", "benchmark_id", "benchmark_version", "split_sha256", "harness_sha256", "protocol_sha256")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _read_json(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid preflight JSON ({name}): {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} preflight must be an object")
    return value


def _require_preflight(name: str, payload: dict[str, object]) -> None:
    if payload.get("result") != "PREFLIGHT_ONLY" or payload.get("admission") != "NOT_ELIGIBLE":
        raise ValueError(f"{name} must be a non-admissible evaluator preflight")
    checkpoint = payload.get("subject_checkpoint_sha256")
    if not isinstance(checkpoint, str) or not SHA256.fullmatch(checkpoint):
        raise ValueError(f"{name} requires a checkpoint hash")
    for field in FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} requires {field}")
        if field.endswith("_sha256") and not SHA256.fullmatch(value):
            raise ValueError(f"{name} requires lowercase {field}")


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--comparator", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    try:
        target = _read_json(arguments.target, "target")
        comparator = _read_json(arguments.comparator, "comparator")
        _require_preflight("target", target)
        _require_preflight("comparator", comparator)
        if comparator.get("subject_kind") != "open_comparator" or comparator.get("comparator_size_class") not in ("open_3b", "open_27b_or_31b"):
            raise ValueError("comparator requires pinned open identity and required size class")
        revision = comparator.get("comparator_revision")
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise ValueError("comparator requires a pinned revision")
        if target["subject_checkpoint_sha256"] == comparator["subject_checkpoint_sha256"]:
            raise ValueError("comparator must be a different checkpoint")
        for field in FIELDS:
            if target.get(field) != comparator.get(field):
                raise ValueError(f"target and comparator must share {field}")
        payload = {
            "result": "COMPARISON_PREFLIGHT",
            "admission": "NOT_ELIGIBLE",
            **{field: target[field] for field in FIELDS},
            "target_subject_checkpoint_sha256": target["subject_checkpoint_sha256"],
            "comparator_subject_checkpoint_sha256": comparator["subject_checkpoint_sha256"],
            "comparator_revision": revision,
            "comparator_size_class": comparator["comparator_size_class"],
        }
        _atomic_write(arguments.output, payload)
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())