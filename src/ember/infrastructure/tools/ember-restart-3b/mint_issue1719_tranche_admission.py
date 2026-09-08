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
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PARTITION_AUTHORITY_FILE = re.compile(
    r"partition-authority-[0-9a-f]{64}/(?:partition-receipt\.json|blobs/sha256/[0-9a-f]{2}/[0-9a-f]{64})\Z"
)
PARTITION_RECEIPT_LOCATOR = re.compile(
    r"partition-authority-([0-9a-f]{64})/partition-receipt\.json\Z"
)
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
PARTITION_BINDING_CURE = "tranche-admission-partition-binding-cure.json"
PARTITION_BINDING_CURE_AUTHORITY = "github:issue:1581"
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
    path = repo / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "text_lab_corpus.py"
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


def load_projection_module(repo: Path):
    path = repo / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "project_text_lab_custody_paths.py"
    spec = importlib.util.spec_from_file_location("issue1719_custody_projection", path)
    if spec is None or spec.loader is None:
        raise ValueError("custody projection module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
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


def _custody_files(root: Path, module: Any) -> dict[str, Path]:
    """Enumerate one exact non-reparse custody tree by portable relative path."""

    files: dict[str, Path] = {}
    seen_directories: set[str] = set()
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for directory in directories:
            child = current_path / directory
            if module._is_reparse_or_symlink(child) or not child.is_dir():
                raise ValueError("custody directory tree is reparsed or non-regular")
            seen_directories.add(child.relative_to(root).as_posix())
            kept.append(directory)
        directories[:] = kept
        for name in names:
            child = current_path / name
            if module._is_reparse_or_symlink(child) or not child.is_file():
                raise ValueError("custody file set is not exact")
            relative = child.relative_to(root).as_posix()
            if relative in files:
                raise ValueError("custody file set is ambiguous")
            files[relative] = child
    expected_directories = {
        parent.as_posix()
        for relative in files
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    if seen_directories != expected_directories:
        raise ValueError("custody directory set is not exact")
    return files


def _bound_generated_file(root: Path, generated: dict[str, Any], name: str, module: Any) -> bytes:
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("generated-file path is not portable")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
        raise ValueError("generated-file path is not portable")
    path = root.joinpath(*relative.parts)
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ValueError(f"custody file is absent or escapes root: {name}") from error
    for cursor in (path, *path.parents):
        if cursor == root.parent:
            break
        if module._is_reparse_or_symlink(cursor):
            raise ValueError(f"custody file is reparsed: {name}")
        if cursor == root:
            break
    if not path.is_file():
        raise ValueError(f"custody file is absent or non-regular: {name}")
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


# The producers moved to `src/ember/infrastructure/tools/` in the layout cutover. A historical
# predecessor is pinned to an older commit by construction, and one pinned before the cutover
# carries them at `tools/`. Both locations are named so a commit is read at its own layout.
PRODUCER_RELATIVES: dict[str, tuple[str, ...]] = {
    "text_lab_corpus": (
        "src/ember/infrastructure/tools/ember-restart-3b/text_lab_corpus.py",
        "tools/ember-restart-3b/text_lab_corpus.py",
    ),
    "train": (
        "src/ember/infrastructure/tools/ember-restart-3b/train.py",
        "tools/ember-restart-3b/train.py",
    ),
    "run_vertical_slice": (
        "src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py",
        "tools/ember-restart-3b/run_vertical_slice.py",
    ),
}


def _code_files(repo: Path) -> dict[str, str]:
    """Hash the three producers, reading each at whichever layout this checkout carries."""

    resolved: dict[str, str] = {}
    for name, candidates in PRODUCER_RELATIVES.items():
        for relative in candidates:
            path = repo.joinpath(*relative.split("/"))
            if path.is_file():
                resolved[name] = sha256_file(path)
                break
        else:
            raise ValueError("historical predecessor producer layout is unrecognised")
    return resolved


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


def _projected_custody_root(canonical_receipts: dict[str, str]) -> Path:
    """The one absolute root every cured row's recorded path resolves against.

    Each entry maps a recorded absolute path to its corpus-relative tail, already proven by
    `_validate_partition_binding_cure` to BE that path's tail. Stripping the tail yields the root,
    and every row must yield the same one -- rows spanning two roots cannot be described by a single
    runtime-supplied root and are refused rather than partially bound.
    """

    roots: set[str] = set()
    for recorded, relative in canonical_receipts.items():
        posix = PureWindowsPath(recorded).as_posix()
        tail = "/" + relative
        if not posix.endswith(tail):
            raise ValueError("projected custody root does not match the recorded path")
        roots.add(posix[: -len(tail)])
    if len(roots) != 1:
        raise ValueError("cured partition rows span more than one custody root")
    root = Path(next(iter(roots)))
    if not root.is_absolute():
        raise ValueError("projected custody root is not absolute")
    return root


PORTABLE_CUSTODY_ROOT_BINDING = "runtime-supplied-corpus-root-v1"


def _portable_partition_names(
    *,
    names: set[str],
    bound_partition_sidecars: dict[str, Any],
    declared_binding: Any,
    custody_root: Path | None,
    module: Any,
) -> set[str]:
    """The locators a predecessor spells relative to a runtime-supplied corpus root.

    A successor minted with portable locators records its partition receipts corpus-root-relative and
    declares `receipt_custody_root_binding` to say so. Those names do not match
    `PARTITION_RECEIPT_LOCATOR`, but they are not legacy bindings: they are the spelling this tool
    itself produces, and the caller supplies the root they resolve against.

    Treating them as legacy strands the tranche, because the cure that legacy rows fall back to
    cannot be formed for a relative recorded path -- `_validate_partition_binding_cure` opens the
    recorded path directly, and `_projected_custody_root` requires the stripped remainder to be one
    absolute root. That is the exact stranding `--predecessor-receipt-custody-root` was added to
    prevent.

    A name is portable only when it resolves, under the supplied root, to a regular non-reparse file
    whose bytes hash to the sha the corpus row itself records. That is the same content proof the
    cure performs, so nothing is admitted on a weaker basis; what is dropped is the demand for a
    hand-signed cure covering a spelling the tool wrote. Anything else -- an absolute recorded path,
    a traversal, a missing or altered file -- is left to the legacy path untouched.
    """

    if not names or custody_root is None or declared_binding != PORTABLE_CUSTODY_ROOT_BINDING:
        return set()
    try:
        root = custody_root.resolve(strict=True)
    except OSError:
        return set()
    if not root.is_dir():
        return set()
    portable: set[str] = set()
    for name in sorted(names):
        expected_sha = bound_partition_sidecars.get(name)
        if not isinstance(expected_sha, str) or HEX64.fullmatch(expected_sha) is None:
            continue
        # A drive letter or a backslash means an absolute recorded path, which is the cure's domain
        # and never resolved against the supplied root.
        if "\\" in name or ":" in name or name.startswith("/"):
            continue
        relative = PurePosixPath(name)
        if ".." in relative.parts or not relative.parts:
            continue
        candidate = root.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if not resolved.is_file() or module._is_reparse_or_symlink(resolved):
            continue
        if sha256_bytes(resolved.read_bytes()) != expected_sha:
            continue
        portable.add(name)
    return portable


def _validate_partition_binding_cure(
    *,
    module: Any,
    source_custody: Path,
    predecessor_receipt_sha256: str,
    predecessor_generated_files: dict[str, Any],
    bound_partition_sidecars: dict[Any, Any],
    legacy_names: set[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Admit legacy partition rows whose evidence lives outside custody.

    Returns the cured name -> sha map and the evidence to surface in the record. Every
    enumerated row is re-verified: the cure's sha must equal the sha the corpus row itself
    declares, the file must be present and not a reparse point, and its bytes must hash to
    that sha. The cure must cover the legacy rows EXACTLY -- a cure naming a row that is
    already canonical, or omitting one that is not, is refused rather than partially applied.
    """

    path = source_custody / PARTITION_BINDING_CURE
    if not path.is_file() or module._is_reparse_or_symlink(path):
        raise ValueError("partition binding cure receipt is invalid")
    raw = path.read_bytes()
    cure = json.loads(raw)
    expected_keys = {
        "schema_version", "result", "predecessor_receipt_sha256",
        "predecessor_generated_files_sha256", "reviewer_reference",
        "legacy_binding_kind", "data_bytes_status", "rows",
    }
    rows = cure.get("rows") if isinstance(cure, dict) else None
    if (
        not isinstance(cure, dict)
        or set(cure) != expected_keys
        or cure.get("schema_version") != "ember-issue1719-partition-binding-cure-v1"
        or cure.get("result") != "VERIFIED_LEGACY_PARTITION_BINDING"
        or cure.get("predecessor_receipt_sha256") != predecessor_receipt_sha256
        or cure.get("predecessor_generated_files_sha256")
        != sha256_bytes(canonical(predecessor_generated_files))
        or cure.get("reviewer_reference") != PARTITION_BINDING_CURE_AUTHORITY
        or cure.get("legacy_binding_kind") != "EXTERNAL_ABSOLUTE_PARTITION_RECEIPT_PATH"
        or cure.get("data_bytes_status") != "UNCHANGED_AND_BOUND_BY_RECORDED_SHA256"
        or not isinstance(rows, list)
        or not rows
    ):
        raise ValueError("partition binding cure receipt is invalid")

    cured: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"source_id", "recorded_receipt_path",
                                                     "receipt_sha256",
                                                     "custody_relative_receipt"}:
            raise ValueError("partition binding cure receipt is invalid")
        name = row["recorded_receipt_path"]
        sha = row["receipt_sha256"]
        # NOT named `canonical`: this module defines a module-level `canonical()` used earlier in
        # this same function, and a local of that name would shadow it for the whole scope.
        canonical_name = row["custody_relative_receipt"]
        # The two spellings must name the same trailing path. Without this the cure could rebind a
        # row to an unrelated receipt that merely hashes correctly for some other source.
        if (
            not isinstance(canonical_name, str)
            or not canonical_name
            or canonical_name.startswith("/")
            or ".." in PurePosixPath(canonical_name).parts
            or not PureWindowsPath(name).as_posix().endswith("/" + canonical_name)
        ):
            raise ValueError("partition binding cure spelling does not match the recorded path")
        if (
            not isinstance(name, str)
            or not isinstance(sha, str)
            or HEX64.fullmatch(sha) is None
            or name in cured
            or name not in bound_partition_sidecars
            or bound_partition_sidecars[name] != sha
        ):
            raise ValueError("partition binding cure receipt is invalid")
        receipt = Path(name)
        if not receipt.is_file() or module._is_reparse_or_symlink(receipt):
            raise ValueError("partition binding cure evidence is missing")
        if sha256_bytes(receipt.read_bytes()) != sha:
            raise ValueError("partition binding cure evidence bytes changed")
        cured[name] = sha

    if set(cured) != legacy_names:
        raise ValueError("partition binding cure does not cover the legacy rows exactly")

    evidence = {
        "partition_binding_cure_path": str(path.resolve(strict=True)),
        "partition_binding_cure_sha256": sha256_bytes(raw),
        "partition_binding_cure_authority": cure["reviewer_reference"],
        "legacy_binding_kind": cure["legacy_binding_kind"],
        "data_bytes_status": cure["data_bytes_status"],
        "cured_partition_rows": {
            row["source_id"]: row["receipt_sha256"] for row in sorted(
                rows, key=lambda r: r["source_id"])
        },
        "canonical_partition_receipts": {
            row["recorded_receipt_path"]: row["custody_relative_receipt"]
            for row in sorted(rows, key=lambda r: r["source_id"])
        },
    }
    return cured, evidence


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
    reopened = {}
    for name, candidates in PRODUCER_RELATIVES.items():
        for relative in candidates:
            try:
                blob = _git_blob(current_repo, resolved_commit, relative)
            except ValueError:
                # `_git_blob` raises exactly one error, for an object git could not produce.
                # That is the same signal for "this commit uses the other layout" and for a
                # genuinely unreadable object; the seam does not distinguish them. Trying the
                # next candidate is therefore correct, and exhausting them still refuses loudly
                # below rather than proceeding with a missing producer.
                continue
            reopened[name] = sha256_bytes(blob)
            break
        else:
            raise ValueError("historical predecessor producer layout is unrecognised")
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
    receipt_custody_root: Path | None = None,
) -> dict[str, Any]:
    paths = {
        "text_lab_corpus": "src/ember/infrastructure/tools/ember-restart-3b/text_lab_corpus.py",
        "train": "src/ember/infrastructure/tools/ember-restart-3b/train.py",
        "run_vertical_slice": "src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py",
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
            receipt_custody_root=receipt_custody_root,
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
    receipt_custody_root: Path | None = None,
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
            receipt_custody_root=receipt_custody_root,
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
            receipt_custody_root=receipt_custody_root,
        )
        if cure_evidence is not None
        else module.validate_authority_index(
            historical,
            index_relative=ARTIFACT_NAMES["index"],
            external_authority_root=source_custody,
            receipt_custody_root=receipt_custody_root,
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


def _publish_partition_custody(
    *,
    module: Any,
    receipt_path: Path,
    expected_receipt_sha: str,
    partition_sidecars: dict[str, bytes],
) -> str:
    """Copy a receipt's directory into custody under its content-addressed prefix.

    Returns the published locator. Refuses a reparsed directory, a reparsed or non-regular file, a
    name outside the expected pattern, or two different byte sequences under one published name.
    """

    authority_prefix = f"partition-authority-{expected_receipt_sha}"
    for current, directories, names in os.walk(
        receipt_path.parent, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        kept: list[str] = []
        for directory in directories:
            child = current_path / directory
            if module._is_reparse_or_symlink(child) or not child.is_dir():
                raise ValueError("partition custody tree is reparsed or non-regular")
            kept.append(directory)
        directories[:] = kept
        for name in names:
            child = current_path / name
            if module._is_reparse_or_symlink(child) or not child.is_file():
                raise ValueError("partition custody file is reparsed or non-regular")
            relative = child.relative_to(receipt_path.parent).as_posix()
            published_name = f"{authority_prefix}/{relative}"
            if PARTITION_AUTHORITY_FILE.fullmatch(published_name) is None:
                raise ValueError("partition custody contains an unexpected file")
            raw = child.read_bytes()
            existing = partition_sidecars.setdefault(published_name, raw)
            if existing != raw:
                raise ValueError("partition sidecar name has conflicting bytes")
    return f"{authority_prefix}/partition-receipt.json"


def _apply_cases(
    *,
    module: Any,
    repo: Path,
    rows: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    predecessor_row_receipts: list[dict[str, Any]],
    predecessor_file_count: int,
    predecessor_total_bytes: int,
    partition_sidecars: dict[str, bytes] | None = None,
    legacy_partition_migration: dict[str, str] | None = None,
    projected_custody_root: Path | None = None,
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
            published_receipt = str(receipt_path.resolve(strict=True))
            if partition_sidecars is not None:
                published_receipt = _publish_partition_custody(
                    module=module,
                    receipt_path=receipt_path,
                    expected_receipt_sha=expected_receipt_sha,
                    partition_sidecars=partition_sidecars,
                )
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
            admitted["license_partition_receipt"] = published_receipt
            row_map[source_id] = admitted
            file_count = reopened["file_count"]
            byte_count = reopened["blob_bytes"]
            total_files += file_count
            total_bytes += byte_count
            row_receipts.append({
                "source_id": source_id,
                "connector_slot": case["connector_slot"],
                "license_partition_receipt_path": published_receipt,
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
    # The repository already owns this transformation. `project_text_lab_custody_paths.project_rows`
    # rewrites the closed twelve-row class's receipt locators to the portable spelling that
    # `receipt_custody_root_binding` declares, AND completes the PDF rows' evidence with
    # `transform_receipt_raw_sha256`, which the projected-row validator requires.
    #
    # An earlier revision of this branch hand-rolled only the partition half and left the PDF half
    # undone. That is why the staging validation refused with "projected PDF license evidence is not
    # closed": the rows were routed down the projected path without being projected. Calling the
    # producer keeps exactly one definition of what a projected row is, and it refuses outright
    # unless the class is the reviewed twelve rows -- a check the hand-rolled rename could not make.
    if projected_custody_root is not None:
        projection = load_projection_module(repo)
        subject = [
            row for row in row_map.values()
            if row["source_id"] in projection.PROJECTED_SOURCE_IDS
        ]
        for row in projection.project_rows(
            subject, receipt_custody_root=projected_custody_root
        ):
            row_map[row["source_id"]] = row
        if legacy_partition_migration:
            # The cure independently proved the portable spelling for every legacy partition row.
            # Requiring the producer to agree with it keeps the cure load-bearing rather than
            # decorative: a disagreement means one of the two is wrong about the custody root.
            spelled = {
                row["license_partition_receipt"]
                for row in row_map.values()
                if row["source_id"] in projection.PARTITION_SOURCE_IDS
            }
            if spelled != set(legacy_partition_migration.values()):
                raise ValueError("projected partition spelling does not match the cure")
        # Projection rewrites evidence bytes, and an L4 receipt binds `evidence_sha256` precisely so
        # that a claim cannot change underneath its receipt. So the receipt is re-derived here with
        # the same function the validator re-derives with. That is derivation, not assertion: the
        # receipt is a function of the evidence, so recomputing it after a rename preserves the
        # invariant the check exists to enforce. Leaving it stale is what the validation refused.
        #
        # Only the PDF rows need this. A partition row's receipt binds `source_sha256` and
        # `license_partition_sha256` and names no path at all, so renaming its locator cannot
        # invalidate it.
        for row in row_map.values():
            if row["source_id"] not in projection.PDF_SOURCE_IDS:
                continue
            receipt = row.get("l4_receipt")
            if not isinstance(receipt, dict):
                raise ValueError("projected PDF row has no receipt to re-derive")
            row["l4_receipt"] = module.local_license_provenance_v1(
                content_sha256=row["content_sha256"],
                license_spdx=row["license_spdx"],
                evidence=row["license_evidence"],
                generator=receipt.get("generator", ""),
            )

        # The predecessor's row receipts are carried forward verbatim (`copy.deepcopy` above) and
        # nothing re-verifies them against the rows they describe. A migrated row whose locator,
        # evidence, or receipt changed would therefore keep a row receipt still quoting the old
        # values, and no check anywhere would catch it. The absence of a check is not permission to
        # leave a false record, so the entries for exactly the migrated rows are updated here.
        migrated_ids = projection.PROJECTED_SOURCE_IDS
        seen_receipts: set[str] = set()
        for receipt_row in row_receipts:
            source_id = receipt_row.get("source_id")
            if source_id not in migrated_ids:
                continue
            row = row_map[source_id]
            seen_receipts.add(source_id)
            if source_id in projection.PARTITION_SOURCE_IDS:
                receipt_row["license_partition_receipt_path"] = row["license_partition_receipt"]
                continue
            evidence = row["license_evidence"]
            receipt_row["connector_receipt_path"] = evidence["connector_receipt_path"]
            receipt_row["transform_receipt_path"] = evidence["transform_receipt_path"]
            receipt_row["license_evidence_sha256"] = sha256_bytes(canonical(evidence))
            receipt_row["l4_receipt_sha256"] = sha256_bytes(canonical(row["l4_receipt"]))
        if seen_receipts != set(migrated_ids):
            raise ValueError("migrated rows are not all covered by predecessor row receipts")
    elif legacy_partition_migration:
        raise ValueError("legacy partition migration requires a projected custody root")
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
    predecessor_projection_receipt: Path | None = None,
    predecessor_projection_receipt_sha256: str | None = None,
    predecessor_receipt_custody_root: Path | None = None,
) -> dict[str, Any]:
    if HEX40.fullmatch(source_commit) is None or HEX64.fullmatch(predecessor_receipt_sha256) is None:
        raise ValueError("source commit or predecessor receipt hash is invalid")
    repo = repo.resolve(strict=True)
    if (predecessor_projection_receipt is None) != (predecessor_projection_receipt_sha256 is None):
        raise ValueError("predecessor projection receipt path/hash must be supplied together")
    if predecessor_projection_receipt_sha256 is not None and HEX64.fullmatch(predecessor_projection_receipt_sha256) is None:
        raise ValueError("predecessor projection receipt hash is invalid")
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

    try:
        source_files = _custody_files(source_custody, module)
    except ValueError as error:
        raise ValueError("predecessor custody file set is not exact") from error
    actual_source_files = set(source_files)
    actual_partition_sidecars = {
        name for name in actual_source_files if PARTITION_AUTHORITY_FILE.fullmatch(name)
    }
    has_partition_cure = PARTITION_BINDING_CURE in actual_source_files
    packet_source_files = (
        actual_source_files - actual_partition_sidecars - {PARTITION_BINDING_CURE}
    )
    expected_v3 = set(ARTIFACT_NAMES.values()) | {predecessor_receipt_name, OUTPUT_LOG}
    expected_v4 = set(PARTITION_ARTIFACT_NAMES.values()) | {predecessor_receipt_name, OUTPUT_LOG}
    allowed_source_sets = {
        frozenset(expected_v3), frozenset(expected_v3 | {OUTPUT_PLAN}),
        frozenset(expected_v4), frozenset(expected_v4 | {OUTPUT_PLAN}),
        frozenset(expected_v3 | {OUTPUT_PLAN, IDENTITY_CURE}),
        frozenset(expected_v4 | {OUTPUT_PLAN, IDENTITY_CURE}),
    }
    if frozenset(packet_source_files) not in allowed_source_sets:
        raise ValueError("predecessor custody file set is not exact")
    source_names = PARTITION_ARTIFACT_NAMES if set(PARTITION_ARTIFACT_NAMES.values()).issubset(packet_source_files) else ARTIFACT_NAMES
    expected_source_files = set(source_names.values()) | {predecessor_receipt_name, OUTPUT_LOG} | actual_partition_sidecars | (
        {PARTITION_BINDING_CURE} if has_partition_cure else set())
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
    if (
        not isinstance(generated_bindings, dict)
        or set(generated_bindings) != set(source_names.values()) | actual_partition_sidecars
    ):
        raise ValueError("predecessor generated-file set is invalid")
    source_raw = {
        name: _bound_generated_file(source_custody, generated_bindings, name, module)
        for name in source_names.values()
    }
    bundle = json.loads(source_raw[source_names["bundle"]])
    corpus = json.loads(source_raw[source_names["corpus"]])
    source_identity = json.loads(source_raw[source_names["identity"]])
    source_index = json.loads(source_raw[source_names["index"]])
    bound_partition_sidecars = {
        row.get("license_partition_receipt"): row.get("license_partition_sha256")
        for row in corpus.get("sources", [])
        if isinstance(row, dict) and "license_partition_receipt" in row
    }
    non_canonical_partition_names = {
        name for name in bound_partition_sidecars
        if isinstance(name, str) and PARTITION_RECEIPT_LOCATOR.fullmatch(name) is None
    }
    portable_partition_names = _portable_partition_names(
        names=non_canonical_partition_names,
        bound_partition_sidecars=bound_partition_sidecars,
        declared_binding=corpus.get("receipt_custody_root_binding"),
        custody_root=predecessor_receipt_custody_root,
        module=module,
    )
    legacy_partition_names = non_canonical_partition_names - portable_partition_names
    cured_partition_names: dict[str, str] = {}
    partition_binding_cure = None
    if legacy_partition_names:
        if not has_partition_cure:
            raise ValueError("predecessor partition sidecar set is invalid")
        cured_partition_names, partition_binding_cure = _validate_partition_binding_cure(
            module=module,
            source_custody=source_custody,
            predecessor_receipt_sha256=predecessor_receipt_sha256,
            predecessor_generated_files=generated_bindings,
            bound_partition_sidecars=bound_partition_sidecars,
            legacy_names=legacy_partition_names,
        )
    elif has_partition_cure:
        # a cure with nothing to cure is a stale artifact, not a harmless extra file
        raise ValueError("partition binding cure covers no legacy rows")
    if partition_binding_cure:
        projected_custody_root = _projected_custody_root(
            partition_binding_cure["canonical_partition_receipts"])
    elif portable_partition_names:
        # Locators already portable stay portable: the successor re-declares the binding against the
        # same root, so a consumer resolves them the way this mint just did.
        projected_custody_root = predecessor_receipt_custody_root.resolve(strict=True)
    else:
        projected_custody_root = None
    expected_partition_sidecars: set[str] = set()
    for name, expected_sha in bound_partition_sidecars.items():
        if name in cured_partition_names or name in portable_partition_names:
            continue
        match = PARTITION_RECEIPT_LOCATOR.fullmatch(name) if isinstance(name, str) else None
        if (
            match is None
            or not isinstance(expected_sha, str)
            or expected_sha != match.group(1)
        ):
            raise ValueError("predecessor partition sidecar set is invalid")
        receipt_raw = _bound_generated_file(
            source_custody, generated_bindings, name, module
        )
        if sha256_bytes(receipt_raw) != expected_sha:
            raise ValueError("predecessor partition sidecar set is invalid")
        try:
            partition_receipt = json.loads(receipt_raw)
            repositories = partition_receipt["repositories"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError("predecessor partition sidecar set is invalid") from error
        if not isinstance(repositories, list):
            raise ValueError("predecessor partition sidecar set is invalid")
        authority_prefix = name.rsplit("/", 1)[0]
        expected_partition_sidecars.add(name)
        for repository in repositories:
            files = repository.get("files") if isinstance(repository, dict) else None
            if not isinstance(files, list):
                raise ValueError("predecessor partition sidecar set is invalid")
            for item in files:
                blob_path = item.get("blob_path") if isinstance(item, dict) else None
                published_name = f"{authority_prefix}/{blob_path}"
                if (
                    not isinstance(blob_path, str)
                    or PARTITION_AUTHORITY_FILE.fullmatch(published_name) is None
                ):
                    raise ValueError("predecessor partition sidecar set is invalid")
                expected_partition_sidecars.add(published_name)
    if expected_partition_sidecars != actual_partition_sidecars:
        raise ValueError("predecessor partition sidecar set is invalid")
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
            receipt_custody_root=predecessor_receipt_custody_root,
        )
    elif predecessor_source_repo is not None:
        raise ValueError("historical predecessor source repo is forbidden for legacy predecessor")
    projection_binding = None
    if predecessor_projection_receipt is not None:
        projection_path = predecessor_projection_receipt.resolve(strict=True)
        projection = load_projection_module(repo).validate_projection_custody(
            repo=repo,
            projection_receipt_path=projection_path,
            expected_receipt_sha256=predecessor_projection_receipt_sha256,
            source_custody=source_custody,
            source_receipt_name=predecessor_receipt_name,
            source_receipt_sha256=predecessor_receipt_sha256,
        )
        projected_raw = projection.get("generated")
        if not isinstance(projected_raw, dict) or set(projected_raw) != set(source_names.values()):
            raise ValueError("projected predecessor artifact set changed")
        source_raw = projected_raw
        bundle = json.loads(source_raw[source_names["bundle"]])
        corpus = json.loads(source_raw[source_names["corpus"]])
        source_identity = json.loads(source_raw[source_names["identity"]])
        source_index = json.loads(source_raw[source_names["index"]])
        projection_binding = {
            "receipt_path": str(projection_path),
            "receipt_sha256": predecessor_projection_receipt_sha256,
        }
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
    partition_sidecars: dict[str, bytes] = {
        name: _bound_generated_file(source_custody, generated_bindings, name, module)
        for name in sorted(actual_partition_sidecars)
    }
    rows, row_receipts, reopened_file_count, reopened_total_bytes = _apply_cases(
        module=module,
        repo=repo,
        rows=rows,
        cases=plan["cases"],
        predecessor_row_receipts=predecessor_row_receipts,
        predecessor_file_count=predecessor_file_count,
        predecessor_total_bytes=predecessor_total_bytes,
        partition_sidecars=partition_sidecars,
        # recorded absolute path -> portable custody-relative spelling, proven by the cure
        legacy_partition_migration=(
            partition_binding_cure["canonical_partition_receipts"]
            if partition_binding_cure else {}
        ),
        projected_custody_root=projected_custody_root,
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
    # Projected locators and their root declaration travel together: the successor carries cured
    # rows spelled relative to a corpus root, so it must say so, or every consumer resolves them
    # inside the authority and finds nothing.
    if projected_custody_root is not None:
        corpus["receipt_custody_root_binding"] = "runtime-supplied-corpus-root-v1"
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
        **partition_sidecars,
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
            target = staging.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (staging / OUTPUT_PLAN).write_bytes(plan_raw)
        staging_validation = module.validate_authority_index(
            repo,
            index_relative=output_names["index"],
            external_authority_root=staging,
            receipt_custody_root=projected_custody_root,
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
                **(
                    {"custody_projection": projection_binding}
                    if projection_binding is not None
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
                "producer_path": "src/ember/infrastructure/tools/ember-restart-3b/mint_issue1719_tranche_admission.py",
                "producer_sha256": sha256_file(
                    repo / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "mint_issue1719_tranche_admission.py"
                ),
                "plan_sha256": sha256_bytes(plan_raw),
                "predecessor_receipt_sha256": predecessor_receipt_sha256,
                "receipt_sha256": sha256_bytes(receipt_raw),
                "overall_authority_result": staging_validation["result"],
            },
        )
        atomic_publish_no_replace(staging, output)
        published = True
        # Same receipt custody root as the staged validation. The published corpus is the staged
        # corpus byte-for-byte, so it declares the same root binding and resolves the same portable
        # locators; only the authority root moves, from staging to the published custody. Passing a
        # different root here -- or none -- would either refuse outright or, worse, return a result
        # that differs from the staged one for a reason having nothing to do with the bytes.
        published_validation = module.validate_authority_index(
            repo,
            index_relative=output_names["index"],
            external_authority_root=output,
            receipt_custody_root=projected_custody_root,
        )
        if published_validation != staging_validation:
            raise ValueError("published authority validation differs from staged validation")
        expected_names = set(generated) | {OUTPUT_RECEIPT, OUTPUT_LOG, OUTPUT_PLAN}
        try:
            published_entries = _custody_files(output, module)
        except ValueError as error:
            raise ValueError("published custody file set changed on reopen") from error
        reopened = {
            name: sha256_file(path)
            for name, path in published_entries.items()
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
    parser.add_argument("--predecessor-projection-receipt", type=Path)
    parser.add_argument("--predecessor-projection-receipt-sha256")
    # A predecessor whose corpus declares `receipt_custody_root_binding` spells its receipt
    # locators relative to a root the caller supplies -- that is what "runtime-supplied" means.
    # Without this, the first successor minted with portable locators could never be reopened,
    # which would strand the next tranche exactly as this tranche was stranded.
    parser.add_argument("--predecessor-receipt-custody-root", type=Path)
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
        predecessor_projection_receipt=args.predecessor_projection_receipt,
        predecessor_projection_receipt_sha256=args.predecessor_projection_receipt_sha256,
        predecessor_receipt_custody_root=args.predecessor_receipt_custody_root,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
