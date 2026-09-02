#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify the C0 failure-class ledger (EMBER-01 OD-2 declaration conjunct-3).

The B7 declaration rule (OD-2 default) requires three conjuncts before EMBER-01 can be
declared: (1) the RECORD-COHERENT blocking subset, (2) the nine-leg verifier ok:true,
(3) an operator-drivable spine with every birth-relevant failure class CLOSED_GUARDED.
This module is conjunct (3).

DESIGN RULE - HONESTY OVER GREEN, same law as verify_ember01_completion.py. A row is
either CLOSED_GUARDED (a named, resolvable guard proves the class cannot silently
recur) or BLOCKING (explicitly open). A ledger that omits a known birth-relevant class
is a defect the ledger cannot self-report -> this verifier cross-references the
class-kill law's own enumerated class set (memory/feedback_training_failure_class_kill_
law_2026_07_21.md, Jun 2026-07-21: "every FUTURE failure is deterministically minimized,
and no failure of the exact same CLASS can EVER have the possibility of repeating") and
REDs if any law-listed class is absent from the ledger. A ledger row whose guard_ref does
not resolve to real in-repo bytes is RED, never silently accepted. A BLOCKING row makes
the conjunct verdict BLOCKED, not CLOSED - the ledger tells the truth, it does not fake
green.

COLLECTABILITY GATE (dead-on-import false-CLOSE class, 2026-07-23): bytes existing is not
proof a guard works. A CLOSED_GUARDED row whose guard_ref names a test file is additionally
probed with a bounded pytest --collect-only; a guard that cannot even be collected (a
module-scope import chain frozen out by a later, unrelated commit; an internal collection
error) never regression-guards its class and now REDs the row instead of counting as closed.
Non-test guard_refs (validator modules referenced by symbol) are unaffected.

Verdict states (mutually exclusive):
    RED      - the ledger could not be loaded, or fails schema / completeness /
               guard-resolution checks. Never a valid declaration input.
    BLOCKED  - the ledger is well-formed and complete but at least one class is still
               BLOCKING. Honest, expected pre-birth state.
    CLOSED   - the ledger is well-formed, complete, and every class is CLOSED_GUARDED
               with a guard_ref that resolves to real in-repo bytes. Conjunct-3 holds.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
DEFAULT_LEDGER_PATH = (
    REPO_ROOT / "manifests" / "ember-01-custody" / "c0-failure-class-ledger.json"
)

LEDGER_SCHEMA = "ember-01-c0-failure-class-ledger-v1"
VERDICT_SCHEMA = "ember-01-c0-conjunct3-verdict-v1"

STATE_CLOSED_GUARDED = "CLOSED_GUARDED"
STATE_BLOCKING = "BLOCKING"
VALID_STATES = {STATE_CLOSED_GUARDED, STATE_BLOCKING}
VALID_GUARD_KINDS = {"schema", "test", "runtime-assert", "hook"}

REQUIRED_BASE_KEYS = {"class_id", "title", "birth_relevance", "state"}
ALLOWED_KEYS = REQUIRED_BASE_KEYS | {
    "guard_ref",
    "guard_kind",
    "evidence",
    "blocking_reason",
}

# The class-kill law's enumerated root-cause classes (Jun 2026-07-21, memory file
# feedback_training_failure_class_kill_law_2026_07_21.md, quoted verbatim in the
# module docstring above). This set is the completeness floor: any of these class_ids
# missing from the ledger is a defect the ledger's own JSON cannot self-report, so it
# is hardcoded here rather than trusted to the data file.
LAW_LISTED_CLASS_IDS = frozenset(
    {
        "VRAM_OOM",
        "COMMIT_CHARGE",
        "NATIVE_CRASH",
        "BF16_SILENT_FREEZE",
        "GOVERNED_ABORT_OBSERVABILITY",
        "SHARD_DIR_WIRING",
        "CRASH_SURVIVAL",
        "TEXT_LAB_DATA_AUTHORITY",
    }
)

# guard_ref syntax: a repo-relative file path, optionally followed by ":symbol" for a
# named function/class inside that file (python) or a bare test/manifest file path.
_GUARD_REF_RE = re.compile(
    r"^(?P<path>[^:]+\.(?:py|ts|json|md))(?::(?P<symbol>[A-Za-z_][A-Za-z0-9_]*))?$"
)

# Collectability-gate constants (dead-on-import false-CLOSE class, see module docstring
# amendment below). A CLOSED_GUARDED row's guard_ref bytes existing is NOT sufficient
# proof the guard can regression-guard anything -> a test file whose bytes resolve but
# whose collection dies on import (module-scope SystemExit / an unrelated import chain
# frozen out by a later commit) must never count as closed.
_COLLECTABILITY_TIMEOUT_S = 120
_TEST_PATH_RE = re.compile(r".*test.*\.py$", re.IGNORECASE)


def _is_test_guard_path(rel_path: str) -> bool:
    """True when a guard_ref path names a test file (collectability-gate scope).
    Non-test guard_refs (validator modules like census.py:symbol) are out of scope for
    this gate and keep the prior bytes+symbol-only behavior."""
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("tests/"):
        return True
    if "/test" in normalized:
        return True
    basename = normalized.rsplit("/", 1)[-1]
    return bool(_TEST_PATH_RE.match(basename))


def check_collectability(
    repo_root: Path, rel_path: str, symbol: str | None = None
) -> tuple[bool, str]:
    """Bounded `pytest --collect-only` probe on a single test file. Returns
    (collectable, reason-if-not). Never raises on ordinary probe failure - a timeout or
    an unexpected exception is itself treated as non-collectable (fail-closed), never
    silently accepted as collectable.

    When `symbol` is given (a guard_ref of the form `file.py:symbol`), the probe is
    not satisfied merely by the FILE collecting: a collected pytest test node whose
    LEAF name (the final `::` component, parametrization suffix stripped) equals
    `symbol` must exist. This closes the symbol-granularity false-CLOSE class (a cited
    helper / non-test def, or a selectively-uncollectable test, in a file whose OTHER
    tests collect fine). The leaf match - rather than a bare `file::symbol` nodeid -
    is deliberate: a real test that is a class method collects as
    `file::Class::method`, so a bare-symbol nodeid would false-BLOCK it; the leaf of
    that nodeid is still `method`, which the cited symbol correctly matches."""
    full_path = repo_root / rel_path
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(full_path), "--collect-only", "-q"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_COLLECTABILITY_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"collect-only probe timed out after {_COLLECTABILITY_TIMEOUT_S}s"
    except OSError as exc:
        return False, f"collect-only probe could not be started: {exc}"

    combined = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode != 0:
        first_line = next(
            (line for line in combined.splitlines() if line.strip()), "(no output)"
        )
        return False, f"collect-only exited {proc.returncode} -> {first_line.strip()}"
    if "INTERNALERROR" in combined:
        first_line = next(
            (line for line in combined.splitlines() if "INTERNALERROR" in line),
            "INTERNALERROR",
        )
        return False, first_line.strip()
    if "SystemExit" in combined:
        first_line = next(
            (line for line in combined.splitlines() if "SystemExit" in line),
            "SystemExit",
        )
        return False, first_line.strip()
    if "no tests collected" in combined and (
        "error" in combined.lower() or "INTERNALERROR" in combined
    ):
        first_line = next(
            (line for line in combined.splitlines() if line.strip()), "(no output)"
        )
        return False, first_line.strip()
    if symbol is not None:
        collected_leaves = set()
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if "::" in stripped:
                leaf = stripped.rsplit("::", 1)[-1].split("[", 1)[0].strip()
                if leaf:
                    collected_leaves.add(leaf)
        if symbol not in collected_leaves:
            return (
                False,
                f"cited test symbol {symbol!r} is not a collected pytest test node "
                "(helper/non-test/uncollectable; the file collects other tests)",
            )
    return True, ""


class LedgerLoadError(Exception):
    """Raised when the ledger file cannot be loaded at all (missing/malformed)."""


def _red(errors: list[str], **extra: Any) -> dict[str, Any]:
    verdict: dict[str, Any] = {
        "schema": VERDICT_SCHEMA,
        "ok": False,
        "verdict": "RED",
        "errors": errors,
    }
    verdict.update(extra)
    return verdict


def load_ledger(path: Path) -> dict[str, Any]:
    """Fail-closed load. Missing file or malformed JSON -> LedgerLoadError, never a
    silently-empty structure."""
    if not path.is_file():
        raise LedgerLoadError(f"ledger file missing: {path}")
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise LedgerLoadError(f"ledger file is empty: {path}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LedgerLoadError(
            f"ledger file is malformed JSON at {path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise LedgerLoadError(f"ledger top-level value must be an object: {path}")
    return data


def resolve_guard_ref(repo_root: Path, guard_ref: str) -> tuple[bool, str]:
    """Resolve a guard_ref to real in-repo bytes. Returns (ok, reason-if-not-ok)."""
    match = _GUARD_REF_RE.match(guard_ref)
    if not match:
        return False, f"malformed guard_ref syntax: {guard_ref!r}"
    rel_path = match.group("path")
    symbol = match.group("symbol")
    full_path = repo_root / rel_path
    try:
        full_path_resolved = full_path.resolve()
        full_path_resolved.relative_to(repo_root.resolve())
    except ValueError:
        return False, f"guard_ref escapes repo root: {guard_ref!r}"
    if not full_path.is_file():
        return False, f"guard_ref path does not exist: {rel_path}"
    if symbol:
        text = full_path.read_text(encoding="utf-8", errors="replace")
        def_pattern = re.compile(
            rf"^\s*(?:async\s+)?def\s+{re.escape(symbol)}\b"
            rf"|^\s*class\s+{re.escape(symbol)}\b",
            re.MULTILINE,
        )
        if not def_pattern.search(text):
            return False, f"guard_ref symbol not found in {rel_path}: {symbol!r}"
    return True, ""


def validate_row(row: Any, repo_root: Path) -> tuple[list[str], dict[str, Any] | None]:
    """Validate a single ledger row. Returns (errors, normalized-row-or-None)."""
    errors: list[str] = []
    if not isinstance(row, dict):
        return [f"ledger row is not an object: {row!r}"], None

    unknown_keys = set(row.keys()) - ALLOWED_KEYS
    if unknown_keys:
        errors.append(f"row has unknown keys (closed schema): {sorted(unknown_keys)}")

    missing_keys = REQUIRED_BASE_KEYS - set(row.keys())
    if missing_keys:
        errors.append(f"row missing required keys: {sorted(missing_keys)}")
        # Cannot safely continue validating this row's state-specific rules.
        return errors, None

    class_id = row.get("class_id")
    state = row.get("state")
    if not isinstance(class_id, str) or not class_id:
        errors.append(f"class_id must be a non-empty string: {class_id!r}")
    if state not in VALID_STATES:
        errors.append(
            f"class {class_id!r}: state must be one of {sorted(VALID_STATES)}, got {state!r}"
        )
        return errors, None

    if state == STATE_CLOSED_GUARDED:
        if "blocking_reason" in row:
            errors.append(
                f"class {class_id!r}: CLOSED_GUARDED row must not carry blocking_reason"
            )
        guard_ref = row.get("guard_ref")
        guard_kind = row.get("guard_kind")
        if not isinstance(guard_ref, str) or not guard_ref:
            errors.append(
                f"class {class_id!r}: CLOSED_GUARDED requires a non-empty guard_ref"
            )
        if guard_kind not in VALID_GUARD_KINDS:
            errors.append(
                f"class {class_id!r}: CLOSED_GUARDED requires guard_kind in "
                f"{sorted(VALID_GUARD_KINDS)}, got {guard_kind!r}"
            )
        if isinstance(guard_ref, str) and guard_ref:
            ok, reason = resolve_guard_ref(repo_root, guard_ref)
            if not ok:
                errors.append(f"class {class_id!r}: dangling guard_ref -> {reason}")
            else:
                match = _GUARD_REF_RE.match(guard_ref)
                rel_path = match.group("path") if match else guard_ref
                symbol = match.group("symbol") if match else None
                if _is_test_guard_path(rel_path):
                    collectable, dead_reason = check_collectability(
                        repo_root, rel_path, symbol
                    )
                    if not collectable:
                        errors.append(
                            f"class {class_id!r}: guard test not collectable "
                            f"(dead-on-import or collection error) -> {dead_reason}"
                        )
    else:  # STATE_BLOCKING
        blocking_reason = row.get("blocking_reason")
        if not isinstance(blocking_reason, str) or not blocking_reason.strip():
            errors.append(
                f"class {class_id!r}: BLOCKING requires a non-empty blocking_reason"
            )
        if "guard_ref" in row or "guard_kind" in row:
            errors.append(
                f"class {class_id!r}: BLOCKING row must not carry guard_ref/guard_kind"
            )

    return errors, (row if not errors else None)


def verify(ledger_path: Path, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Run the full conjunct-3 verification. Never raises on ordinary bad input -
    callers get a structured RED verdict. Only truly unexpected errors propagate."""
    try:
        data = load_ledger(ledger_path)
    except LedgerLoadError as exc:
        return _red([str(exc)], ledger_path=str(ledger_path))

    if data.get("schema") != LEDGER_SCHEMA:
        return _red(
            [f"ledger schema mismatch: expected {LEDGER_SCHEMA!r}, got {data.get('schema')!r}"],
            ledger_path=str(ledger_path),
        )

    classes = data.get("classes")
    if not isinstance(classes, list) or not classes:
        return _red(
            ["ledger 'classes' must be a non-empty array"],
            ledger_path=str(ledger_path),
        )

    errors: list[str] = []
    seen_ids: set[str] = set()
    closed_guarded: list[str] = []
    blocking: list[str] = []

    for row in classes:
        row_errors, normalized = validate_row(row, repo_root)
        if row_errors:
            errors.extend(row_errors)
            continue
        assert normalized is not None
        class_id = normalized["class_id"]
        if class_id in seen_ids:
            errors.append(f"duplicate class_id in ledger: {class_id!r}")
            continue
        seen_ids.add(class_id)
        if normalized["state"] == STATE_CLOSED_GUARDED:
            closed_guarded.append(class_id)
        else:
            blocking.append(class_id)

    missing_law_classes = sorted(LAW_LISTED_CLASS_IDS - seen_ids)
    if missing_law_classes:
        errors.append(
            "completeness cross-check FAILED: law-listed birth-relevant class(es) "
            f"absent from ledger: {missing_law_classes}"
        )

    if errors:
        return _red(
            errors,
            ledger_path=str(ledger_path),
            classes_checked=len(classes),
        )

    result: dict[str, Any] = {
        "schema": VERDICT_SCHEMA,
        "ledger_path": str(ledger_path),
        "classes_checked": len(classes),
        "closed_guarded": sorted(closed_guarded),
        "blocking": sorted(blocking),
        "errors": [],
    }

    if blocking:
        result["ok"] = False
        result["verdict"] = "BLOCKED"
        return result

    result["ok"] = True
    result["verdict"] = "CLOSED"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help="Path to the c0 failure-class ledger JSON file.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repo root guard_ref paths resolve against.",
    )
    parser.add_argument(
        "--require-non-red",
        action="store_true",
        help=(
            "Exit zero for a structurally valid BLOCKED or CLOSED ledger; "
            "continue to reject RED. This does not convert BLOCKED into CLOSED."
        ),
    )
    args = parser.parse_args(argv)

    verdict = verify(args.ledger, args.repo_root)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    if args.require_non_red:
        return 0 if verdict["verdict"] in {"BLOCKED", "CLOSED"} else 1
    return 0 if verdict["verdict"] == "CLOSED" else 1


if __name__ == "__main__":
    sys.exit(main())
