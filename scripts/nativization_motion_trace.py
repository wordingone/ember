#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic run/import trace producer for nativization motion."""
from __future__ import annotations

import hashlib
import ast
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any, Iterable

TRACE_SCHEMA_VERSION = "ember-run-import-trace-v3"
TRACE_RUN_ID = "ember-02-governed-run-import-v2"
TRACE_PHASES = ("creation", "current_rung_training", "growth_run")
PHASE_ENTRYPOINTS = {
    "creation": "src/ember/infrastructure/tools/ember-restart-3b/model.py",
    "current_rung_training": "tools/ember-restart-3b/pretrain.py",
    "growth_run": "tools/ember-restart-3b/run_vertical_slice.py",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


_GIT_TREE_CACHE: dict[tuple[str, str], dict[str, bytes]] = {}


def _git_tree_bytes(repo_root: Path, commit: str) -> dict[str, bytes]:
    key = (str(repo_root.resolve()), commit)
    cached = _GIT_TREE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            ["git", "archive", "--format=tar", commit],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
        archive = tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:")
        files = {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }
    except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        raise ValueError("Git source tree is unavailable") from exc
    _GIT_TREE_CACHE[key] = files
    return files


def git_blob_bytes(repo_root: Path, commit: str, relative_path: str) -> bytes:
    try:
        return _git_tree_bytes(repo_root, commit)[relative_path]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Git blob is unavailable for {relative_path}") from exc


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


LAYER_SEMANTICS = {
    "CUDA kernels (cuBLAS matmul, elementwise)": {
        "imports": ("torch",),
        "symbols": ("cuda",),
        "require_all_symbols": True,
    },
    "Tensor abstraction (storage/strides/dtype)": {
        "imports": ("torch",),
        "symbols": ("Tensor", "tensor", "dtype", "stride"),
    },
    "Autograd (" + chr(96) + "grad_fn" + chr(96) + " graph, " + chr(96) + "backward()" + chr(96) + ")": {
        "imports": ("torch.autograd",),
        "symbols": ("backward", "grad_fn"),
    },
    "Optimizer (Adam/Muon: separable state + update)": {
        "imports": ("torch.optim",),
        "symbols": ("step", "Adam", "Muon"),
    },
    "Training loop (fwd " + chr(0x2192) + " loss " + chr(0x2192) + " backward " + chr(0x2192) + " step)": {
        "imports": (),
        "symbols": ("forward", "loss", "backward", "step"),
    },
}


def _source_bytes(root: Path, commit: str | None, relative_path: str) -> bytes:
    if commit is not None:
        return git_blob_bytes(root, commit, relative_path)
    return (root / relative_path).read_bytes()


def _resolve_local_import(root: Path, importer: Path, module: str, commit: str | None = None) -> Path | None:
    if not module:
        return None
    module_path = module.replace(".", "/")
    suffixes = (module_path + ".py", module_path + "/__init__.py")
    if commit is not None:
        tree = _git_tree_bytes(root, commit)
        candidates = sorted(
            path for path in tree
            if path.startswith(("tools/", "scripts/", "baseline/"))
            and "/tests/" not in path
            and not path.startswith("tests/")
            and any(path == suffix or path.endswith("/" + suffix) for suffix in suffixes)
        )
        if candidates:
            return (root / candidates[0]).resolve()
        return None
    candidates = [
        importer.parent / f"{module.split('.')[-1]}.py",
        root / (module_path + ".py"),
        root / (module_path + "/__init__.py"),
    ]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate.resolve()
    return None

def _reachable_source_paths(root: Path, entrypoint: str, commit: str | None = None) -> list[Path]:
    first = (root / entrypoint).resolve()
    try:
        first.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("governed phase entrypoint escapes repo root") from exc
    if commit is not None:
        try:
            git_blob_bytes(root, commit, entrypoint)
        except ValueError as exc:
            raise ValueError(f"governed phase entrypoint missing: {entrypoint}") from exc
    elif not first.is_file():
        raise ValueError(f"governed phase entrypoint missing: {entrypoint}")
    queue = [first]
    seen: set[Path] = set()
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        relative = _relative(root, current)
        try:
            payload = _source_bytes(root, commit, relative)
            tree = ast.parse(payload.decode("utf-8-sig"), filename=relative)
        except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
            raise ValueError("governed phase entrypoint is not parseable") from exc
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in sorted(set(imported)):
            dependency = _resolve_local_import(root, current, module, commit)
            if dependency is not None and dependency not in seen:
                queue.append(dependency)
    return sorted(seen, key=lambda path: _relative(root, path))


def _reachable_projection(root: Path, entrypoint: str, commit: str | None = None) -> list[dict[str, str]]:
    return [
        {"path": _relative(root, path), "sha256": sha256_bytes(_source_bytes(root, commit, _relative(root, path)))}
        for path in _reachable_source_paths(root, entrypoint, commit)
    ]


def _semantic_layer_reachable(
    root: Path,
    commit: str,
    layer_name: str,
    reachable: list[dict[str, str]],
) -> list[dict[str, str]]:
    predicate = LAYER_SEMANTICS.get(layer_name)
    if predicate is None:
        raise ValueError(f"closed layer predicate is not defined for {layer_name}")
    matched: list[dict[str, str]] = []
    required_imports = tuple(predicate["imports"])
    required_symbols = set(predicate["symbols"])
    require_all_symbols = bool(predicate.get("require_all_symbols"))
    for item in reachable:
        try:
            tree = ast.parse(git_blob_bytes(root, commit, item["path"]).decode("utf-8-sig"), filename=item["path"])
        except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
            raise ValueError("reachable source is not parseable") from exc
        imported: set[str] = set()
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        import_hit = any(
            value == module or value.startswith(module + ".")
            for value in imported
            for module in required_imports
        )
        symbol_hit = required_symbols.issubset(names) if require_all_symbols else bool(required_symbols.intersection(names))
        matches = import_hit and symbol_hit if require_all_symbols else (import_hit or symbol_hit)
        if matches:
            matched.append(item)
    return matched

def build_trace(repo_root: Path, layer_names: list[str], layer_patterns: dict[str, list[str]], source_commit: str | None = None) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for name in layer_names:
        patterns = layer_patterns.get(name)
        if not isinstance(patterns, list) or not patterns or not all(isinstance(item, str) for item in patterns):
            raise ValueError(f"closed layer predicate is required for {name}")
        for phase in TRACE_PHASES:
            entrypoint = PHASE_ENTRYPOINTS[phase]
            reachable = _reachable_projection(repo_root, entrypoint, source_commit)
            entrypoint_digest = next(item["sha256"] for item in reachable if item["path"] == entrypoint)
            if source_commit is None:
                raise ValueError("exact Git source commit is required for trace construction")
            layer_reachable = _semantic_layer_reachable(
                repo_root, source_commit, name, reachable
            )
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
