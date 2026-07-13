# goal_id: EMBER-01
# workstream_id: EMBER-01B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic, read-only custody and benchmark census primitives."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
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


def _file_rows(root: Path) -> Iterable[tuple[str, Path]]:
    candidates: list[Path] = []
    for candidate in root.rglob("*"):
        try:
            if candidate.is_file():
                candidates.append(candidate)
        except OSError:
            # Preserve inaccessible candidates for the per-artifact error record.
            candidates.append(candidate)
    for path in sorted(
        candidates,
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        yield path.relative_to(root).as_posix(), path


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
        {"worktree_id": f"worktree-{index:04d}", **row}
        for index, (_, row) in enumerate(sorted(parsed, key=lambda item: item[0]), 1)
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
    completed_journal = load_hash_journal(journal_path) if journal_path else {}
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
    physical_hash_cache: dict[tuple[str, int, int], str] = {}
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
        try:
            if scan == "git_repository":
                summary = git_repository_summary(root_id, bound)
                root_row["git"] = summary
                artifacts.extend(
                    [
                        virtual_artifact("git-refs", summary["refs_sha256"]),
                        virtual_artifact("git-status", summary["status_sha256"]),
                    ]
                )
                continue
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
                        artifacts.append(
                            virtual_artifact(
                                f"{child.name}/git-refs",
                                summary["refs_sha256"],
                            )
                        )
                        if summary["status_sha256"] is not None:
                            artifacts.append(
                                virtual_artifact(
                                    f"{child.name}/git-status",
                                    summary["status_sha256"],
                                )
                            )
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
                            file_candidates.extend(
                                (f"{child.name}/{relative}", candidate)
                                for relative, candidate in _file_rows(child)
                            )
                root_row["discovered_roots"] = discovered
                root_row["discovered_root_count"] = len(discovered)
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
                file_candidates = [
                    (relative, bound / Path(relative)) for relative in ignored_paths
                ]
            if scan != "files":
                if scan not in {
                    "directory_discovery",
                    "git_ignored_registry",
                    "git_worktree_material_registry",
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
            candidates = list(_file_rows(bound))
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
                    stat.st_size,
                    stat.st_mtime_ns,
                )
                physical_digest = physical_hash_cache.get(physical_key)
                if physical_digest is not None:
                    digest = physical_digest
                else:
                    cached = completed_journal.get(artifact_key)
                    if (
                        cached is not None
                        and cached.get("size_bytes") == stat.st_size
                        and cached.get("mtime_ns_non_authoritative")
                        == stat.st_mtime_ns
                    ):
                        digest = str(cached["sha256"])
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
                }
            )
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
        "roots": roots,
        "artifacts": artifacts,
        "duplicate_groups": build_duplicate_groups(artifacts),
        "contradictions": sorted(
            contradictions,
            key=lambda row: (row["code"], row.get("root_id", ""), row.get("artifact_id", "")),
        ),
    }


def validate_benchmark_registry(registry: Mapping[str, Any]) -> list[str]:
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
        for field in ("subject_manifest", "result_receipt"):
            if not isinstance(row.get(field), str) or not row[field]:
                errors.append(f"completion_{field}_missing:{benchmark_id}")
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


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
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
    parser.add_argument("--binding", action="append", default=[])
    parser.add_argument("--journal")
    parser.add_argument("--output", required=True)
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
        root_census = build_root_census(
            specification,
            bindings,
            Path(arguments.journal) if arguments.journal else None,
        )
        benchmark_errors = validate_benchmark_registry(registry)
        issue_errors = validate_issue_census(issue_census)
        manifest_binding = {
            "root_census_sha256": _sha256_text(
                json.dumps(root_census, sort_keys=True, separators=(",", ":"))
            ),
            "benchmark_registry_sha256": sha256_file(registry_path),
            "issue_census_sha256": sha256_file(issue_path),
            "source_commit": source_commit,
        }
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
        _write_json_atomic(Path(arguments.output), payload)
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
