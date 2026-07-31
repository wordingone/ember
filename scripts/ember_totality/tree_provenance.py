#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed run-tree provenance for the Ember totality board."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class TreeProvenanceError(RuntimeError):
    """The run tree cannot authorize a current totality-board receipt."""


def _git(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )


def _closed_sha(value: str, label: str) -> str:
    candidate = value.strip().lower()
    if not _SHA_RE.fullmatch(candidate):
        raise TreeProvenanceError(f"{label} did not resolve to one Git SHA")
    return candidate


def _tracked_dirty_paths(root: Path) -> list[str]:
    proc = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    dirty: list[str] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        if len(line) < 4 or line[:2] == "??":
            continue
        dirty.append(line[3:])
    return sorted(dirty)


def _ls_remote_master(root: Path, remote: str, branch: str) -> str | None:
    proc = _git(
        root,
        "ls-remote",
        "--exit-code",
        remote,
        f"refs/heads/{branch}",
        check=False,
    )
    if proc.returncode != 0:
        return None
    rows = [line for line in proc.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise TreeProvenanceError("canonical remote master did not resolve exactly once")
    sha, separator, ref = rows[0].partition("\t")
    if separator != "\t" or ref != f"refs/heads/{branch}":
        raise TreeProvenanceError("canonical remote master response was malformed")
    return _closed_sha(sha, "canonical remote master")


def _fetch_head_master(root: Path, branch: str) -> str | None:
    proc = _git(root, "rev-parse", "--git-path", "FETCH_HEAD")
    fetch_head = Path(proc.stdout.strip())
    if not fetch_head.is_absolute():
        fetch_head = root / fetch_head
    try:
        lines = fetch_head.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    named = [line for line in lines if f"branch '{branch}'" in line]
    if len(named) != 1:
        return None
    sha = named[0].split("\t", 1)[0]
    try:
        return _closed_sha(sha, "FETCH_HEAD master fallback")
    except TreeProvenanceError:
        return None


def _ensure_commit_object(root: Path, remote: str, sha: str) -> bool:
    exists = _git(root, "cat-file", "-e", f"{sha}^{{commit}}", check=False)
    if exists.returncode == 0:
        return True
    fetched = _git(root, "fetch", "--no-tags", "--quiet", remote, sha, check=False)
    if fetched.returncode != 0:
        return False
    return _git(root, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def inspect_run_tree(
    repo_root: str | Path,
    *,
    remote: str = "origin",
    branch: str = "master",
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    head = _closed_sha(_git(root, "rev-parse", "HEAD").stdout, "run tree HEAD")
    dirty = _tracked_dirty_paths(root)

    remote_sha = _ls_remote_master(root, remote, branch)
    source = "LS_REMOTE"
    if remote_sha is not None:
        # Refresh FETCH_HEAD to the exact remotely observed ref so a later
        # offline run has an explicit, bounded degraded provenance source.
        _git(
            root,
            "fetch",
            "--no-tags",
            "--quiet",
            remote,
            f"refs/heads/{branch}",
            check=False,
        )
    if remote_sha is None:
        remote_sha = _fetch_head_master(root, branch)
        source = "FETCH_HEAD_DEGRADED"
    if remote_sha is None:
        raise TreeProvenanceError(
            "TOTALITY_TREE_REFUSED: canonical remote master and FETCH_HEAD "
            "fallback are unavailable"
        )

    object_available = _ensure_commit_object(root, remote, remote_sha)
    behind_by: int | None = None
    if object_available:
        count = _git(root, "rev-list", "--count", f"{head}..{remote_sha}").stdout
        try:
            behind_by = int(count.strip())
        except ValueError as exc:
            raise TreeProvenanceError("behind_by was not an integer") from exc

    return {
        "run_tree_sha": head,
        "remote_master_sha": remote_sha,
        "remote_master_source": source,
        "tree_is_stale": head != remote_sha,
        "behind_by": behind_by,
        "tree_dirty": dirty,
    }


def enforce_run_tree(
    state: dict[str, Any],
    *,
    allow_stale_tree: bool = False,
) -> dict[str, Any]:
    stale = state.get("tree_is_stale") is True
    dirty = state.get("tree_dirty")
    if not isinstance(dirty, list):
        raise TreeProvenanceError("tree_dirty must be a list")
    if (stale or dirty) and not allow_stale_tree:
        reasons: list[str] = []
        if stale:
            reasons.append(
                f"run tree {state.get('run_tree_sha')} differs from remote master "
                f"{state.get('remote_master_sha')} (behind_by={state.get('behind_by')})"
            )
        if dirty:
            reasons.append(f"tracked files are dirty: {', '.join(dirty)}")
        raise TreeProvenanceError(
            "TOTALITY_TREE_REFUSED: "
            + "; ".join(reasons)
            + ". Sync with `git fetch origin master` and run from exact "
            "`origin/master`; use --allow-stale-tree only for archaeology."
        )

    degraded = state.get("remote_master_source") == "FETCH_HEAD_DEGRADED"
    if stale or dirty:
        status = "STALE_DIRTY_OVERRIDE"
    elif degraded:
        status = "DEGRADED_REMOTE_CHECK"
    else:
        status = "CURRENT_CLEAN"
    result = dict(state)
    result.update(
        {
            "stale_tree_override": bool(allow_stale_tree and (stale or dirty)),
            "provenance_status": status,
            "publishable_as_current": status == "CURRENT_CLEAN",
        }
    )
    return result


def inspect_and_enforce(
    repo_root: str | Path,
    *,
    allow_stale_tree: bool = False,
    remote: str = "origin",
    branch: str = "master",
) -> dict[str, Any]:
    return enforce_run_tree(
        inspect_run_tree(repo_root, remote=remote, branch=branch),
        allow_stale_tree=allow_stale_tree,
    )


def _require_commits_in_source(
    repo_root: str | Path,
    source_sha: str,
    required_commits: list[str] | tuple[str, ...],
) -> None:
    root = Path(repo_root).resolve()
    source = _closed_sha(source_sha, "board source")
    if _git(root, "cat-file", "-e", f"{source}^{{commit}}", check=False).returncode != 0:
        raise TreeProvenanceError(
            "README_TREE_REFUSED: board source commit is unavailable"
        )
    for value in required_commits:
        if not isinstance(value, str):
            raise TreeProvenanceError(
                "README_TREE_REFUSED: required merge did not resolve to one Git SHA"
            )
        required = _closed_sha(value, "required merge")
        if _git(root, "cat-file", "-e", f"{required}^{{commit}}", check=False).returncode != 0:
            raise TreeProvenanceError(
                f"README_TREE_REFUSED: required merge is unavailable: {required}"
            )
        ancestor = _git(
            root,
            "merge-base",
            "--is-ancestor",
            required,
            source,
            check=False,
        )
        if ancestor.returncode == 1:
            raise TreeProvenanceError(
                "README_TREE_REFUSED: required merge is newer than the board "
                f"source: {required}"
            )
        if ancestor.returncode != 0:
            raise TreeProvenanceError(
                f"README_TREE_REFUSED: required merge ancestry is unproven: {required}"
            )


def validate_receipt_for_render(
    receipt: dict[str, Any],
    *,
    allow_stale_tree: bool = False,
    repo_root: str | Path | None = None,
    required_commits: list[str] | tuple[str, ...] = (),
) -> dict[str, Any] | None:
    state = receipt.get("run_tree_provenance")
    if state is None:
        if required_commits:
            raise TreeProvenanceError(
                "README_TREE_REFUSED: required merge cannot be checked without "
                "run-tree provenance"
            )
        return None
    if not isinstance(state, dict):
        raise TreeProvenanceError("README_TREE_REFUSED: run_tree_provenance is malformed")
    expected_fields = {
        "run_tree_sha",
        "remote_master_sha",
        "remote_master_source",
        "tree_is_stale",
        "behind_by",
        "tree_dirty",
        "stale_tree_override",
        "provenance_status",
        "publishable_as_current",
    }
    if set(state) != expected_fields:
        raise TreeProvenanceError("README_TREE_REFUSED: provenance fields are not closed")
    run_sha = state["run_tree_sha"]
    remote_sha = state["remote_master_sha"]
    if not isinstance(run_sha, str) or not _SHA_RE.fullmatch(run_sha):
        raise TreeProvenanceError("README_TREE_REFUSED: run_tree_sha is malformed")
    if not isinstance(remote_sha, str) or not _SHA_RE.fullmatch(remote_sha):
        raise TreeProvenanceError("README_TREE_REFUSED: remote_master_sha is malformed")
    source = state["remote_master_source"]
    if source not in {"LS_REMOTE", "FETCH_HEAD_DEGRADED"}:
        raise TreeProvenanceError("README_TREE_REFUSED: remote source is malformed")
    if type(state["tree_is_stale"]) is not bool:
        raise TreeProvenanceError("README_TREE_REFUSED: stale flag is malformed")
    stale = state["tree_is_stale"]
    if stale != (run_sha != remote_sha):
        raise TreeProvenanceError("README_TREE_REFUSED: stale flag contradicts Git SHAs")
    dirty = state["tree_dirty"]
    if (
        not isinstance(dirty, list)
        or any(not isinstance(path, str) or not path for path in dirty)
        or dirty != sorted(set(dirty))
    ):
        raise TreeProvenanceError("README_TREE_REFUSED: tree_dirty is malformed")
    behind = state["behind_by"]
    if behind is not None and (type(behind) is not int or behind < 0):
        raise TreeProvenanceError("README_TREE_REFUSED: behind_by is malformed")
    expected_status = (
        "STALE_DIRTY_OVERRIDE"
        if stale or dirty
        else "DEGRADED_REMOTE_CHECK"
        if source == "FETCH_HEAD_DEGRADED"
        else "CURRENT_CLEAN"
    )
    if state["provenance_status"] != expected_status:
        raise TreeProvenanceError("README_TREE_REFUSED: provenance status is contradictory")
    if type(state["stale_tree_override"]) is not bool or state["stale_tree_override"] != bool(stale or dirty):
        raise TreeProvenanceError("README_TREE_REFUSED: override flag is contradictory")
    expected_publishable = expected_status == "CURRENT_CLEAN"
    if type(state["publishable_as_current"]) is not bool or state["publishable_as_current"] != expected_publishable:
        raise TreeProvenanceError("README_TREE_REFUSED: publishability is contradictory")
    if (stale or dirty) and not allow_stale_tree:
        raise TreeProvenanceError(
            "README_TREE_REFUSED: stale/dirty board receipt requires the same "
            "--allow-stale-tree archaeology opt-out"
        )
    if required_commits:
        if repo_root is None:
            raise TreeProvenanceError(
                "README_TREE_REFUSED: repository root is required for merge ancestry"
            )
        _require_commits_in_source(repo_root, run_sha, required_commits)
    return state
