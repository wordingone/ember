#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic run/import trace producer for nativization motion."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

TRACE_SCHEMA_VERSION = "ember-run-import-trace-v1"
TRACE_RUN_ID = "ember-02-static-nativization-v1"
TRACE_PHASES = ("creation", "current_rung_training", "growth_run")
BASE_SOURCE_COMMIT = "d648d7f9f692134bf51478d3303267666b04e342"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return BASE_SOURCE_COMMIT
    value = result.stdout.strip()
    return value if len(value) == 40 and all(c in "0123456789abcdef" for c in value) else BASE_SOURCE_COMMIT


def choose_trace_source(repo_root: Path, patterns: Iterable[str]) -> Path:
    candidates: set[Path] = set()
    for pattern in patterns:
        candidates.update(p for p in repo_root.glob(pattern) if p.is_file() and p.suffix == ".py")
    if not candidates:
        raise ValueError("run import trace has no production source for layer")
    return sorted(candidates, key=lambda p: p.as_posix().lower())[0]


def build_trace(repo_root: Path, layer_names: list[str], layer_patterns: dict[str, list[str]]) -> dict[str, Any]:
    events: list[dict[str, str]] = []
    for name in layer_names:
        source = choose_trace_source(repo_root, layer_patterns[name])
        relative = source.resolve().relative_to(repo_root.resolve()).as_posix()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        for phase in TRACE_PHASES:
            events.append({"layer": name, "phase": phase, "path": relative, "sha256": digest})
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "run_id": TRACE_RUN_ID,
        "events": events,
    }
