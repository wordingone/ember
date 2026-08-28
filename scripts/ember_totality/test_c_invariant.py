#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Totality status-probe for Ember goal condition C-INV (constitutional invariant).

Condition (from docs/domains/governance/authority/GOAL.md §9, docs/authority/INVARIANT.md binds):

  C-INV — Invariant persists, stamped, and unchained in every post-genesis artifact.
  Invariant file exists and hashes correctly; docs/domains/governance/authority/GOAL.md pins the hash; all post-genesis
  manifests and receipts carry the invariant_sha256 stamp. If docs/authority/INVARIANT.md is missing,
  this is a BREACH, not UNEVALUABLE — the receipt is written anyway with
  invariant_breach:true, complete:false.

This file is a STATUS PROBE. Execution:
  - Asserts invariant file exists and hashes correctly
  - Asserts docs/domains/governance/authority/GOAL.md pin is present
  - Asserts post-genesis receipts are stamped
  - Prints "RED <reason>" or "GREEN <reason>" and exits 0
  - On MISSING FILE: prints "RED invariant_breach" with receipt written

Run: python3 <this file>
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

# Compute repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_env_root = os.environ.get("EMBER_TOTALITY_ROOT")
ROOT = next(
    (p for p in (Path(_env_root) if _env_root else None, REPO_ROOT)
     if p is not None and p.is_dir()),
    REPO_ROOT,
)

RECEIPTS = ROOT / "receipts"
INVARIANT_FILE = ROOT / "docs/authority/INVARIANT.md"
GOAL_FILE = ROOT / "docs/domains/governance/authority/GOAL.md"

# The canonical invariant hash
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"

# [PROBE-HARDEN cure] Genesis boundary for the post-genesis stamp scan below.
# Same value as scripts/receipt_check.py's GENESIS_TS (committerDate of the
# genesis merge commit 9c89f7f66, "genesis: entrench constitutional invariant
# (#281)") -- duplicated rather than imported, matching the existing
# scripts/test_receipt_check_invariant.py precedent of a standalone constant
# so this probe stays self-contained (test_c11.py-style: no cross-script
# import chain for a status probe).
GENESIS_TS = "2026-07-06T14:13:23-07:00"

# [ERRATA cure, gh issue #612, FROZEN SPEC] Append-only historical-defect annex:
# docs/ledgers/receipt-errata.jsonl. One row per pre-hardening post-genesis receipt that
# lacks (or mismatches) the invariant_sha256 stamp -- discovered by the #608
# hardening scan, recorded rather than retro-stamped (refs #482, receipts are
# append-only; landed receipt bytes are never touched).
ERRATA_FILE = ROOT / "docs" / "ledgers" / "receipt-errata.jsonl"

# [ERRATA cure, gh issue #612 point 3, FROZEN SPEC] Hard cutoff: the #608
# hardening merge's own committer-date timestamp (sha 411d35e5, "fix:
# probe-harden C-GROW/C-INV vocabulary gaps + totality ts self-stamp (#608)").
# Errata coverage is CLOSED to any receipt whose OWN `ts` is AFTER this
# constant -- the annex is a historical record, never an ongoing bypass.
ERRATA_CUTOFF_TS = "2026-07-10T00:08:35Z"

# [SUPERSESSION cure, gh issue #625, FROZEN SPEC point 2] Append-only tracked
# file mapping an unstamped post-cutoff receipt to its re-executed, correctly
# stamped replacement. Stamp-coverage accounting ONLY -- never alters, hides,
# or re-scores any verdict content anywhere; the superseded receipt's content
# remains landed history, never edited or deleted (refs #482 append-only
# convention, same as the errata annex).
SUPERSESSIONS_FILE = ROOT / "docs" / "ledgers" / "receipt-supersessions.jsonl"

# Invalid tokens for this condition
INVALID_TOKENS = [
    "invariant_breach",  # docs/authority/INVARIANT.md missing or hash wrong
    "invariant_unstamped_receipt",  # post-genesis receipt lacks stamp
    "invariant_errata_chain_broken",  # errata sha chain invalid
]

# [ERRATA cure, gh issue #612] Coverage counts from the most recent
# check_stamped_receipts() run, stashed here so write_receipt() can disclose
# stamped / errata_covered / uncovered counts on the C-INV rerun receipt
# without changing the uniform (bool, str) contract every check_* function in
# `main()`'s checks list shares. Set only by check_stamped_receipts(); read
# only by write_receipt(). None until check_stamped_receipts() has run once.
_LAST_STAMP_COUNTS: Optional[Dict[str, Any]] = None


def read_invariant_bytes() -> Optional[bytes]:
    """Read docs/authority/INVARIANT.md bytes if it exists."""
    if not INVARIANT_FILE.exists():
        return None
    return INVARIANT_FILE.read_bytes()


def compute_hash(data: bytes) -> str:
    """Compute sha256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def check_invariant_file() -> tuple[bool, str]:
    """Check that docs/authority/INVARIANT.md exists and hashes correctly.

    Returns:
        (success: bool, reason: str)
    """
    inv_bytes = read_invariant_bytes()
    if inv_bytes is None:
        return False, "docs/authority/INVARIANT.md missing"

    computed = compute_hash(inv_bytes)
    if computed != INVARIANT_SHA256:
        return False, f"docs/authority/INVARIANT.md hash mismatch: {computed[:16]}... != {INVARIANT_SHA256[:16]}..."

    return True, f"docs/authority/INVARIANT.md present and correct"


def check_goal_pin() -> tuple[bool, str]:
    """Check that docs/domains/governance/authority/GOAL.md pins the invariant hash.

    Returns:
        (success: bool, reason: str)
    """
    if not GOAL_FILE.exists():
        return False, "docs/domains/governance/authority/GOAL.md missing"

    goal_text = GOAL_FILE.read_text(encoding="utf-8")
    pins = re.findall(
        r'(?im)^\s*(?:"invariant_sha256"|invariant_sha256)\s*:\s*'
        r'"?([0-9a-f]{64})"?\s*,?\s*$',
        goal_text,
    )

    if not pins:
        return False, "docs/domains/governance/authority/GOAL.md missing invariant_sha256 pin"

    if len(pins) != 1:
        return False, f"docs/domains/governance/authority/GOAL.md must contain exactly one invariant_sha256 pin, found {len(pins)}"

    if pins[0].lower() != INVARIANT_SHA256:
        return False, f"docs/domains/governance/authority/GOAL.md pin does not match canonical hash"

    return True, "docs/domains/governance/authority/GOAL.md pin present and correct"


def _parse_receipt_ts(ts: Any) -> Optional[float]:
    """Parse a receipt's `ts` field to epoch seconds under BOTH conventions
    actually found on disk across receipts/: dash-ISO8601 (with or without a
    fractional-seconds component, e.g. "2026-07-07T02:56:47Z" or
    "2026-07-07T01:49:30.546657Z") and the compact form used by the
    developmental-duration milestones (test_c11.py's TS_FMT,
    e.g. "20260707T053613Z"). Returns None on anything unparseable -- an
    unparseable ts is NEVER treated as a passing stamp check, it is simply
    excluded from the post-genesis population (mirrors scripts/receipt_check.py's
    _parse_ts: other schema rules own malformed timestamps, not this probe)."""
    if not isinstance(ts, str):
        return None
    t = ts.strip()
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    try:
        return datetime.strptime(t, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _load_errata_coverage(cutoff_epoch: float) -> tuple[Dict[str, Dict[str, Any]], list[str]]:
    """[ERRATA cure, gh issue #612] Load docs/ledgers/receipt-errata.jsonl (if it
    exists) into a {receipt_path: row} map. A row only counts as coverage if
    it parses as a JSON object, carries a non-empty `receipt_path`, and its
    own `discovered_ts` parses and predates-or-equals ERRATA_CUTOFF_TS (issue
    #612 point 2/3: discovery via the #608 hardening scan is itself bounded
    by the same cutoff that governs which receipts are eligible at all).
    Malformed or out-of-bound rows are never silently trusted as coverage --
    they are skipped and returned in `skipped` for disclosure, same posture
    as check_errata_structure's honest-absent/honest-empty branches above.

    Returns:
        (coverage: {receipt_path: row}, skipped: [description, ...])
    """
    coverage: Dict[str, Dict[str, Any]] = {}
    skipped: list[str] = []
    if not ERRATA_FILE.exists():
        return coverage, skipped

    with ERRATA_FILE.open("r", encoding="utf-8", errors="ignore") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                skipped.append(f"line {lineno}: malformed JSON ({exc})")
                continue
            if not isinstance(row, dict):
                skipped.append(f"line {lineno}: not a JSON object")
                continue
            receipt_path = row.get("receipt_path")
            if not isinstance(receipt_path, str) or not receipt_path:
                skipped.append(f"line {lineno}: missing/empty receipt_path")
                continue
            discovered_epoch = _parse_receipt_ts(row.get("discovered_ts"))
            if discovered_epoch is None:
                skipped.append(f"line {lineno} ({receipt_path}): unparseable discovered_ts")
                continue
            if discovered_epoch > cutoff_epoch:
                skipped.append(
                    f"line {lineno} ({receipt_path}): discovered_ts is after "
                    "the hardening cutoff -- not admissible coverage"
                )
                continue
            coverage[receipt_path] = row

    return coverage, skipped


def _leg_class_identity(d: Dict[str, Any]) -> Optional[str]:
    """[SUPERSESSION cure, gh issue #625, FROZEN SPEC point 2] Stable identity
    string for "is this a re-execution of the same leg class" -- the probe
    check a supersession row must satisfy before it counts as coverage.

    Preference order, first available wins:
      1. receipt_class + leg (IND-3/4/5 producer shape, e.g. "IND-4:customize")
      2. ticket (e.g. loop_econ_gate.py's "DT6-LOOP-ECON-GATE-SELFTEST")
      3. None -- no identity field present; caller must NOT treat this as a
         match (an absent identity on either side fails closed, never a
         wildcard match).
    """
    if "receipt_class" in d:
        return f"{d.get('receipt_class')}:{d.get('leg', '')}"
    if "ticket" in d:
        return f"ticket:{d.get('ticket')}"
    return None


def _load_supersessions() -> tuple[Dict[str, Dict[str, Any]], list[str]]:
    """[SUPERSESSION cure, gh issue #625, FROZEN SPEC point 2] Load
    docs/ledgers/receipt-supersessions.jsonl (if it exists) into a
    {old_path: row} map. Malformed rows are never silently trusted -- they
    are skipped and returned in `skipped` for disclosure (same posture as
    _load_errata_coverage).

    Returns:
        (supersessions: {old_path: row}, skipped: [description, ...])
    """
    supersessions: Dict[str, Dict[str, Any]] = {}
    skipped: list[str] = []
    if not SUPERSESSIONS_FILE.exists():
        return supersessions, skipped

    with SUPERSESSIONS_FILE.open("r", encoding="utf-8", errors="ignore") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                skipped.append(f"line {lineno}: malformed JSON ({exc})")
                continue
            if not isinstance(row, dict):
                skipped.append(f"line {lineno}: not a JSON object")
                continue
            old_path = row.get("old_path")
            new_path = row.get("new_path")
            if not isinstance(old_path, str) or not old_path:
                skipped.append(f"line {lineno}: missing/empty old_path")
                continue
            if not isinstance(new_path, str) or not new_path:
                skipped.append(f"line {lineno} ({old_path}): missing/empty new_path")
                continue
            supersessions[old_path] = row

    return supersessions, skipped


def _supersession_covers(old_rel_path: str, old_data: Dict[str, Any],
                          row: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """[SUPERSESSION cure, gh issue #625, FROZEN SPEC point 2, LAUNDERING
    GUARD] A supersession row counts as coverage iff the row's `new_path`
    (a) exists, (b) is correctly stamped, and (c) is a re-execution of the
    SAME leg class as the old receipt. Any failure of (a)/(b)/(c) means the
    row does NOT count -- a supersession row pointing at a missing,
    unstamped, or different-class target is exactly the laundering shape
    this guard exists to reject.

    Returns:
        (covered: bool, reason_if_not: str | None)
    """
    new_rel = row.get("new_path")
    new_path = ROOT / new_rel
    if not new_path.is_file():
        return False, f"new_path {new_rel!r} does not exist"

    try:
        with new_path.open("r", encoding="utf-8", errors="ignore") as fh:
            new_data = json.load(fh)
    except Exception as exc:
        return False, f"new_path {new_rel!r} is not valid JSON ({exc})"
    if not isinstance(new_data, dict):
        return False, f"new_path {new_rel!r} is not a JSON object"

    if new_data.get("invariant_sha256") != INVARIANT_SHA256:
        return False, f"new_path {new_rel!r} is not correctly stamped"

    old_identity = _leg_class_identity(old_data)
    new_identity = _leg_class_identity(new_data)
    if old_identity is None or new_identity is None or old_identity != new_identity:
        return False, (
            f"leg/class identity mismatch: old={old_identity!r} "
            f"({old_rel_path}) vs new={new_identity!r} ({new_rel})"
        )

    return True, None


def check_stamped_receipts() -> tuple[bool, str]:
    """Check that every POST-GENESIS receipt under receipts/ carries the
    correct invariant_sha256 stamp -- OR is covered by the docs/receipt-
    errata.jsonl annex, bounded by ERRATA_CUTOFF_TS.

    [PROBE-HARDEN cure, coordinator code-read audit] This replaces the prior
    unconditional-True genesis stub ("this clause becomes active in later
    board runs" -- it never did; board runs kept passing genesis unmodified).
    Execution-binding per test_c11.py's pattern: every JSON file actually on
    disk under receipts/ (recursive) is opened and its bytes parsed; nothing
    is asserted from a hardcoded verdict. This mirrors scripts/receipt_check.py's
    R4 rule (same GENESIS_TS/INVARIANT_SHA256 constants) but is re-implemented
    here directly (not imported) so the status probe stays self-contained,
    matching test_c11.py's no-cross-import convention.

    [ERRATA cure, gh issue #612, FROZEN SPEC point 2] A post-genesis receipt
    now passes iff (stamped AND stamp matches) OR (covered by an admissible
    errata row -- see _load_errata_coverage). [FROZEN SPEC point 3] Hard
    cutoff: a receipt whose own `ts` is AFTER ERRATA_CUTOFF_TS can NEVER be
    covered by errata -- it must carry a real stamp, or it is a genuine
    violation regardless of any errata row naming it. [FROZEN SPEC point 5]
    Wince guard: this is exactly what makes a future post-cutoff unstamped
    receipt RED C-INV regardless of errata coverage elsewhere -- the errata
    annex is a historical annex, never an ongoing bypass.

    [SUPERSESSION cure, gh issue #625, FROZEN SPEC point 2] A post-cutoff
    unstamped receipt (ineligible for errata coverage above) may instead be
    covered by a docs/ledgers/receipt-supersessions.jsonl row -- STAMP-COVERAGE
    ACCOUNTING ONLY, never a verdict-content change, and only when
    _supersession_covers() confirms the row's new_path exists, is correctly
    stamped, and is a re-execution of the same leg class (the laundering
    guard: a row failing any of those three stays uncovered).

    Returns:
        (success: bool, reason: str)
    """
    if not RECEIPTS.exists():
        # Genuinely nothing to scan -- this is a real state check, not an
        # assumed pass.
        return True, "receipts/ does not exist yet -- nothing to scan"

    genesis_epoch = _parse_receipt_ts(GENESIS_TS)
    cutoff_epoch = _parse_receipt_ts(ERRATA_CUTOFF_TS)
    errata_coverage, errata_skipped = _load_errata_coverage(cutoff_epoch)
    supersessions, supersessions_skipped = _load_supersessions()

    scanned = 0
    post_genesis = 0
    stamped = 0
    errata_covered = 0
    superseded = 0
    uncovered_pre_cutoff: list[str] = []
    uncovered_post_cutoff: list[str] = []
    for path in sorted(RECEIPTS.rglob("*.json")):
        if not path.is_file():
            continue
        scanned += 1
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                d = json.load(fh)
        except Exception:
            # Malformed JSON is receipt_check.py's schema-floor concern, not
            # this invariant-stamp probe's -- never silently counted as a pass.
            continue
        if not isinstance(d, dict):
            continue
        receipt_epoch = _parse_receipt_ts(d.get("ts"))
        if receipt_epoch is None or receipt_epoch < genesis_epoch:
            continue
        post_genesis += 1
        rel_path = path.relative_to(ROOT).as_posix()
        stamp_val = d.get("invariant_sha256")
        if stamp_val == INVARIANT_SHA256:
            stamped += 1
            continue
        offender = f"{rel_path} (ts={d.get('ts')!r}, invariant_sha256={stamp_val!r})"
        if receipt_epoch > cutoff_epoch:
            # Post-cutoff: errata coverage is CLOSED. The ONLY other cure is
            # a laundering-guarded supersession row -- anything else is a
            # genuine violation regardless of any row naming it.
            row = supersessions.get(rel_path)
            if row is not None:
                covered, reason = _supersession_covers(rel_path, d, row)
                if covered:
                    superseded += 1
                    continue
                offender = f"{offender} [supersession row present but REJECTED: {reason}]"
            uncovered_post_cutoff.append(offender)
            continue
        if rel_path in errata_coverage:
            errata_covered += 1
            continue
        uncovered_pre_cutoff.append(offender)

    violations = uncovered_post_cutoff + uncovered_pre_cutoff
    global _LAST_STAMP_COUNTS
    _LAST_STAMP_COUNTS = {
        "post_genesis_scanned": post_genesis,
        "stamped": stamped,
        "errata_covered": errata_covered,
        "superseded": superseded,
        "uncovered_pre_cutoff": len(uncovered_pre_cutoff),
        "uncovered_post_cutoff": len(uncovered_post_cutoff),
        "errata_rows_skipped": len(errata_skipped),
        "supersession_rows_skipped": len(supersessions_skipped),
    }

    if violations:
        return False, (
            f"{len(violations)}/{post_genesis} post-genesis receipt(s) missing/"
            f"mismatched invariant_sha256 stamp and not errata-covered (of "
            f"{scanned} receipts scanned under receipts/; stamped={stamped}, "
            f"errata_covered={errata_covered}, superseded={superseded}, "
            f"uncovered_pre_cutoff={len(uncovered_pre_cutoff)}, "
            f"uncovered_post_cutoff={len(uncovered_post_cutoff)}); "
            f"first offenders: {violations[:3]}"
        )

    return True, (
        f"{post_genesis} post-genesis receipt(s) checked (of {scanned} receipts "
        f"scanned under receipts/): stamped={stamped}, errata_covered="
        f"{errata_covered}, superseded={superseded}, all pass (0 uncovered)"
    )


def _errata_append_only_violation(errata_file: Path) -> Optional[str]:
    """Return a violation description if `errata_file`'s own git history shows
    a commit that removed or rewrote a previously-committed line (receipts are
    append-only, refs #482). Returns None if the history is clean append-only,
    or if the file has no commit history yet to judge (a brand-new
    uncommitted file is not itself a violation).

    This shells out to `git log -p` on the file's own path -- read-only,
    scoped to this one path, never touching any other repo state. Sandbox-
    verified against a disposable temp git repo before wiring in: a clean
    two-commit append-only history produced zero '-' hunks, and a third commit
    that rewrote an already-committed line was caught as a '-' hunk.
    """
    try:
        rel = errata_file.relative_to(ROOT).as_posix()
    except ValueError:
        rel = str(errata_file)
    try:
        result = subprocess.run(
            ["git", "log", "--follow", "-p", "--format=COMMIT %H", "--", rel],
            cwd=str(ROOT), capture_output=True, text=True, timeout=15,
        )
    except Exception as exc:
        return f"could not run 'git log' to verify append-only history: {exc}"
    if result.returncode != 0:
        # No git repo / no history for this path -- nothing committed yet to
        # judge against; a not-yet-committed file is not a chain violation.
        return None
    removed_lines = [
        line for line in result.stdout.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    if removed_lines:
        return (
            f"{len(removed_lines)} removed/rewritten line(s) found in "
            f"{rel}'s git history -> append-only property violated "
            f"(invariant_errata_chain_broken)"
        )
    return None


# [ERRATA cure, gh issue #612, FROZEN SPEC] Required non-empty string fields
# on every docs/ledgers/receipt-errata.jsonl row.
ERRATA_ROW_REQUIRED_FIELDS = (
    "defect", "discovered_ts", "discovery_source", "disposition", "note", "receipt_path",
)


def _errata_row_schema_violations(cutoff_epoch: float) -> list[str]:
    """[ERRATA cure, gh issue #625 point 3, FROZEN SPEC] Row-by-row schema
    validation of ERRATA_FILE (docs/ledgers/receipt-errata.jsonl): every non-blank
    line must parse as a JSON object carrying every field in
    ERRATA_ROW_REQUIRED_FIELDS as a non-empty string, and no row's own
    `discovered_ts` may be strictly after ERRATA_CUTOFF_TS -- the annex is a
    historical record of the #608 hardening scan, never a live/ongoing filing
    surface (same cutoff _load_errata_coverage already enforces for coverage
    eligibility; this enforces it structurally on the file itself, so an
    unused-for-coverage post-cutoff row cannot silently sit in the annex).

    Returns a list of violation description strings (empty = clean).
    """
    violations: list[str] = []
    if not ERRATA_FILE.exists():
        return violations
    with ERRATA_FILE.open("r", encoding="utf-8", errors="ignore") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                violations.append(f"line {lineno}: malformed JSON ({exc})")
                continue
            if not isinstance(row, dict):
                violations.append(f"line {lineno}: not a JSON object")
                continue
            missing = [f for f in ERRATA_ROW_REQUIRED_FIELDS
                       if not isinstance(row.get(f), str) or not row.get(f)]
            if missing:
                violations.append(f"line {lineno}: missing/empty field(s) {missing}")
                continue
            discovered_epoch = _parse_receipt_ts(row.get("discovered_ts"))
            if discovered_epoch is None:
                violations.append(f"line {lineno}: unparseable discovered_ts")
                continue
            if discovered_epoch > cutoff_epoch:
                violations.append(
                    f"line {lineno} ({row.get('receipt_path')}): discovered_ts "
                    "is after the hard cutoff -- the annex is historical-only, "
                    "never an ongoing bypass"
                )
    return violations


def check_errata_structure() -> tuple[bool, str]:
    """[ERRATA cure, gh issue #625 point 3, FROZEN SPEC] Check that
    docs/ledgers/receipt-errata.jsonl -- the REAL errata file _load_errata_coverage()
    reads for coverage lookups (gh issue #612) -- is genuinely append-only,
    schema-conformant per ERRATA_ROW_REQUIRED_FIELDS, and carries no row whose
    own `discovered_ts` postdates the hard cutoff.

    [PROBE-HARDEN cure, PR #623 finding] This repoints the prior check away
    from INVARIANT-ERRATA.md -- a filename that was never created anywhere in
    this repo's history; the check was a structurally-untestable stub against
    a file that could never exist. docs/ledgers/receipt-errata.jsonl is the file that
    actually carries the historical annex.

    Returns:
        (success: bool, reason: str)
    """
    if not ERRATA_FILE.exists():
        return True, f"{ERRATA_FILE.name} does not exist -- no errata filed yet"

    errata_text = ERRATA_FILE.read_text(encoding="utf-8", errors="ignore")
    if not errata_text.strip():
        return True, f"{ERRATA_FILE.name} exists and is empty -- no errata filed yet"

    cutoff_epoch = _parse_receipt_ts(ERRATA_CUTOFF_TS)
    schema_violations = _errata_row_schema_violations(cutoff_epoch)
    if schema_violations:
        return False, (
            f"{len(schema_violations)} schema violation(s) in {ERRATA_FILE.name}: "
            f"{schema_violations[:3]}"
        )

    violation = _errata_append_only_violation(ERRATA_FILE)
    if violation:
        return False, violation

    return True, (
        f"{ERRATA_FILE.name} present, non-empty, schema-conformant, and "
        "append-only per git history"
    )


def write_receipt(status: str, reason: str, breach: bool = False) -> str:
    """Write timestamped C-INV receipt to scripts/ember_totality/receipts-c-invariant/<ts>.json.

    The genesis snapshot at receipts/c-invariant-probe.json stays frozen (never rewritten).
    All board runs write fresh timestamped receipts to scripts/ember_totality/receipts-c-invariant/
    (outside the canonical receipts/ tree, mirroring receipts-totality/ pattern).

    Returns:
        Path to the written timestamped receipt file (repo-relative).

    Args:
        status: "GREEN" or "RED"
        reason: Human-readable reason
        breach: If True, sets invariant_breach:true and complete:false
    """
    # Create scripts/ember_totality/receipts-c-invariant directory for timestamped receipts
    # (outside canonical receipts/ tree to avoid C-CUSTODY probe conflicts)
    script_dir = Path(__file__).resolve().parent
    c_inv_dir = script_dir / "receipts-c-invariant"
    c_inv_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "probe": "c_invariant",
        "condition": "C-INV",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": status,
        "reason": reason,
        "invariant_sha256": INVARIANT_SHA256,
        "invariant_file_hash": compute_hash(read_invariant_bytes()) if read_invariant_bytes() else None,
    }

    # [ERRATA cure, gh issue #612 point 4, FROZEN SPEC] Disclose stamp/errata
    # coverage counts on every receipt this probe writes, whenever
    # check_stamped_receipts() has run (it always has, by the time main()
    # calls write_receipt -- see the `checks` list order). Coverage is
    # visible, never silent.
    if _LAST_STAMP_COUNTS is not None:
        receipt["stamp_coverage"] = dict(_LAST_STAMP_COUNTS)

    # Add breach marker if this is a missing-file / wrong-hash situation
    if breach:
        receipt["invariant_breach"] = True
        receipt["complete"] = False
    else:
        receipt["complete"] = status == "GREEN"

    # Write timestamped receipt to scripts/ember_totality/receipts-c-invariant/c-invariant-probe-<ts>.json
    receipt_path = c_inv_dir / f"c-invariant-probe-{ts}.json"
    with receipt_path.open("w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
        f.write("\n")

    # Return repo-relative path for board receipt
    return f"scripts/ember_totality/receipts-c-invariant/c-invariant-probe-{ts}.json"


def main():
    """Run C-INV status probe."""
    checks = [
        ("docs/authority/INVARIANT.md file & hash", check_invariant_file),
        ("docs/domains/governance/authority/GOAL.md pin", check_goal_pin),
        ("Stamped receipts", check_stamped_receipts),
        ("Errata structure", check_errata_structure),
    ]

    results = []
    for check_name, check_fn in checks:
        success, reason = check_fn()
        results.append((check_name, success, reason))
        if not success:
            # On any failure, write breach receipt and exit
            write_receipt("RED", f"{check_name}: {reason}", breach=True)
            print(f"RED invariant_breach: {check_name}: {reason}")
            sys.exit(0)

    # All checks passed
    write_receipt("GREEN", "all invariant checks pass")
    print("GREEN invariant complete")
    sys.exit(0)


if __name__ == "__main__":
    main()
