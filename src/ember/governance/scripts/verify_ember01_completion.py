#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Emit the unified EMBER-01 nine-condition completion receipt.

EMBER-01 certification today requires assembling evidence from five separate
tools. This aggregates all nine legs into ONE clean-detached-checkout command
and one atomic receipt written OUTSIDE the checkout.

DESIGN RULE - HONESTY OVER GREEN. Every leg carries one of three states:

    resolved-true    the leg's real tool ran and passed
    resolved-false   the leg's real tool ran and failed
    unresolved       the leg could not be evaluated on this checkout
                     (RUNNER-BLOCKED: operator-machine roots or an owned
                      checkpoint are not bindable on a bare clean clone)

`ok` is the AND of all nine legs being resolved-true PLUS checkout integrity
(clean + detached + head_unchanged both ends) and selection integrity. A leg
that cannot be evaluated is UNRESOLVED, never silently true. On a bare clone
the custody/identity/seat legs are honestly UNRESOLVED - that is the proof the
legs bind to real operator state, not a stub.

The receipt does NOT claim training, a model, runtime, or benchmark work
completed - only that the nine authority/custody/identity conditions hold.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent / "ember_01_custody"),
)
from issue_census import canonical_open_issue_source_snapshot

# Leg 8 imports the SAME authority function verify_ember00_completion.py uses.
# issue2015 exact-local-import:scripts/verify_authority_conservation.py
import importlib.util as _ember_6684f8b7ce199219_importlib
import sys as _ember_6684f8b7ce199219_sys
from pathlib import Path as _ember_6684f8b7ce199219_Path
_ember_6684f8b7ce199219_path = _ember_6684f8b7ce199219_Path(__file__).resolve().parents[4].joinpath('scripts', 'verify_authority_conservation.py')
if not _ember_6684f8b7ce199219_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/verify_authority_conservation.py')
_ember_6684f8b7ce199219_aliases = ('_ember_issue2015_6684f8b7ce199219', 'scripts.verify_authority_conservation', 'verify_authority_conservation')
_ember_6684f8b7ce199219_existing = []
for _ember_6684f8b7ce199219_alias in _ember_6684f8b7ce199219_aliases:
    _ember_6684f8b7ce199219_candidate = _ember_6684f8b7ce199219_sys.modules.get(_ember_6684f8b7ce199219_alias)
    if _ember_6684f8b7ce199219_candidate is not None and all(_ember_6684f8b7ce199219_candidate is not item for item in _ember_6684f8b7ce199219_existing):
        _ember_6684f8b7ce199219_existing.append(_ember_6684f8b7ce199219_candidate)
if len(_ember_6684f8b7ce199219_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/verify_authority_conservation.py')
if _ember_6684f8b7ce199219_existing:
    _ember_6684f8b7ce199219_module = _ember_6684f8b7ce199219_existing[0]
    _ember_6684f8b7ce199219_observed = getattr(_ember_6684f8b7ce199219_module, '__file__', None)
    if _ember_6684f8b7ce199219_observed is None or _ember_6684f8b7ce199219_Path(_ember_6684f8b7ce199219_observed).resolve() != _ember_6684f8b7ce199219_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/verify_authority_conservation.py')
else:
    _ember_6684f8b7ce199219_spec = _ember_6684f8b7ce199219_importlib.spec_from_file_location('_ember_issue2015_6684f8b7ce199219', _ember_6684f8b7ce199219_path)
    if _ember_6684f8b7ce199219_spec is None or _ember_6684f8b7ce199219_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/verify_authority_conservation.py')
    _ember_6684f8b7ce199219_module = _ember_6684f8b7ce199219_importlib.module_from_spec(_ember_6684f8b7ce199219_spec)
    for _ember_6684f8b7ce199219_alias in _ember_6684f8b7ce199219_aliases:
        _ember_6684f8b7ce199219_prior = _ember_6684f8b7ce199219_sys.modules.get(_ember_6684f8b7ce199219_alias)
        if _ember_6684f8b7ce199219_prior is not None and _ember_6684f8b7ce199219_prior is not _ember_6684f8b7ce199219_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/verify_authority_conservation.py')
        _ember_6684f8b7ce199219_sys.modules[_ember_6684f8b7ce199219_alias] = _ember_6684f8b7ce199219_module
    try:
        _ember_6684f8b7ce199219_spec.loader.exec_module(_ember_6684f8b7ce199219_module)
    except BaseException:
        for _ember_6684f8b7ce199219_alias in _ember_6684f8b7ce199219_aliases:
            if _ember_6684f8b7ce199219_sys.modules.get(_ember_6684f8b7ce199219_alias) is _ember_6684f8b7ce199219_module:
                _ember_6684f8b7ce199219_sys.modules.pop(_ember_6684f8b7ce199219_alias, None)
        raise
for _ember_6684f8b7ce199219_alias in _ember_6684f8b7ce199219_aliases:
    _ember_6684f8b7ce199219_prior = _ember_6684f8b7ce199219_sys.modules.get(_ember_6684f8b7ce199219_alias)
    if _ember_6684f8b7ce199219_prior is not None and _ember_6684f8b7ce199219_prior is not _ember_6684f8b7ce199219_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/verify_authority_conservation.py')
    _ember_6684f8b7ce199219_sys.modules[_ember_6684f8b7ce199219_alias] = _ember_6684f8b7ce199219_module
ACTIVE_GOAL_ID = getattr(_ember_6684f8b7ce199219_module, 'ACTIVE_GOAL_ID')
ACTIVE_WORKSTREAM_IDS = getattr(_ember_6684f8b7ce199219_module, 'ACTIVE_WORKSTREAM_IDS')
NEXT_EXECUTED_OUTCOME = getattr(_ember_6684f8b7ce199219_module, 'NEXT_EXECUTED_OUTCOME')
verify = getattr(_ember_6684f8b7ce199219_module, 'verify')
# issue2015 exact-local-import-end:scripts/verify_authority_conservation.py
from ember_01_identity import validate_identity as identity_validator
# issue2015 exact-local-import:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py
import importlib.util as _ember_bbbf7b42c6105c50_importlib
import sys as _ember_bbbf7b42c6105c50_sys
from pathlib import Path as _ember_bbbf7b42c6105c50_Path
_ember_bbbf7b42c6105c50_path = _ember_bbbf7b42c6105c50_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'ember_01_identity', 'parameter_identity_binding.py')
if not _ember_bbbf7b42c6105c50_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py')
_ember_bbbf7b42c6105c50_aliases = ('_ember_issue2015_bbbf7b42c6105c50', 'ember_01_identity.parameter_identity_binding', 'parameter_identity_binding', 'scripts.ember_01_identity.parameter_identity_binding')
_ember_bbbf7b42c6105c50_existing = []
for _ember_bbbf7b42c6105c50_alias in _ember_bbbf7b42c6105c50_aliases:
    _ember_bbbf7b42c6105c50_candidate = _ember_bbbf7b42c6105c50_sys.modules.get(_ember_bbbf7b42c6105c50_alias)
    if _ember_bbbf7b42c6105c50_candidate is not None and all(_ember_bbbf7b42c6105c50_candidate is not item for item in _ember_bbbf7b42c6105c50_existing):
        _ember_bbbf7b42c6105c50_existing.append(_ember_bbbf7b42c6105c50_candidate)
if len(_ember_bbbf7b42c6105c50_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py')
if _ember_bbbf7b42c6105c50_existing:
    _ember_bbbf7b42c6105c50_module = _ember_bbbf7b42c6105c50_existing[0]
    _ember_bbbf7b42c6105c50_observed = getattr(_ember_bbbf7b42c6105c50_module, '__file__', None)
    if _ember_bbbf7b42c6105c50_observed is None or _ember_bbbf7b42c6105c50_Path(_ember_bbbf7b42c6105c50_observed).resolve() != _ember_bbbf7b42c6105c50_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py')
else:
    _ember_bbbf7b42c6105c50_spec = _ember_bbbf7b42c6105c50_importlib.spec_from_file_location('_ember_issue2015_bbbf7b42c6105c50', _ember_bbbf7b42c6105c50_path)
    if _ember_bbbf7b42c6105c50_spec is None or _ember_bbbf7b42c6105c50_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py')
    _ember_bbbf7b42c6105c50_module = _ember_bbbf7b42c6105c50_importlib.module_from_spec(_ember_bbbf7b42c6105c50_spec)
    for _ember_bbbf7b42c6105c50_alias in _ember_bbbf7b42c6105c50_aliases:
        _ember_bbbf7b42c6105c50_prior = _ember_bbbf7b42c6105c50_sys.modules.get(_ember_bbbf7b42c6105c50_alias)
        if _ember_bbbf7b42c6105c50_prior is not None and _ember_bbbf7b42c6105c50_prior is not _ember_bbbf7b42c6105c50_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py')
        _ember_bbbf7b42c6105c50_sys.modules[_ember_bbbf7b42c6105c50_alias] = _ember_bbbf7b42c6105c50_module
    try:
        _ember_bbbf7b42c6105c50_spec.loader.exec_module(_ember_bbbf7b42c6105c50_module)
    except BaseException:
        for _ember_bbbf7b42c6105c50_alias in _ember_bbbf7b42c6105c50_aliases:
            if _ember_bbbf7b42c6105c50_sys.modules.get(_ember_bbbf7b42c6105c50_alias) is _ember_bbbf7b42c6105c50_module:
                _ember_bbbf7b42c6105c50_sys.modules.pop(_ember_bbbf7b42c6105c50_alias, None)
        raise
for _ember_bbbf7b42c6105c50_alias in _ember_bbbf7b42c6105c50_aliases:
    _ember_bbbf7b42c6105c50_prior = _ember_bbbf7b42c6105c50_sys.modules.get(_ember_bbbf7b42c6105c50_alias)
    if _ember_bbbf7b42c6105c50_prior is not None and _ember_bbbf7b42c6105c50_prior is not _ember_bbbf7b42c6105c50_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py')
    _ember_bbbf7b42c6105c50_sys.modules[_ember_bbbf7b42c6105c50_alias] = _ember_bbbf7b42c6105c50_module
ParameterIdentityMismatch = getattr(_ember_bbbf7b42c6105c50_module, 'ParameterIdentityMismatch')
measure_live_checkpoint = getattr(_ember_bbbf7b42c6105c50_module, 'measure_live_checkpoint')
verify_parameter_identity_binding = getattr(_ember_bbbf7b42c6105c50_module, 'verify_parameter_identity_binding')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py
from cond4_behavior_surface import (
    COND4_AXES,
    EXECUTION_SCHEMA as COND4_EXECUTION_SCHEMA,
    SurfaceRefusal as Cond4SurfaceRefusal,
    build_surface_manifest,
    validate_execution_evidence,
    validate_execution_packet,
    validate_surface_manifest,
)

RESOLVED_TRUE = "resolved-true"
RESOLVED_FALSE = "resolved-false"
UNRESOLVED = "unresolved"

CONFIG_REL = "configs/ember-restart-3b.json"
LAUNCH_PACKET_REL = "tools/ember-restart-3b/launch_packet.py"
CENSUS_REL = "scripts/ember_01_custody/census.py"
VALIDATE_IDENTITY_REL = "src/ember/governance/scripts/ember_01_identity/validate_identity.py"
SEAT_TEST_REL = "tools/ember-cli/src/entrypoints/model-seat.test.ts"
COND4_SURFACE_VALIDATOR_PATH = Path(__file__).with_name("cond4_behavior_surface.py")
COND4_SURFACE_MANIFEST_REL = (
    "manifests/ember-01-identity/cond4-behavior-surface-v1.json"
)

# The nine EMBER-01 conditions and which tool certifies each.
LEG_TITLES = {
    "1": "custody root census (operator-machine roots)",
    "2": "artifact custody census",
    "3": "identity round-trip on real checkpoint",
    "4": "identity fail-closed on tampered checkpoint",
    "5": "reference model seat resolves and serves",
    "6": "benchmark registry freeze",
    "7": "3B launch packet readiness",
    "8": "authority conservation certificate",
    "9": "public issue census freeze",
}

LIVE_ISSUE_JSON_FIELDS = (
    "number,title,body,url,createdAt,updatedAt,labels,author,"
    "state,stateReason,closedAt,comments"
)
LIVE_ISSUE_LIMIT = 1000
RECEIPT_WORKSTREAM_ID = "EMBER-02A"

# `goal_id` in this receipt is NOT this receipt's subject. Per docs/domains/governance/authority/GOAL.md
# section 11 ("Every future pull request, experiment, receipt, ...artifact
# names the active goal_id and the next executed model or capability outcome
# it directly enables") and docs/domains/governance/authority/GOAL.md's `required_future_artifact_fields`
# (["goal_id", "workstream_id", "next_executed_outcome"]), every artifact's
# `goal_id` field records the CURRENTLY ACTIVE authority goal that artifact
# was produced under and directly enables -- today that is ACTIVE_GOAL_ID
# ("EMBER-02"), the same value verify_ember00_completion.py's receipt
# schema stamps for the same binding-rule reason. Changing `goal_id` here to
# "EMBER-01" would violate that standing rule, not honor it.
#
# What this receipt actually certifies (its subject) is unambiguous from its
# `schema` string ("ember-01-completion-receipt-v1") and its nine EMBER-01
# leg titles, but the 2026-08-01 cert adjudication flagged that an EMBER-01
# receipt carrying `goal_id: "EMBER-02"` reads, on its own, as a field
# reinterpretation in the exact instrument that certifies against field
# reinterpretation. The fix is not to overload `goal_id` with a second,
# conflicting meaning -- it is to name the subject explicitly, alongside the
# required active-authority stamp, so both facts are legible without either
# one shadowing the other.
COMPLETION_SUBJECT_GOAL_ID = "EMBER-01"

if RECEIPT_WORKSTREAM_ID not in ACTIVE_WORKSTREAM_IDS:
    raise RuntimeError("completion receipt workstream is not active")


def validate_receipt_path(root: Path, receipt: Path) -> Path:
    root = root.resolve()
    receipt = receipt.resolve()
    try:
        receipt.relative_to(root)
    except ValueError:
        return receipt
    raise ValueError("completion receipt must be outside the verified checkout")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# A real 2026-08 run lost a ~100-minute custody census to this class: the
# FINAL inspect_checkout() call hit a transient `git rev-parse HEAD` with
# nonzero returncode and EMPTY stderr (git worked fine in the same checkout
# immediately after), and the top-level except discarded the entire run with
# exit 2 and no receipt. A transient subprocess hiccup destroying the whole
# attestation is a probe defect, not a custody signal -- so read-only git
# calls here retry the SUBPROCESS-FAILURE mode only, with short backoff.
#
# What must never happen: reinterpreting a genuine result as a failure to
# retry it away. `git symbolic-ref` returning 1 means "detached HEAD" -- an
# expected, meaningful result, not an error -- so it is never retried; only
# a returncode outside its own expected set is. Likewise a clean `git
# status --porcelain` invocation that legitimately reports a dirty tree
# still returns 0 and is accepted on the first try, dirty result intact.
GIT_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 5.0, 10.0)


def _git_call_diagnostics(root: Path, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "stderr": result.stderr,
        "stdout": result.stdout,
        "cwd": str(root),
        "git_dir_exists": (root / ".git").exists(),
    }


def _git_readonly_with_retry(
    root: Path,
    *args: str,
    ok_returncodes: frozenset[int] = frozenset({0}),
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[subprocess.CompletedProcess[str], int]:
    """Run a read-only git call, retrying ONLY a genuine subprocess-failure
    returncode (not in `ok_returncodes`), up to `len(GIT_RETRY_BACKOFF_SECONDS)`
    additional attempts with short backoff between each. Returns the final
    CompletedProcess and how many retries it took (0 on a first-try pass).
    Raises RuntimeError with full diagnostics (returncode, stderr, stdout,
    cwd, whether .git exists) if every attempt fails.
    """
    result = git(root, *args)
    retries = 0
    for backoff in GIT_RETRY_BACKOFF_SECONDS:
        if result.returncode in ok_returncodes:
            return result, retries
        retries += 1
        sleep(backoff)
        result = git(root, *args)
    if result.returncode not in ok_returncodes:
        diagnostics = _git_call_diagnostics(root, result)
        raise RuntimeError(
            "git " + " ".join(args) + f" failed after {retries} retr"
            + ("y" if retries == 1 else "ies")
            + ": " + json.dumps(diagnostics, sort_keys=True)
        )
    return result, retries


def inspect_checkout(
    root: Path,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    total_retries = 0

    head, retries = _git_readonly_with_retry(root, "rev-parse", "HEAD", sleep=sleep)
    total_retries += retries

    symbolic, retries = _git_readonly_with_retry(
        root, "symbolic-ref", "--quiet", "--short", "HEAD",
        ok_returncodes=frozenset({0, 1}),
        sleep=sleep,
    )
    total_retries += retries

    status, retries = _git_readonly_with_retry(
        root, "status", "--porcelain", "--untracked-files=all", sleep=sleep,
    )
    total_retries += retries

    return {
        "head": head.stdout.strip(),
        "detached": symbolic.returncode != 0,
        "branch": None if symbolic.returncode != 0 else symbolic.stdout.strip(),
        "clean": not status.stdout.strip(),
        "status": status.stdout.strip().splitlines(),
        "git_retries": total_retries,
    }


def selection_evidence(selection: Path) -> dict[str, Any]:
    """Mirror EMBER-00: exactly one active_goal_path, file must exist."""
    selection_bytes = selection.read_bytes()
    text = selection_bytes.decode("utf-8")
    paths = [
        raw.split(":", 1)[1].strip()
        for raw in text.splitlines()
        if raw.split(":", 1)[0].strip() == "active_goal_path" and ":" in raw
    ]
    if len(paths) != 1:
        raise ValueError("selection must contain exactly one active_goal_path")
    goal_path = Path(paths[0])
    if not goal_path.is_absolute():
        goal_path = (selection.parent / goal_path).resolve()
    if not goal_path.is_file():
        raise ValueError(f"selected goal file is missing: {goal_path}")
    return {
        "selected_goal_suffix": Path(paths[0]).name,
        "selector_sha256": hashlib.sha256(selection_bytes).hexdigest(),
    }


def run(
    args: Sequence[str],
    *,
    root: Path,
    name: str,
    display: Sequence[str] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            list(args),
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "returncode": None,
            "timed_out": True,
            "command": list(display or args),
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout}s",
        }
    except OSError as exc:
        return {
            "name": name,
            "returncode": None,
            "timed_out": False,
            "command": list(display or args),
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "name": name,
        "returncode": completed.returncode,
        "timed_out": False,
        "command": list(display or args),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def leg(state: str, title: str, reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    if state not in {RESOLVED_TRUE, RESOLVED_FALSE, UNRESOLVED}:
        raise ValueError(f"illegal leg state: {state}")
    row: dict[str, Any] = {"title": title, "state": state, "reason": reason}
    if evidence is not None:
        row["evidence"] = evidence
    return row


def fetch_live_open_issues(
    root: Path,
) -> dict[str, Any]:
    executable_value = shutil.which("gh")
    if executable_value is None:
        return {
            "name": "github_live_open_issues",
            "returncode": 2,
            "timed_out": False,
            "command": ["gh", "issue", "list"],
            "stdout": "",
            "stderr": "GitHub CLI executable not found",
            "issues": None,
            "stdout_sha256": None,
            "executable_name": None,
            "executable_sha256": None,
        }
    executable = Path(executable_value).resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="ember-gh-snapshot-") as directory:
            snapshot = Path(directory) / executable.name
            shutil.copy2(executable, snapshot)
            executable_sha_before = hashlib.sha256(
                snapshot.read_bytes()
            ).hexdigest()
            command = [
                str(snapshot),
                "issue",
                "list",
                "--repo",
                "wordingone/ember",
                "--state",
                "open",
        "--limit",
        str(LIVE_ISSUE_LIMIT),
                "--json",
                LIVE_ISSUE_JSON_FIELDS,
            ]
            result = run(
                command,
                root=root,
                name="github_live_open_issues",
                display=["gh", *command[1:]],
                timeout=300,
            )
            try:
                executable_sha_after = hashlib.sha256(
                    snapshot.read_bytes()
                ).hexdigest()
            except OSError:
                executable_sha_after = None
    except OSError as error:
        return {
            "name": "github_live_open_issues",
            "returncode": 2,
            "timed_out": False,
            "command": ["gh", "issue", "list"],
            "stdout": "",
            "stderr": f"GitHub CLI executable unreadable: {error}",
            "issues": None,
            "stdout_sha256": None,
            "executable_name": executable.name,
            "executable_sha256": None,
        }
    executable_evidence = {
        "executable_name": executable.name,
        "executable_sha256": executable_sha_before,
    }
    if executable_sha_after != executable_sha_before:
        return {
            **result,
            **executable_evidence,
            "returncode": 2,
            "issues": None,
            "stdout_sha256": None,
            "stderr": "GitHub CLI executable snapshot changed during acquisition",
        }
    if result["returncode"] != 0:
        return {
            **result,
            **executable_evidence,
            "issues": None,
            "stdout_sha256": None,
        }
    try:
        issues = json.loads(result["stdout"])
    except json.JSONDecodeError as error:
        return {
            **result,
            **executable_evidence,
            "returncode": 2,
            "issues": None,
            "stdout_sha256": hashlib.sha256(
                result["stdout"].encode("utf-8")
            ).hexdigest(),
            "stderr": f"live GitHub issue JSON invalid: {error}",
        }
    if not isinstance(issues, list):
        return {
            **result,
            **executable_evidence,
            "returncode": 2,
            "issues": None,
            "stdout_sha256": hashlib.sha256(
                result["stdout"].encode("utf-8")
            ).hexdigest(),
            "stderr": "live GitHub issue result is not a list",
        }
    if len(issues) >= LIVE_ISSUE_LIMIT:
        return {
            **result,
            **executable_evidence,
            "returncode": 2,
            "issues": None,
            "stdout_sha256": hashlib.sha256(
                result["stdout"].encode("utf-8")
            ).hexdigest(),
            "stderr": (
                "live GitHub issue result reached the acquisition limit; "
                "completeness is unproven"
            ),
        }
    return {
        **result,
        **executable_evidence,
        "issues": issues,
        "stdout_sha256": hashlib.sha256(
            result["stdout"].encode("utf-8")
        ).hexdigest(),
    }


ISO_INSTANT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ISSUE_SNAPSHOT_ATTEMPTS = 3


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capture_issue_snapshot(
    root: Path, attempts: int = ISSUE_SNAPSHOT_ATTEMPTS
) -> dict[str, Any]:
    """Capture the open-issue list INSIDE this verification run.

    Once the snapshot is the authority rather than a same-run equality check, a
    torn read becomes durable: GitHub serves this list paginated, so an edit
    landing mid-read returns a set that never existed at any instant. A capture
    therefore counts only when two back-to-back reads project to the same
    canonical snapshot - the same double-read the gh binary itself gets above.

    `captured_at_utc` and `capture_nonce` are stamped here, from this process,
    so a consumer can refuse a snapshot older than the run that certified it.
    """
    started = _now_utc()
    torn: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        first = fetch_live_open_issues(root)
        second = (
            fetch_live_open_issues(root)
            if first["returncode"] == 0 and isinstance(first["issues"], list)
            else None
        )
        for read in (first, second):
            if read is None or read["returncode"] != 0 or not isinstance(read["issues"], list):
                failed = read if read is not None else first
                return {
                    "ok": False,
                    "failure": "acquisition_failed",
                    "attempts": attempt,
                    "capture_started_at_utc": started,
                    "command": failed["command"],
                    "returncode": failed["returncode"],
                    "stdout_sha256": failed["stdout_sha256"],
                    "github_cli_executable_name": failed.get("executable_name"),
                    "github_cli_executable_sha256": failed.get("executable_sha256"),
                    "stderr_tail": str(failed["stderr"])[-400:],
                }
        canonical_first = canonical_open_issue_source_snapshot(first["issues"])
        canonical_second = canonical_open_issue_source_snapshot(second["issues"])
        if canonical_first == canonical_second:
            return {
                "ok": True,
                "attempts": attempt,
                "torn_reads": torn,
                "snapshot": canonical_first,
                "snapshot_sha256": _canonical_sha256(canonical_first),
                "issue_count": len(canonical_first),
                "capture_started_at_utc": started,
                "captured_at_utc": _now_utc(),
                "capture_nonce": secrets.token_hex(16),
                "command": first["command"],
                "stdout_sha256": first["stdout_sha256"],
                "confirming_stdout_sha256": second["stdout_sha256"],
                "github_cli_executable_name": first.get("executable_name"),
                "github_cli_executable_sha256": first.get("executable_sha256"),
            }
        torn.append(
            {
                "attempt": attempt,
                "first_snapshot_sha256": _canonical_sha256(canonical_first),
                "second_snapshot_sha256": _canonical_sha256(canonical_second),
            }
        )
    return {
        "ok": False,
        "failure": "torn_read",
        "attempts": attempts,
        "torn_reads": torn,
        "capture_started_at_utc": started,
        "command": first["command"],
        "github_cli_executable_name": first.get("executable_name"),
        "github_cli_executable_sha256": first.get("executable_sha256"),
    }


def census_capture_instant(payload: Any) -> tuple[str | None, str | None]:
    """Read the census snapshot's own capture instant out of the artifact.

    Never a wall-clock read here: a certificate that stamps verification time as
    capture time would claim a freshness it did not measure. Snapshots built by
    issue_census.py carry `captured_at`; older ones are bound by
    `snapshot_max_issue_updated_at`, which is a true LOWER bound on capture (the
    snapshot cannot predate the newest issue it contains).
    """
    if not isinstance(payload, dict):
        return None, None
    for field, source in (
        ("captured_at", "census.captured_at"),
        (
            "snapshot_max_issue_updated_at",
            "census.snapshot_max_issue_updated_at (lower bound)",
        ),
    ):
        value = payload.get(field)
        if isinstance(value, str) and ISO_INSTANT_RE.fullmatch(value):
            return value, source
    return None, None


def _instant_seconds(value: Any) -> float | None:
    if not isinstance(value, str) or not ISO_INSTANT_RE.fullmatch(value):
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    ).timestamp()


def census_snapshot_binding(
    payload: Any,
    census_sha256: str,
    capture_instant: str,
    capture_instant_source: str | None,
    head: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """The fields that make the issue legs a point-in-time certification.

    These live INSIDE the leg evidence on purpose: the completion receipt's
    top-level key set is validated with exact set equality by
    tools/ember-restart-3b/certified_train_launch.py, so a new top-level field
    would make every certificate minted afterwards unlaunchable.
    """
    pinned = payload.get("public_master_sha") if isinstance(payload, dict) else None
    count = payload.get("open_issue_count") if isinstance(payload, dict) else None
    census_seconds = _instant_seconds(capture_instant)
    run_seconds = _instant_seconds(snapshot.get("captured_at_utc"))
    return {
        "issue_census_binding_mode": "point_in_time_snapshot",
        "issue_census_sha256": census_sha256,
        "issue_census_capture_instant": capture_instant,
        "issue_census_capture_instant_source": capture_instant_source,
        "issue_census_public_master_sha": pinned,
        "issue_census_open_issue_count": count,
        "issue_census_snapshot_sha256": (
            payload.get("issue_snapshot_sha256") if isinstance(payload, dict) else None
        ),
        "verified_checkout_head": head,
        # Freshness for the external mint consumer: the in-run capture is
        # stamped by THIS process, so a census artifact captured days earlier is
        # visible as an age rather than hiding behind self-consistent hashes.
        "in_run_issue_snapshot": {
            "captured_at_utc": snapshot.get("captured_at_utc"),
            "capture_started_at_utc": snapshot.get("capture_started_at_utc"),
            "capture_nonce": snapshot.get("capture_nonce"),
            "snapshot_sha256": snapshot.get("snapshot_sha256"),
            "issue_count": snapshot.get("issue_count"),
            "capture_attempts": snapshot.get("attempts"),
            "torn_reads": snapshot.get("torn_reads"),
            "command": snapshot.get("command"),
            "stdout_sha256": snapshot.get("stdout_sha256"),
            "confirming_stdout_sha256": snapshot.get("confirming_stdout_sha256"),
            "github_cli_executable_name": snapshot.get("github_cli_executable_name"),
            "github_cli_executable_sha256": snapshot.get("github_cli_executable_sha256"),
            "equals_census_snapshot": (
                payload.get("issue_source_snapshot") == snapshot.get("snapshot")
                if isinstance(payload, dict)
                else None
            ),
            "divergence_resolves_leg_state": False,
        },
        "issue_census_age_seconds": (
            None
            if census_seconds is None or run_seconds is None
            else int(run_seconds - census_seconds)
        ),
        "issue_census_claim": (
            f"open issues as of {capture_instant}, census sha256 {census_sha256}, "
            f"pinned tip {pinned}"
        ),
    }


# ---- Legs 1/2/6/9: custody / roots / benchmark / issues (census.py) ----------
def custody_legs(
    root: Path,
    bindings: list[str],
    run_custody: bool,
    issue_census: Path | None = None,
    preserve_custody_output: Path | None = None,
    receipt_dir: Path | None = None,
) -> dict[str, Any]:
    manifests = root / "manifests" / "ember-01-custody"
    root_spec = manifests / "root-spec.json"
    bench = manifests / "benchmark-registry.json"
    # The live issue census cannot be content-bound to the commit that contains
    # it: merging a tracked refresh necessarily creates a successor commit.
    # Accept an explicit, externally generated census so census.py can enforce
    # its existing exact-current-master check without a self-referential file.
    issues = issue_census or manifests / "public-issue-census.json"
    have_manifests = root_spec.is_file() and bench.is_file() and issues.is_file()

    # A bare clean clone cannot bind operator-machine roots. Without real ROOT
    # bindings the census legs are UNRESOLVED (RUNNER-BLOCKED) - never a green
    # pass and never a hard fail. They resolve only when an operator supplies
    # the machine-root bindings and asks to run the census.
    if not (run_custody and bindings):
        why = "no operator-machine ROOT bindings supplied; census cannot bind roots on a bare clone"
        if not have_manifests:
            why = "custody manifests absent AND no ROOT bindings supplied"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("1", "2", "6", "9")}

    if issue_census is None:
        return {
            k: leg(
                RESOLVED_FALSE,
                LEG_TITLES[k],
                "explicit live issue census is required for a custody run",
                {"tool": CENSUS_REL},
            )
            for k in ("1", "2", "6", "9")
        }

    if not have_manifests:
        return {
            k: leg(UNRESOLVED, LEG_TITLES[k], "custody manifests absent from checkout")
            for k in ("1", "2", "6", "9")
        }

    try:
        issue_census_bytes = issues.read_bytes()
        issue_census_sha_before = hashlib.sha256(issue_census_bytes).hexdigest()
        issue_census_payload = json.loads(issue_census_bytes)
    except (OSError, json.JSONDecodeError) as error:
        evidence = {
            "tool": CENSUS_REL,
            "error_type": type(error).__name__,
            "error": str(error)[-400:],
        }
        return {
            k: leg(
                RESOLVED_FALSE,
                LEG_TITLES[k],
                "issue census unreadable before custody run",
                evidence,
            )
            for k in ("1", "2", "6", "9")
        }

    capture_instant, capture_instant_source = census_capture_instant(
        issue_census_payload
    )
    if capture_instant is None:
        return {
            k: leg(
                RESOLVED_FALSE,
                LEG_TITLES[k],
                "issue census carries no capture instant",
                {"tool": CENSUS_REL, "issue_census_sha256": issue_census_sha_before},
            )
            for k in ("1", "2", "6", "9")
        }

    # Capture the snapshot of record INSIDE this run, before the census executes.
    # Nothing downstream compares it to a live re-read: an issue filed, closed,
    # relabelled, or commented on while a multi-hour census runs must invalidate
    # nothing. Divergence from the census artifact is recorded, never fatal.
    snapshot = capture_issue_snapshot(root)
    if not snapshot["ok"]:
        reason = (
            "in-run issue snapshot could not be captured"
            if snapshot["failure"] == "acquisition_failed"
            else "issue snapshot torn across repeated live reads"
        )
        return {
            k: leg(RESOLVED_FALSE, LEG_TITLES[k], reason, snapshot)
            for k in ("1", "2", "6", "9")
        }

    out = root / ".ember01-verify-custody.tmp.json"
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    snapshot_binding = census_snapshot_binding(
        issue_census_payload,
        issue_census_sha_before,
        capture_instant,
        capture_instant_source,
        head,
        snapshot,
    )
    cmd = [
        sys.executable, "-B", CENSUS_REL,
        "--root-spec", str(root_spec),
        "--benchmark-registry", str(bench),
        "--issue-census", str(issues),
        "--issue-census-sha256", issue_census_sha_before,
        "--source-commit", head,
        "--public-master-ref", "refs/remotes/origin/master",
        "--output", str(out),
    ]
    for b in bindings:
        cmd += ["--binding", b]
    result = run(cmd, root=root, name="ember_01_custody")
    rc = result["returncode"]
    preserved: dict[str, Any] = {}
    if preserve_custody_output is not None:
        # Preserve the raw census.py output OUTSIDE the checkout before it is
        # unlinked below, on BOTH a green and a red run -- the caller (ember-cli's
        # /verify) needs the per-file contradiction detail even when this leg
        # resolves false, not just when it passes. Best-effort: a copy failure
        # (e.g. census.py never produced `out` because it crashed before writing)
        # never changes a leg verdict, so this is swallowed, not raised.
        try:
            if out.is_file():
                preserve_custody_output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(out, preserve_custody_output)
        except OSError:
            pass
    if rc != 0 and receipt_dir is not None:
        # A red census IS the diagnosis: its per-file contradiction rows are the
        # only thing that says WHICH files contradict. Deleting them and keeping
        # the 400-char stdout tail costs a full standalone census re-run to
        # recover (run20, 2026-08-03: 8050 contradictions, ~80 minutes). Keep
        # the payload beside the receipt -- outside the checkout by contract, so
        # the checkout stays clean either way -- and name the path in evidence.
        try:
            if out.is_file():
                receipt_dir.mkdir(parents=True, exist_ok=True)
                dest = receipt_dir / f"ember01-custody-census-red.{head[:12]}.json"
                shutil.copy2(out, dest)
                preserved["preserved_custody_output"] = str(dest)
        except OSError as exc:
            # Never let a preservation failure change a leg verdict; say so.
            preserved["preserved_custody_output_error"] = str(exc)
    try:
        out.unlink(missing_ok=True)  # keep the checkout clean
    except OSError:
        pass
    try:
        issue_census_sha_after = hashlib.sha256(issues.read_bytes()).hexdigest()
    except OSError:
        issue_census_sha_after = None
    if issue_census_sha_after != issue_census_sha_before:
        # The snapshot ARTIFACT mutating mid-run is real corruption of the thing
        # being certified - distinct from GitHub metadata moving on, which is not.
        evidence = {
            "tool": CENSUS_REL,
            "issue_census_sha256_before": issue_census_sha_before,
            "issue_census_sha256_after": issue_census_sha_after,
            **preserved,
        }
        return {
            k: leg(
                RESOLVED_FALSE,
                LEG_TITLES[k],
                "issue census changed during custody run",
                evidence,
            )
            for k in ("1", "2", "6", "9")
        }
    if rc == 0:
        state, reason = RESOLVED_TRUE, "census PASS"
    elif rc == 2:
        state, reason = RESOLVED_FALSE, "census INCOMPLETE (benchmark/issue/contradiction errors)"
    else:
        state, reason = RESOLVED_FALSE, f"census FAIL (exit {rc})"
    ev = {
        "tool": CENSUS_REL,
        "returncode": rc,
        "stdout_tail": result["stdout"][-400:],
        **snapshot_binding,
        **preserved,
    }
    return {k: leg(state, LEG_TITLES[k], reason, ev) for k in ("1", "2", "6", "9")}


# ---- Legs 3/4: identity round-trip / fail-closed (validate_identity.py) ------
def _checkpoint_shard_rows(checkpoint_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(checkpoint_payload, dict):
        raise ValueError("checkpoint manifest must be an object")
    shards = checkpoint_payload.get("shards")
    if not isinstance(shards, list) or not shards:
        raise ValueError("checkpoint manifest must contain shard records")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in shards:
        if not isinstance(record, dict):
            raise ValueError("checkpoint shard record must be an object")
        path = record.get("path")
        size = record.get("bytes")
        digest = record.get("sha256")
        if (
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or path in seen
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("checkpoint shard record is not closed and content-addressed")
        seen.add(path)
        rows.append(
            {
                "name": path,
                "shape": [size],
                "dtype": "ember-checkpoint-shard-v1",
                "sha256": digest,
            }
        )
    return rows


def _flipped_sha256(value: Any) -> str:
    return "1" * 64 if value == "0" * 64 else "0" * 64


def _identity_tamper_mutants(
    payload: dict[str, Any],
) -> list[tuple[str, dict[str, Any], str]]:
    mutants: list[tuple[str, dict[str, Any], str]] = []

    parameter = copy.deepcopy(payload)
    parameter["parameters"]["allocated"] += 1
    mutants.append(
        ("param_count", parameter, "binding.parameters_mismatch")
    )

    tokenizer = copy.deepcopy(payload)
    tokenizer["tokenizer"]["sha256"] = _flipped_sha256(
        tokenizer["tokenizer"].get("sha256")
    )
    mutants.append(
        ("tokenizer", tokenizer, "binding.tokenizer_mismatch")
    )

    learned_signal = copy.deepcopy(payload)
    sources = learned_signal["provenance"]["learned_signal_sources"]
    if "hidden_external_cognition" not in sources:
        sources.append("hidden_external_cognition")
    else:
        sources.append("borrowed_stopping_decision")
    mutants.append(
        (
            "data_learned_signal",
            learned_signal,
            "provenance.forbidden_learned_signal",
        )
    )

    mechanism = copy.deepcopy(payload)
    routers = mechanism["mechanisms"]["router"]
    if not routers or not isinstance(routers[0], dict):
        raise ValueError("real identity manifest has no concrete router to tamper")
    routers[0]["sha256"] = _flipped_sha256(routers[0].get("sha256"))
    mutants.append(
        ("mechanism", mechanism, "binding.mechanisms_mismatch")
    )

    backend = copy.deepcopy(payload)
    backend["backend"]["executable_sha256"] = _flipped_sha256(
        backend["backend"].get("executable_sha256")
    )
    mutants.append(
        ("backend", backend, "binding.backend_mismatch")
    )

    benchmark = copy.deepcopy(payload)
    benchmark["evaluation"]["benchmark_id"] = (
        "ember-cond4-unregistered-benchmark"
    )
    mutants.append(
        (
            "benchmark_id",
            benchmark,
            "binding.evaluation.benchmark_id_mismatch",
        )
    )

    comparator = copy.deepcopy(payload)
    comparator["evaluation"]["comparator_identity"] = (
        "ember-cond4-foreign-comparator"
    )
    mutants.append(
        (
            "comparator",
            comparator,
            "binding.evaluation.comparator_identity_mismatch",
        )
    )
    return mutants


def _run_identity_tamper_battery(
    *,
    root: Path,
    payload: dict[str, Any],
    receipt: dict[str, Any],
    checkpoint_bytes: bytes,
    model_config: Path,
    scratch_root: Path,
) -> dict[str, Any]:
    """Execute cond4's eight isolated fail-closed probes.

    The checkpoint-bytes axis goes through the real parameter-identity verifier.
    The other seven axes go through the shipping validate_identity.py CLI with
    the clean identity as its expected binding. A rejection counts only when
    the process is non-zero, emits ``ok:false``, and includes the axis's bound
    finding code.
    """
    scratch_root.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {}
    created: list[Path] = []
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".ember01-cond4-checkpoint-bytes-",
            suffix=".json",
            dir=scratch_root,
            delete=False,
        ) as handle:
            handle.write(checkpoint_bytes + b"\n")
            checkpoint_tamper = Path(handle.name)
            created.append(checkpoint_tamper)
        started_ns = time.perf_counter_ns()
        try:
            verify_parameter_identity_binding(
                payload,
                receipt,
                checkpoint_manifest=checkpoint_tamper,
                model_config=model_config,
            )
        except ParameterIdentityMismatch as error:
            evidence["checkpoint_bytes"] = {
                "rejected": True,
                "finding": "parameter_identity_mismatch",
                "detail": str(error)[-400:],
            }
        else:
            evidence["checkpoint_bytes"] = {
                "rejected": False,
                "finding": None,
                "detail": "tampered checkpoint manifest was accepted",
            }
        evidence["checkpoint_bytes"]["duration_ms"] = max(
            1, (time.perf_counter_ns() - started_ns + 999_999) // 1_000_000
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".ember01-cond4-expected-",
            suffix=".json",
            dir=scratch_root,
            delete=False,
        ) as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            expected_path = Path(handle.name)
            created.append(expected_path)

        for axis, mutant, expected_code in _identity_tamper_mutants(payload):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".ember01-cond4-{axis}-",
                suffix=".json",
                dir=scratch_root,
                delete=False,
            ) as handle:
                json.dump(mutant, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                mutant_path = Path(handle.name)
                created.append(mutant_path)
            started_ns = time.perf_counter_ns()
            result = run(
                [
                    sys.executable,
                    "-B",
                    VALIDATE_IDENTITY_REL,
                    str(mutant_path),
                    "--expected",
                    str(expected_path),
                ],
                root=root,
                name=f"cond4_{axis}",
                timeout=180,
            )
            try:
                parsed = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                parsed = {}
            findings = parsed.get("findings")
            finding_codes = sorted(
                {
                    row.get("code")
                    for row in findings
                    if isinstance(row, dict) and isinstance(row.get("code"), str)
                }
            ) if isinstance(findings, list) else []
            rejected = (
                result["returncode"] != 0
                and parsed.get("ok") is False
                and expected_code in finding_codes
            )
            evidence[axis] = {
                "rejected": rejected,
                "expected_finding": expected_code,
                "finding_codes": finding_codes,
                "returncode": result["returncode"],
                "timed_out": result["timed_out"],
                "duration_ms": max(
                    1, (time.perf_counter_ns() - started_ns + 999_999) // 1_000_000
                ),
            }
    finally:
        for path in reversed(created):
            path.unlink(missing_ok=True)

    failures = [
        axis
        for axis, row in evidence.items()
        if not isinstance(row, dict) or row.get("rejected") is not True
    ]
    return {
        "tool": "src/ember/governance/scripts/verify_ember01_completion.py::cond4_tamper_battery",
        "axis_count": 8,
        "axes": evidence,
        "failures": failures,
        "all_rejected": not failures and len(evidence) == 8,
    }


def _cond4_surface_manifest(root: Path) -> dict[str, Any]:
    return build_surface_manifest(
        root,
        {
            "src/ember/governance/scripts/verify_ember01_completion.py": {
                "roots": [
                    "_cond4_execution_evidence",
                    "_cond4_surface_manifest",
                    "_load_cond4_surface_manifest",
                    "_run_bound_cond4_battery",
                    "_run_identity_tamper_battery",
                ],
                "dynamic_call_bindings": [
                    "backend['backend'].get",
                    "completed.stderr.strip",
                    "completed.stdout.strip",
                    "manifest_candidate.resolve",
                    "manifest_parent_candidate.resolve",
                    "path.read_text",
                    "checkpoint_bytes.decode",
                    "created.append",
                    "evidence.items",
                    "handle.write",
                    "mutants.append",
                    "parsed.get",
                    "path.unlink",
                    "row.get",
                    "rows.append",
                    "routers[0].get",
                    "scratch_root.mkdir",
                    "sources.append",
                    "tokenizer['tokenizer'].get",
                ],
            },
            "src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py": {
                "roots": [
                    "measure_live_checkpoint",
                    "verify_parameter_identity_binding",
                ],
                "dynamic_call_bindings": [
                    "checkpoint.get",
                    "manifest.get",
                    "parameters.get",
                    "receipt.get",
                    "remeasured.get",
                ],
            },
            "src/ember/governance/scripts/ember_01_identity/validate_identity.py": {
                "roots": ["main"],
                "dynamic_call_bindings": [
                    "accepted_input.get",
                    "admitted_counts.get",
                    "admitted_mixture.get",
                    "admitted_modalities.get",
                    "args.artifact_bundle.read_text",
                    "args.checkpoint.read_bytes",
                    "args.expected.read_text",
                    "args.manifest.read_text",
                    "args.receipt_bundle.read_text",
                    "args.tensor_hashes.read_text",
                    "args.tensor_manifest.read_text",
                    "args.trusted_verifier_registry.read_text",
                    "args.verifier.read_bytes",
                    "artifact_bundle.get",
                    "backend.get",
                    "capability.get",
                    "checkpoint_bytes.decode",
                    "counts.get",
                    "data.get",
                    "declared.get",
                    "dependency.get",
                    "entry.get",
                    "envelope.get",
                    "evaluation.get",
                    "expected_claims.items",
                    "findings.append",
                    "found.update",
                    "item.get",
                    "mixture.values",
                    "native.get",
                    "optimizer_contract.get",
                    "parameter_receipts.get",
                    "parameters.get",
                    "parsed_checkpoint_tensors.append",
                    "parser.add_argument",
                    "parser.parse_args",
                    "path.split",
                    "payload.get",
                    "process_identity.get",
                    "provenance.get",
                    "reason.casefold",
                    "reason.strip",
                    "receipt.get",
                    "receipt_bundle.get",
                    "registry.get",
                    "registry['active'].get",
                    "required.add",
                    "required.update",
                    "required_artifacts.items",
                    "row.get",
                    "seen.add",
                    "seen_checkpoint_names.add",
                    "source.casefold",
                    "stopping_rule.get",
                    "supplied_artifacts.get",
                    "tensor.get",
                    "tensor_hashes.get",
                    "tensor_manifest.get",
                    "tokenizer.get",
                    "trusted_verifier_registry.get",
                    "unresolved.values",
                    "unsigned.pop",
                    "validated.get",
                    "value.get",
                    "value.items",
                    "verifier_bytes.decode",
                ],
            },
        },
    )


def _load_cond4_surface_manifest(root: Path) -> dict[str, Any]:
    manifest_candidate = root / COND4_SURFACE_MANIFEST_REL
    path = manifest_candidate.resolve(strict=True)
    manifest_parent_candidate = root / Path(COND4_SURFACE_MANIFEST_REL).parent
    if path.parent != manifest_parent_candidate.resolve():
        raise Cond4SurfaceRefusal("COND4_SURFACE_PATH_INVALID")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Cond4SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID") from exc
    validate_surface_manifest(root, manifest)
    if manifest != _cond4_surface_manifest(root):
        raise Cond4SurfaceRefusal("COND4_SURFACE_SPEC_MISMATCH")
    return manifest


def _run_bound_cond4_battery(
    *,
    root: Path,
    payload: dict[str, Any],
    receipt: dict[str, Any],
    checkpoint_bytes: bytes,
    model_config: Path,
    scratch_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    surface_manifest = _load_cond4_surface_manifest(root)
    battery = _run_identity_tamper_battery(
        root=root,
        payload=payload,
        receipt=receipt,
        checkpoint_bytes=checkpoint_bytes,
        model_config=model_config,
        scratch_root=scratch_root,
    )
    return battery, surface_manifest


def _cond4_execution_evidence(
    *,
    checkpoint_bytes: bytes,
    surface_manifest: dict[str, Any],
    battery: dict[str, Any],
    load_count: int,
) -> dict[str, Any]:
    try:
        checkpoint_payload = json.loads(checkpoint_bytes.decode("utf-8"))
        shards = checkpoint_payload["shards"]
        if not isinstance(shards, list) or not shards:
            raise TypeError("shards")
        shard_bytes = [row["bytes"] for row in shards]
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in shard_bytes
        ):
            raise TypeError("shard bytes")
        if not isinstance(load_count, int) or isinstance(load_count, bool) or load_count <= 0:
            raise TypeError("load count")
        axes = battery["axes"]
        rows = []
        for axis in COND4_AXES:
            row = axes[axis]
            findings = row.get("finding_codes")
            if findings is None and isinstance(row.get("finding"), str):
                findings = [row["finding"]]
            rows.append(
                {
                    "axis": axis,
                    "duration_ms": row["duration_ms"],
                    "rejected": row["rejected"],
                    "finding_codes": findings,
                }
            )
        evidence = {
            "schema": COND4_EXECUTION_SCHEMA,
            "subject": {
                "behavior_surface_validator_sha256": hashlib.sha256(
                    COND4_SURFACE_VALIDATOR_PATH.read_bytes()
                ).hexdigest(),
                "checkpoint_manifest_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
                "surface_aggregate_sha256": surface_manifest["aggregate_sha256"],
                "checkpoint_bytes_loaded": sum(shard_bytes) * load_count,
                "load_count": load_count,
            },
            "axes": rows,
        }
        validate_execution_evidence(evidence)
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, Cond4SurfaceRefusal) as exc:
        raise Cond4SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID") from exc
    return evidence


def identity_legs(
    root: Path,
    manifest: Path | None,
    checkpoint_manifest: Path | None,
    model_config: Path | None,
    scratch_root: Path,
) -> dict[str, Any]:
    # Requires a real checkpoint manifest on disk. Absent on a bare clone
    # -> UNRESOLVED, never a fake pass.
    if manifest is None:
        why = "no real-checkpoint identity manifest supplied; cannot evaluate on a bare clone"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}
    if not manifest.is_file():
        return {k: leg(UNRESOLVED, LEG_TITLES[k], f"identity manifest missing: {manifest}") for k in ("3", "4")}
    if checkpoint_manifest is None or not checkpoint_manifest.is_file():
        why = "identity manifest supplied but the checkpoint manifest is not on disk (RUNNER-BLOCKED)"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}
    if model_config is None or not model_config.is_file():
        why = "identity manifest supplied but the exact model config is not on disk (RUNNER-BLOCKED)"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}

    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        checkpoint_bytes = checkpoint_manifest.read_bytes()
        checkpoint_payload = json.loads(checkpoint_bytes.decode("utf-8"))
        identity_validator.validate_manifest(payload)
        expected_rows = _checkpoint_shard_rows(checkpoint_payload)
        checkpoint_identity = payload.get("checkpoint")
        if not isinstance(checkpoint_identity, dict):
            raise ValueError("identity manifest lacks checkpoint identity")
        if checkpoint_identity.get("format") != checkpoint_payload.get("schema_version"):
            raise ValueError("identity checkpoint format does not match the real checkpoint manifest")
        if checkpoint_identity.get("tensors") != expected_rows:
            raise ValueError("identity checkpoint shard rows do not match the real checkpoint manifest")
        receipt = measure_live_checkpoint(
            model_config=model_config,
            checkpoint_manifest=checkpoint_manifest,
            active_expert="shared",
        )
        load_count = 1
        load_count += verify_parameter_identity_binding(
            payload,
            receipt,
            checkpoint_manifest=checkpoint_manifest,
            model_config=model_config,
        )
    except Exception as error:  # noqa: BLE001 - completion must fail closed
        evidence = {
            "tool": "src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py",
            "error_type": type(error).__name__,
            "error": str(error)[-400:],
        }
        return {
            "3": leg(RESOLVED_FALSE, LEG_TITLES["3"], "real checkpoint identity failed", evidence),
            "4": leg(RESOLVED_FALSE, LEG_TITLES["4"], "tamper proof unavailable because clean round-trip failed", evidence),
        }

    receipt_sha = hashlib.sha256(
        json.dumps(
            receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    clean_evidence = {
        "tool": "src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py",
        "checkpoint_sha256": receipt["subject_checkpoint_sha256"],
        "parameter_receipt_sha256": receipt_sha,
        "disposition": payload["identity"]["disposition"],
        "ownership": payload["provenance"]["ownership"],
    }

    try:
        tamper_evidence, surface_manifest = _run_bound_cond4_battery(
            root=root,
            payload=payload,
            receipt=receipt,
            checkpoint_bytes=checkpoint_bytes,
            model_config=model_config,
            scratch_root=scratch_root,
        )
        execution_evidence = _cond4_execution_evidence(
            checkpoint_bytes=checkpoint_bytes,
            surface_manifest=surface_manifest,
            battery=tamper_evidence,
            load_count=load_count,
        )
        validate_execution_packet(root, surface_manifest, execution_evidence)
        tamper_evidence["behavior_surface"] = surface_manifest
        tamper_evidence["execution_evidence"] = execution_evidence
    except Exception as error:  # noqa: BLE001 - battery itself fails closed
        tamper_evidence = {
            "tool": "src/ember/governance/scripts/verify_ember01_completion.py::cond4_tamper_battery",
            "axis_count": 8,
            "axes": {},
            "failures": ["battery_execution"],
            "all_rejected": False,
            "error_type": type(error).__name__,
            "error": str(error)[-400:],
        }
    tamper_rejected = tamper_evidence["all_rejected"] is True
    return {
        "3": leg(RESOLVED_TRUE, LEG_TITLES["3"], "real checkpoint identity re-derived", clean_evidence),
        "4": leg(
            RESOLVED_TRUE if tamper_rejected else RESOLVED_FALSE,
            LEG_TITLES["4"],
            "all eight isolated identity tamper axes rejected"
            if tamper_rejected
            else "one or more isolated identity tamper axes failed open",
            tamper_evidence,
        ),
    }


# ---- Leg 5: reference seat (model-seat.ts via bun test) -----------------------
def seat_leg(root: Path, run_seat: bool) -> dict[str, Any]:
    seat_test = root / SEAT_TEST_REL
    if not seat_test.is_file():
        return {"5": leg(UNRESOLVED, LEG_TITLES["5"], "no reference model seat resolvable in checkout")}
    if not run_seat:
        why = "seat proxy not run (pass --run-seat on a machine with bun deps installed)"
        return {"5": leg(UNRESOLVED, LEG_TITLES["5"], why)}
    cli_dir = root / "tools" / "ember-cli"
    bun = shutil.which("bun")
    if bun is None:
        return {
            "5": leg(
                UNRESOLVED,
                LEG_TITLES["5"],
                "seat test could not execute (bun command is unavailable)",
            )
        }
    cmd = [bun, "test", "src/entrypoints/model-seat.test.ts"]
    result = run(cmd, root=cli_dir, name="model_seat", timeout=240)
    rc = result["returncode"]
    if rc == 0:
        return {"5": leg(RESOLVED_TRUE, LEG_TITLES["5"], "bun test model-seat passed",
                         {"tool": "bun test", "returncode": rc})}
    # A non-zero from missing installed deps is a runner block, not a real fail.
    combined = (result["stdout"] + result["stderr"]).lower()
    if result["timed_out"] or "cannot find" in combined or "error: script" in combined or "no such" in combined:
        return {"5": leg(UNRESOLVED, LEG_TITLES["5"],
                         "seat test could not execute (deps not installed / runner-blocked)",
                         {"tool": "bun test", "returncode": rc, "stderr_tail": result["stderr"][-300:]})}
    return {"5": leg(RESOLVED_FALSE, LEG_TITLES["5"], f"bun test model-seat failed (exit {rc})",
                     {"tool": "bun test", "returncode": rc, "stderr_tail": result["stderr"][-300:]})}


# ---- Leg 7: 3B launch packet (launch_packet.py) ------------------------------
def launch_packet_leg(root: Path) -> dict[str, Any]:
    config = root / CONFIG_REL
    if not config.is_file():
        return {"7": leg(UNRESOLVED, LEG_TITLES["7"], f"launch config absent: {CONFIG_REL}")}
    # launch_packet.py writes a transient receipt INTO root/receipts/ember-01-launch-packet/<ts>/
    # and has no output-path override. Snapshot the dir so the receipt it creates can be removed
    # afterward — otherwise leg 7 dirties the checkout mid-run and breaks the integrity invariant
    # (clean+detached+head-unchanged throughout) that every later leg and the final `ok` depend on.
    packet_root = root / "receipts" / "ember-01-launch-packet"
    before = {p.name for p in packet_root.iterdir()} if packet_root.is_dir() else set()
    packet_root_preexisting = packet_root.is_dir()
    cmd = [sys.executable, "-B", LAUNCH_PACKET_REL, "--config", str(config)]
    result = run(cmd, root=root, name="launch_packet", timeout=180)
    # Remove the transient receipt launch_packet just created, restoring the clean tree.
    if packet_root.is_dir():
        for entry in packet_root.iterdir():
            if entry.name not in before:
                shutil.rmtree(entry, ignore_errors=True) if entry.is_dir() else entry.unlink(missing_ok=True)
        if not packet_root_preexisting:
            try:
                packet_root.rmdir()
            except OSError:
                pass
    rc = result["returncode"]
    state = RESOLVED_TRUE if rc == 0 else RESOLVED_FALSE
    reason = "launch packet ready" if rc == 0 else f"launch packet not ready (exit {rc})"
    ev = {"tool": LAUNCH_PACKET_REL, "returncode": rc, "stdout_tail": result["stdout"][-400:]}
    return {"7": leg(state, LEG_TITLES["7"], reason, ev)}


# ---- Leg 8: authority conservation (imported verify()) -----------------------
def authority_leg(root: Path, selection: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cert = verify(root, selection)
    ok = bool(cert.get("ok"))
    state = RESOLVED_TRUE if ok else RESOLVED_FALSE
    reason = "authority conservation certificate ok" if ok else "authority certificate failed"
    return {"8": leg(state, LEG_TITLES["8"], reason, {"tool": "verify_authority_conservation.verify"})}, cert


def closure_evidence_at(root: Path) -> tuple[str | None, str]:
    """Training-dependency-closure hash at the verified-at commit, and why.

    Rides inside `checkout` rather than as a new top-level receipt key, so the
    receipt's key set is unchanged and an unmodified launch consumer still
    validates it. The launch consumer compares the hash against the closure it
    recomputes from live bytes, so a merge outside the closure no longer
    invalidates a pending certificate.

    Fail-closed, and audited BEFORE it is hashed: if the declared closure does
    not match what the entrypoints actually reach, no hash is pinned. The
    launch consumer then falls back to whole-tip equality -- a violated
    boundary loses the relaxation and gets the older, blunter, stricter
    binding. A green certificate must never pin a closure hash over an
    already-violated boundary.

    The second element records WHY a hash is absent, because a bare None
    cannot distinguish a tree that predates the closure manifest from one
    whose boundary is broken, and whoever reads the receipt has to tell those
    apart.
    """
    module_path = Path(root) / "scripts" / "training_closure.py"
    specification = importlib.util.spec_from_file_location(
        "ember_training_closure", module_path
    )
    if specification is None or specification.loader is None:
        return None, "unavailable: no training closure module in this checkout"
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
        manifest = module.load_manifest(Path(root))
        audit = module.audit_closure(Path(root), manifest)
        if not audit.ok:
            return None, f"violated: {audit.failure_report()}"
        return str(module.compute_closure_hash(Path(root), manifest)), "ok"
    except (OSError, ValueError) as error:
        return None, f"unavailable: {error}"


def write_receipt(path: Path, payload: dict[str, Any]) -> None:
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
    parser.add_argument("--root", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--binding", action="append", default=[],
                        help="operator-machine ROOT binding NAME=PATH (repeatable)")
    parser.add_argument("--run-custody", action="store_true",
                        help="run the custody census (requires real ROOT bindings)")
    parser.add_argument(
        "--preserve-custody-output",
        default=None,
        help=(
            "copy census.py's raw per-file custody-census output to this path "
            "(outside the checkout) before it is unlinked, on both a green and "
            "a red custody run; optional -- a red census is preserved beside "
            "the receipt regardless, with the path named in leg evidence"
        ),
    )
    parser.add_argument(
        "--issue-census",
        default=None,
        help=(
            "live public-issue census generated outside the verified checkout; "
            "required for --run-custody; omission fails the custody legs closed"
        ),
    )
    parser.add_argument("--identity-manifest", default=None,
                        help="owned-checkpoint identity manifest path")
    parser.add_argument("--checkpoint-manifest", "--checkpoint", dest="checkpoint_manifest", default=None,
                        help="real sharded checkpoint-manifest.json for identity round-trip")
    parser.add_argument("--model-config", default=None,
                        help="exact model config bound by the checkpoint manifest")
    parser.add_argument("--run-seat", action="store_true",
                        help="run bun test on the reference model seat")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    selection = Path(args.selection).resolve()
    ident_manifest = Path(args.identity_manifest).resolve() if args.identity_manifest else None
    checkpoint_manifest = Path(args.checkpoint_manifest).resolve() if args.checkpoint_manifest else None
    model_config = Path(args.model_config).resolve() if args.model_config else None
    issue_census = Path(args.issue_census).resolve() if args.issue_census else None
    preserve_custody_output = (
        Path(args.preserve_custody_output).resolve() if args.preserve_custody_output else None
    )

    try:
        receipt = validate_receipt_path(root, Path(args.receipt))
        before = inspect_checkout(root)
        selection_before = selection_evidence(selection)

        # Executable legs run only if the checkout is clean AND detached, same
        # gate EMBER-00 uses, so certifying cannot mutate the tree it certifies.
        if before["clean"] and before["detached"]:
            legs: dict[str, Any] = {}
            authority_row, authority_cert = authority_leg(root, selection)
            legs.update(authority_row)
            legs.update(launch_packet_leg(root))
            legs.update(
                custody_legs(
                    root,
                    args.binding,
                    args.run_custody,
                    issue_census=issue_census,
                    preserve_custody_output=preserve_custody_output,
                    receipt_dir=receipt.parent,
                )
            )
            legs.update(
                identity_legs(
                    root,
                    ident_manifest,
                    checkpoint_manifest,
                    model_config,
                    receipt.parent,
                )
            )
            legs.update(seat_leg(root, args.run_seat))
        else:
            authority_cert = {"ok": False, "skipped": "checkout not clean+detached"}
            legs = {
                k: leg(UNRESOLVED, LEG_TITLES[k],
                       "checkout not clean+detached; executable legs skipped")
                for k in LEG_TITLES
            }

        selection_after = selection_evidence(selection)
        after = inspect_checkout(root)
    except Exception as exc:  # noqa: BLE001 - honest fail-closed
        print(f"EMBER01_COMPLETION FAIL: {exc}")
        return 2

    checkout = {
        **{k: v for k, v in after.items() if k != "git_retries"},
        "clean": bool(before["clean"] and after["clean"]),
        "detached": bool(before["detached"] and after["detached"]),
        "head_unchanged": before["head"] == after["head"],
        "status_before": before["status"],
        "git_retries_before": before["git_retries"],
        "git_retries_after": after["git_retries"],
    }
    closure_sha256, closure_boundary = closure_evidence_at(root)
    selection_unchanged = selection_before == selection_after

    legs = {k: legs[k] for k in sorted(legs, key=int)}
    leg_states = {k: v["state"] for k, v in legs.items()}
    exact_nine = set(legs) == {str(n) for n in range(1, 10)}
    all_resolved_true = exact_nine and all(s == RESOLVED_TRUE for s in leg_states.values())
    checkout_integrity = bool(
        checkout["clean"] and checkout["detached"] and checkout["head_unchanged"]
    )
    ok = bool(all_resolved_true and checkout_integrity and selection_unchanged)

    summary = {
        "resolved_true": sorted(k for k, s in leg_states.items() if s == RESOLVED_TRUE),
        "resolved_false": sorted(k for k, s in leg_states.items() if s == RESOLVED_FALSE),
        "unresolved": sorted(k for k, s in leg_states.items() if s == UNRESOLVED),
    }

    payload = {
        "schema": "ember-01-completion-receipt-v1",
        "ok": ok,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "goal_id": ACTIVE_GOAL_ID,
        "completion_subject_goal_id": COMPLETION_SUBJECT_GOAL_ID,
        "workstream_id": RECEIPT_WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "certificate_legs": leg_states,
        "leg_detail": legs,
        "leg_summary": summary,
        "claim_scope": {
            # What all-nine-resolved-true WOULD prove: EMBER-01 custody, identity,
            # seat, benchmark, launch-packet, authority, and issue conditions.
            # What it NEVER proves:
            "training_completed": False,
            "model_completed": False,
            "runtime_completed": False,
            "benchmark_completed": False,
            "note": (
                "A bare clean clone honestly reports the operator-machine-bound "
                "legs (custody/identity/seat) as UNRESOLVED. ok=true requires an "
                "operator-machine run with real roots + owned checkpoint + seat."
            ),
        },
        "checkout": {
            **checkout,
            "closure_sha256": closure_sha256,
            "closure_boundary": closure_boundary,
        },
        "selection": {**selection_after, "unchanged_during_verification": selection_unchanged},
        "authority_certificate": authority_cert,
    }
    write_receipt(receipt, payload)

    if ok:
        print(f"EMBER01_COMPLETION PASS: {receipt}")
        return 0
    print(f"EMBER01_COMPLETION FAIL: {receipt}")
    print(f"  resolved-true : {summary['resolved_true']}")
    print(f"  resolved-false: {summary['resolved_false']}")
    print(f"  UNRESOLVED    : {summary['unresolved']}")
    for k in summary["unresolved"] + summary["resolved_false"]:
        print(f"    leg {k} [{leg_states[k]}] {legs[k]['title']}: {legs[k]['reason']}")
    if not checkout_integrity:
        print("  checkout was not clean+detached+head-unchanged throughout")
    if not selection_unchanged:
        print("  goal selector changed during verification")
    return 1


if __name__ == "__main__":
    sys.exit(main())
