#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed collection guard for the canonical governance scripts test suite.

The normal suite invocation reports test failures, but a module-level import
failure can truncate collection before the suite reports its population.  This
bounded probe makes both conditions terminal: pytest must exit successfully
from ``--collect-only`` and the reported population must stay above the frozen
floor.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MINIMUM = 380
DEFAULT_TIMEOUT_SECONDS = 180
MAX_FAILURE_DIAGNOSTIC_CHARS = 4_000
_COLLECTION_RE = re.compile(r"\b(\d+)\s+tests?\s+collected\b")


class CollectionGuardError(RuntimeError):
    """Raised when collection is incomplete, malformed, or below the floor."""


@dataclass(frozen=True)
class CollectionReport:
    collected: int
    command: tuple[str, ...]
    output: str


def parse_collection_count(output: str) -> int:
    match = _COLLECTION_RE.search(output)
    if match is None:
        raise CollectionGuardError(
            "collection count is missing; refusing to accept an incomplete report"
        )
    return int(match.group(1))


def validate_collection(*, returncode: int, output: str, minimum: int) -> int:
    if returncode != 0:
        diagnostic = output.strip()[-MAX_FAILURE_DIAGNOSTIC_CHARS:]
        detail = f"; diagnostic tail:\n{diagnostic}" if diagnostic else ""
        raise CollectionGuardError(
            f"collection command failed with exit code {returncode}; "
            f"refusing truncated population{detail}"
        )
    collected = parse_collection_count(output)
    if collected < minimum:
        raise CollectionGuardError(
            f"collected test count {collected} is below floor {minimum}; refusing truncation"
        )
    return collected


def run_collection(
    repo_root: Path,
    *,
    minimum: int = DEFAULT_MINIMUM,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CollectionReport:
    if minimum < 1:
        raise CollectionGuardError("collection floor must be positive")
    command = (
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "src/ember/governance/scripts/tests",
    )
    try:
        completed = subprocess.run(
            list(command),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionGuardError(f"collection command could not complete: {exc}") from exc
    output = f"{completed.stdout}\n{completed.stderr}"
    collected = validate_collection(
        returncode=completed.returncode,
        output=output,
        minimum=minimum,
    )
    return CollectionReport(collected=collected, command=command, output=output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--minimum", type=int, default=DEFAULT_MINIMUM)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        report = run_collection(
            args.repo,
            minimum=args.minimum,
            timeout_seconds=args.timeout_seconds,
        )
    except CollectionGuardError as exc:
        print(f"SCRIPTS_TESTS_COLLECTION_REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"SCRIPTS_TESTS_COLLECTION_PASS: collected={report.collected} floor={args.minimum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
