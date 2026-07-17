#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze HellaSwag test bytes without caller-attested protocol identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SPLIT = Path("data/test-00000-of-00001.parquet")
SCORER_PATH = "scripts/ember_restart_eval_hellaswag_score.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derived_protocol_sha256(revision: str, split_sha256: str, license_sha256: str, adapter_sha256: str) -> str:
    return digest(f"hellaswag:{revision}:{split_sha256}:{license_sha256}:{adapter_sha256}".encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    # Compatibility option retained for old packets, but never trusted or used.
    parser.add_argument("--protocol-sha256", required=False, help=argparse.SUPPRESS)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    if not COMMIT.fullmatch(args.revision):
        parser.error("revision must be a lowercase source commit")
    try:
        card = (args.dataset_root / "README.md").read_bytes()
        split = (args.dataset_root / SPLIT).read_bytes()
        card_text = card.decode("utf-8").lower()
        if "licensing information" not in card_text or "mit" not in card_text:
            raise ValueError("HellaSwag card must provide explicit MIT licensing information")
        rows = pq.read_table(pa.BufferReader(split), columns=["ind", "source_id", "ctx", "endings", "label"]).to_pylist()
        ids = [(row.get("source_id"), row.get("ind")) if isinstance(row, dict) else None for row in rows]

        def valid(row: object) -> bool:
            return (
                isinstance(row, dict)
                and isinstance(row.get("ind"), int)
                and isinstance(row.get("source_id"), str)
                and bool(row["source_id"])
                and isinstance(row.get("ctx"), str)
                and bool(row["ctx"])
                and isinstance(row.get("endings"), list)
                and bool(row["endings"])
                and all(isinstance(value, str) and value for value in row["endings"])
                and isinstance(row.get("label"), str)
            )

        labels = [row["label"] for row in rows if isinstance(row, dict)]
        labels_withheld = bool(labels) and all(label == "" for label in labels)
        labels_complete = bool(labels) and all(label.isdigit() and int(label) < len(row["endings"]) for label, row in zip(labels, rows))
        if not rows or len(set(ids)) != len(rows) or any(not valid(row) for row in rows) or not (labels_withheld or labels_complete):
            raise ValueError("HellaSwag rows require unique ids, nonempty endings, and uniformly withheld or in-range labels")
        license_sha256 = digest(card)
        split_sha256 = digest(split)
        adapter_sha256 = digest(Path(__file__).resolve().with_name("ember_restart_eval_hellaswag_score.py").read_bytes())
        protocol_sha256 = derived_protocol_sha256(args.revision, split_sha256, license_sha256, adapter_sha256)
    except (OSError, UnicodeDecodeError, pa.ArrowException, ValueError) as error:
        parser.error(str(error))
    withheld = labels_withheld
    payload = {
        "schema_version": "ember-restart-hellaswag-freeze-v2",
        "result": "PREFLIGHT_ONLY",
        "admission": "NOT_EXECUTABLE_NO_FROZEN_LABELS" if withheld else "NOT_EXECUTABLE_NO_CHECKPOINT_BOUND_PREDICTIONS",
        "claim_status": "FROZEN_HELLASWAG_TEST_INPUTS_NO_FROZEN_LABELS" if withheld else "FROZEN_HELLASWAG_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS",
        "benchmark_id": "hellaswag",
        "benchmark_version": args.revision,
        "capability": "reasoning",
        "license": "MIT",
        "license_sha256": license_sha256,
        "references_sha256": split_sha256,
        "split_sha256": split_sha256,
        "protocol_sha256": protocol_sha256,
        "scoring_adapter_path": SCORER_PATH,
        "scoring_adapter_sha256": adapter_sha256,
        "task_count": len(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, prefix=args.output.name + ".", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())