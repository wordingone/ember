#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""External post-termination authority for MTP execution candidates.

The child writes only an execution candidate.  This parent-side runner starts
the child, records PID/start identity, waits for termination, then finalizes a
governed receipt from the observed exit and durable candidate bytes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from mtp_parameter_manifest import finalize_governed_execution_receipt


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_external_candidate(
    *,
    manifest_path: Path | str,
    candidate_path: Path | str,
    receipt_path: Path | str,
    source_path: Path | str,
    config_path: Path | str,
    command: Sequence[str],
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Run one child and persist the externally verified parent receipt."""
    manifest_file = Path(manifest_path).resolve()
    candidate_file = Path(candidate_path).resolve()
    receipt_file = Path(receipt_path)
    source_file = Path(source_path).resolve(strict=True)
    config_file = Path(config_path).resolve(strict=True)
    source_sha_before = _sha256_file(source_file)
    config_sha_before = _sha256_file(config_file)
    command_list = [str(item) for item in command]
    if not command_list or any(not item or "\x00" in item for item in command_list):
        raise ValueError("external command must contain nonempty strings")
    executable = Path(command_list[0]).resolve(strict=True)
    process = subprocess.Popen(command_list, cwd=str(cwd) if cwd is not None else None)
    start_time_ns = time.time_ns()
    returncode = process.wait()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_file.read_text(encoding="utf-8"))
    source_sha_after = _sha256_file(source_file)
    config_sha_after = _sha256_file(config_file)
    if source_sha_before != source_sha_after:
        raise ValueError("external source_sha256 changed during execution")
    if config_sha_before != config_sha_after:
        raise ValueError("external config_sha256 changed during execution")
    if candidate.get("source_sha256") != source_sha_before:
        raise ValueError("external source_sha256 mismatch")
    if candidate.get("config_sha256") != config_sha_before:
        raise ValueError("external config_sha256 mismatch")
    parent = finalize_governed_execution_receipt(
        manifest,
        candidate,
        command=command_list,
        process_identity={
            "pid": int(process.pid),
            "start_time_ns": int(start_time_ns),
            "executable_sha256": _sha256_file(executable),
        },
        child_exit_code=int(returncode),
        verifier_id="ember-mtp-external-runner-v1",
        verifier_sha256=_sha256_file(Path(__file__).resolve()),
    )
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(json.dumps(parent, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return parent
