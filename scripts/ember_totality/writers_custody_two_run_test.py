#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed two-run custody proof for issue #400's relocated writers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _get_all_json_files(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {str(f.relative_to(path)) for f in path.rglob("*.json")}


def _get_all_files(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {str(f.relative_to(path)) for f in path.rglob("*") if f.is_file()}


def _run_writer_step(
    repo_root: Path, script_path: str, args: list[str] | None = None
) -> tuple[str, int]:
    script = repo_root / script_path
    if not script.exists():
        return f"Script {script} not found", 1
    result = subprocess.run(
        [sys.executable, str(script), *(args or [])],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout, result.returncode


def _has_zero_spend_declaration(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("api_spend_usd") == 0.0
        and payload.get("paid_api_surface_used") is False
    )


def _remove_new_files(directory: Path, relative_paths: set[str]) -> None:
    for relative in relative_paths:
        path = directory / relative
        if path.is_file():
            path.unlink()


def test_writers_custody_two_run() -> bool:
    """Run both writers twice and reject any canonical receipts/ mutation."""
    print("=" * 70)
    print("WRITERS CUSTODY TEST (ISSUE #400)")
    print("=" * 70)

    receipts_dir = REPO_ROOT / "receipts"
    milestone_dir = REPO_ROOT / "scripts" / "ember_totality" / "receipts-milestone"
    publication_dir = (
        REPO_ROOT / "scripts" / "ember_totality" / "receipts-publication"
    )
    canonical_before = _get_all_files(receipts_dir)
    milestone_before = _get_all_json_files(milestone_dir)
    publication_before = _get_all_json_files(publication_dir)

    runs: list[tuple[str, int]] = []
    for run_number in (1, 2):
        print(f"\n--- RUN {run_number} ---")
        for label, script in (
            ("milestone", "scripts/check_milestone_reconciliation.py"),
            ("publication", "scripts/check_publication_gate.py"),
        ):
            stdout, exit_code = _run_writer_step(REPO_ROOT, script)
            runs.append((label, exit_code))
            print(f"{label}: exit={exit_code}")
            if stdout:
                print(stdout.rstrip())

        leaked = _get_all_files(receipts_dir) - canonical_before
        if leaked:
            print("[FAIL] Writer run changed canonical receipts/:")
            for relative in sorted(leaked):
                print(f"       {relative}")
            new_milestone = _get_all_json_files(milestone_dir) - milestone_before
            new_publication = _get_all_json_files(publication_dir) - publication_before
            _remove_new_files(milestone_dir, new_milestone)
            _remove_new_files(publication_dir, new_publication)
            return False

    new_milestone = _get_all_json_files(milestone_dir) - milestone_before
    new_publication = _get_all_json_files(publication_dir) - publication_before
    try:
        milestone_ok = bool(new_milestone) and all(
            _has_zero_spend_declaration(milestone_dir / relative)
            for relative in new_milestone
        )
        publication_ok = bool(new_publication) and all(
            _has_zero_spend_declaration(publication_dir / relative)
            for relative in new_publication
        )
        if not milestone_ok or not publication_ok:
            print(
                "[FAIL] Designated receipts missing or lacking exact zero-spend "
                f"declarations: milestone={milestone_ok} publication={publication_ok}"
            )
            return False
        if _get_all_files(receipts_dir) != canonical_before:
            print("[FAIL] Canonical receipts/ did not remain at its exact baseline")
            return False
        print("[PASS] Both runs left the entire canonical receipts/ tree unchanged")
        print("[PASS] Both designated receipt families explicitly declare zero paid spend")
        print("writer exits (gate RED is allowed when receipted): " + repr(runs))
        return True
    finally:
        _remove_new_files(milestone_dir, new_milestone)
        _remove_new_files(publication_dir, new_publication)


if __name__ == "__main__":
    try:
        sys.exit(0 if test_writers_custody_two_run() else 1)
    except Exception as exc:  # noqa: BLE001
        print(f"TEST FAILED [ERROR]: {type(exc).__name__}: {exc}")
        sys.exit(1)
