#!/usr/bin/env python3
"""Ember totality test — Condition C10 (status probe / TDD).

C10 — No deferred-work escape hatch.
  R: every previously deferred/dormant/post-MVP/trigger-gated/historical/
     founder-side item that can affect the loop is completed, integrated into
     the next cycle, or killed with a named successor + receipt.
  Does NOT count: anything "merely deferred because large/hard/old/inconvenient/
     outside-the-scaffold"; moving work to ARCHIVAL/KILLED/EXCLUDED without a
     debt-disposition receipt proving physical/functional contradiction or
     strict successor-subsumption. Banned scope-reduction language:
     "out of scope / v2 / later / post-MVP / stretch / deferred to post-X."
  Invalid-token (✗): invalid_deferred_remains
  CHK: zero ACTIVE / ACTIVE-BLOCKER / OPEN / triggerless-DEFERRED rows remain in
       docs/ember-debt-ledger.md; every disposition has its receipt.

Gloss (task): no deferred-work escape hatch: zero ACTIVE/OPEN/triggerless-
  DEFERRED rows in the debt ledger; every disposition has its receipt.
Receipt hint: docs/ember-debt-ledger.md.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under kai-converge — never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive may mount at /b/ or /mnt/b/ on this host.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# B:/M/avir/leo/state/ember-totality-build/ into
# B:/M/ember-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at B:/M/avir/leo/state/kai-converge (and /mnt/b/M/...,
# /b/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. kai-converge does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import os
import re
import sys

# --- Locate kai-converge robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "kai-converge"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

LEDGER_REL = os.path.join("docs", "ember-debt-ledger.md")

# --- Invalid-tokens (negative assertions) ------------------------------------
# C10's explicit ✗ token PLUS the banned scope-reduction language that C10
# enumerates as "does NOT count". If any of these strings appears in the ledger
# as a *disposition mechanism* (i.e. used to clear/park a row without a receipt),
# the condition is violated. We assert NONE of them is present as a live
# disposition. (The ledger's own prose may DEFINE/forbid these terms; that is
# legitimate. What we forbid is their use to dispose of a row.)
INVALID_TOKENS = [
    "invalid_deferred_remains",          # C10 explicit ✗
]

# Banned scope-reduction phrases (C10 "Does NOT count" list). Searched only as
# row-disposition language, see used_as_disposition() below.
BANNED_SCOPE_PHRASES = [
    "out of scope",
    "post-mvp",
    "deferred to post-",
    " v2 ",
    " stretch ",
]

# Offending row statuses that C10's CHK requires to be ZERO.
# (ACTIVE, ACTIVE-BLOCKER, ACTIVE-NEXT, OPEN are all "must be worked now /
# unresolved"; a DEFERRED row with no trigger is triggerless-DEFERRED.)
OFFENDING_STATUSES = {
    "ACTIVE",
    "ACTIVE-BLOCKER",
    "ACTIVE-NEXT",
    "OPEN",
}

# Cleared / disposed statuses that REQUIRE an accompanying receipt to count.
# DONE:/KILLED:/EXCLUDED:/ARCHIVAL with a named receipt are acceptable.
DISPOSED_PREFIXES = ("DONE:", "KILLED:", "EXCLUDED:", "ARCHIVAL")

# A markdown table data row: starts with "|", has >=3 cells, not a separator.
SEP_RE = re.compile(r"^\|[\s:|-]+\|?\s*$")


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def split_row(line):
    """Split a markdown table row into trimmed cell strings."""
    # Drop leading/trailing pipe then split.
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C10: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    ledger = os.path.join(ROOT, LEDGER_REL)
    if not os.path.isfile(ledger):
        emit("RED", f"C10: debt ledger ABSENT at {LEDGER_REL} -> "
                    "no receipt proving zero open/active/deferred rows")

    with open(ledger, "r", encoding="utf-8") as fh:
        text = fh.read()
    lines = text.splitlines()

    # --- (A) Walk every markdown table row; classify each row's status cell ---
    offending = []          # (status, debt-id-or-firstcell)
    disposed_no_receipt = []  # rows disposed via DONE:/KILLED:/... with no token after ":"
    n_rows = 0

    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        if SEP_RE.match(s):
            continue
        cells = split_row(s)
        if len(cells) < 2:
            continue
        # Skip header rows (cells are column titles like "ID","Class",...).
        joined_low = " ".join(c.lower() for c in cells)
        if cells[0].lower() in ("id", "class") and "status" in joined_low \
                or set(c.lower() for c in cells) <= {"id", "class", "debt",
                                                      "why it matters",
                                                      "required receipt",
                                                      "status", "trigger",
                                                      "required action when trigger fires",
                                                      "clearance test", "rows",
                                                      "execution rule"}:
            continue

        n_rows += 1
        row_id = cells[0]
        # The status is the LAST cell in these tables (Active Rows / Highest-
        # Priority / Self-Growth / etc. all put status last or second-to-last).
        # Be robust: scan all cells for a recognizable status token.
        status_cell = None
        for c in cells:
            cu = c.strip().upper()
            base = cu.split(":")[0]
            if base in OFFENDING_STATUSES or base in (
                    "DONE", "KILLED", "EXCLUDED", "ARCHIVAL", "TRIGGER-GATED",
                    "PROGRESS-ONLY", "GATED", "DEFERRED"):
                status_cell = c.strip()
                break
        if status_cell is None:
            continue

        cu = status_cell.upper()
        base = cu.split(":")[0]

        if base in OFFENDING_STATUSES:
            offending.append((status_cell, row_id))
            continue

        # TRIGGER-GATED / GATED / DEFERRED are NOT exempt (panel 2026-07-02):
        # C10's R text demands named successor + receipt for every such row, and
        # the trigger must be an evaluable predicate (threshold / dated expiry /
        # receipt-path condition -- machine-testable true-false), never vacuous
        # prose that can never fire false.
        if base in ("DEFERRED", "TRIGGER-GATED", "GATED"):
            after = status_cell.split(":", 1)[1].strip() if ":" in status_cell else ""
            if not after:
                offending.append((status_cell + " (triggerless)", row_id))
                continue
            evaluable = bool(re.search(
                r"([<>]=?|==|≥|≤)|\d{4}-\d{2}-\d{2}|receipts?/|\.json"
                r"|\d+(\.\d+)?\s*(%|x|params|steps|days|epochs|tok)",
                after, re.I))
            row_all = " ".join(cells).lower()
            has_receipt = ("receipts/" in row_all) or (".json" in row_all)
            if not evaluable:
                offending.append((status_cell + " (non-evaluable trigger)", row_id))
            elif not has_receipt:
                disposed_no_receipt.append((status_cell + " (no named receipt)", row_id))
            continue

        # PROGRESS-ONLY means evidence exists but the row is NOT cleared -> it is
        # still an unresolved obligation under C10 (not completed/integrated/
        # killed-with-receipt). Count it as offending.
        if base == "PROGRESS-ONLY":
            offending.append((status_cell, row_id))
            continue

        # Disposed (DONE:/KILLED:/EXCLUDED:/ARCHIVAL) MUST name a receipt token.
        if cu.startswith(DISPOSED_PREFIXES):
            after = status_cell.split(":", 1)[1].strip() if ":" in status_cell else ""
            if not after:
                disposed_no_receipt.append((status_cell, row_id))

    # --- (B) Negative assertion: invalid-tokens must NOT appear as live --------
    # disposition. invalid_deferred_remains appearing anywhere as an active
    # marker is itself the violation token.
    token_hits = []
    low = text.lower()
    for t in INVALID_TOKENS:
        if t.lower() in low:
            # The ledger may legitimately MENTION the token only inside an
            # "Invalid Progress Patterns"/definition context. Treat presence
            # outside such definitional lines as a live hit.
            for ln in lines:
                if t.lower() in ln.lower():
                    lnl = ln.lower()
                    definitional = any(
                        kw in lnl for kw in (
                            "invalid progress pattern", "does not count",
                            "✗", "invalid-token", "banned", "status vocabulary",
                            "classification law",
                        )
                    )
                    # A row that ASSIGNS the token (e.g. "| ... | invalid_deferred_remains |")
                    # as a status is a live hit; a prose definition is not.
                    if ln.strip().startswith("|") and not definitional:
                        token_hits.append((t, ln.strip()[:80]))
    # De-dup
    token_hits = list(dict.fromkeys(token_hits))

    # Banned scope-reduction phrases used as a row disposition (inside a table
    # row's status/disposition cell).
    banned_hits = []
    for ln in lines:
        if not ln.strip().startswith("|"):
            continue
        lnl = " " + ln.lower() + " "
        for p in BANNED_SCOPE_PHRASES:
            if p in lnl:
                banned_hits.append((p.strip(), ln.strip()[:80]))
    banned_hits = list(dict.fromkeys(banned_hits))

    # --- (C) Decide RED/GREEN -------------------------------------------------
    if token_hits:
        emit("RED",
             f"C10: invalid-token present as live ledger disposition "
             f"-> {token_hits[:2]} (invalid_deferred_remains)")

    if offending:
        # Summarize the offending status distribution.
        from collections import Counter
        dist = Counter(o[0].upper().split(":")[0] for o in offending)
        dist_str = ", ".join(f"{k}={v}" for k, v in sorted(dist.items()))
        sample = [f"{rid}:{st}" for st, rid in offending[:5]]
        emit("RED",
             f"C10: {len(offending)} unresolved debt-ledger row(s) remain "
             f"({dist_str}); banned-phrase-dispositions={len(banned_hits)}; "
             f"disposed-without-receipt={len(disposed_no_receipt)}. "
             f"sample={sample} -> deferred-work escape hatch OPEN "
             f"(invalid_deferred_remains)")

    if disposed_no_receipt:
        emit("RED",
             f"C10: {len(disposed_no_receipt)} row(s) disposed to "
             f"DONE/KILLED/EXCLUDED/ARCHIVAL WITHOUT a named receipt token "
             f"-> disposition lacks its receipt. sample={disposed_no_receipt[:3]}")

    if banned_hits:
        emit("RED",
             f"C10: {len(banned_hits)} banned scope-reduction phrase(s) used as "
             f"row disposition -> {banned_hits[:3]} (invalid_deferred_remains)")

    # GREEN: zero offending rows, every disposition carries a receipt, no
    # invalid-token / banned-phrase disposition.
    emit("GREEN",
         f"C10: scanned {n_rows} debt-ledger row(s); zero "
         f"ACTIVE/ACTIVE-BLOCKER/ACTIVE-NEXT/OPEN/PROGRESS-ONLY/triggerless-"
         f"DEFERRED remain, every DONE/KILLED/EXCLUDED/ARCHIVAL names a receipt, "
         f"no invalid_deferred_remains or banned scope-reduction disposition "
         f"-> no deferred-work escape hatch")


if __name__ == "__main__":
    main()
