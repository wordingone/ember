#!/usr/bin/env python3
# goal_id: EMBER-00
# next_executed_outcome: EMBER-01 clean 3B custody and identity spine
"""Emit the EMBER-00 completion receipt from a clean detached checkout.

The receipt is authority-only. It does not claim that training, a model,
runtime work, or benchmark work completed. The output must live outside the
verified checkout so creating the receipt cannot change the tree it certifies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from verify_authority_conservation import (
    ACTIVE_GOAL_ID,
    INVARIANT_SHA256,
    NEXT_EXECUTED_OUTCOME,
    sha256,
    verify,
)


def validate_receipt_path(root: Path, receipt: Path) -> Path:
    root = root.resolve()
    receipt = receipt.resolve()
    try:
        receipt.relative_to(root)
    except ValueError:
        return receipt
    raise ValueError("completion receipt must be outside the verified checkout")


def completion_is_valid(
    *,
    authority: dict[str, Any],
    checks: list[dict[str, Any]],
    checkout: dict[str, Any],
    invariant_matches: bool,
    selection_integrity: bool,
) -> bool:
    legs = authority.get("certificate_legs") or {}
    exact_legs = set(legs) == {str(leg) for leg in range(1, 8)}
    return bool(
        authority.get("ok")
        and exact_legs
        and all(legs.values())
        and checks
        and all(check.get("ok") for check in checks)
        and checkout.get("clean")
        and checkout.get("detached")
        and checkout.get("head_unchanged")
        and invariant_matches
        and selection_integrity
    )


def require_stdout_prefix(
    result: dict[str, Any], required_prefix: str
) -> dict[str, Any]:
    result = dict(result)
    result["required_stdout_prefix"] = required_prefix
    result["ok"] = bool(
        result.get("ok") and str(result.get("stdout", "")).startswith(required_prefix)
    )
    return result


def run(
    args: Sequence[str],
    *,
    root: Path,
    name: str,
    display: Sequence[str] | None = None,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        list(args),
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "name": name,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": list(display or args),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


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


def inspect_checkout(root: Path) -> dict[str, Any]:
    head = git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {head.stderr.strip()}")
    symbolic = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if symbolic.returncode not in {0, 1}:
        raise RuntimeError(f"git symbolic-ref failed: {symbolic.stderr.strip()}")
    status = git(root, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip()}")
    return {
        "head": head.stdout.strip(),
        "detached": symbolic.returncode != 0,
        "branch": None if symbolic.returncode != 0 else symbolic.stdout.strip(),
        "clean": not status.stdout.strip(),
        "status": status.stdout.strip().splitlines(),
    }


def selection_evidence(selection: Path) -> dict[str, Any]:
    text = selection.read_text(encoding="utf-8")
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
    normalized = paths[0].replace("\\", "/")
    return {
        "pointer_sha256": sha256(selection),
        "selected_goal_suffix": "/".join(normalized.split("/")[-4:]),
        "selected_goal_sha256": sha256(goal_path),
    }


def repository_guard_command() -> list[str]:
    if os.name == "nt":
        candidate = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        candidate /= "Git/bin/bash.exe"
        if not candidate.is_file():
            raise RuntimeError(f"Git Bash is required: {candidate}")
        return [str(candidate), "tools/repo-guard.sh"]
    return ["bash", "tools/repo-guard.sh"]


def executable_checks(root: Path) -> list[dict[str, Any]]:
    py = sys.executable
    checks: list[tuple[str, list[str], list[str]]] = [
        (
            "mutation_and_gate_tests",
            [
                py,
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "scripts/tests/test_authority_conservation.py",
                "scripts/tests/test_authority_completion.py",
                "scripts/tests/test_registry_authority_gate.py",
                "scripts/tests/test_pr_authority_binding.py",
            ],
            ["python", "-B", "-m", "pytest", "<four authority/gate suites>"],
        ),
        (
            "registry_gate_selftest",
            [py, "-B", "scripts/registry_gate_selftest.py"],
            ["python", "-B", "scripts/registry_gate_selftest.py"],
        ),
        (
            "repo_guard_selftest",
            [py, "-B", "tools/repo_guard_selftest.py"],
            ["python", "-B", "tools/repo_guard_selftest.py"],
        ),
        (
            "condition_registry_sync",
            [py, "-B", "scripts/ember_totality/check_registry_sync.py"],
            ["python", "-B", "scripts/ember_totality/check_registry_sync.py"],
        ),
        (
            "c_authority_condition",
            [py, "-B", "scripts/ember_totality/test_c_authority.py"],
            ["python", "-B", "scripts/ember_totality/test_c_authority.py"],
        ),
        (
            "pr_authority_binding",
            [
                py,
                "-B",
                "scripts/check_pr_authority_binding.py",
                "--body-file",
                ".github/PULL_REQUEST_TEMPLATE.md",
            ],
            [
                "python",
                "-B",
                "scripts/check_pr_authority_binding.py",
                "--body-file",
                ".github/PULL_REQUEST_TEMPLATE.md",
            ],
        ),
    ]
    results = [
        run(command, root=root, name=name, display=display)
        for name, command, display in checks
    ]
    results = [
        require_stdout_prefix(result, "GREEN C-AUTHORITY:")
        if result["name"] == "c_authority_condition"
        else result
        for result in results
    ]
    guard = repository_guard_command()
    results.append(
        run(
            guard,
            root=root,
            name="repository_guard",
            display=["bash", "tools/repo-guard.sh"],
        )
    )
    return results


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
    args = parser.parse_args()

    root = Path(args.root).resolve()
    selection = Path(args.selection).resolve()
    try:
        receipt = validate_receipt_path(root, Path(args.receipt))
        before = inspect_checkout(root)
        selection_before = selection_evidence(selection)
        authority = verify(root, selection)
        invariant_actual = sha256(root / "docs/authority/INVARIANT.md")
        invariant_matches = invariant_actual == INVARIANT_SHA256
        checks = executable_checks(root) if before["clean"] and before["detached"] else []
        selection_after = selection_evidence(selection)
        after = inspect_checkout(root)
    except Exception as exc:
        print(f"EMBER00_COMPLETION FAIL: {exc}")
        return 2

    checkout = {
        **after,
        "clean": bool(before["clean"] and after["clean"]),
        "detached": bool(before["detached"] and after["detached"]),
        "head_unchanged": before["head"] == after["head"],
        "status_before": before["status"],
    }
    selection_unchanged = selection_before == selection_after
    ok = completion_is_valid(
        authority=authority,
        checks=checks,
        checkout=checkout,
        invariant_matches=invariant_matches,
        selection_integrity=selection_unchanged,
    )
    payload = {
        "schema": "ember-00-completion-receipt-v1",
        "ok": ok,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "goal_id": ACTIVE_GOAL_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "authority_only": True,
        "allows_new_network": False,
        "claim_scope": {
            "training_completed": False,
            "model_completed": False,
            "runtime_completed": False,
            "benchmark_completed": False,
        },
        "checkout": checkout,
        "selection": {
            **selection_after,
            "unchanged_during_verification": selection_unchanged,
        },
        "invariant": {
            "expected_sha256": INVARIANT_SHA256,
            "actual_sha256": invariant_actual,
            "matches": invariant_matches,
        },
        "authority_certificate": authority,
        "executable_checks": checks,
    }
    write_receipt(receipt, payload)
    if ok:
        print(f"EMBER00_COMPLETION PASS: {receipt}")
        return 0
    print(f"EMBER00_COMPLETION FAIL: {receipt}")
    for check in checks:
        if not check["ok"]:
            print(f"  {check['name']}: exit {check['returncode']}")
    if not authority.get("ok"):
        print("  authority conservation certificate failed")
    if not checkout["clean"] or not checkout["detached"]:
        print("  checkout was not clean and detached throughout")
    if not invariant_matches:
        print("  docs/authority/INVARIANT.md hash changed")
    if not selection_unchanged:
        print("  goal selector or selected goal bytes changed during verification")
    return 1


if __name__ == "__main__":
    sys.exit(main())
