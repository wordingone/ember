#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed validator for honest evaluator completion-certificate records."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
FAMILIES = frozenset(("text", "image", "audio", "reasoning", "code", "mathematics", "sql", "files", "browser_ui", "terminal", "structured_tools"))
BENCHMARK_FIELDS = frozenset(("family", "benchmark_id", "benchmark_version", "split_sha256", "protocol_sha256", "command_sha256", "result"))
OPTIONAL_BENCHMARK_FIELDS = frozenset(("command_path", "custody_path", "custody_sha256"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("command_path must be a nonempty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("command_path must stay inside the repository")
    return path


def _validate_benchmark(row: object, root: Path) -> None:
    if not isinstance(row, dict) or not BENCHMARK_FIELDS.issubset(row) or set(row) - BENCHMARK_FIELDS - OPTIONAL_BENCHMARK_FIELDS:
        raise ValueError("certificate benchmark record is invalid")
    if row.get("family") not in FAMILIES or not isinstance(row.get("benchmark_id"), str) or not row["benchmark_id"] or not isinstance(row.get("benchmark_version"), str) or not row["benchmark_version"]:
        raise ValueError("certificate benchmark identity is invalid")
    if any(not SHA.fullmatch(row.get(key, "")) for key in ("split_sha256", "protocol_sha256", "command_sha256")) or row.get("result") not in ("PREFLIGHT_ONLY", "NON_CLAIM_RAW_FORWARD"):
        raise ValueError("certificate benchmark hashes/result are invalid")
    if "command_path" in row:
        command_path = _safe_relative(row["command_path"])
        path = root / command_path
        if not path.is_file() or _digest(path) != row["command_sha256"]:
            raise ValueError("certificate command hash does not match command_path")
    if ("custody_path" in row) != ("custody_sha256" in row):
        raise ValueError("custody_path and custody_sha256 must be supplied together")
    if "custody_path" in row:
        custody_path = _safe_relative(row["custody_path"])
        path = root / custody_path
        if not path.is_file() or _digest(path) != row["custody_sha256"]:
            raise ValueError("certificate custody hash does not match custody_path")


def _validate(value: object, certificate_bytes: bytes, root: Path) -> dict:
    required = {"schema_version", "goal_id", "workstream_id", "checkpoint_manifest_sha256", "evaluator_commit", "benchmarks", "comparators", "resource_receipts", "honest_unresolved_gaps", "next_checkpoint_evaluation"}
    if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != "ember-restart-eval-completion-certificate-v1" or value.get("goal_id") != "EMBER-02" or value.get("workstream_id") != "EMBER-02C" or not SHA.fullmatch(value.get("checkpoint_manifest_sha256", "")) or not COMMIT.fullmatch(value.get("evaluator_commit", "")) or not isinstance(value["benchmarks"], list) or not value["benchmarks"] or not isinstance(value["comparators"], list) or not isinstance(value["resource_receipts"], list) or not isinstance(value["honest_unresolved_gaps"], list) or not value["honest_unresolved_gaps"] or not isinstance(value["next_checkpoint_evaluation"], str) or not value["next_checkpoint_evaluation"]:
        raise ValueError("certificate schema is invalid or lacks honest unresolved gaps")
    for benchmark in value["benchmarks"]:
        _validate_benchmark(benchmark, root)
    if {benchmark["family"] for benchmark in value["benchmarks"]} != FAMILIES or len(value["benchmarks"]) != len(FAMILIES):
        raise ValueError("certificate must enumerate every required evaluation family exactly once")
    for comparator in value["comparators"]:
        if not isinstance(comparator, dict) or set(comparator) != {"class", "identity", "command_sha256", "result"} or comparator.get("class") not in {"open_3b", "open_27b_or_31b"} or not isinstance(comparator.get("identity"), str) or not comparator["identity"] or not SHA.fullmatch(comparator.get("command_sha256", "")) or comparator.get("result") not in {"PREFLIGHT_ONLY", "NOT_EXECUTABLE", "NON_CLAIM_RAW_FORWARD"}:
            raise ValueError("certificate comparator record is invalid")
    for receipt in value["resource_receipts"]:
        if not isinstance(receipt, dict) or set(receipt) != {"kind", "receipt_sha256"} or not isinstance(receipt.get("kind"), str) or not receipt["kind"] or not SHA.fullmatch(receipt.get("receipt_sha256", "")):
            raise ValueError("certificate resource receipt record is invalid")
    return {"result": "PREFLIGHT_ONLY", "certificate_sha256": hashlib.sha256(certificate_bytes).hexdigest(), "benchmark_count": len(value["benchmarks"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("validate")
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        certificate_bytes = args.certificate.read_bytes()
        value = json.loads(certificate_bytes.decode("utf-8"))
        root = args.root.resolve() if args.root else (args.certificate.parent.parent if args.certificate.parent.name == "manifests" else Path.cwd()).resolve()
        result = _validate(value, certificate_bytes, root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(f"invalid certificate: {error}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(result, handle, sort_keys=True)
        handle.write(chr(10))
        temporary = handle.name
    try:
        os.replace(temporary, args.output)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    main()
