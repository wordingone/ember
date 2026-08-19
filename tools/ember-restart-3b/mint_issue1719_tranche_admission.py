#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
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
PARTITION_ARTIFACT_NAMES = {
    "bundle": "text-lab-source-receipt-bundle-v4.json",
    "corpus": "owned-text-lab-corpus-v4.json",
    "identity": "owned-text-lab-input-identity-v4.json",
    "index": "text-lab-authority-index-v2.json",
}
OUTPUT_RECEIPT = "tranche-admission-receipt.json"
OUTPUT_LOG = "mint-log.json"
OUTPUT_PLAN = "tranche-admission-plan.json"
IDENTITY_CURE = "tranche-admission-source-identity-cure.json"
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
    *,
    source_names: dict[str, str],
    output_names: dict[str, str],
    repo: Path,
) -> bytes:
    if not isinstance(index, dict) or index.get("schema_version") != "ember-text-lab-authority-index-v2":
        raise ValueError("predecessor authority index is not v2")
    rewritten = copy.deepcopy(index)
    for role in ("receipt_bundle", "corpus", "input_identity"):
        binding = rewritten.get(role)
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "schema"}:
            raise ValueError("predecessor authority binding is invalid")
        artifact_role = {"receipt_bundle": "bundle", "corpus": "corpus", "input_identity": "identity"}[role]
        expected_name = source_names[artifact_role]
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
        output_name = output_names[artifact_role]
        binding["path"] = output_name
        binding["sha256"] = sha256_bytes(successor_generated[output_name])
        if output_names is PARTITION_ARTIFACT_NAMES and artifact_role in {"bundle", "corpus"}:
            schema_name = f"text-lab-{artifact_role}-v4.schema.json"
            schema_path = repo / "data" / "ember-restart-3b" / schema_name
            binding["schema"] = {
                "path": f"data/ember-restart-3b/{schema_name}",
                "sha256": sha256_file(schema_path),
            }
    return canonical(rewritten)


def _code_files(repo: Path) -> dict[str, str]:
    return {
        "text_lab_corpus": sha256_file(repo / "tools" / "ember-restart-3b" / "text_lab_corpus.py"),
        "train": sha256_file(repo / "tools" / "ember-restart-3b" / "train.py"),
        "run_vertical_slice": sha256_file(repo / "tools" / "ember-restart-3b" / "run_vertical_slice.py"),
    }


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "check": False,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(["git", "-C", str(repo), *args], **kwargs)


def _git_blob(repo: Path, commit: str, path: str) -> bytes:
    kwargs: dict[str, Any] = {"capture_output": True, "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], **kwargs)
    if result.returncode != 0:
        raise ValueError("source identity cure commit object is unavailable")
    return result.stdout


def _validate_identity_cure(
    *,
    module: Any,
    current_repo: Path,
    current_source_commit: str,
    source_custody: Path,
    source_identity: dict[str, Any],
    predecessor_receipt_sha256: str,
    predecessor_generated_files: dict[str, Any],
) -> dict[str, Any]:
    path = source_custody / IDENTITY_CURE
    if not path.is_file() or module._is_reparse_or_symlink(path):
        raise ValueError("historical predecessor code bytes changed")
    raw = path.read_bytes()
    cure = json.loads(raw)
    expected_keys = {
        "schema_version", "result", "predecessor_receipt_sha256",
        "predecessor_generated_files_sha256", "recorded_source_base_commit",
        "executed_code_files", "resolved_source_commit", "resolved_code_files",
        "reviewer_reference", "supersedes_sha256", "replacement_authority",
        "misbinding_kind", "data_bytes_status",
    }
    expected_code = source_identity["code_files"]
    resolved_commit = cure.get("resolved_source_commit") if isinstance(cure, dict) else None
    if (
        not isinstance(cure, dict)
        or set(cure) != expected_keys
        or cure.get("schema_version") != "ember-issue1719-source-identity-cure-v1"
        or cure.get("result") != "VERIFIED_SOURCE_IDENTITY_SUPERSESSION"
        or cure.get("predecessor_receipt_sha256") != predecessor_receipt_sha256
        or cure.get("predecessor_generated_files_sha256")
        != sha256_bytes(canonical(predecessor_generated_files))
        or cure.get("recorded_source_base_commit") != source_identity["source_base_commit"]
        or cure.get("executed_code_files") != expected_code
        or cure.get("resolved_code_files") != expected_code
        or not isinstance(resolved_commit, str)
        or HEX40.fullmatch(resolved_commit) is None
        or cure.get("reviewer_reference") != "mailbox:review:24111"
        or cure.get("supersedes_sha256")
        != "3b66e73afcb864769b218a581fc9525eee8af84c30006a65725c24da50d20b60"
        or cure.get("replacement_authority") != "mailbox:review:24148"
        or cure.get("misbinding_kind") != "BASE_HEAD_LABEL_WITH_REVIEWED_BRANCH_BYTES"
        or cure.get("data_bytes_status") != "UNCHANGED_AND_BOUND_BY_PREDECESSOR_RECEIPT"
    ):
        raise ValueError("source identity cure receipt is invalid")
    ancestry = _git(current_repo, "merge-base", "--is-ancestor", resolved_commit, current_source_commit)
    if ancestry.returncode != 0:
        raise ValueError("source identity cure commit is not an ancestor of current source")
    paths = {
        "text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py",
        "train": "tools/ember-restart-3b/train.py",
        "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py",
    }
    reopened = {
        name: sha256_bytes(_git_blob(current_repo, resolved_commit, relative))
        for name, relative in paths.items()
    }
    if reopened != expected_code:
        raise ValueError("source identity cure git objects do not match executed code")
    return {
        "source_identity_cure_path": str(path.resolve(strict=True)),
        "source_identity_cure_sha256": sha256_bytes(raw),
        "resolved_source_commit": resolved_commit,
        "resolved_source_code_files": reopened,
        "reviewer_reference": cure["reviewer_reference"],
        "supersedes_sha256": cure["supersedes_sha256"],
        "replacement_authority": cure["replacement_authority"],
        "data_bytes_status": cure["data_bytes_status"],
    }


class _CureBoundCodePath:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read_bytes(self) -> bytes:
        return self._payload


def _validate_authority_with_identity_cure(
    *,
    module: Any,
    current_repo: Path,
    validation_root: Path,
    source_custody: Path,
    cure_evidence: dict[str, Any],
    expected_code: dict[str, str],
) -> dict[str, Any]:
    paths = {
        "text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py",
        "train": "tools/ember-restart-3b/train.py",
        "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py",
    }
    resolved_commit = cure_evidence["resolved_source_commit"]
    bound_code = {
        relative: _git_blob(current_repo, resolved_commit, relative)
        for relative in paths.values()
    }
    if {
        name: sha256_bytes(bound_code[relative])
        for name, relative in paths.items()
    } != expected_code:
        raise ValueError("source identity cure git objects do not match executed code")

    original_path = module._path
    validation_root = validation_root.resolve(strict=True)

    def cure_bound_path(root: Path, value: object):
        relative = PurePosixPath(str(value).replace("\\", "/")).as_posix()
        if Path(root).resolve(strict=True) == validation_root and relative in bound_code:
            return _CureBoundCodePath(bound_code[relative])
        return original_path(root, value)

    module._path = cure_bound_path
    try:
        return module.validate_authority_index(
            validation_root,
            index_relative=ARTIFACT_NAMES["index"],
            external_authority_root=source_custody,
        )
    finally:
        module._path = original_path


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.resolve(strict=True)))).casefold()


def _validate_predecessor_authority(
    *,
    module: Any,
    current_repo: Path,
    current_source_commit: str,
    source_custody: Path,
    source_identity: dict[str, Any],
    stored_validation: dict[str, Any],
    predecessor_source_repo: Path | None,
    predecessor_receipt_sha256: str | None = None,
    predecessor_generated_files: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    expected_code = source_identity.get("code_files")
    pinned_commit = source_identity.get("source_base_commit")
    if (
        not isinstance(expected_code, dict)
        or set(expected_code) != {"text_lab_corpus", "train", "run_vertical_slice"}
        or any(not isinstance(value, str) or HEX64.fullmatch(value) is None for value in expected_code.values())
        or not isinstance(pinned_commit, str)
        or HEX40.fullmatch(pinned_commit) is None
        or not isinstance(stored_validation, dict)
    ):
        raise ValueError("predecessor source identity is invalid")
    current_code = _code_files(current_repo)
    if expected_code == current_code:
        if predecessor_source_repo is not None:
            raise ValueError("historical predecessor source repo is forbidden for current-source bytes")
        validation = module.validate_authority_index(
            current_repo,
            index_relative=ARTIFACT_NAMES["index"],
            external_authority_root=source_custody,
        )
        if validation != stored_validation:
            raise ValueError("predecessor validation receipt changed")
        return validation, None

    if predecessor_source_repo is None:
        raise ValueError("historical predecessor source repo is required")
    if HEX40.fullmatch(current_source_commit) is None:
        raise ValueError("current source commit is invalid")
    historical = _regular_root(predecessor_source_repo, "historical predecessor source repo", module)
    ancestry = _git(current_repo, "merge-base", "--is-ancestor", pinned_commit, current_source_commit)
    if ancestry.returncode != 0:
        raise ValueError("historical predecessor commit is not an ancestor of current source")
    top = _git(historical, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve(strict=True) != historical:
        raise ValueError("historical predecessor checkout root changed")
    status = _git(historical, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0 or status.stdout:
        raise ValueError("historical predecessor checkout must be clean")
    attached = _git(historical, "symbolic-ref", "--quiet", "HEAD")
    if attached.returncode not in {0, 1}:
        raise ValueError("historical predecessor checkout state is unreadable")
    if attached.returncode == 0:
        raise ValueError("historical predecessor checkout must be detached")
    head = _git(historical, "rev-parse", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != pinned_commit:
        raise ValueError("historical predecessor checkout HEAD changed")
    cure_evidence = None
    if _code_files(historical) != expected_code:
        if predecessor_receipt_sha256 is None or predecessor_generated_files is None:
            raise ValueError("historical predecessor code bytes changed")
        cure_evidence = _validate_identity_cure(
            module=module,
            current_repo=current_repo,
            current_source_commit=current_source_commit,
            source_custody=source_custody,
            source_identity=source_identity,
            predecessor_receipt_sha256=predecessor_receipt_sha256,
            predecessor_generated_files=predecessor_generated_files,
        )

    common_result = _git(historical, "rev-parse", "--git-common-dir")
    if common_result.returncode != 0 or not common_result.stdout.strip():
        raise ValueError("historical predecessor lifecycle root is unavailable")
    common = Path(common_result.stdout.strip())
    if not common.is_absolute():
        common = historical / common
    common = common.resolve(strict=True)
    state_path = common / "ember-worktree-lifecycle.json"
    if not state_path.is_file() or module._is_reparse_or_symlink(state_path):
        raise ValueError("historical predecessor lifecycle state is unavailable")
    state_raw = state_path.read_bytes()
    state = json.loads(state_raw)
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or not isinstance(state.get("managed"), dict)
        or not isinstance(state.get("target"), int)
        or not isinstance(state.get("ceiling"), int)
        or not isinstance(state.get("legacy_paths"), list)
    ):
        raise ValueError("historical predecessor lifecycle state is invalid")
    key = _path_key(historical)
    row = state["managed"].get(key)
    if not isinstance(row, dict):
        raise ValueError("historical predecessor checkout is not governed")
    try:
        row_path = Path(row["path"]).resolve(strict=True)
    except (KeyError, OSError):
        raise ValueError("historical predecessor lifecycle row changed") from None
    if (
        row_path != historical
        or row.get("detached") is not True
        or row.get("branch") is not None
        or row.get("head") != pinned_commit
    ):
        raise ValueError("historical predecessor lifecycle row changed")

    validation = (
        _validate_authority_with_identity_cure(
            module=module,
            current_repo=current_repo,
            validation_root=historical,
            source_custody=source_custody,
            cure_evidence=cure_evidence,
            expected_code=expected_code,
        )
        if cure_evidence is not None
        else module.validate_authority_index(
            historical,
            index_relative=ARTIFACT_NAMES["index"],
            external_authority_root=source_custody,
        )
    )
    if validation != stored_validation:
        raise ValueError("predecessor validation receipt changed")
    return validation, {
        "result": (
            "HISTORICAL_PREDECESSOR_REOPENED_WITH_IDENTITY_CURE"
            if cure_evidence is not None else "HISTORICAL_PREDECESSOR_REOPENED"
        ),
        "source_base_commit": pinned_commit,
        "source_code_files": expected_code,
        "lifecycle_state_sha256": sha256_bytes(state_raw),
        "lifecycle_managed_key": key,
        "ancestry": "ANCESTOR_OF_CURRENT_SOURCE",
        **(cure_evidence or {}),
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
    repo: Path,
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
    homogeneous_case_keys = {
        "source_id", "connector_slot", "connector_receipt_path",
        "connector_receipt_sha256", "expected_license_spdx", "evidence",
    }
    partition_case_keys = {
        "source_id", "connector_slot", "license_partition_receipt_path",
        "license_partition_receipt_sha256",
    }
    pdf_case_keys = {
        "source_id", "connector_slot", "connector_receipt_path",
        "connector_receipt_sha256", "transform_receipt_path",
        "transform_receipt_raw_sha256", "transform_receipt_sha256",
        "expected_license_spdx", "evidence",
    }
    for case in cases:
        if not isinstance(case, dict) or set(case) not in (
            homogeneous_case_keys, partition_case_keys, pdf_case_keys,
        ):
            raise ValueError("tranche case is not closed")
        source_id = case["source_id"]
        if not isinstance(source_id, str) or source_id in seen_cases or source_id not in row_map:
            raise ValueError("tranche case source is absent or duplicated")
        seen_cases.add(source_id)
        old = row_map[source_id]
        if old.get("admission") != "UNRESOLVED_CANDIDATE":
            raise ValueError("tranche case does not target an unresolved candidate")
        if set(case) == partition_case_keys:
            receipt_path = Path(case["license_partition_receipt_path"])
            expected_receipt_sha = case["license_partition_receipt_sha256"]
            if (
                not isinstance(expected_receipt_sha, str)
                or HEX64.fullmatch(expected_receipt_sha) is None
                or not receipt_path.is_file()
                or module._is_reparse_or_symlink(receipt_path)
            ):
                raise ValueError("partition receipt path or hash is invalid")
            receipt_raw = receipt_path.read_bytes()
            if sha256_bytes(receipt_raw) != expected_receipt_sha:
                raise ValueError("partition receipt bytes changed")
            partition = json.loads(receipt_raw)
            content = partition.get("partition_root_sha256") if isinstance(partition, dict) else None
            admitted = {
                **old,
                "admission": "ADMITTED",
                "content_sha256": content,
                "license_partition_receipt": str(receipt_path.resolve(strict=True)),
                "license_partition_sha256": expected_receipt_sha,
                "l4_receipt": {
                    "schema_version": "ember-text-source-partition-receipt-v1",
                    "result": "VERIFIED",
                    "source_sha256": content,
                    "generator": "github-license-partition-v1",
                    "verifier": "github-license-partition-reopen-v1",
                    "model_mediated": False,
                    "borrowed_labels": False,
                    "license_partition_sha256": expected_receipt_sha,
                },
            }
            reopened = module._validate_partition_authority_row(repo, repo, admitted)
            if reopened.get("connector_slot") != case["connector_slot"]:
                raise ValueError("partition receipt connector slot does not match the tranche case")
            row_map[source_id] = admitted
            file_count = reopened["file_count"]
            byte_count = reopened["blob_bytes"]
            total_files += file_count
            total_bytes += byte_count
            row_receipts.append({
                "source_id": source_id,
                "connector_slot": case["connector_slot"],
                "license_partition_receipt_path": str(receipt_path.resolve(strict=True)),
                "license_partition_receipt_sha256": expected_receipt_sha,
                "repository_count": reopened["repository_count"],
                "partition_file_count": file_count,
                "partition_total_bytes": byte_count,
                "content_sha256": content,
                "license_summary": reopened["license_summary"],
                "l4_receipt_sha256": sha256_bytes(canonical(admitted["l4_receipt"])),
            })
            continue
        receipt_path = Path(case["connector_receipt_path"])
        expected_receipt_sha = case["connector_receipt_sha256"]
        if (
            not isinstance(expected_receipt_sha, str)
            or HEX64.fullmatch(expected_receipt_sha) is None
            or not receipt_path.is_file()
            or module._is_reparse_or_symlink(receipt_path)
        ):
            raise ValueError("connector receipt path or hash is invalid")
        receipt_raw = receipt_path.read_bytes()
        if sha256_bytes(receipt_raw) != expected_receipt_sha:
            raise ValueError("connector receipt bytes changed")
        connector = json.loads(receipt_raw)
        if set(case) == pdf_case_keys:
            transform_path = Path(case["transform_receipt_path"])
            expected_transform_raw_sha = case["transform_receipt_raw_sha256"]
            expected_transform_sha = case["transform_receipt_sha256"]
            if (
                not isinstance(expected_transform_raw_sha, str)
                or HEX64.fullmatch(expected_transform_raw_sha) is None
                or not isinstance(expected_transform_sha, str)
                or HEX64.fullmatch(expected_transform_sha) is None
                or not transform_path.is_file()
                or module._is_reparse_or_symlink(transform_path)
            ):
                raise ValueError("PDF transform receipt path or hash is invalid")
            transform_raw = transform_path.read_bytes()
            if sha256_bytes(transform_raw) != expected_transform_raw_sha:
                raise ValueError("PDF transform receipt bytes changed")
            transform = json.loads(transform_raw)
            if not isinstance(transform, dict) or transform.get("receipt_sha256") != expected_transform_sha:
                raise ValueError("PDF transform receipt identity changed")
            evidence = case["evidence"]
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {
                    "kind", "terms_url", "declared_spdx",
                    "connector_receipt_path", "connector_receipt_sha256",
                    "transform_receipt_path", "transform_receipt_sha256",
                }
                or evidence.get("connector_receipt_sha256") != expected_receipt_sha
                or evidence.get("transform_receipt_sha256") != expected_transform_sha
            ):
                raise ValueError("PDF evidence hashes do not match the tranche case")
            try:
                evidence_connector_path = Path(evidence["connector_receipt_path"]).resolve(strict=True)
                evidence_transform_path = Path(evidence["transform_receipt_path"]).resolve(strict=True)
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise ValueError("PDF evidence paths do not match the tranche case") from error
            if (
                evidence_connector_path != receipt_path.resolve(strict=True)
                or evidence_transform_path != transform_path.resolve(strict=True)
            ):
                raise ValueError("PDF evidence paths do not match the tranche case")
            adapted = module.adapt_pdf_extraction_receipt(
                receipt_path=transform_path,
                connector_receipt=receipt_path,
                connector_receipt_sha256=expected_receipt_sha,
                evidence=evidence,
            )
            if adapted.get("license_spdx") != case["expected_license_spdx"]:
                raise ValueError("PDF source license does not match the approved tranche case")
            output = transform.get("output")
            if not isinstance(output, dict):
                raise ValueError("PDF transform receipt output is missing")
            if adapted.get("content_sha256") != output.get("sha256"):
                raise ValueError("PDF transform output does not match adapted content")
            output_bytes = output.get("bytes")
            if not isinstance(output_bytes, int) or isinstance(output_bytes, bool) or output_bytes < 0:
                raise ValueError("PDF transform receipt output byte count is invalid")
            row_map[source_id] = {**old, "admission": "ADMITTED", **adapted}
            total_files += 1
            total_bytes += output_bytes
            row_receipts.append({
                "source_id": source_id,
                "connector_slot": case["connector_slot"],
                "connector_receipt_path": str(receipt_path.resolve(strict=True)),
                "connector_receipt_sha256": expected_receipt_sha,
                "transform_receipt_path": str(transform_path.resolve(strict=True)),
                "transform_receipt_raw_sha256": expected_transform_raw_sha,
                "transform_receipt_sha256": expected_transform_sha,
                "transform_output_sha256": output.get("sha256"),
                "transform_output_bytes": output_bytes,
                "transform_page_count": output.get("pages"),
                "transform_decoded_content_bytes": output.get("decoded_content_bytes"),
                "content_sha256": adapted["content_sha256"],
                "license_spdx": adapted["license_spdx"],
                "license_evidence_sha256": sha256_bytes(canonical(adapted["license_evidence"])),
                "l4_receipt_sha256": sha256_bytes(canonical(adapted["l4_receipt"])),
            })
            continue
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
    predecessor_source_repo: Path | None = None,
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
    plan_adds_partition = any(
        isinstance(case, dict) and "license_partition_receipt_path" in case
        for case in plan["cases"]
    )

    source_entries = list(source_custody.iterdir())
    if any(not path.is_file() or module._is_reparse_or_symlink(path) for path in source_entries):
        raise ValueError("predecessor custody file set is not exact")
    actual_source_files = {path.name for path in source_entries}
    expected_v3 = set(ARTIFACT_NAMES.values()) | {predecessor_receipt_name, OUTPUT_LOG}
    expected_v4 = set(PARTITION_ARTIFACT_NAMES.values()) | {predecessor_receipt_name, OUTPUT_LOG}
    allowed_source_sets = {
        frozenset(expected_v3), frozenset(expected_v3 | {OUTPUT_PLAN}),
        frozenset(expected_v4), frozenset(expected_v4 | {OUTPUT_PLAN}),
        frozenset(expected_v3 | {OUTPUT_PLAN, IDENTITY_CURE}),
        frozenset(expected_v4 | {OUTPUT_PLAN, IDENTITY_CURE}),
    }
    if frozenset(actual_source_files) not in allowed_source_sets:
        raise ValueError("predecessor custody file set is not exact")
    source_names = PARTITION_ARTIFACT_NAMES if set(PARTITION_ARTIFACT_NAMES.values()).issubset(actual_source_files) else ARTIFACT_NAMES
    expected_source_files = set(source_names.values()) | {predecessor_receipt_name, OUTPUT_LOG}
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
        expected_generic_files = expected_source_files | {OUTPUT_PLAN}
        if actual_source_files not in (expected_generic_files, expected_generic_files | {IDENTITY_CURE}):
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
    if not isinstance(generated_bindings, dict) or set(generated_bindings) != set(source_names.values()):
        raise ValueError("predecessor generated-file set is invalid")
    source_raw = {
        name: _bound_generated_file(source_custody, generated_bindings, name, module)
        for name in source_names.values()
    }
    bundle = json.loads(source_raw[source_names["bundle"]])
    corpus = json.loads(source_raw[source_names["corpus"]])
    source_identity = json.loads(source_raw[source_names["identity"]])
    source_index = json.loads(source_raw[source_names["index"]])
    historical_reopen = None
    if generic_receipt:
        _, historical_reopen = _validate_predecessor_authority(
            module=module,
            current_repo=repo,
            current_source_commit=source_commit,
            source_custody=source_custody,
            source_identity=source_identity,
            stored_validation=predecessor.get("validation_receipt"),
            predecessor_source_repo=predecessor_source_repo,
            predecessor_receipt_sha256=predecessor_receipt_sha256,
            predecessor_generated_files=generated_bindings,
        )
    elif predecessor_source_repo is not None:
        raise ValueError("historical predecessor source repo is forbidden for legacy predecessor")
    rows = corpus.get("sources")
    if (
        not isinstance(rows, list)
        or len(rows) != 44
        or bundle.get("candidates") != rows
        or sum(row.get("admission") == "ADMITTED" for row in rows) != predecessor.get("admitted_row_count")
        or predecessor.get("unresolved_row_count") != 44 - predecessor.get("admitted_row_count", -1)
    ):
        raise ValueError("predecessor row authority is inconsistent")
    partition_plan = plan_adds_partition or source_names is PARTITION_ARTIFACT_NAMES
    output_names = PARTITION_ARTIFACT_NAMES if partition_plan else ARTIFACT_NAMES

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
        repo=repo,
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
        "schema_version": (
            "ember-text-source-receipt-bundle-v4"
            if partition_plan
            else "ember-text-source-receipt-bundle-v3"
        ),
        "result": "RESOLVED" if admitted_count == 44 else "UNRESOLVED_CANDIDATE",
        "candidates": rows,
    }
    bundle_raw = canonical(bundle)
    corpus = {
        "schema_version": "ember-text-lab-corpus-v4" if partition_plan else "ember-text-lab-corpus-v3",
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
        output_names["bundle"]: bundle_raw,
        output_names["corpus"]: corpus_raw,
        output_names["identity"]: identity_raw,
    }
    index_raw = _rewrite_packet_local_index(
        source_index,
        source_raw,
        generated,
        source_names=source_names,
        output_names=output_names,
        repo=repo,
    )
    index = json.loads(index_raw)
    index_raw = canonical(index)
    generated[output_names["index"]] = index_raw

    staging = output.with_name(f".{output.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir()
    published = False
    try:
        for name, raw in generated.items():
            (staging / name).write_bytes(raw)
        (staging / OUTPUT_PLAN).write_bytes(plan_raw)
        staging_validation = module.validate_authority_index(
            repo,
            index_relative=output_names["index"],
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
                **(
                    {"historical_predecessor_reopen": historical_reopen}
                    if historical_reopen is not None
                    else {}
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
                "predecessor_sha256": sha256_bytes(source_raw[source_names["index"]]),
                "successor_sha256": sha256_bytes(index_raw),
                "rewrite": "scratch-relative artifact paths replaced by packet-local basenames",
            },
            "identity_transition": {
                "predecessor_sha256": sha256_bytes(source_raw[source_names["identity"]]),
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
                "producer_path": "tools/ember-restart-3b/mint_issue1719_tranche_admission.py",
                "producer_sha256": sha256_file(
                    repo / "tools" / "ember-restart-3b" / "mint_issue1719_tranche_admission.py"
                ),
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
            index_relative=output_names["index"],
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
    parser.add_argument("--predecessor-source-repo", type=Path)
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
        predecessor_source_repo=args.predecessor_source_repo,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
