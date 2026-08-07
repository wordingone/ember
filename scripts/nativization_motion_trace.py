#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic run/import trace producer for nativization motion."""
from __future__ import annotations

import hashlib
import ast
import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

TRACE_SCHEMA_VERSION = "ember-run-import-trace-v3"
TRACE_RUN_ID = "ember-02-governed-run-import-v2"
TRACE_PHASES = ("creation", "current_rung_training", "growth_run")
PHASE_ENTRYPOINTS = {
    "creation": "tools/ember-restart-3b/model.py",
    "current_rung_training": "tools/ember-restart-3b/pretrain.py",
    "growth_run": "tools/ember-restart-3b/run_vertical_slice.py",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_blob_bytes(repo_root: Path, commit: str, relative_path: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Git blob is unavailable for {relative_path}") from exc
    return result.stdout


def git_blob_sha256(repo_root: Path, commit: str, relative_path: str) -> str:
    return sha256_bytes(git_blob_bytes(repo_root, commit, relative_path))


def ensure_source_tree_clean(repo_root: Path) -> None:
    if not (repo_root / ".git").exists():
        raise ValueError("exact Git source authority is required")
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("exact Git source authority is required") from exc
    if result.stdout.strip():
        raise ValueError("exact Git source tree must be clean before trace construction")


def source_commit(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        raise ValueError("exact Git source authority is required")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("exact Git source authority is required") from exc
    value = result.stdout.strip()
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("exact Git source authority is required")
    return value


def choose_trace_source(repo_root: Path, patterns: Iterable[str]) -> Path:
    raise ValueError("broad trace source enumeration is forbidden")


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _resolve_local_import(root: Path, importer: Path, module: str) -> Path | None:
    if not module:
        return None
    leaf = module.split(".")[-1]
    candidates = [
        importer.parent / f"{leaf}.py",
        root / (module.replace(".", "/") + ".py"),
        root / "tools" / "ember-restart-3b" / f"{leaf}.py",
    ]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate.resolve()
    return None


def _reachable_source_paths(root: Path, entrypoint: str) -> list[Path]:
    first = (root / entrypoint).resolve()
    try:
        first.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("governed phase entrypoint escapes repo root") from exc
    if not first.is_file():
        raise ValueError(f"governed phase entrypoint missing: {entrypoint}")
    queue = [first]
    seen: set[Path] = set()
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        try:
            tree = ast.parse(current.read_text(encoding="utf-8"), filename=str(current))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise ValueError("governed phase entrypoint is not parseable") from exc
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in sorted(set(imported)):
            dependency = _resolve_local_import(root, current, module)
            if dependency is not None and dependency not in seen:
                queue.append(dependency)
    return sorted(seen, key=lambda path: _relative(root, path))


def _reachable_projection(root: Path, entrypoint: str) -> list[dict[str, str]]:
    return [
        {"path": _relative(root, path), "sha256": sha256_bytes(path.read_bytes())}
        for path in _reachable_source_paths(root, entrypoint)
    ]


def build_trace(repo_root: Path, layer_names: list[str], layer_patterns: dict[str, list[str]]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for name in layer_names:
        patterns = layer_patterns.get(name)
        if not isinstance(patterns, list) or not patterns or not all(isinstance(item, str) for item in patterns):
            raise ValueError(f"closed layer predicate is required for {name}")
        for phase in TRACE_PHASES:
            entrypoint = PHASE_ENTRYPOINTS[phase]
            reachable = _reachable_projection(repo_root, entrypoint)
            entrypoint_digest = next(item["sha256"] for item in reachable if item["path"] == entrypoint)
            layer_reachable = [
                item for item in reachable
                if any(fnmatch.fnmatchcase(item["path"], pattern) for pattern in patterns)
            ]
            events.append(
                {
                    "layer": name,
                    "phase": phase,
                    "entrypoint": entrypoint,
                    "entrypoint_sha256": entrypoint_digest,
                    "layer_patterns": list(patterns),
                    "reachable": reachable,
                    "reachability_sha256": sha256_bytes(canonical_json_bytes(reachable)),
                    "layer_reachable": layer_reachable,
                    "layer_reachability_sha256": sha256_bytes(canonical_json_bytes(layer_reachable)),
                }
            )
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "run_id": TRACE_RUN_ID,
        "events": events,
    }
