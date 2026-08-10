# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""CPU/file-only #1413 launch-readiness gate; not product authority."""

import hashlib
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path


_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
READINESS_SCHEMA = "ember-llmq-adoption-readiness-v1"
READINESS_FIELDS = frozenset(
    {
        "schema",
        "llmq_dev_commit",
        "llmq_source_path",
        "source_sha256",
        "build_receipt",
        "adoption_design_path",
        "adoption_design_sha256",
        "mechanism_attribution_path",
        "mechanism_attribution_sha256",
        "benchmark_receipt",
    }
)


def _has_reparse_component(path: Path, root: Path) -> bool:
    """Reject symlink/junction/reparse components before resolving a custody path."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        try:
            stat_result = os.lstat(current)
        except OSError:
            return True
        if current.is_symlink() or (getattr(stat_result, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
            return True
    return False


def _safe_file(root: Path, relative_value: object) -> Path | None:
    if (
        not isinstance(relative_value, str)
        or not relative_value
        or Path(relative_value).is_absolute()
        or ".." in Path(relative_value).parts
    ):
        return None
    try:
        root = root.resolve(strict=True)
        candidate = root / relative_value
        if _has_reparse_component(candidate, root):
            return None
        candidate = candidate.resolve(strict=True)
    except OSError:
        return None
    return candidate if candidate.is_file() and candidate.is_relative_to(root) else None


def assess(source_root: Path, payload: dict) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    missing = []
    if not isinstance(payload, dict) or payload.get("schema") != READINESS_SCHEMA:
        missing.append("schema")
    if isinstance(payload, dict):
        missing.extend(f"unknown:{key}" for key in sorted(set(payload) - READINESS_FIELDS))
    commit = payload.get("llmq_dev_commit")
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        missing.append("llmq_dev_commit")
    source_path = _safe_file(Path(source_root), payload.get("llmq_source_path"))
    if source_path is None:
        missing.append("llmq_source_path")
    source_sha = payload.get("source_sha256")
    if not isinstance(source_sha, str) or not _DIGEST.fullmatch(source_sha):
        missing.append("source_sha256")
    elif source_path is not None:
        try:
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha:
                missing.append("source_sha256")
        except OSError:
            missing.append("source_sha256")
    build = payload.get("build_receipt")
    if not isinstance(build, dict) or build.get("schema") != "ember-llmq-build-receipt-v1":
        missing.append("build_receipt")
    else:
        if build.get("status") != "PASS":
            missing.append("build_receipt.status")
        if build.get("source_commit") != commit:
            missing.append("build_receipt.source_commit")
        if build.get("source_sha256") != source_sha:
            missing.append("build_receipt.source_sha256")
        binary_path = _safe_file(Path(source_root), build.get("binary_path"))
        if binary_path is None:
            missing.append("build_receipt.binary_path")
        if not isinstance(build.get("binary_sha256"), str) or not _DIGEST.fullmatch(build["binary_sha256"]):
            missing.append("build_receipt.binary_sha256")
        elif binary_path is not None:
            try:
                if hashlib.sha256(binary_path.read_bytes()).hexdigest() != build["binary_sha256"]:
                    missing.append("build_receipt.binary_sha256")
            except OSError:
                missing.append("build_receipt.binary_sha256")

    for path_field, digest_field in (
        ("adoption_design_path", "adoption_design_sha256"),
        ("mechanism_attribution_path", "mechanism_attribution_sha256"),
    ):
        bound_path = _safe_file(Path(source_root), payload.get(path_field))
        if bound_path is None:
            missing.append(path_field)
        value = payload.get(digest_field)
        if not isinstance(value, str) or not _DIGEST.fullmatch(value):
            missing.append(digest_field)
        elif bound_path is not None:
            try:
                if hashlib.sha256(bound_path.read_bytes()).hexdigest() != value:
                    missing.append(digest_field)
            except OSError:
                missing.append(digest_field)

    benchmark = payload.get("benchmark_receipt")
    if not isinstance(benchmark, dict) or benchmark.get("schema") != "ember-4090-3b-benchmark-receipt-v1":
        missing.append("benchmark_receipt")
    else:
        if benchmark.get("hardware") != "RTX 4090":
            missing.append("benchmark_receipt.hardware")
        if benchmark.get("status") != "PASS":
            missing.append("benchmark_receipt.status")
        if benchmark.get("model") != "Qwen2.5-3B":
            missing.append("benchmark_receipt.model")
        for field in ("fp8_tok_s", "bf16_tok_s"):
            value = benchmark.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                missing.append(f"benchmark_receipt.{field}")

    source_or_design_missing = any(
        field in missing
        for field in (
            "llmq_dev_commit",
            "llmq_source_path",
            "source_sha256",
            "build_receipt",
            "adoption_design_path",
            "adoption_design_sha256",
            "mechanism_attribution_path",
            "mechanism_attribution_sha256",
        )
    )
    if (
        source_or_design_missing
        or any(field.startswith("build_receipt") for field in missing)
        or any(field.startswith("benchmark_receipt.") for field in missing)
    ):
        verdict = "PRELAUNCH_REJECTED"
    elif "benchmark_receipt" in missing:
        verdict = "READY_FOR_EXTERNAL_EXECUTION"
    else:
        verdict = "READY_FOR_EXTERNAL_EXECUTION"
    external_remainder = []
    if any(field in missing for field in ("llmq_dev_commit", "llmq_source_path", "source_sha256")):
        external_remainder.append("pinned LLMQ source commit and source bytes")
    if any(field.startswith("build_receipt") for field in missing):
        external_remainder.append("governed LLMQ build receipt and binary bytes")
    if any(field in missing for field in ("adoption_design_path", "adoption_design_sha256")):
        external_remainder.append("frozen adoption design bytes")
    if any(field in missing for field in ("mechanism_attribution_path", "mechanism_attribution_sha256")):
        external_remainder.append("mechanism attribution bytes")
    if any(field.startswith("benchmark_receipt") for field in missing):
        external_remainder.append("owned RTX 4090 x1 3B benchmark receipt")
    return {
        "schema": READINESS_SCHEMA,
        "verdict": verdict,
        "missing": missing,
        "source_root": "CURRENT_REPOSITORY_SOURCE_ONLY",
        "execution_claim": False,
        "result_credit": False,
        "external_remainder": external_remainder,
        "rollback": "discard readiness artifact; no product state changed",
        "next_action": (
            "obtain a governed LLMQ build and one-RTX-4090 3B benchmark receipt"
            if "benchmark_receipt" in missing
            else "dispatch only through Ember CLI -> Ember Lab after external evidence"
        ),
    }


def _receipt_bytes(payload: dict) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    return (json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the CPU-only #1413 readiness packet.")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() if args.payload == "-" else Path(args.payload).read_text(encoding="utf-8"))
        result = assess(Path(args.source_root), payload)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        result = {
            "schema": READINESS_SCHEMA,
            "verdict": "PRELAUNCH_REJECTED",
            "missing": ["payload"],
            "source_root": "CURRENT_REPOSITORY_SOURCE_ONLY",
            "execution_claim": False,
            "result_credit": False,
            "external_remainder": ["readable JSON readiness payload"],
            "rollback": "discard readiness artifact; no product state changed",
            "next_action": "provide a readable readiness payload",
            "error": type(exc).__name__,
        }
    result["receipt_sha256"] = hashlib.sha256(_receipt_bytes(result)).hexdigest()
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.out == "-":
        print(encoded, end="")
    else:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(encoded, encoding="utf-8")
    return 0 if result["verdict"] != "PRELAUNCH_REJECTED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
