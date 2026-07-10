#!/usr/bin/env python3
"""Totality status-probe for Ember goal condition C-INV (constitutional invariant).

Condition (from GOAL.md §9, INVARIANT.md binds):

  C-INV — Invariant persists, stamped, and unchained in every post-genesis artifact.
  Invariant file exists and hashes correctly; GOAL.md pins the hash; all post-genesis
  manifests and receipts carry the invariant_sha256 stamp. If INVARIANT.md is missing,
  this is a BREACH, not UNEVALUABLE — the receipt is written anyway with
  invariant_breach:true, complete:false.

This file is a STATUS PROBE. Execution:
  - Asserts invariant file exists and hashes correctly
  - Asserts GOAL.md pin is present
  - Asserts post-genesis receipts are stamped
  - Prints "RED <reason>" or "GREEN <reason>" and exits 0
  - On MISSING FILE: prints "RED invariant_breach" with receipt written

Run: python3 <this file>
"""

from __future__ import annotations

import hashlib
import json
import os
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
INVARIANT_FILE = ROOT / "INVARIANT.md"
GOAL_FILE = ROOT / "GOAL.md"

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

# Invalid tokens for this condition
INVALID_TOKENS = [
    "invariant_breach",  # INVARIANT.md missing or hash wrong
    "invariant_unstamped_receipt",  # post-genesis receipt lacks stamp
    "invariant_errata_chain_broken",  # errata sha chain invalid
]


def read_invariant_bytes() -> Optional[bytes]:
    """Read INVARIANT.md bytes if it exists."""
    if not INVARIANT_FILE.exists():
        return None
    return INVARIANT_FILE.read_bytes()


def compute_hash(data: bytes) -> str:
    """Compute sha256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def check_invariant_file() -> tuple[bool, str]:
    """Check that INVARIANT.md exists and hashes correctly.

    Returns:
        (success: bool, reason: str)
    """
    inv_bytes = read_invariant_bytes()
    if inv_bytes is None:
        return False, "INVARIANT.md missing"

    computed = compute_hash(inv_bytes)
    if computed != INVARIANT_SHA256:
        return False, f"INVARIANT.md hash mismatch: {computed[:16]}... != {INVARIANT_SHA256[:16]}..."

    return True, f"INVARIANT.md present and correct"


def check_goal_pin() -> tuple[bool, str]:
    """Check that GOAL.md pins the invariant hash.

    Returns:
        (success: bool, reason: str)
    """
    if not GOAL_FILE.exists():
        return False, "GOAL.md missing"

    goal_text = GOAL_FILE.read_text()

    # Check for the pin line in §9
    if "invariant_sha256:" not in goal_text:
        return False, "GOAL.md missing invariant_sha256 pin"

    # Check that the pin value matches
    if INVARIANT_SHA256 not in goal_text:
        return False, f"GOAL.md pin does not match canonical hash"

    return True, "GOAL.md pin present and correct"


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


def check_stamped_receipts() -> tuple[bool, str]:
    """Check that every POST-GENESIS receipt under receipts/ carries the
    correct invariant_sha256 stamp.

    [PROBE-HARDEN cure, coordinator code-read audit] This replaces the prior
    unconditional-True genesis stub ("this clause becomes active in later
    board runs" -- it never did; board runs kept passing genesis unmodified).
    Execution-binding per test_c11.py's pattern: every JSON file actually on
    disk under receipts/ (recursive) is opened and its bytes parsed; nothing
    is asserted from a hardcoded verdict. A receipt whose `ts` resolves to at
    or after GENESIS_TS and that lacks invariant_sha256, or carries the wrong
    value, is a genuine invariant_unstamped_receipt violation -> RED. This
    mirrors scripts/receipt_check.py's R4 rule (same GENESIS_TS/INVARIANT_SHA256
    constants) but is re-implemented here directly (not imported) so the
    status probe stays self-contained, matching test_c11.py's no-cross-import
    convention.

    Returns:
        (success: bool, reason: str)
    """
    if not RECEIPTS.exists():
        # Genuinely nothing to scan -- this is a real state check, not an
        # assumed pass.
        return True, "receipts/ does not exist yet -- nothing to scan"

    genesis_epoch = _parse_receipt_ts(GENESIS_TS)

    scanned = 0
    post_genesis = 0
    violations: list[str] = []
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
        stamp_val = d.get("invariant_sha256")
        if stamp_val != INVARIANT_SHA256:
            violations.append(
                f"{path.relative_to(ROOT).as_posix()} (ts={d.get('ts')!r}, "
                f"invariant_sha256={stamp_val!r})"
            )

    if violations:
        return False, (
            f"{len(violations)}/{post_genesis} post-genesis receipt(s) missing/"
            f"mismatched invariant_sha256 stamp (of {scanned} receipts scanned "
            f"under receipts/); first offenders: {violations[:3]}"
        )

    return True, (
        f"{post_genesis} post-genesis receipt(s) checked (of {scanned} receipts "
        f"scanned under receipts/), all correctly stamped invariant_sha256"
    )


def _errata_append_only_violation(errata_file: Path) -> Optional[str]:
    """Return a violation description if INVARIANT-ERRATA.md's own git history
    shows a commit that removed or rewrote a previously-committed line
    (INVARIANT.md clause 6: "Errata are append-only"). Returns None if the
    history is clean append-only, or if the file has no commit history yet to
    judge (a brand-new uncommitted file is not itself a violation).

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
            f"INVARIANT-ERRATA.md's git history -> append-only property "
            f"violated (invariant_errata_chain_broken)"
        )
    return None


def check_errata_structure() -> tuple[bool, str]:
    """Check that INVARIANT-ERRATA.md, if it exists, is genuinely append-only.

    [PROBE-HARDEN cure] The prior stub returned True unconditionally even for
    a non-empty file ("we'd check append-only chaining here"). The absent and
    empty branches below are still True -- that is the honest state (no
    errata has ever been filed; verified: the file has never existed in this
    repo's history) -- but the non-empty branch now performs the real,
    execution-binding check instead of assuming it.

    Returns:
        (success: bool, reason: str)
    """
    errata_file = ROOT / "INVARIANT-ERRATA.md"
    if not errata_file.exists():
        return True, "INVARIANT-ERRATA.md does not exist -- no errata filed yet"

    errata_text = errata_file.read_text()
    if not errata_text.strip():
        return True, "INVARIANT-ERRATA.md exists and is empty -- no errata filed yet"

    violation = _errata_append_only_violation(errata_file)
    if violation:
        return False, violation

    return True, "INVARIANT-ERRATA.md present, non-empty, and append-only per git history"


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
        ("INVARIANT.md file & hash", check_invariant_file),
        ("GOAL.md pin", check_goal_pin),
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
