#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mint one forward, externally reopenable #1719 text-authority successor."""
from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
ARTIFACT_NAMES = {
    "bundle": "text-lab-source-receipt-bundle-v3.json",
    "corpus": "owned-text-lab-corpus-v3.json",
    "identity": "owned-text-lab-input-identity-v3.json",
    "index": "text-lab-authority-index-v2.json",
}
OUTPUT_RECEIPT = "tranche-admission-receipt.json"
OUTPUT_LOG = "mint-log.json"
OUTPUT_PLAN = "tranche-admission-plan.json"
OLD_RECEIPT_KEYS = {
    "admitted_row_count", "boundary", "generated_files", "minted_at",
    "negative_receipts", "overall_authority_result", "reopened_connector_file_count",
    "reopened_connector_total_bytes", "result", "row_receipts", "schema_version",
    "source_authority", "source_code_files", "source_commit", "unresolved_row_count",
    "validation_receipt",
}
NEW_RECEIPT_KEYS = {
    "schema_version", "successor_id", "result", "overall_authority_result", "boundary",
    "source_commit", "source_code_files", "predecessor", "plan", "admitted_row_count",
    "unresolved_row_count", "reopened_connector_file_count", "reopened_connector_total_bytes",
    "row_receipts", "negative_receipts", "index_transition", "identity_transition",
    "generated_files", "validation_receipt", "minted_at",
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> bytes:
    raw = canonical(value)
    path.write_bytes(raw)
    return raw


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename one directory while refusing every existing destination."""
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file = kernel32.MoveFileExW
        move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move_file.restype = ctypes.c_int
        if move_file(str(source), str(destination), 0) != 0:
            return
        error = ctypes.get_last_error()
        if error in {80, 183}:
            raise FileExistsError(error, "destination already exists", str(destination))
        raise OSError(error, os.strerror(error), str(destination))
    libc = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise RuntimeError("atomic no-replace directory publication is unsupported")
        rename.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, source_raw, -100, destination_raw, 1)
    elif sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is None:
            raise RuntimeError("atomic no-replace directory publication is unsupported")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(source_raw, destination_raw, 4)
    else:
        raise RuntimeError("atomic no-replace directory publication is unsupported")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error, "destination already exists", str(destination))
    raise OSError(error, os.strerror(error), str(destination))


def load_authority_module(repo: Path):
    path = repo / "tools" / "ember-restart-3b" / "text_lab_corpus.py"
    spec = importlib.util.spec_from_file_location("issue1719_tranche_authority", path)
    if spec is None or spec.loader is None:
        raise ValueError("current text-lab authority module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original_run = module.subprocess.run

    def hidden_run(*args: Any, **kwargs: Any):
        if os.name == "nt":
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        return original_run(*args, **kwargs)

    module.subprocess.run = hidden_run
    return module


def _regular_root(path: Path, label: str, module: Any) -> Path:
    path = path.absolute()
    if not path.is_dir() or module._is_reparse_or_symlink(path):
        raise ValueError(f"{label} must be a non-reparse directory")
    return path.resolve(strict=True)


def _exact_file(root: Path, name: str, module: Any) -> Path:
    if PurePosixPath(name).name != name or not name:
        raise ValueError("custody file name is not an exact basename")
    path = root / name
    if not path.is_file() or module._is_reparse_or_symlink(path):
        raise ValueError(f"custody file is absent or reparsed: {name}")
    return path


def _bound_generated_file(root: Path, generated: dict[str, Any], name: str, module: Any) -> bytes:
    path = _exact_file(root, name, module)
    raw = path.read_bytes()
    binding = generated.get(name)
    if not isinstance(binding, dict) or set(binding) != {"bytes", "sha256"}:
        raise ValueError(f"predecessor generated-file binding is invalid: {name}")
    if binding["bytes"] != len(raw) or binding["sha256"] != sha256_bytes(raw):
        raise ValueError(f"predecessor generated-file binding changed: {name}")
    return raw


def _rewrite_packet_local_index(
    index: dict[str, Any],
    predecessor_generated: dict[str, bytes],
    successor_generated: dict[str, bytes],
) -> bytes:
    if not isinstance(index, dict) or index.get("schema_version") != "ember-text-lab-authority-index-v2":
        raise ValueError("predecessor authority index is not v2")
    rewritten = copy.deepcopy(index)
    for role in ("receipt_bundle", "corpus", "input_identity"):
        binding = rewritten.get(role)
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "schema"}:
            raise ValueError("predecessor authority binding is invalid")
        expected_name = ARTIFACT_NAMES[{"receipt_bundle": "bundle", "corpus": "corpus", "input_identity": "identity"}[role]]
        old_path = binding["path"]
        old_relative = PurePosixPath(old_path) if isinstance(old_path, str) else None
        if (
            old_relative is None
            or old_relative.is_absolute()
            or ".." in old_relative.parts
            or old_relative.name != expected_name
        ):
            raise ValueError("predecessor authority artifact path is not a safe exact file binding")
        if binding["sha256"] != sha256_bytes(predecessor_generated[expected_name]):
            raise ValueError("predecessor authority artifact hash changed")
        binding["path"] = expected_name
        binding["sha256"] = sha256_bytes(successor_generated[expected_name])
    return canonical(rewritten)


def _code_files(repo: Path) -> dict[str, str]:
    return {
        "text_lab_corpus": sha256_file(repo / "tools" / "ember-restart-3b" / "text_lab_corpus.py"),
        "train": sha256_file(repo / "tools" / "ember-restart-3b" / "train.py"),
        "run_vertical_slice": sha256_file(repo / "tools" / "ember-restart-3b" / "run_vertical_slice.py"),
    }


def _read_plan(path: Path, expected_sha256: str, module: Any) -> tuple[dict[str, Any], bytes]:
    if HEX64.fullmatch(expected_sha256) is None or not path.is_file() or module._is_reparse_or_symlink(path):
        raise ValueError("tranche plan path or hash is invalid")
    raw = path.read_bytes()
    if sha256_bytes(raw) != expected_sha256:
        raise ValueError("tranche plan bytes changed")
    plan = json.loads(raw)
    if (
        not isinstance(plan, dict)
        or set(plan) != {"schema_version", "successor_id", "cases"}
        or plan["schema_version"] != "ember-issue1719-tranche-admission-plan-v1"
        or re.fullmatch(r"tranche[0-9]+[a-z]?", plan.get("successor_id", "")) is None
        or not isinstance(plan["cases"], list)
    ):
        raise ValueError("tranche plan is not closed")
    return plan, raw


def _apply_cases(
    *,
    module: Any,
    rows: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    predecessor_row_receipts: list[dict[str, Any]],
    predecessor_file_count: int,
    predecessor_total_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
    row_map = {row.get("source_id"): copy.deepcopy(row) for row in rows if isinstance(row, dict)}
    if len(row_map) != len(rows):
        raise ValueError("predecessor source mapping is ambiguous")
    row_receipts = copy.deepcopy(predecessor_row_receipts)
    total_files = predecessor_file_count
    total_bytes = predecessor_total_bytes
    seen_cases: set[str] = set()
    expected_case_keys = {
        "source_id", "connector_slot", "connector_receipt_path",
        "connector_receipt_sha256", "expected_license_spdx", "evidence",
    }
    for case in cases:
        if not isinstance(case, dict) or set(case) != expected_case_keys:
            raise ValueError("tranche case is not closed")
        source_id = case["source_id"]
        if not isinstance(source_id, str) or source_id in seen_cases or source_id not in row_map:
            raise ValueError("tranche case source is absent or duplicated")
        seen_cases.add(source_id)
        old = row_map[source_id]
        if old.get("admission") != "UNRESOLVED_CANDIDATE":
            raise ValueError("tranche case does not target an unresolved candidate")
        receipt_path = Path(case["connector_receipt_path"])
        expected_receipt_sha = case["connector_receipt_sha256"]
        if (
            HEX64.fullmatch(expected_receipt_sha) is None
            or not receipt_path.is_file()
            or module._is_reparse_or_symlink(receipt_path)
        ):
            raise ValueError("connector receipt path or hash is invalid")
        receipt_raw = receipt_path.read_bytes()
        if sha256_bytes(receipt_raw) != expected_receipt_sha:
            raise ValueError("connector receipt bytes changed")
        connector = json.loads(receipt_raw)
        adapted = module.adapt_connector_receipt(connector, evidence=case["evidence"])
        if adapted.get("license_spdx") != case["expected_license_spdx"]:
            raise ValueError("connector license does not match the approved tranche case")
        row_map[source_id] = {**old, "admission": "ADMITTED", **adapted}
        files = connector["files"]
        file_count = len(files)
        byte_count = sum(item["bytes"] for item in files)
        total_files += file_count
        total_bytes += byte_count
        row_receipts.append(
            {
                "source_id": source_id,
                "connector_slot": case["connector_slot"],
                "connector_receipt_path": str(receipt_path),
                "connector_receipt_sha256": expected_receipt_sha,
                "connector_file_count": file_count,
                "connector_total_bytes": byte_count,
                "connector_sha256_manifest": connector["sha256_manifest"],
                "content_sha256": adapted["content_sha256"],
                "license_spdx": adapted["license_spdx"],
                "license_evidence_sha256": sha256_bytes(canonical(adapted["license_evidence"])),
                "l4_receipt_sha256": sha256_bytes(canonical(adapted["l4_receipt"])),
            }
        )
    return [row_map[row["source_id"]] for row in rows], sorted(row_receipts, key=lambda row: row["source_id"]), total_files, total_bytes


def mint_successor(
    *,
    repo: Path,
    source_commit: str,
    source_custody: Path,
    predecessor_receipt_name: str,
    predecessor_receipt_sha256: str,
    plan_path: Path,
    plan_sha256: str,
    output: Path,
) -> dict[str, Any]:
    if HEX40.fullmatch(source_commit) is None or HEX64.fullmatch(predecessor_receipt_sha256) is None:
        raise ValueError("source commit or predecessor receipt hash is invalid")
    repo = repo.resolve(strict=True)
    module = load_authority_module(repo)
    source_custody = _regular_root(source_custody, "source custody", module)
    output = output.absolute()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if module._is_reparse_or_symlink(output.parent):
        raise ValueError("output parent is reparsed")

    plan, plan_raw = _read_plan(plan_path, plan_sha256, module)

    expected_source_files = set(ARTIFACT_NAMES.values()) | {predecessor_receipt_name, OUTPUT_LOG}
    source_entries = list(source_custody.iterdir())
    if any(not path.is_file() or module._is_reparse_or_symlink(path) for path in source_entries):
        raise ValueError("predecessor custody file set is not exact")
    actual_source_files = {path.name for path in source_entries}
    if actual_source_files not in (expected_source_files, expected_source_files | {OUTPUT_PLAN}):
        raise ValueError("predecessor custody file set is not exact")
    predecessor_path = _exact_file(source_custody, predecessor_receipt_name, module)
    predecessor_raw = predecessor_path.read_bytes()
    if sha256_bytes(predecessor_raw) != predecessor_receipt_sha256:
        raise ValueError("predecessor receipt bytes changed")
    predecessor = json.loads(predecessor_raw)
    old_receipt = (
        isinstance(predecessor, dict)
        and set(predecessor) == OLD_RECEIPT_KEYS
        and predecessor.get("schema_version") == "ember-issue1719-tranche3-admission-v1"
    )
    generic_receipt = (
        isinstance(predecessor, dict)
        and set(predecessor) == NEW_RECEIPT_KEYS
        and predecessor.get("schema_version") == "ember-issue1719-tranche-admission-v1"
    )
    if (
        not (old_receipt or generic_receipt)
        or predecessor.get("result") != "PARTIAL_AUTHORITY_SUCCESSOR"
        or predecessor.get("overall_authority_result") != "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"
    ):
        raise ValueError("predecessor receipt is not an admitted tranche source")
    if old_receipt and actual_source_files != expected_source_files:
        raise ValueError("legacy predecessor custody has an unexpected plan sidecar")
    if generic_receipt:
        if actual_source_files != expected_source_files | {OUTPUT_PLAN}:
            raise ValueError("generic predecessor custody lacks its plan sidecar")
        source_plan_raw = _exact_file(source_custody, OUTPUT_PLAN, module).read_bytes()
        if predecessor.get("plan") != {
            "file_name": OUTPUT_PLAN,
            "sha256": sha256_bytes(source_plan_raw),
            "successor_id": json.loads(source_plan_raw).get("successor_id"),
        }:
            raise ValueError("generic predecessor plan binding changed")
    predecessor_log = json.loads(_exact_file(source_custody, OUTPUT_LOG, module).read_bytes())
    if predecessor_log.get("receipt_sha256") != predecessor_receipt_sha256:
        raise ValueError("predecessor mint log does not bind its receipt")
    generated_bindings = predecessor.get("generated_files")
    if not isinstance(generated_bindings, dict) or set(generated_bindings) != set(ARTIFACT_NAMES.values()):
        raise ValueError("predecessor generated-file set is invalid")
    source_raw = {
        name: _bound_generated_file(source_custody, generated_bindings, name, module)
        for name in ARTIFACT_NAMES.values()
    }
    if generic_receipt:
        predecessor_validation = module.validate_authority_index(
            repo,
            index_relative=ARTIFACT_NAMES["index"],
            external_authority_root=source_custody,
        )
        if predecessor_validation != predecessor.get("validation_receipt"):
            raise ValueError("predecessor validation receipt changed")
    bundle = json.loads(source_raw[ARTIFACT_NAMES["bundle"]])
    corpus = json.loads(source_raw[ARTIFACT_NAMES["corpus"]])
    source_identity = json.loads(source_raw[ARTIFACT_NAMES["identity"]])
    source_index = json.loads(source_raw[ARTIFACT_NAMES["index"]])
    rows = corpus.get("sources")
    if (
        not isinstance(rows, list)
        or len(rows) != 44
        or bundle.get("candidates") != rows
        or sum(row.get("admission") == "ADMITTED" for row in rows) != predecessor.get("admitted_row_count")
        or predecessor.get("unresolved_row_count") != 44 - predecessor.get("admitted_row_count", -1)
    ):
        raise ValueError("predecessor row authority is inconsistent")

    predecessor_row_receipts = predecessor.get("row_receipts")
    predecessor_file_count = predecessor.get("reopened_connector_file_count")
    predecessor_total_bytes = predecessor.get("reopened_connector_total_bytes")
    if (
        not isinstance(predecessor_row_receipts, list)
        or not isinstance(predecessor_file_count, int)
        or isinstance(predecessor_file_count, bool)
        or not isinstance(predecessor_total_bytes, int)
        or isinstance(predecessor_total_bytes, bool)
    ):
        raise ValueError("predecessor connector custody is invalid")
    rows, row_receipts, reopened_file_count, reopened_total_bytes = _apply_cases(
        module=module,
        rows=rows,
        cases=plan["cases"],
        predecessor_row_receipts=predecessor_row_receipts,
        predecessor_file_count=predecessor_file_count,
        predecessor_total_bytes=predecessor_total_bytes,
    )
    admitted_count = sum(row.get("admission") == "ADMITTED" for row in rows)
    registry_path = repo / "data" / "ember-restart-3b" / "protected-eval-registry-v2.json"
    registry_raw = registry_path.read_bytes()
    bundle = {
        "schema_version": "ember-text-source-receipt-bundle-v3",
        "result": "RESOLVED" if admitted_count == 44 else "UNRESOLVED_CANDIDATE",
        "candidates": rows,
    }
    bundle_raw = canonical(bundle)
    corpus = {
        "schema_version": "ember-text-lab-corpus-v3",
        "registry_sha256": sha256_bytes(registry_raw),
        "receipt_bundle_sha256": sha256_bytes(bundle_raw),
        "sources": rows,
        "train_root_sha256": module._authority_split_root(rows, "train"),
        "heldout_root_sha256": module._authority_split_root(rows, "heldout"),
    }
    corpus_raw = canonical(corpus)

    code_files = _code_files(repo)
    identity = {
        "schema_version": "ember-text-lab-input-identity-v2",
        "corpus_sha256": sha256_bytes(corpus_raw),
        "code_files": code_files,
        "source_base_commit": source_commit,
    }
    identity_raw = canonical(identity)
    generated = {
        ARTIFACT_NAMES["bundle"]: bundle_raw,
        ARTIFACT_NAMES["corpus"]: corpus_raw,
        ARTIFACT_NAMES["identity"]: identity_raw,
    }
    index_raw = _rewrite_packet_local_index(
        source_index,
        source_raw,
        generated,
    )
    index = json.loads(index_raw)
    index_raw = canonical(index)
    generated[ARTIFACT_NAMES["index"]] = index_raw

    staging = output.with_name(f".{output.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir()
    published = False
    try:
        for name, raw in generated.items():
            (staging / name).write_bytes(raw)
        (staging / OUTPUT_PLAN).write_bytes(plan_raw)
        staging_validation = module.validate_authority_index(
            repo,
            index_relative=ARTIFACT_NAMES["index"],
            external_authority_root=staging,
        )
        if staging_validation.get("result") != "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING":
            raise ValueError("partial tranche successor did not remain fail-closed")
        receipt = {
            "schema_version": "ember-issue1719-tranche-admission-v1",
            "successor_id": plan["successor_id"],
            "result": "PARTIAL_AUTHORITY_SUCCESSOR",
            "overall_authority_result": staging_validation["result"],
            "boundary": "NO_CORPUS_BYTE_MOVEMENT_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM",
            "source_commit": source_commit,
            "source_code_files": code_files,
            "predecessor": {
                "custody_path": str(source_custody),
                "receipt_name": predecessor_receipt_name,
                "receipt_sha256": predecessor_receipt_sha256,
                "published_index_reopenability": (
                    "REFUSED_DELETED_SCRATCH_PATHS"
                    if old_receipt
                    else "REOPENED_BY_PRODUCTION_VALIDATOR"
                ),
            },
            "plan": {
                "file_name": OUTPUT_PLAN,
                "sha256": sha256_bytes(plan_raw),
                "successor_id": plan["successor_id"],
            },
            "admitted_row_count": admitted_count,
            "unresolved_row_count": 44 - admitted_count,
            "reopened_connector_file_count": reopened_file_count,
            "reopened_connector_total_bytes": reopened_total_bytes,
            "row_receipts": row_receipts,
            "negative_receipts": predecessor["negative_receipts"],
            "index_transition": {
                "predecessor_sha256": sha256_bytes(source_raw[ARTIFACT_NAMES["index"]]),
                "successor_sha256": sha256_bytes(index_raw),
                "rewrite": "scratch-relative artifact paths replaced by packet-local basenames",
            },
            "identity_transition": {
                "predecessor_sha256": sha256_bytes(source_raw[ARTIFACT_NAMES["identity"]]),
                "successor_sha256": sha256_bytes(identity_raw),
                "reason": "current source commit and exact validator code binding",
            },
            "generated_files": {
                name: {"bytes": len(raw), "sha256": sha256_bytes(raw)}
                for name, raw in sorted(generated.items())
            },
            "validation_receipt": staging_validation,
            "minted_at": datetime.now(timezone.utc).isoformat(),
        }
        receipt_raw = write_json(staging / OUTPUT_RECEIPT, receipt)
        write_json(
            staging / OUTPUT_LOG,
            {
                "schema_version": "ember-issue1719-tranche-admission-mint-log-v1",
                "source_commit": source_commit,
                "producer_path": "scripts/mint_issue1719_tranche_admission.py",
                "producer_sha256": sha256_file(repo / "scripts" / "mint_issue1719_tranche_admission.py"),
                "plan_sha256": sha256_bytes(plan_raw),
                "predecessor_receipt_sha256": predecessor_receipt_sha256,
                "receipt_sha256": sha256_bytes(receipt_raw),
                "overall_authority_result": staging_validation["result"],
            },
        )
        atomic_publish_no_replace(staging, output)
        published = True
        published_validation = module.validate_authority_index(
            repo,
            index_relative=ARTIFACT_NAMES["index"],
            external_authority_root=output,
        )
        if published_validation != staging_validation:
            raise ValueError("published authority validation differs from staged validation")
        expected_names = set(generated) | {OUTPUT_RECEIPT, OUTPUT_LOG, OUTPUT_PLAN}
        published_entries = list(output.iterdir())
        if any(not path.is_file() or module._is_reparse_or_symlink(path) for path in published_entries):
            raise ValueError("published custody file set changed on reopen")
        reopened = {
            path.name: sha256_file(path)
            for path in published_entries
        }
        if set(reopened) != expected_names:
            raise ValueError("published custody file set changed on reopen")
        return {
            "result": receipt["result"],
            "custody_path": str(output),
            "receipt_sha256": reopened[OUTPUT_RECEIPT],
            "mint_log_sha256": reopened[OUTPUT_LOG],
            "validation_receipt": published_validation,
            "reopened_files": reopened,
        }
    except BaseException:
        if published:
            shutil.rmtree(output, ignore_errors=True)
        else:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-custody", type=Path, required=True)
    parser.add_argument("--predecessor-receipt-name", required=True)
    parser.add_argument("--predecessor-receipt-sha256", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = mint_successor(
        repo=args.repo,
        source_commit=args.source_commit,
        source_custody=args.source_custody,
        predecessor_receipt_name=args.predecessor_receipt_name,
        predecessor_receipt_sha256=args.predecessor_receipt_sha256,
        plan_path=args.plan,
        plan_sha256=args.plan_sha256,
        output=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
