#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit BrowserGym source custody without materializing a browser runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

CUSTODY = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-browser-tool-custody-v1.json"


def _git_identity(root: Path) -> dict[str, str]:
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        tree = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("BrowserGym source identity could not be read") from error
    if head.returncode or tree.returncode:
        raise ValueError("BrowserGym source is not a readable Git checkout")
    return {"source_commit": head.stdout.strip(), "source_tree": tree.stdout.strip()}


def audit_source(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError("BrowserGym source root is not a directory")
    try:
        custody = json.loads(CUSTODY.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("BrowserGym custody manifest is unavailable") from error
    browser = custody.get("browser_ui") if isinstance(custody, dict) else None
    if not isinstance(browser, dict) or browser.get("benchmark_id") != "browsergym-miniwob":
        raise ValueError("BrowserGym custody identity is invalid")
    identity = _git_identity(root)
    if identity["source_commit"] != browser.get("source_commit"):
        raise ValueError("BrowserGym source commit drifted from public custody")
    if identity["source_tree"] != browser.get("source_tree"):
        raise ValueError("BrowserGym source tree drifted from public custody")
    license_path = root / "LICENSE"
    try:
        license_sha = hashlib.sha256(license_path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError("BrowserGym LICENSE is unavailable") from error
    if license_sha != browser.get("license_sha256"):
        raise ValueError("BrowserGym LICENSE drifted from public custody")
    return {
        "schema_version": "ember-restart-browsergym-source-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "admission": "NOT_ELIGIBLE",
        "claim_status": "BROWSERGYM_SOURCE_CUSTODY_ONLY_NO_LOCAL_RUNTIME_OR_TASK_BUNDLE",
        "benchmark_id": browser["benchmark_id"],
        "source_commit": identity["source_commit"],
        "source_tree": identity["source_tree"],
        "license_sha256": license_sha,
        "source_materialization": "SOURCE_ONLY_CUSTODY",
        "target_execution_permitted": False,
        "runtime_or_task_bundle": None,
    }


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise ValueError("audit output must not pre-exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        _atomic_write(arguments.output, audit_source(arguments.source_root))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
