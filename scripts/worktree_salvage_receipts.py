#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Create fail-closed, non-authorizing salvage receipts for registered Git worktrees.

The tool inventories every registered worktree.  It does not remove a directory, update
a ref, or grant retirement authority.  Clean worktrees receive an exact detached-HEAD
reconstruction command.  Dirty worktrees additionally bind every staged, unstaged, and
untracked path to stable local-byte and index-blob evidence and are forced to KEEP.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from types import ModuleType
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


SCHEMA = "ember-worktree-salvage-receipt/v1"
CENSUS_SCHEMA = "ember-worktree-salvage-census/v1"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SalvageError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Worktree:
    path: Path
    head: str
    branch: str | None
    bare: bool
    detached: bool
    locked: str | None
    prunable: str | None

@dataclass(frozen=True)
class RemoteSnapshot:
    refs: dict[str, str]
    sha256: str


def canonical_path(path: str | Path) -> str:
    return str(Path(path).resolve(strict=False))


def path_key(path: str | Path) -> str:
    return canonical_path(path).casefold()


def run_git(
    repo: Path,
    args: Sequence[str],
    *,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="strict" if text else None,
    )
    if check and result.returncode:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise SalvageError("GIT_FAILED", f"{' '.join(args)}: {stderr.strip()}")
    return result


def parse_worktrees(text: str) -> list[Worktree]:
    rows: list[Worktree] = []
    for record in text.strip().split("\n\n"):
        if not record.strip():
            continue
        fields: dict[str, str] = {}
        flags: set[str] = set()
        for line in record.splitlines():
            key, _, value = line.partition(" ")
            if value:
                fields[key] = value
            else:
                flags.add(key)
        raw_path = fields.get("worktree")
        head = fields.get("HEAD")
        if not raw_path or not head or not SHA1_RE.fullmatch(head):
            raise SalvageError("MALFORMED_WORKTREE_LIST", record)
        rows.append(
            Worktree(
                path=Path(canonical_path(raw_path)),
                head=head,
                branch=fields.get("branch"),
                bare="bare" in flags,
                detached="detached" in flags,
                locked=fields.get("locked"),
                prunable=fields.get("prunable"),
            )
        )
    if not rows:
        raise SalvageError("NO_WORKTREES", "git returned no registered worktrees")
    return rows


def list_worktrees(repo: Path) -> list[Worktree]:
    return parse_worktrees(run_git(repo, ["worktree", "list", "--porcelain"]).stdout)


def ref_map_sha256(refs: dict[str, str]) -> str:
    canonical = "".join(f"{refs[ref]}\t{ref}\n" for ref in sorted(refs))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def load_remote_snapshot(repo: Path) -> RemoteSnapshot:
    result = run_git(repo, ["ls-remote", "--heads", "origin"], check=False)
    if result.returncode:
        raise SalvageError(
            "REMOTE_HEADS_UNAVAILABLE",
            result.stderr.strip() or "git ls-remote failed without diagnostics",
        )
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            raise SalvageError("MALFORMED_REMOTE_HEADS", line)
        head, ref = parts
        if not SHA1_RE.fullmatch(head) or not ref.startswith("refs/heads/"):
            raise SalvageError("MALFORMED_REMOTE_HEADS", line)
        if ref in refs:
            raise SalvageError("DUPLICATE_REMOTE_HEAD", ref)
        refs[ref] = head
    if not refs:
        raise SalvageError("NO_REMOTE_HEADS", "origin exposed no branch refs")
    return RemoteSnapshot(refs=refs, sha256=ref_map_sha256(refs))


def load_local_remote_heads(repo: Path) -> dict[str, str]:
    result = run_git(
        repo,
        ["for-each-ref", "--format=%(objectname)%09%(refname)", "refs/remotes/origin"],
    )
    refs: dict[str, str] = {}
    prefix = "refs/remotes/origin/"
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not SHA1_RE.fullmatch(parts[0]):
            raise SalvageError("MALFORMED_LOCAL_REMOTE_HEADS", line)
        sha, local_ref = parts
        if local_ref == "refs/remotes/origin/HEAD":
            continue
        if not local_ref.startswith(prefix):
            raise SalvageError("MALFORMED_LOCAL_REMOTE_HEADS", line)
        public_ref = "refs/heads/" + local_ref[len(prefix):]
        if public_ref in refs:
            raise SalvageError("DUPLICATE_LOCAL_REMOTE_HEAD", public_ref)
        refs[public_ref] = sha
    return refs


def head_durability(
    repo: Path,
    head: str,
    remote: RemoteSnapshot,
    local_remote_heads: dict[str, str],
) -> dict[str, Any]:
    reachable = {ref for ref, sha in remote.refs.items() if sha == head}
    contained = run_git(
        repo,
        [
            "for-each-ref",
            "--format=%(refname)",
            f"--contains={head}",
            "refs/remotes/origin",
        ],
    )
    prefix = "refs/remotes/origin/"
    for local_ref in contained.stdout.splitlines():
        if local_ref == "refs/remotes/origin/HEAD":
            continue
        if not local_ref.startswith(prefix):
            raise SalvageError("MALFORMED_LOCAL_REMOTE_HEAD", local_ref)
        public_ref = "refs/heads/" + local_ref[len(prefix):]
        live_sha = remote.refs.get(public_ref)
        if live_sha is not None and local_remote_heads.get(public_ref) == live_sha:
            reachable.add(public_ref)
    fully_mirrored = all(
        local_remote_heads.get(ref) == sha for ref, sha in remote.refs.items()
    )
    if reachable:
        status = "PROVEN_REACHABLE"
    elif fully_mirrored:
        status = "PROVEN_LOCAL_ONLY"
    else:
        status = "UNRESOLVED_STALE_REMOTE_MIRROR"
    return {
        "status": status,
        "remote_heads_sha256": remote.sha256,
        "remote_head_count": len(remote.refs),
        "head_reachable_from": sorted(reachable),
        "all_remote_heads_exactly_mirrored_locally": fully_mirrored,
        "local_remote_heads_sha256": ref_map_sha256(local_remote_heads),
        "local_remote_head_count": len(local_remote_heads),
    }

def common_dir(repo: Path) -> Path:
    value = run_git(
        repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"]
    ).stdout.strip()
    if not value:
        raise SalvageError("MISSING_COMMON_DIR", str(repo))
    return Path(canonical_path(value))


def load_lifecycle_module() -> ModuleType:
    module_name = "_ember_worktree_lifecycle"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    path = Path(__file__).with_name("worktree_lifecycle.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SalvageError("LIFECYCLE_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def load_lifecycle_state(repo: Path) -> dict[str, Any]:
    path = common_dir(repo) / "ember-worktree-lifecycle.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SalvageError("INVALID_LIFECYCLE_STATE", f"{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SalvageError("INVALID_LIFECYCLE_STATE", "state is not an object")
    required = {
        "version",
        "main_path",
        "legacy_paths",
        "managed",
        "target",
        "ceiling",
        "updated_at",
    }
    if set(payload) != required:
        raise SalvageError(
            "INVALID_LIFECYCLE_STATE",
            f"closed fields mismatch: {sorted(set(payload) ^ required)}",
        )
    if payload["version"] != 1:
        raise SalvageError("INVALID_LIFECYCLE_STATE", "unsupported version")
    if not isinstance(payload["legacy_paths"], list) or not all(
        isinstance(item, str) for item in payload["legacy_paths"]
    ):
        raise SalvageError("INVALID_LIFECYCLE_STATE", "legacy_paths is not a string list")
    if not isinstance(payload["managed"], dict):
        raise SalvageError("INVALID_LIFECYCLE_STATE", "managed is not an object")
    return payload


def decode_paths(raw: bytes, label: str) -> list[str]:
    try:
        values = [item.decode("utf-8", "strict") for item in raw.split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise SalvageError("INVALID_GIT_PATH", f"{label}: {exc}") from exc
    for value in values:
        pure = PurePosixPath(value)
        if (
            not value
            or pure.is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise SalvageError("INVALID_GIT_PATH", f"{label}: {value!r}")
    return values


def git_path_snapshot(worktree: Path) -> dict[str, Any]:
    head = run_git(worktree, ["rev-parse", "--verify", "HEAD"]).stdout.strip()
    if not SHA1_RE.fullmatch(head):
        raise SalvageError("INVALID_HEAD", f"{worktree}: {head!r}")
    branch_result = run_git(worktree, ["symbolic-ref", "-q", "HEAD"], check=False)
    if branch_result.returncode not in {0, 1}:
        raise SalvageError("GIT_FAILED", f"symbolic-ref HEAD: {branch_result.stderr.strip()}")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None

    commands = {
        "unstaged": ["diff", "--name-only", "-z", "--no-renames"],
        "staged": ["diff", "--cached", "--name-only", "-z", "--no-renames"],
        "untracked": ["ls-files", "--others", "--exclude-standard", "-z"],
        "status": ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
    }
    raw: dict[str, bytes] = {}
    path_groups: dict[str, list[str]] = {}
    paths: set[str] = set()
    for label, args in commands.items():
        value = run_git(worktree, args, text=False).stdout
        raw[label] = value
        if label != "status":
            decoded = decode_paths(value, label)
            path_groups[label] = decoded
            paths.update(decoded)
    digest = hashlib.sha256()
    digest.update(head.encode("ascii"))
    digest.update(b"\0")
    digest.update((branch or "").encode("utf-8"))
    for label in sorted(raw):
        digest.update(b"\0" + label.encode("ascii") + b"\0" + raw[label])
    return {
        "head": head,
        "branch": branch,
        "paths": sorted(paths),
        "status_sha256": digest.hexdigest(),
        "untracked": sorted(path_groups["untracked"]),
    }


def hash_regular_file(path: Path) -> dict[str, Any]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise SalvageError("LOCAL_BYTE_INACCESSIBLE", f"{path}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise SalvageError("LOCAL_BYTE_UNSUPPORTED", str(path))
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        after = path.lstat()
    except OSError as exc:
        raise SalvageError("LOCAL_BYTE_INACCESSIBLE", f"{path}: {exc}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or size != after.st_size:
        raise SalvageError("LOCAL_BYTE_DRIFT", str(path))
    return {
        "working_tree_bytes": size,
        "working_tree_sha256": digest.hexdigest(),
    }


def index_entries(
    worktree: Path, relatives: list[str]
) -> dict[str, list[dict[str, Any]]]:
    requested = set(relatives)
    rows: dict[str, list[dict[str, Any]]] = {relative: [] for relative in relatives}
    if not requested:
        return rows
    raw = run_git(worktree, ["ls-files", "--stage", "-z"], text=False).stdout
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            meta, path_raw = record.split(b"\t", 1)
            mode, blob, stage = meta.decode("ascii", "strict").split(" ")
            path_value = path_raw.decode("utf-8", "strict")
        except (ValueError, UnicodeError) as exc:
            raise SalvageError("INVALID_INDEX_ENTRY", repr(record)) from exc
        if not SHA1_RE.fullmatch(blob) or stage not in {"0", "1", "2", "3"}:
            raise SalvageError("INVALID_INDEX_ENTRY", repr(record))
        if path_value in requested:
            rows[path_value].append(
                {"mode": mode, "blob_sha1": blob, "stage": int(stage)}
            )
    return rows


def capture_nested_git_worktree(path: Path, *, nested_depth: int) -> dict[str, Any]:
    if nested_depth > 8:
        raise SalvageError("NESTED_GIT_DEPTH_EXCEEDED", str(path))
    top = run_git(path, ["rev-parse", "--show-toplevel"], check=False)
    if top.returncode or path_key(top.stdout.strip()) != path_key(path):
        raise SalvageError("LOCAL_BYTE_UNSUPPORTED", str(path))

    first = git_path_snapshot(path)
    dirty_first = capture_dirty_bytes(
        path, first["paths"], first["untracked"], nested_depth=nested_depth
    )
    second = git_path_snapshot(path)
    dirty_second = capture_dirty_bytes(
        path, second["paths"], second["untracked"], nested_depth=nested_depth
    )
    third = git_path_snapshot(path)
    if first != second or second != third or dirty_first != dirty_second:
        raise SalvageError("LOCAL_BYTE_DRIFT", str(path))

    return {
        "working_tree_kind": "nested_git_worktree",
        # A nested Git directory is not flattened into one ambiguous file hash.
        "working_tree_bytes": None,
        "working_tree_sha256": None,
        "nested_git": {
            "head_sha": third["head"],
            "branch": third["branch"],
            "status_sha256": third["status_sha256"],
            "dirty_path_count": len(dirty_second),
            "dirty_bytes": dirty_second,
            "stable": True,
            "retirement_authority": "NOT_GRANTED",
        },
    }


def capture_dirty_bytes(
    worktree: Path,
    paths: list[str],
    untracked: list[str],
    *,
    nested_depth: int = 0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = Path(canonical_path(worktree))
    untracked_set = set(untracked)
    entries_by_path = index_entries(
        worktree,
        [relative for relative in paths if relative not in untracked_set],
    )
    for relative in paths:
        candidate = root.joinpath(*PurePosixPath(relative).parts)
        try:
            resolved_parent = candidate.parent.resolve(strict=True)
        except OSError as exc:
            raise SalvageError("LOCAL_BYTE_INACCESSIBLE", f"{candidate}: {exc}") from exc
        if os.path.commonpath([str(root), str(resolved_parent)]) != str(root):
            raise SalvageError("PATH_ESCAPE", relative)
        row: dict[str, Any] = {
            "path": relative,
            # Git has already proven these paths are untracked.
            "index_entries": entries_by_path.get(relative, []),
        }
        if candidate.exists() or candidate.is_symlink():
            try:
                mode = candidate.lstat().st_mode
            except OSError as exc:
                raise SalvageError(
                    "LOCAL_BYTE_INACCESSIBLE", f"{candidate}: {exc}"
                ) from exc
            if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                row.update(
                    capture_nested_git_worktree(
                        candidate, nested_depth=nested_depth + 1
                    )
                )
            else:
                row.update(hash_regular_file(candidate))
        else:
            row.update(
                {
                    "working_tree_bytes": None,
                    "working_tree_sha256": None,
                }
            )
        rows.append(row)
    return rows


def lifecycle_binding(
    state: dict[str, Any], worktree: Worktree
) -> tuple[str, dict[str, Any] | None]:
    key = path_key(worktree.path)
    managed = state["managed"]
    legacy = {str(item).casefold() for item in state["legacy_paths"]}
    if key in managed:
        record = managed[key]
        if not isinstance(record, dict):
            raise SalvageError("INVALID_LIFECYCLE_STATE", f"managed row is not object: {key}")
        required = {
            "path",
            "branch",
            "owner",
            "purpose",
            "expires",
            "created_at",
            "head",
        }
        if set(record) != required or not all(
            isinstance(record[item], str) for item in required
        ):
            raise SalvageError("INVALID_LIFECYCLE_STATE", f"bad managed row: {key}")
        return "MANAGED", record
    if key in legacy:
        return "LEGACY", None
    return "UNMANAGED", None


def capture_worktree(
    repo_common: Path,
    remote_url: str | None,
    remote_snapshot: RemoteSnapshot,
    local_remote_heads: dict[str, str],
    state: dict[str, Any],
    worktree: Worktree,
) -> dict[str, Any]:
    if worktree.bare or worktree.prunable or not worktree.path.is_dir():
        raise SalvageError("WORKTREE_INACCESSIBLE", str(worktree.path))
    first = git_path_snapshot(worktree.path)
    if first["head"] != worktree.head or first["branch"] != worktree.branch:
        raise SalvageError("WORKTREE_DRIFT", str(worktree.path))
    dirty_first = capture_dirty_bytes(
        worktree.path, first["paths"], first["untracked"]
    )
    second = git_path_snapshot(worktree.path)
    dirty_second = capture_dirty_bytes(
        worktree.path, second["paths"], second["untracked"]
    )
    third = git_path_snapshot(worktree.path)
    if first != second or second != third or dirty_first != dirty_second:
        raise SalvageError("WORKTREE_DRIFT", str(worktree.path))

    registration_class, lifecycle = lifecycle_binding(state, worktree)
    durability = head_durability(
        worktree.path, worktree.head, remote_snapshot, local_remote_heads
    )
    if registration_class == "UNMANAGED":
        disposition = "KEEP_UNMANAGED"
    elif dirty_second:
        disposition = "KEEP_DIRTY_LOCAL_BYTES"
    elif durability["status"] == "PROVEN_REACHABLE":
        disposition = "CLEAN_REMOTE_RECONSTRUCTIBLE"
    elif durability["status"] == "PROVEN_LOCAL_ONLY":
        disposition = "KEEP_CLEAN_LOCAL_ONLY"
    else:
        disposition = "KEEP_CLEAN_REMOTE_UNPROVEN"
    canonical = canonical_path(worktree.path)
    identity = hashlib.sha256(canonical.casefold().encode("utf-8")).hexdigest()
    return {
        "schema_version": SCHEMA,
        "repository": {
            "git_common_dir": canonical_path(repo_common),
            "origin_url": remote_url,
        },
        "worktree": {
            "identity_sha256": identity,
            "canonical_path": canonical,
            "head_sha": worktree.head,
            "branch": worktree.branch,
            "detached": worktree.detached,
            "locked": worktree.locked,
        },
        "registration_class": registration_class,
        "lifecycle": lifecycle,
        "snapshot": {
            "stable": True,
            "status_sha256": third["status_sha256"],
            "dirty_path_count": len(dirty_second),
        },
        "dirty_bytes": dirty_second,
        "durability": durability,
        "disposition": disposition,
        "retirement_authority": "NOT_GRANTED",
        "reconstruction": {
            "argv": [
                "git",
                "worktree",
                "add",
                "--detach",
                "<destination>",
                worktree.head,
            ],
            "restores_committed_head_only": True,
            "restores_dirty_local_bytes": False,
        },
    }


def refusal_receipt(
    repo_common: Path,
    remote_url: str | None,
    state: dict[str, Any],
    worktree: Worktree,
    error: SalvageError,
) -> dict[str, Any]:
    canonical = canonical_path(worktree.path)
    identity = hashlib.sha256(canonical.casefold().encode("utf-8")).hexdigest()
    registration_class, lifecycle = lifecycle_binding(state, worktree)
    return {
        "schema_version": SCHEMA,
        "repository": {
            "git_common_dir": canonical_path(repo_common),
            "origin_url": remote_url,
        },
        "worktree": {
            "identity_sha256": identity,
            "canonical_path": canonical,
            "head_sha": worktree.head,
            "branch": worktree.branch,
            "detached": worktree.detached,
            "locked": worktree.locked,
        },
        "registration_class": registration_class,
        "lifecycle": lifecycle,
        "snapshot": {
            "stable": False,
            "status_sha256": None,
            "dirty_path_count": None,
        },
        "dirty_bytes": [],
        "disposition": "REFUSE_INACCESSIBLE",
        "retirement_authority": "NOT_GRANTED",
        "refusal": {
            "code": error.code,
            "detail": str(error),
        },
        "reconstruction": {
            "argv": [
                "git",
                "worktree",
                "add",
                "--detach",
                "<destination>",
                worktree.head,
            ],
            "restores_committed_head_only": True,
            "restores_dirty_local_bytes": False,
        },
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_receipts(
    receipt_dir: Path,
    rows: list[dict[str, Any]],
    remote_snapshot: RemoteSnapshot,
    local_remote_heads: dict[str, str],
) -> dict[str, Any]:
    if receipt_dir.exists() and any(receipt_dir.iterdir()):
        raise SalvageError("OUTPUT_NOT_EMPTY", str(receipt_dir))
    receipt_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for row in rows:
        identity = row["worktree"]["identity_sha256"]
        head = row["worktree"]["head_sha"]
        filename = f"{identity[:16]}-{head[:12]}.json"
        path = receipt_dir / filename
        atomic_json(path, row)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append({"file": filename, "sha256": digest})
    refused = sum(1 for row in rows if row["disposition"] == "REFUSE_INACCESSIBLE")
    unresolved = sum(
        1 for row in rows
        if row["disposition"] == "KEEP_CLEAN_REMOTE_UNPROVEN"
    )
    if refused:
        status = "PARTIAL_REFUSED"
    elif unresolved:
        status = "PARTIAL_UNRESOLVED"
    else:
        status = "PASS"
    summary = {
        "schema_version": CENSUS_SCHEMA,
        "status": status,
        "worktree_count": len(rows),
        "refused_count": refused,
        "unresolved_count": unresolved,
        "dispositions": {
            name: sum(1 for row in rows if row["disposition"] == name)
            for name in sorted({row["disposition"] for row in rows})
        },
        "retirement_authority": "NOT_GRANTED",
        "remote_heads": {
            "sha256": remote_snapshot.sha256,
            "count": len(remote_snapshot.refs),
            "refs": dict(sorted(remote_snapshot.refs.items())),
        },
        "local_remote_heads": {
            "sha256": ref_map_sha256(local_remote_heads),
            "count": len(local_remote_heads),
            "refs": dict(sorted(local_remote_heads.items())),
        },
        "receipts": manifest,
    }
    atomic_json(receipt_dir / "census.json", summary)
    return summary


def capture_all(repo: Path, receipt_dir: Path) -> dict[str, Any]:
    repo = Path(canonical_path(repo))
    common = common_dir(repo)
    lifecycle = load_lifecycle_module()
    try:
        # Lock only lifecycle/registration boundary reads. Individual rows use
        # two byte captures and three Git snapshots to refuse concurrent drift,
        # without blocking unrelated commits during the read-mostly sweep.
        with lifecycle.RepositoryLock(common / lifecycle.LOCK_NAME):
            state = load_lifecycle_state(repo)
            remote = run_git(
                repo, ["config", "--get", "remote.origin.url"], check=False
            )
            if remote.returncode not in {0, 1}:
                raise SalvageError(
                    "GIT_FAILED", f"remote.origin.url: {remote.stderr.strip()}"
                )
            remote_url = remote.stdout.strip() or None
            worktrees = list_worktrees(repo)
            remote_snapshot = load_remote_snapshot(repo)
            local_remote_heads = load_local_remote_heads(repo)

        rows: list[dict[str, Any]] = []
        for worktree in worktrees:
            try:
                receipt = capture_worktree(
                    common,
                    remote_url,
                    remote_snapshot,
                    local_remote_heads,
                    state,
                    worktree,
                )
            except SalvageError as exc:
                receipt = refusal_receipt(
                    common, remote_url, state, worktree, exc
                )
            rows.append(receipt)

        # Refuse publication if lifecycle authority or registration changed
        # during the row-local snapshots.
        with lifecycle.RepositoryLock(common / lifecycle.LOCK_NAME):
            final_state = load_lifecycle_state(repo)
            final_worktrees = list_worktrees(repo)
            if state != final_state:
                raise SalvageError("LIFECYCLE_STATE_DRIFT", str(repo))
            if worktrees != final_worktrees:
                raise SalvageError("WORKTREE_SET_DRIFT", str(repo))
    except lifecycle.LifecycleError as exc:
        raise SalvageError(
            getattr(exc, "code", "LIFECYCLE_LOCK_FAILED"),
            str(exc),
        ) from exc
    return write_receipts(
        receipt_dir, rows, remote_snapshot, local_remote_heads
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--receipt-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = capture_all(Path(args.repo), Path(args.receipt_dir))
    except SalvageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
