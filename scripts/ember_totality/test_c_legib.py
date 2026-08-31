#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_legib.py — STATUS PROBE for Ember goal condition C-LEGIB.

Registry text: docs/spec/conditions-v1.md §4.2 C-LEGIB (gh issue #13,
mandate-coverage sweep 2026-07-02: "the repo-legibility surface [single-file
entry map; cold-read re-probe green; no internal contradiction] has no
condition, no probe, no ticket"). R: the repo is LEGIBLE to a fresh reader
(agentic or human) with no prior session context — a single entry-map file
names every top-level directory's purpose, that map has actually been
re-validated by a cold read (not merely authored once and trusted), and the
citation gate finds zero broken/misattributed references.

CHK enforced here (offline, filesystem + one local subprocess — no network):
GREEN iff ALL THREE hold, checked in this order (first failing clause is the
reported reason, same short-circuit discipline as test_c_proc.py):

  (a) an entry-map file exists at the repo root (`AGENTS.md`, else
      `docs/ENTRY-MAP.md`) whose "Repo map" table names EVERY top-level
      directory the repo actually has on disk (excluding `.git`, which no
      entry map ever documents) with a non-empty one-line purpose. A real
      top-level directory absent from the map, or mapped with an empty
      purpose cell, is RED naming the dir(s).

  (b) a dated receipt exists under `receipts/cold-read-reprobe/` (any
      `*.json` file; newest by filename sort, same convention as
      test_c_proc.py's process-visibility receipts). Receipt-absent = RED.
      A receipt carrying `_synthetic_control_fixture: true` is never
      evidence = RED (same rule as every other probe in this package).

  (c) `src/ember/governance/scripts/check_goal_citations.py` is run as a subprocess (timeout
      120s) and exits 0. Nonzero exit = RED, quoting the checker's last
      output line. The script being absent, the interpreter failing to
      launch it, or it not completing inside the timeout = UNEVALUABLE
      (an environment failure, never a fabricated RED) — this is the one
      clause capable of UNEVALUABLE; (a) and (b) are pure filesystem reads
      and always resolve to RED/GREEN once the root itself is found.

Why offline except one subprocess: (a)/(b) are local-bytes checks, same
discipline as every other probe here. (c) must actually EXECUTE the citation
checker because that script's own pass/fail is a real computation (path
existence, anchor resolution, row-id consistency) — no receipt could stand
in for running it without becoming a second, driftable copy of that logic.

DISCIPLINE: status probe — always exits 0, one line, real bytes decide, no
hardcoded verdict. RED / GREEN / UNEVALUABLE(env); receipt-absent is RED.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_legib_dir_unmapped",
    "invalid_legib_no_coldread_receipt",
    "invalid_legib_synthetic_control_fixture",
    "invalid_legib_coldread_failed",
    "invalid_legib_citation_check_failed",
]

# Directories no entry map is ever expected to document — pure VCS plumbing
# or auto-generated tooling output, never a legibility-relevant piece of the
# repo (the entry map documents real working dirs, including agent-context
# dotdirs, but never `.git/`; the exclusion set mirrors that convention, not
# an invented one).
#
# [ISSUE #97 cure 5, 2026-07-04] The board flapped RED->GREEN 3m15s apart on
# 2026-07-04 because a `.pytest_cache/` directory materialized at repo root
# mid-session (created by an unrelated pytest invocation elsewhere in this
# same tree) and this probe treated it as a real, legibility-relevant
# top-level directory the entry map must document -- which no map ever
# will, since it is not a working directory, it is a build/test-tool
# artifact that appears and disappears on its own schedule. Same failure
# class applies to any other auto-generated tooling output directory that
# can transiently appear at repo root: __pycache__ (Python bytecode cache),
# .ruff_cache (the ruff linter's cache), and the node_modules-class (JS/TS
# package-manager install directories: node_modules, .turbo, .next, dist,
# build -- none of these are ever hand-authored working dirs either).
EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache", "__pycache__", ".ruff_cache",       # tooling caches
    "node_modules", ".turbo", ".next", "dist", "build",  # node_modules-class
}

ENTRY_MAP_CANDIDATES = ["AGENTS.md", os.path.join("docs", "ENTRY-MAP.md")]

CITATION_CHECK_TIMEOUT_S = 120

# Repo-map table row: `| `dir1/`[, `dir2/`, ...] | purpose text | type |`.
# Column 1 may hold MULTIPLE backtick-quoted names sharing one purpose (this
# repo's own AGENTS.md does this for the MLE-bench trio) -- so this is a
# lookup for backtick spans within the first cell, not a single-name match.
BACKTICK_RE = re.compile(r"`([^`]+)`")
VALID_DIRNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def find_entry_map(root):
    """Return (path, error_reason_or_None) for the first candidate that
    exists under root, or (None, reason) if neither candidate exists."""
    for rel in ENTRY_MAP_CANDIDATES:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return p, None
    return None, (
        f"no entry-map file found at repo root (tried {', '.join(ENTRY_MAP_CANDIDATES)})"
    )


def parse_entry_map(text):
    """Parse every markdown table row in `text` of the shape
    `| `dir1/`[, `dir2/`, ...] | purpose | type |` into {dirname: purpose}
    (trailing slash stripped, last occurrence wins on a repeated name).
    Header/separator rows (no backtick-quoted names in column 1) are
    naturally skipped -- no special-casing needed. Only accepts names made
    of ordinary path-safe chars (rejects a command-example row like
    `` `python scripts/foo.py --run` `` from an unrelated table, which has
    no trailing slash to strip and fails VALID_DIRNAME_RE, so it can never
    be mistaken for a directory name)."""
    mapped = {}
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        first_cell, purpose = cells[0], cells[1]
        if not purpose or set(purpose) <= {"-", ":"}:
            continue  # empty purpose column, or a `---|---` separator row
        names = BACKTICK_RE.findall(first_cell)
        for raw in names:
            n = raw.strip().rstrip("/")
            if n and VALID_DIRNAME_RE.match(n):
                mapped[n] = purpose
    return mapped


def real_top_level_dirs(root):
    out = []
    for name in os.listdir(root):
        if name in EXCLUDED_DIRS:
            continue
        if os.path.isdir(os.path.join(root, name)):
            out.append(name)
    return sorted(out)


def check_entry_map(root):
    """Returns None on pass, or a RED reason string on failure."""
    map_path, err = find_entry_map(root)
    if map_path is None:
        return f"C-LEGIB: {err} (invalid_legib_dir_unmapped: no map to check dirs against)"

    try:
        with open(map_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        return f"C-LEGIB: entry-map file {os.path.relpath(map_path, root)} unreadable ({exc})"

    mapped = parse_entry_map(text)
    real_dirs = real_top_level_dirs(root)
    missing = [d for d in real_dirs if d not in mapped]
    if missing:
        return (
            f"C-LEGIB: entry-map {os.path.relpath(map_path, root)} is missing "
            f"{len(missing)} top-level dir(s) with no mapped one-line purpose: "
            f"{missing} (invalid_legib_dir_unmapped)"
        )
    return None


def check_cold_read_reprobe(root):
    """Returns None on pass, or a RED reason string on failure."""
    cr_dir = os.path.join(root, "receipts", "cold-read-reprobe")
    candidates = sorted(glob.glob(os.path.join(cr_dir, "*.json")))
    if not candidates:
        return (
            "C-LEGIB: no cold-read-reprobe receipt under receipts/cold-read-reprobe/ "
            "(invalid_legib_no_coldread_receipt) -- the entry map has never been "
            "re-validated by a fresh read, only authored"
        )
    newest = candidates[-1]
    name = os.path.basename(newest)
    try:
        with open(newest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return f"C-LEGIB: newest cold-read-reprobe receipt {name} unreadable ({exc})"
    if data.get("_synthetic_control_fixture"):
        return (
            f"C-LEGIB: newest cold-read-reprobe receipt {name} is a synthetic "
            f"control fixture, never evidence (invalid_legib_synthetic_control_fixture)"
        )
    # A cold-read receipt is only re-VALIDATION when the read PASSED. A FAIL
    # receipt is honest, admissible evidence -- of ILLEGIBILITY: it names the
    # fix list and keeps the condition RED. (Hole found 2026-07-02 by the very
    # first real cold read, which FAILed 6 of 20 map rows while this clause
    # would have waved it through on mere existence.)
    if data.get("verdict") != "PASS":
        fails = data.get("failures") or []
        return (
            f"C-LEGIB: newest cold-read-reprobe receipt {name} verdict="
            f"{data.get('verdict')!r} -- the map is not re-validated; "
            f"{len(fails)} finding(s) recorded (invalid_legib_coldread_failed)"
        )
    return None


def check_citation_gate(root):
    """Returns (status, reason) where status is None (pass), 'RED', or
    'UNEVALUABLE'."""
    script = os.path.join(root, "scripts", "check_goal_citations.py")
    if not os.path.isfile(script):
        return "UNEVALUABLE", f"C-LEGIB: {script} not found -- probe cannot look"
    try:
        proc = subprocess.run(
            [sys.executable, script],
            cwd=root,
            capture_output=True, text=True,
            timeout=CITATION_CHECK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return "UNEVALUABLE", (
            f"C-LEGIB: check_goal_citations.py exceeded {CITATION_CHECK_TIMEOUT_S}s -- "
            "probe cannot look"
        )
    except OSError as exc:
        return "UNEVALUABLE", f"C-LEGIB: could not launch check_goal_citations.py: {exc}"

    if proc.returncode != 0:
        lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        last_line = lines[-1] if lines else (proc.stderr or "").strip()[:300]
        return "RED", (
            f"C-LEGIB: src/ember/governance/scripts/check_goal_citations.py exited {proc.returncode} "
            f"(invalid_legib_citation_check_failed): {last_line}"
        )
    return None, None


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-LEGIB: state root not found under any known layout -- probe cannot look")

    reason = check_entry_map(ROOT)
    if reason is not None:
        emit("RED", reason)

    reason = check_cold_read_reprobe(ROOT)
    if reason is not None:
        emit("RED", reason)

    status, reason = check_citation_gate(ROOT)
    if status is not None:
        emit(status, reason)

    emit("GREEN", "C-LEGIB CHK satisfied: entry map covers every top-level directory with a "
                  "one-line purpose, a non-synthetic cold-read-reprobe receipt exists, and "
                  "src/ember/governance/scripts/check_goal_citations.py exits 0 (docs/domains/governance/authority/GOAL.md: the repo is legible to a "
                  "fresh reader with no prior session context)")


if __name__ == "__main__":
    main()
