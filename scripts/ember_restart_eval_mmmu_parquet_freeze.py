#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze a locally cached MMMU validation parquet set against an existing answer snapshot."""
import argparse
import ast
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_answer(value: object) -> str | tuple[str, ...]:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ValueError("answers have invalid ground truth")


def parquet_answer(value: str, question_type: str) -> str | tuple[str, ...]:
    if question_type == "multiple-choice":
        return value
    if not value.startswith("["):
        return value
    try:
        return normalize_answer(ast.literal_eval(value))
    except (SyntaxError, ValueError) as error:
        raise ValueError("open validation answer is not a serialized string list") from error

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-root", required=True, type=Path)
    parser.add_argument("--answers", required=True, type=Path)
    parser.add_argument("--upstream-revision", required=True)
    parser.add_argument("--disk-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not re.fullmatch(r"[0-9a-f]{40}", arguments.upstream_revision):
        parser.error("upstream revision must be a lowercase git sha1")
    try:
        import pyarrow.parquet as parquet

        answer_bytes = arguments.answers.read_bytes()
        answers = json.loads(answer_bytes.decode("utf-8"))
        receipt_bytes = arguments.disk_receipt.read_bytes()
        if not isinstance(answers, dict) or not answers:
            raise ValueError("answers must be a nonempty object")
        expected = {}
        for key, value in answers.items():
            if not isinstance(value, dict) or value.get("question_type") not in {"multiple-choice", "short-answer"}:
                raise ValueError("answers have invalid question types")
            expected[key] = (value["question_type"], normalize_answer(value.get("ground_truth")))
        files = sorted(arguments.validation_root.glob("*/validation-*.parquet"))
        if not files:
            raise ValueError("validation parquet files are required")
        observed = {}
        file_index = [{"path": path.relative_to(arguments.validation_root).as_posix(), "sha256": sha256(path.read_bytes())} for path in files]
        for path in files:
            table = parquet.read_table(path, columns=["id", "answer", "question_type"])
            for row in table.to_pylist():
                identifier, answer, question_type = row["id"], row["answer"], row["question_type"]
                if not isinstance(identifier, str) or not isinstance(answer, str) or question_type not in {"multiple-choice", "open"} or identifier in observed:
                    raise ValueError("validation parquet has invalid rows")
                observed[identifier] = ("multiple-choice" if question_type == "multiple-choice" else "short-answer", parquet_answer(answer, question_type))
        if observed != expected:
            raise ValueError("validation parquet does not reproduce the frozen answers")
    except (ImportError, OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-mmmu-validation-freeze-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_SOURCE_COMPATIBILITY_ONLY",
        "benchmark_id": "MMMU",
        "upstream_revision": arguments.upstream_revision,
        "validation_parquet_file_count": len(files),
        "validation_parquet_files": file_index,
        "validation_row_count": len(observed),
        "eligible_multiple_choice_count": sum(1 for question_type, _ in observed.values() if question_type == "multiple-choice"),
        "answer_dictionary_sha256": sha256(answer_bytes),
        "validation_answer_dictionary_sha256": sha256(answer_bytes),
        "disk_receipt_sha256": sha256(receipt_bytes),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, prefix=arguments.output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
