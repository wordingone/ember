# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic, read-only custody and benchmark census primitives."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import secrets
import re
import subprocess
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable, Mapping

from issue_census import validate_issue_census


DIRECT_MANDATE_IDS = {
    "swe-bench-pro",
    "frontiercode-diamond",
    "gdpval-aa",
    "gdppdf",
    "blueprint-bench-2",
    "automationbench",
    "osworld-verified",
    "legal-agent-benchmark",
    "humanitys-last-exam",
    "terminal-bench-2.1",
    "arc-agi-1",
    "arc-agi-2",
    "arc-agi-3",
}


HASH_ALGORITHM = "sha256-byte-stream-v1"


def hash_file_streaming(
    path: Path,
    chunk_size: int = 1024 * 1024,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    completed = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            completed += len(chunk)
            if on_progress is not None:
                on_progress({"state": "partial", "completed_bytes": completed})
    return {
        "state": "complete",
        "size_bytes": completed,
        "sha256": digest.hexdigest(),
        "algorithm": HASH_ALGORITHM,
    }


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    return str(hash_file_streaming(path, chunk_size=chunk_size)["sha256"])


def append_hash_journal(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")
        stream.flush()


def load_hash_journal(path: Path) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get("state") != "complete":
                continue
            key = record.get("artifact_key")
            digest = record.get("sha256")
            if (
                not isinstance(key, str)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or record.get("algorithm") != HASH_ALGORITHM
            ):
                continue
            completed[key] = record
    return completed


def _discover_file_rows(
    root: Path,
) -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    candidates: list[tuple[str, Path]] = []
    errors: list[dict[str, Any]] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            errors.append({
                "relative_path": directory.relative_to(root).as_posix(),
                "exception": type(exc).__name__,
                "winerror": getattr(exc, "winerror", None),
                "errno": exc.errno,
            })
            continue
        for candidate in children:
            try:
                if candidate.is_dir():
                    pending.append(candidate)
                elif candidate.is_file():
                    candidates.append((candidate.relative_to(root).as_posix(), candidate))
            except OSError as exc:
                errors.append({
                    "relative_path": candidate.relative_to(root).as_posix(),
                    "exception": type(exc).__name__,
                    "winerror": getattr(exc, "winerror", None),
                    "errno": exc.errno,
                })
                candidates.append((candidate.relative_to(root).as_posix(), candidate))
    return sorted(candidates), sorted(errors, key=lambda row: row["relative_path"])


def _file_rows(root: Path) -> Iterable[tuple[str, Path]]:
    rows, _ = _discover_file_rows(root)
    yield from rows


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for relative, path in _file_rows(root):
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            "git command failed: "
            + " ".join(arguments)
            + ": "
            + (result.stderr.strip() or result.stdout.strip())
        )
    return result.stdout.replace("\r\n", "\n").rstrip("\n")


def git_reference_inventory(root_id: str, root: Path) -> dict[str, Any]:
    refs = _git(
        root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        "refs",
    )
    normalized = sorted(line for line in refs.splitlines() if line)
    names = sorted(line.partition("\x00")[0] for line in normalized)
    serialized = "\n".join(normalized)
    return {
        "root_id": root_id,
        "ref_names": names,
        "ref_count": len(normalized),
        "refs_sha256": _sha256_text(serialized),
        "stash_present": "refs/stash" in names,
        "pull_ref_count": sum(name.startswith("refs/pull/") for name in names),
    }


def git_repository_summary(root_id: str, root: Path) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD")
    is_bare = _git(root, "rev-parse", "--is-bare-repository") == "true"
    branch_result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    branch = (
        branch_result.stdout.strip().replace("\\", "/")
        if branch_result.returncode == 0
        else None
    )
    status = (
        None
        if is_bare
        else _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    )
    normalized_status = "\n".join(sorted(status.splitlines())) if status else ""
    refs = git_reference_inventory(root_id, root)
    reachable = "\n".join(sorted(_git(root, "rev-list", "--objects", "--all").splitlines()))
    tracked_tree = "\n".join(sorted(_git(root, "ls-tree", "-r", "--full-tree", head).splitlines()))
    index_manifest = None if is_bare else "\n".join(sorted(_git(root, "ls-files", "--stage").splitlines()))
    return {
        "root_id": root_id,
        "head": head,
        "is_bare": is_bare,
        "branch": branch,
        "detached": branch is None,
        "dirty": None if is_bare else bool(normalized_status),
        "status_sha256": None if is_bare else _sha256_text(normalized_status),
        "status_entry_count": (
            len(normalized_status.splitlines()) if normalized_status else 0
        ),
        "refs_sha256": refs["refs_sha256"],
        "ref_count": refs["ref_count"],
        "stash_present": refs["stash_present"],
        "pull_ref_count": refs["pull_ref_count"],
        "reachable_object_count": len(reachable.splitlines()) if reachable else 0,
        "reachable_object_manifest_sha256": _sha256_text(reachable),
        "tracked_tree_entry_count": len(tracked_tree.splitlines()) if tracked_tree else 0,
        "tracked_tree_manifest_sha256": _sha256_text(tracked_tree),
        "index_entry_count": None if index_manifest is None else len(index_manifest.splitlines()),
        "index_manifest_sha256": None if index_manifest is None else _sha256_text(index_manifest),
    }

def parse_worktree_porcelain(text: str) -> list[dict[str, Any]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        values: dict[str, str | bool] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            values[key] = value if value else True
        local_path = str(values.get("worktree", ""))
        if not local_path:
            continue
        branch = values.get("branch")
        parsed.append(
            (
                local_path.replace("\\", "/").casefold(),
                {
                    "normalized_path": local_path.replace("\\", "/"),
                    "head": str(values.get("HEAD", "")),
                    "branch": str(branch) if isinstance(branch, str) else None,
                    "detached": bool(values.get("detached")),
                    "prunable": bool(values.get("prunable")),
                },
            )
        )
    return [
        {
            "worktree_id": "worktree-" + hashlib.sha256(
                normalized_path.encode("utf-8")
            ).hexdigest()[:16],
            **row,
        }
        for normalized_path, row in sorted(parsed, key=lambda item: item[0])
    ]


def _git_material_paths(root: Path) -> list[str]:
    paths: set[str] = set()
    commands = (
        ("ls-files", "--modified", "--others", "--exclude-standard", "-z"),
        ("diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB", "-z"),
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
    )
    for arguments in commands:
        output = _git(root, *arguments)
        paths.update(
            item.replace("\\", "/")
            for item in output.split("\0")
            if item
        )
    return sorted(paths)

def _material_file_rows(
    root: Path, paths: Iterable[str], prefix: str = ""
) -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    rows: list[tuple[str, Path]] = []
    errors: list[dict[str, Any]] = []
    for relative in sorted(set(paths)):
        candidate = root / Path(relative)
        if candidate.is_dir():
            nested, nested_errors = _discover_file_rows(candidate)
            rows.extend((f"{prefix}{relative}/{child}", path) for child, path in nested)
            errors.extend(
                {**error, "relative_path": f"{prefix}{relative}/{error['relative_path']}"}
                for error in nested_errors
            )
        else:
            rows.append((f"{prefix}{relative}", candidate))
    return rows, errors


def canonical_root_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    encoded = json.loads(json.dumps(payload))
    for artifact in encoded.get("artifacts", []):
        artifact.pop("mtime_ns_non_authoritative", None)
    return encoded


def build_duplicate_groups(artifacts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for artifact in artifacts:
        digest = artifact.get("sha256")
        artifact_id = artifact.get("artifact_id")
        if isinstance(digest, str) and isinstance(artifact_id, str):
            by_hash[digest].append(artifact_id)
    return [
        {"sha256": digest, "artifact_ids": sorted(ids)}
        for digest, ids in sorted(by_hash.items())
        if len(ids) > 1
    ]


def detect_contradictions(
    artifacts: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_identity: dict[str, set[str]] = defaultdict(set)
    for artifact in artifacts:
        artifact_id = artifact.get("artifact_id")
        digest = artifact.get("sha256")
        if isinstance(artifact_id, str) and isinstance(digest, str):
            by_identity[artifact_id].add(digest)
    return [
        {
            "code": "conflicting_artifact_identity",
            "artifact_id": artifact_id,
            "candidate_sha256": sorted(hashes),
            "resolution": "unresolved_preserve_all",
        }
        for artifact_id, hashes in sorted(by_identity.items())
        if len(hashes) > 1
    ]


def build_root_census(
    specification: Mapping[str, Any],
    bindings: Mapping[str, Path],
    journal_path: Path | None = None,
) -> dict[str, Any]:
    roots: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    # Journals are progress receipts only. Exact custody hashes always come
    # from current bytes; metadata can be restored without restoring bytes.
    if journal_path:
        load_hash_journal(journal_path)
    direct_paths: dict[str, list[str]] = defaultdict(list)
    for candidate_spec in specification.get("roots", []):
        if candidate_spec.get("source_root_id"):
            continue
        candidate_id = candidate_spec.get("root_id")
        candidate_bound = bindings.get(candidate_id)
        if (
            isinstance(candidate_id, str)
            and candidate_bound is not None
            and Path(candidate_bound).exists()
        ):
            key = str(Path(candidate_bound).resolve()).replace("\\", "/").casefold()
            direct_paths[key].append(candidate_id)
    for root_ids in direct_paths.values():
        if len(root_ids) > 1:
            contradictions.append(
                {
                    "code": "root_path_alias",
                    "root_ids": sorted(root_ids),
                    "resolution": "unresolved_preserve_all",
                }
            )
    physical_hash_cache: dict[tuple[object, ...], str] = {}
    for root_spec in sorted(
        specification.get("roots", []), key=lambda row: row["root_id"]
    ):
        root_id = root_spec["root_id"]
        scan = root_spec.get("scan", "files")
        source_root_id = root_spec.get("source_root_id")
        binding_id = source_root_id if isinstance(source_root_id, str) else root_id
        bound_value = bindings.get(binding_id)
        bound = Path(bound_value) if bound_value is not None else None
        present = bool(bound is not None and bound.exists())
        root_row = {
            "root_id": root_id,
            "required": bool(root_spec.get("required")),
            "present": present,
            "scan": scan,
            "provenance_class": root_spec.get(
                "provenance_class", "unresolved"
            ),
            "lineage_admissibility": root_spec.get(
                "lineage_admissibility", "unresolved"
            ),
        }
        if not isinstance(source_root_id, str) and bound is not None:
            root_row["normalized_bound_path"] = str(bound.resolve()).replace("\\", "/")
        roots.append(root_row)
        if not present:
            if root_spec.get("required"):
                contradictions.append(
                    {
                        "code": (
                            "required_source_binding_missing"
                            if bound is None and source_root_id
                            else "required_root_missing"
                        ),
                        "root_id": root_id,
                        "resolution": "unresolved",
                    }
                )
            continue
        assert bound is not None
        provenance_class = root_spec.get("provenance_class", "unresolved")
        lineage_admissibility = root_spec.get(
            "lineage_admissibility", "unresolved"
        )

        def virtual_artifact(relative: str, digest: str) -> dict[str, Any]:
            return {
                "artifact_id": f"{root_id}:{relative}",
                "source": {"root_id": root_id, "relative_path": relative},
                "sha256": digest,
                "size_bytes": 0,
                "mtime_ns_non_authoritative": None,
                "provenance_class": provenance_class,
                "lineage_admissibility": lineage_admissibility,
                "mutability": root_spec.get("mutability", "unresolved"),
                "owner": root_spec.get("owner", "unresolved"),
                "authority_status": root_spec.get(
                    "authority_status", "unresolved"
                ),
            }

        file_candidates: list[tuple[str, Path]] | None = None
        directory_errors: list[dict[str, Any]] = []
        initial_membership: list[str] | None = None
        initial_git_summary: dict[str, Any] | None = None
        initial_discovery_snapshot: list[dict[str, Any]] | None = None
        initial_content_identities: dict[str, tuple[str, int]] = {}
        final_discovery_candidates: list[tuple[str, Path]] | None = None
        try:
            if scan == "git_repository":
                summary = git_repository_summary(root_id, bound)
                root_row["git"] = summary
                initial_git_summary = summary
                artifacts.extend(
                    [
                        virtual_artifact("git-refs", summary["refs_sha256"]),
                        virtual_artifact("git-status", summary["status_sha256"]),
                        virtual_artifact("git-reachable-objects", summary["reachable_object_manifest_sha256"]),
                        virtual_artifact("git-tracked-tree", summary["tracked_tree_manifest_sha256"]),
                    ]
                )
                if summary["index_manifest_sha256"] is not None:
                    artifacts.append(virtual_artifact("git-index", summary["index_manifest_sha256"]))
                if summary["is_bare"]:
                    file_candidates = []
                else:
                    file_candidates, directory_errors = _material_file_rows(
                        bound, _git_material_paths(bound), "git-material/"
                    )
                    initial_membership = [
                        relative for relative, _ in file_candidates
                    ]
            if scan == "git_remote":
                remote_name = str(root_spec.get("remote_name", ""))
                remote_names = set(_git(bound, "remote").splitlines())
                remote_present = bool(remote_name and remote_name in remote_names)
                root_row["present"] = remote_present
                if not remote_present:
                    if root_spec.get("required"):
                        contradictions.append(
                            {
                                "code": "required_git_remote_missing",
                                "root_id": root_id,
                                "resolution": "unresolved",
                            }
                        )
                    continue
                refs = _git(
                    bound,
                    "for-each-ref",
                    "--format=%(refname)%00%(objectname)",
                    f"refs/remotes/{remote_name}",
                )
                normalized_refs = "\n".join(sorted(refs.splitlines()))
                digest = _sha256_text(normalized_refs)
                root_row["git_remote"] = {
                    "remote_name": remote_name,
                    "ref_count": len(normalized_refs.splitlines())
                    if normalized_refs
                    else 0,
                    "refs_sha256": digest,
                }
                artifacts.append(virtual_artifact("git-remote-refs", digest))
                continue
            if scan == "directory_discovery":
                patterns = root_spec.get("name_patterns")
                if (
                    not isinstance(patterns, list)
                    or not patterns
                    or not all(isinstance(item, str) and item for item in patterns)
                ):
                    raise ValueError("directory_discovery requires name_patterns")
                children = sorted(
                    (
                        child
                        for child in bound.iterdir()
                        if any(
                            fnmatch.fnmatch(child.name.casefold(), pattern.casefold())
                            for pattern in patterns
                        )
                    ),
                    key=lambda child: child.name.casefold(),
                )
                discovered: list[dict[str, Any]] = []
                file_candidates = []
                for child in children:
                    normalized_path = str(child.resolve()).replace("\\", "/")
                    git_probe = subprocess.run(
                        ["git", "rev-parse", "--git-dir"],
                        cwd=child if child.is_dir() else bound,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        capture_output=True,
                        check=False,
                    )
                    if child.is_dir() and git_probe.returncode == 0:
                        summary = git_repository_summary(
                            f"{root_id}:{child.name}", child
                        )
                        kind = "bare_git" if summary["is_bare"] else "git_worktree"
                        discovered.append(
                            {
                                "name": child.name,
                                "normalized_path": normalized_path,
                                "kind": kind,
                                "git": summary,
                            }
                        )
                        git_identities = {
                            "git-refs": summary["refs_sha256"],
                            "git-reachable-objects": summary["reachable_object_manifest_sha256"],
                            "git-tracked-tree": summary["tracked_tree_manifest_sha256"],
                            "git-status": summary["status_sha256"],
                            "git-index": summary["index_manifest_sha256"],
                        }
                        artifacts.extend(
                            virtual_artifact(f"{child.name}/{suffix}", digest)
                            for suffix, digest in git_identities.items()
                            if digest is not None
                        )
                        if not summary["is_bare"]:
                            material_rows, material_errors = _material_file_rows(
                                child,
                                _git_material_paths(child),
                                f"{child.name}/git-material/",
                            )
                            file_candidates.extend(material_rows)
                            directory_errors.extend(material_errors)
                    else:
                        discovered.append(
                            {
                                "name": child.name,
                                "normalized_path": normalized_path,
                                "kind": "non_git",
                            }
                        )
                        if child.is_file():
                            file_candidates.append((child.name, child))
                        elif child.is_dir():
                            nested_rows, nested_errors = _discover_file_rows(child)
                            file_candidates.extend(
                                (f"{child.name}/{relative}", candidate)
                                for relative, candidate in nested_rows
                            )
                            directory_errors.extend(
                                {**error, "relative_path": f"{child.name}/{error['relative_path']}"}
                                for error in nested_errors
                            )
                root_row["discovered_roots"] = discovered
                root_row["discovered_root_count"] = len(discovered)
                initial_discovery_snapshot = discovered
            if scan == "git_worktree_registry":
                worktrees = parse_worktree_porcelain(
                    _git(bound, "worktree", "list", "--porcelain")
                )
                root_row["worktrees"] = worktrees
                serialized = json.dumps(
                    worktrees, sort_keys=True, separators=(",", ":")
                )
                artifacts.append(
                    virtual_artifact("git-worktree-registry", _sha256_text(serialized))
                )
                continue
            if scan == "git_worktree_material_registry":
                worktrees = parse_worktree_porcelain(
                    _git(bound, "worktree", "list", "--porcelain")
                )
                root_row["worktrees"] = worktrees
                root_row["registered_worktree_count"] = len(worktrees)
                file_candidates = []
                worktree_errors: list[dict[str, Any]] = []
                materialized = 0
                for worktree in worktrees:
                    worktree_path = Path(worktree["normalized_path"])
                    if not worktree_path.exists():
                        error = {
                            "code": "registered_worktree_missing",
                            "root_id": root_id,
                            "worktree_id": worktree["worktree_id"],
                            "resolution": "unresolved",
                        }
                        contradictions.append(error)
                        worktree_errors.append(error)
                        continue
                    try:
                        material_paths = _git_material_paths(worktree_path)
                    except Exception as exc:
                        error = {
                            "code": "registered_worktree_scan_failed",
                            "root_id": root_id,
                            "worktree_id": worktree["worktree_id"],
                            "exception": type(exc).__name__,
                            "resolution": "unresolved",
                        }
                        contradictions.append(error)
                        worktree_errors.append(error)
                        continue
                    materialized += 1
                    file_candidates.extend(
                        (
                            f"{worktree['worktree_id']}/{relative}",
                            worktree_path / Path(relative),
                        )
                        for relative in material_paths
                        if (worktree_path / Path(relative)).is_file()
                    )
                root_row["materialized_worktree_count"] = materialized
                root_row["worktree_errors"] = worktree_errors
            if scan == "git_ignored_registry":
                ignored_text = _git(
                    bound,
                    "ls-files",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "-z",
                )
                ignored_paths = sorted(
                    relative.replace("\\", "/")
                    for relative in ignored_text.split("\0")
                    if relative
                )
                root_row["ignored_entry_count"] = len(ignored_paths)
                file_candidates, directory_errors = _material_file_rows(
                    bound, ignored_paths
                )
                initial_membership = [relative for relative, _ in file_candidates]
            if scan != "files":
                if scan not in {
                    "directory_discovery",
                    "git_ignored_registry",
                    "git_worktree_material_registry",
                    "git_repository",
                }:
                    raise ValueError(f"unsupported scan mode: {scan}")
        except Exception as exc:
            root_row["present"] = False
            contradictions.append(
                {
                    "code": "root_scan_failed",
                    "root_id": root_id,
                    "detail": str(exc),
                    "resolution": "unresolved",
                }
            )
            continue
        if file_candidates is not None:
            candidates = file_candidates
        elif bound.is_file():
            candidates = [(bound.name, bound)]
        else:
            candidates, directory_errors = _discover_file_rows(bound)
            initial_membership = [relative for relative, _ in candidates]
        if initial_membership is None:
            initial_membership = [relative for relative, _ in candidates]
        for error in directory_errors:
            contradictions.append({
                "code": "directory_coverage_inaccessible",
                "root_id": root_id,
                **error,
                "resolution": "unresolved_preserve_directory",
            })
        for relative, path in candidates:
            artifact_key = f"{root_id}:{relative}"
            base_row = {
                "artifact_id": artifact_key,
                "source": {
                    "root_id": root_id,
                    "relative_path": relative,
                },
                "provenance_class": provenance_class,
                "lineage_admissibility": lineage_admissibility,
                "mutability": root_spec.get("mutability", "unresolved"),
                "owner": root_spec.get("owner", "unresolved"),
                "authority_status": root_spec.get(
                    "authority_status", "unresolved"
                ),
            }
            try:
                stat = path.stat()
                physical_key = (
                    str(path.resolve()).replace("\\", "/").casefold(),
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                )
                physical_digest = physical_hash_cache.get(physical_key)
                if physical_digest is not None:
                    digest = physical_digest
                else:
                    def progress(record: dict[str, Any]) -> None:
                        if journal_path is not None:
                            append_hash_journal(
                                journal_path,
                                {
                                    **record,
                                    "artifact_key": artifact_key,
                                    "size_bytes": stat.st_size,
                                    "mtime_ns_non_authoritative": stat.st_mtime_ns,
                                },
                            )

                    result = hash_file_streaming(
                        path,
                        on_progress=(
                            progress if stat.st_size > 1024 * 1024 else None
                        ),
                    )
                    post_stat = path.stat()
                    post_key = (
                        str(path.resolve()).replace("\\", "/").casefold(),
                        post_stat.st_dev,
                        post_stat.st_ino,
                        post_stat.st_size,
                        post_stat.st_mtime_ns,
                        post_stat.st_ctime_ns,
                    )
                    if (
                        post_key != physical_key
                        or result["size_bytes"] != post_stat.st_size
                    ):
                        raise RuntimeError("artifact_mutated_during_hash")
                    digest = str(result["sha256"])
                    if journal_path is not None:
                        append_hash_journal(
                            journal_path,
                            {
                                **result,
                                "artifact_key": artifact_key,
                                "mtime_ns_non_authoritative": stat.st_mtime_ns,
                            },
                        )
                    physical_hash_cache[physical_key] = digest
            except RuntimeError as exc:
                if str(exc) != "artifact_mutated_during_hash":
                    raise
                artifacts.append(
                    {
                        **base_row,
                        "sha256": None,
                        "size_bytes": None,
                        "mtime_ns_non_authoritative": None,
                        "hash_source": "rejected_mutation",
                    }
                )
                contradictions.append(
                    {
                        "code": "artifact_mutated_during_hash",
                        "root_id": root_id,
                        "relative_path": relative,
                        "resolution": "unresolved_preserve_entry",
                    }
                )
                continue
            except OSError as exc:
                access_error = {
                    "exception": type(exc).__name__,
                    "winerror": getattr(exc, "winerror", None),
                    "errno": exc.errno,
                }
                artifacts.append(
                    {
                        **base_row,
                        "sha256": None,
                        "size_bytes": None,
                        "mtime_ns_non_authoritative": None,
                        "access_error": access_error,
                    }
                )
                contradictions.append(
                    {
                        "code": "artifact_access_failed",
                        "root_id": root_id,
                        "relative_path": relative,
                        **access_error,
                        "resolution": "unresolved_preserve_entry",
                    }
                )
                continue
            artifacts.append(
                {
                    **base_row,
                    "sha256": digest,
                    "size_bytes": stat.st_size,
                    "mtime_ns_non_authoritative": stat.st_mtime_ns,
                    "hash_source": "current_bytes",
                }
            )
            initial_content_identities[relative] = (digest, stat.st_size)
        if scan == "directory_discovery" and initial_discovery_snapshot is not None:
            patterns = root_spec["name_patterns"]
            final_discovery_snapshot: list[dict[str, Any]] = []
            final_discovery_candidates = []
            for child in sorted(
                (
                    child for child in bound.iterdir()
                    if any(
                        fnmatch.fnmatch(child.name.casefold(), pattern.casefold())
                        for pattern in patterns
                    )
                ),
                key=lambda child: child.name.casefold(),
            ):
                normalized_path = str(child.resolve()).replace("\\", "/")
                git_probe = subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=child if child.is_dir() else bound,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    check=False,
                )
                if child.is_dir() and git_probe.returncode == 0:
                    summary = git_repository_summary(f"{root_id}:{child.name}", child)
                    final_discovery_snapshot.append({
                        "name": child.name,
                        "normalized_path": normalized_path,
                        "kind": "bare_git" if summary["is_bare"] else "git_worktree",
                        "git": summary,
                    })
                    if not summary["is_bare"]:
                        material_rows, _ = _material_file_rows(
                            child, _git_material_paths(child), f"{child.name}/git-material/"
                        )
                        final_discovery_candidates.extend(material_rows)
                else:
                    final_discovery_snapshot.append({
                        "name": child.name,
                        "normalized_path": normalized_path,
                        "kind": "non_git",
                    })
                    if child.is_file():
                        final_discovery_candidates.append((child.name, child))
                    elif child.is_dir():
                        nested_rows, _ = _discover_file_rows(child)
                        final_discovery_candidates.extend(
                            (f"{child.name}/{relative}", candidate)
                            for relative, candidate in nested_rows
                        )
            if final_discovery_snapshot != initial_discovery_snapshot:
                contradictions.append({
                    "code": "directory_snapshot_changed_during_scan",
                    "root_id": root_id,
                    "resolution": "unresolved_retry_snapshot",
                })
        if scan == "git_repository" and initial_git_summary is not None:
            final_git_summary = git_repository_summary(root_id, bound)
            if final_git_summary != initial_git_summary:
                contradictions.append({
                    "code": "git_snapshot_changed_during_scan",
                    "root_id": root_id,
                    "resolution": "unresolved_retry_snapshot",
                })
        if initial_membership is not None:
            if scan == "git_repository":
                final_paths, _ = _material_file_rows(
                    bound, _git_material_paths(bound), "git-material/"
                )
                final_membership = [relative for relative, _ in final_paths]
            elif scan == "directory_discovery" and final_discovery_candidates is not None:
                final_membership = [relative for relative, _ in final_discovery_candidates]
            elif scan == "git_ignored_registry":
                final_ignored = [
                    relative.replace("\\", "/")
                    for relative in _git(
                        bound, "ls-files", "--others", "--ignored",
                        "--exclude-standard", "-z"
                    ).split("\0") if relative
                ]
                final_paths, _ = _material_file_rows(bound, final_ignored)
                final_membership = [relative for relative, _ in final_paths]
            elif scan == "files" and bound.is_dir():
                final_membership = [
                    relative for relative, _ in _discover_file_rows(bound)[0]
                ]
            else:
                final_membership = initial_membership
            if final_membership != initial_membership:
                contradictions.append({
                    "code": "directory_membership_changed_during_scan",
                    "root_id": root_id,
                    "resolution": "unresolved_retry_snapshot",
                })
        for relative, path in candidates:
            expected = initial_content_identities.get(relative)
            if expected is None:
                continue
            try:
                final_stat = path.stat()
                final_hash = hash_file_streaming(path)
                final_post_stat = path.stat()
                if (
                    final_stat.st_size != final_post_stat.st_size
                    or final_stat.st_mtime_ns != final_post_stat.st_mtime_ns
                    or final_hash["size_bytes"] != final_post_stat.st_size
                    or (str(final_hash["sha256"]), final_post_stat.st_size) != expected
                ):
                    raise RuntimeError("artifact_changed_after_hash")
            except (OSError, RuntimeError):
                contradictions.append({
                    "code": "artifact_changed_after_hash",
                    "root_id": root_id,
                    "relative_path": relative,
                    "resolution": "unresolved_retry_snapshot",
                })
    artifacts.sort(
        key=lambda row: (
            row["source"]["root_id"],
            row["source"]["relative_path"],
        )
    )
    contradictions.extend(detect_contradictions(artifacts))
    return {
        "schema": "ember-01-root-census-v1",
        "hash_algorithm": HASH_ALGORITHM,
        "proof_mode": "current_bytes_rehashed",
        "roots": roots,
        "artifacts": artifacts,
        "duplicate_groups": build_duplicate_groups(artifacts),
        "contradictions": sorted(
            contradictions,
            key=lambda row: (row["code"], row.get("root_id", ""), row.get("artifact_id", "")),
        ),
    }


def validate_benchmark_registry(
    registry: Mapping[str, Any], repository_root: Path | None = None,
    source_commit: str | None = None,
) -> list[str]:
    errors: list[str] = []
    rows = registry.get("benchmarks")
    if not isinstance(rows, list):
        return ["benchmarks_not_list"]
    identifiers = [
        row.get("benchmark_id") for row in rows if isinstance(row, Mapping)
    ]
    for benchmark_id in sorted(DIRECT_MANDATE_IDS - set(identifiers)):
        errors.append(f"direct_mandate_missing:{benchmark_id}")
    duplicates = sorted(
        benchmark_id
        for benchmark_id in set(identifiers)
        if identifiers.count(benchmark_id) > 1
    )
    errors.extend(f"benchmark_id_duplicate:{item}" for item in duplicates)
    unresolved = sum(
        1
        for row in rows
        if isinstance(row, Mapping)
        and row.get("provenance_class") == "unresolved_direct_request"
    )
    required_unresolved = max(
        0,
        int(registry.get("operator_recollection_minimum", 15))
        - int(registry.get("direct_recovered_minimum", 13)),
    )
    if unresolved < required_unresolved:
        errors.append(
            f"unresolved_direct_requests_missing:{required_unresolved - unresolved}"
        )
    required_fields = (
        "split",
        "harness_path",
        "harness_identity",
        "comparator_requirements",
        "lineage_admissibility",
        "completion_eligibility",
    )
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        benchmark_id = row.get("benchmark_id", "<missing>")
        for field in required_fields:
            if field not in row:
                errors.append(f"required_field_missing:{benchmark_id}:{field}")
        comparator = row.get("comparator_requirements")
        if isinstance(comparator, Mapping) and (
            comparator.get("owned_subject_required") is not True
            or comparator.get("borrowed_reference_role") != "frozen_reference_only"
            or comparator.get("lineage_signal_allowed") is not False
        ):
            errors.append(f"comparator_boundary_invalid:{benchmark_id}")
        if (
            row.get("completion") is True
            and row.get("provenance_class")
            not in {"direct_mandate", "broader_research_candidate"}
        ):
            errors.append(f"completion_benchmark_class_not_frozen:{benchmark_id}")
    for row in rows:
        if not isinstance(row, Mapping) or row.get("completion") is not True:
            continue
        benchmark_id = row.get("benchmark_id", "<missing>")
        if row.get("subject_class") != "owned_admissible_ember_checkpoint":
            errors.append(f"completion_subject_not_owned:{benchmark_id}")
        if row.get("lineage_admissibility") != "owned_subject_only":
            errors.append(f"completion_lineage_not_admissible:{benchmark_id}")
        if row.get("execution_status") != "executed":
            errors.append(f"completion_not_executed:{benchmark_id}")
        for field in ("version", "split"):
            value = row.get(field)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value.casefold() == "unresolved"
            ):
                errors.append(f"completion_{field}_unresolved:{benchmark_id}")
        exact_values = {
            "harness_status": "verified",
            "data_status": "frozen",
            "license_status": "verified",
            "completion_eligibility": "eligible_exact_owned_execution",
        }
        for field, expected in exact_values.items():
            if row.get(field) != expected:
                errors.append(f"completion_{field}_invalid:{benchmark_id}")
        bindings = (
            ("harness_path", "harness_identity"),
            ("subject_manifest_path", "subject_manifest"),
            ("result_receipt_path", "result_receipt"),
            ("data_evidence_path", "data_evidence"),
            ("license_evidence_path", "license_evidence"),
        )
        for path_field, identity_field in bindings:
            relative = row.get(path_field)
            identity = row.get(identity_field)
            if not isinstance(relative, str) or not relative.strip():
                errors.append(f"completion_{path_field}_missing:{benchmark_id}")
                continue
            if not isinstance(identity, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is None:
                errors.append(f"completion_{identity_field}_not_content_bound:{benchmark_id}")
                continue
            if repository_root is None:
                errors.append(f"completion_repository_unresolved:{benchmark_id}")
                continue
            root = repository_root.resolve()
            if source_commit is None:
                errors.append(f"completion_source_commit_unresolved:{benchmark_id}")
                continue
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                errors.append(f"completion_{path_field}_outside_repository:{benchmark_id}")
                continue
            shown = subprocess.run(
                ["git", "show", f"{source_commit}:{relative_path.as_posix()}"],
                cwd=root,
                capture_output=True,
                check=False,
            )
            if shown.returncode != 0:
                errors.append(f"completion_{path_field}_unresolved:{benchmark_id}")
                continue
            actual = "sha256:" + hashlib.sha256(shown.stdout).hexdigest()
            if actual != identity:
                errors.append(f"completion_{identity_field}_mismatch:{benchmark_id}")
        if row.get("official_boundary") is not True:
            errors.append(f"completion_boundary_not_official:{benchmark_id}")
    return errors


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _parse_bindings(values: Iterable[str]) -> dict[str, Path]:
    bindings: dict[str, Path] = {}
    for value in values:
        root_id, separator, raw_path = value.partition("=")
        if not separator or not root_id or not raw_path:
            raise ValueError(f"binding must be ROOT_ID=PATH: {value}")
        if root_id in bindings:
            raise ValueError(f"duplicate binding: {root_id}")
        bindings[root_id] = Path(raw_path)
    return bindings


def _write_json_atomic(path: Path, payload: Mapping[str, Any], *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-spec", required=True)
    parser.add_argument("--benchmark-registry", required=True)
    parser.add_argument("--issue-census", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--public-master-ref", required=True)
    parser.add_argument("--binding", action="append", default=[])
    parser.add_argument("--journal")
    parser.add_argument("--output", required=True)
    parser.add_argument("--sidecar")
    arguments = parser.parse_args()
    try:
        spec_path = Path(arguments.root_spec)
        registry_path = Path(arguments.benchmark_registry)
        specification = _load_json(spec_path)
        registry = _load_json(registry_path)
        issue_path = Path(arguments.issue_census)
        issue_census = _load_json(issue_path)
        source_commit = str(arguments.source_commit).lower()
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            raise ValueError("source commit must be exactly 40 lowercase hex")
        bindings = _parse_bindings(arguments.binding)
        public_repository = bindings.get("public-repository")
        if public_repository is None:
            raise ValueError("public-repository binding is required")
        try:
            resolved_source = _git(public_repository, "rev-parse", "--verify", source_commit + "^{commit}").strip().lower()
        except ValueError as exc:
            raise ValueError("source commit does not resolve in public repository") from exc
        if resolved_source != source_commit:
            raise ValueError("source commit does not match public repository object")
        if arguments.public_master_ref != "refs/remotes/origin/master":
            raise ValueError("public master ref must be refs/remotes/origin/master")
        resolved_public_master = _git(
            public_repository,
            "rev-parse",
            "--verify",
            arguments.public_master_ref + "^{commit}",
        ).strip().lower()
        if resolved_public_master != source_commit:
            raise ValueError("source commit is not the bound public master ref")
        root_census = build_root_census(
            specification,
            bindings,
            Path(arguments.journal) if arguments.journal else None,
        )
        benchmark_errors = validate_benchmark_registry(
            registry,
            repository_root=bindings.get("public-repository"),
            source_commit=source_commit,
        )
        if issue_census.get("public_master_sha") != source_commit:
            raise ValueError("issue census public master does not match source commit")
        issue_errors = validate_issue_census(issue_census, repository_root=bindings.get("public-repository"))
        manifest_binding = {
            "root_census_sha256": _sha256_text(
                json.dumps(canonical_root_identity(root_census), sort_keys=True, separators=(",", ":"))
            ),
            "benchmark_registry_sha256": sha256_file(registry_path),
            "issue_census_sha256": sha256_file(issue_path),
            "source_commit": source_commit,
        }
        transient_codes = {
            "artifact_mutated_during_hash",
            "artifact_changed_after_hash",
            "directory_membership_changed_during_scan",
            "directory_snapshot_changed_during_scan",
            "git_snapshot_changed_during_scan",
        }
        transient = [
            row for row in root_census["contradictions"]
            if row.get("code") in transient_codes
        ]
        payload = {
            "schema": "ember-01-custody-census-v1",
            "authority": specification.get("authority"),
            "source_commit": source_commit,
            "root_spec_sha256": sha256_file(spec_path),
            "benchmark_registry_sha256": manifest_binding[
                "benchmark_registry_sha256"
            ],
            "issue_census_sha256": manifest_binding["issue_census_sha256"],
            "canonical_manifest_sha256": _sha256_text(
                json.dumps(
                    manifest_binding, sort_keys=True, separators=(",", ":")
                )
            ),
            "root_census": root_census,
            "benchmark_registry": registry,
            "public_issue_census": issue_census,
            "benchmark_validation_errors": benchmark_errors,
            "issue_validation_errors": issue_errors,
            "summary": {
                "root_count": len(root_census["roots"]),
                "artifact_count": len(root_census["artifacts"]),
                "artifact_bytes": sum(
                    row["size_bytes"]
                    for row in root_census["artifacts"]
                    if isinstance(row.get("size_bytes"), int)
                ),
                "duplicate_group_count": len(root_census["duplicate_groups"]),
                "access_error_count": sum(
                    row.get("code") == "artifact_access_failed"
                    for row in root_census["contradictions"]
                ),
                "contradiction_count": len(root_census["contradictions"]),
                "benchmark_row_count": len(registry.get("benchmarks", [])),
                "issue_row_count": len(issue_census.get("issues", [])),
            },
        }
        run_identity = {
            "authority": specification.get("authority"),
            "execution_id": secrets.token_hex(16),
            "source_commit": source_commit,
            "root_spec_sha256": sha256_file(spec_path),
            "benchmark_registry_sha256": manifest_binding["benchmark_registry_sha256"],
            "issue_census_sha256": manifest_binding["issue_census_sha256"],
            "canonical_root_census_sha256": manifest_binding["root_census_sha256"],
            "canonical_manifest_sha256": payload["canonical_manifest_sha256"],
            "summary": payload["summary"],
            "benchmark_validation_errors": benchmark_errors,
            "issue_validation_errors": issue_errors,
            "contradiction_count": len(root_census["contradictions"]),
            "transient_contradictions": transient,
        }
        payload = {"run_identity": run_identity, **payload}
        output_path = Path(arguments.output)
        _write_json_atomic(output_path, payload, sort_keys=False)
        if arguments.sidecar:
            sidecar = {
                "schema": "ember-01-custody-run-sidecar-v1",
                "receipt_name": output_path.name,
                "receipt_sha256": sha256_file(output_path),
                "receipt_size_bytes": output_path.stat().st_size,
                "run_identity": run_identity,
            }
            _write_json_atomic(Path(arguments.sidecar), sidecar)
    except Exception as exc:
        print(f"EMBER_01_CUSTODY FAIL: {exc}")
        return 1
    if benchmark_errors or issue_errors or root_census["contradictions"]:
        print(
            "EMBER_01_CUSTODY INCOMPLETE: "
            f"benchmark_errors={len(benchmark_errors)} "
            f"issue_errors={len(issue_errors)} "
            f"contradictions={len(root_census['contradictions'])}"
        )
        return 2
    print(
        "EMBER_01_CUSTODY PASS: "
        f"roots={len(root_census['roots'])} "
        f"artifacts={len(root_census['artifacts'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
