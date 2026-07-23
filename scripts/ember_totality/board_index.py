#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""board_index.py -- canonical totality-board receipt index (R3, ember01plan F4/F5/F6/A3).

Twin 2026-07-11 board receipts (~18 min apart, different counts, different
locations) exposed the fracture this module closes: `gen_readme_status.py`'s
old selection rule ("newest lexicographic filename in one glob'd directory")
is location-blind, index-blind, and freshness-blind. This module adds three
layers on top of the existing run/chain-verify machinery:

  1. **Canonicality** -- exactly one directory (`receipts-totality/`, the
     runner's own write target) is the board-output authority. Every other
     tracked location (`receipts/`, `receipts-parity/`, ...) is classified
     and kept, never current, never deleted.
  2. **Append-only adjudication index** -- `BOARD-INDEX.jsonl` records every
     tracked board/noncanonical receipt plus explicit supersession rulings.
     Duplicate-epoch detection (D1/D2/D3, see `duplicate_epochs`) makes an
     unadjudicated twin fail closed instead of silently picking one by
     filename sort.
  3. **Mechanical freshness** -- a board row's `basis` snapshot (governing
     commit, GOAL.md/conditions-v1.md hashes, probe-set hash, evidence-index
     head, and -- once the R2 current-subject artifact lands -- current-subject identity) is
     compared against the live tree to answer FRESH vs STALE without a human
     eyeballing dates.

Nothing in this module ever deletes, moves, renames, or rewrites a tracked
receipt (classify-without-deletion is absolute -- receipts/'s 2026-07-11
103912Z copy is C-FED federation-design evidence and stays exactly where it
is). The one 2026-07-11 twin adjudication this module ships pre-ruled is
appended by backfill, not decided by the caller (see _PRE_RULED_SUPERSESSION).

Full rule text: docs/spec/board-canonicality-v1.md
Frozen spec: fspec-R3-1436-20260722T213546Z

Stdlib only. No network. PYTHONIOENCODING=utf-8 required on every invocation
(cp1252 console).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# receipt_chain_verify.py lives alongside this file -- import it directly
# (this also makes CLI invocation, python scripts/ember_totality/board_index.py,
# work without REPO_ROOT on sys.path).
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import receipt_chain_verify  # noqa: E402

CANONICAL_DIR = os.path.join(HERE, "receipts-totality")
INDEX_PATH = os.path.join(CANONICAL_DIR, "BOARD-INDEX.jsonl")


def _canonical_dir_for(repo_root: str) -> str:
    """The canonical board-output directory for an ARBITRARY repo_root --
    a throwaway test repo or a lane tree, not just this installation’s
    own checkout. CANONICAL_DIR above is only the convenience default for
    when repo_root == REPO_ROOT (the CLI’s own --root default)."""
    return os.path.join(repo_root, "scripts", "ember_totality", "receipts-totality")


def _index_path_for(repo_root: str) -> str:
    return os.path.join(_canonical_dir_for(repo_root), "BOARD-INDEX.jsonl")
# Do not redeclare the receipt-filename pattern -- receipt_chain_verify.py
# already owns it (_RECEIPT_NAME_RE).
RECEIPT_NAME_RE = receipt_chain_verify._RECEIPT_NAME_RE

# Empty until the R2 current-subject artifact lands (see A1/A2 boundary
# in the R3 spec section 9) -- wiring its path here is the one-line integration.
SUBJECT_IDENTITY_PATHS: list[str] = []

# The four freshness triggers (README plan): condition code covers both
# the probe set and the conditions-v1.md spec bytes; the other three map
# 1:1 onto a single basis field.
_BASIS_FIELDS_UNKNOWN_CAPABLE = (
    "governing_commit",
    "goal_sha256",
    "conditions_spec_sha256",
    "probe_set_sha256",
    "receipts_head_commit",
)
_FRESHNESS_TRIGGER_FIELDS = {
    "probe_set_sha256": "condition_code",
    "conditions_spec_sha256": "condition_code",
    "goal_sha256": "governing_hashes",
    "receipts_head_commit": "evidence_index_head",
}

# R3 repo-wide authority-conservation binding (verify_authority_conservation.py
# leg 4 artifact.goal_binding): every row this module writes carries the
# CURRENT active-goal binding so a later `git diff --cached` scan of this
# file's added lines always validates against GOAL.md's active policy.
# Update these three when the active goal/workstream changes (mirrors the
# .py header convention this file itself carries).
_ARTIFACT_GOAL_ID = "EMBER-02"
_ARTIFACT_WORKSTREAM_ID = "EMBER-02A"
_ARTIFACT_NEXT_EXECUTED_OUTCOME = (
    "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
)

_SUBJECT_IDENTITY_DISCLOSURE = (
    "PRE-A1: no current-subject surface landed (R2)"
)

# The one pre-ruled 2026-07-11 twin adjudication (R3 spec section 3) -- this is
# This adjudication ruling is encoded here; backfill appends it, the builder never decides it.
_PRE_RULED_SUPERSESSION_OLD = (
    "scripts/ember_totality/receipts-totality/ember-totality-20260711T102112Z.json"
)
_PRE_RULED_SUPERSESSION_NEW = (
    "receipts/ember-totality-20260711T103912Z.json"
)
_PRE_RULED_SUPERSESSION_REASON = (
    "R3 twin adjudication (ember01plan F4/F5): same-morning re-run 18 minutes "
    "later; 103912Z is the 2026-07-11 board-of-record; 102112Z remained "
    "README-cited only because gen_readme_status selection was "
    "location-blind. Both receipts preserved unmodified."
)
_PRE_RULED_SUPERSESSION_AUTHORITY = "fspec-R3-1436-20260722T213546Z"

# C-prime (fadv-1912, 2026-07-23): the 2026-07-11 board-of-record lives in receipts/ as C-FED
# evidence, pre-dating board canonicality. It is referenced IN PLACE as the board-of-record --
# never copied into the canonical dir (a byte-identical copy cannot carry the EMBER-02 goal_id
# the authority guard requires of a new receipt artifact; the .jsonl index row carries the
# binding instead). Self-extinguishing: the first post-A fresh run writes a bound receipt into
# receipts-totality/ and supersedes this in-place row.
_PRE_RULED_BOARD_PATH = "receipts/ember-totality-20260711T103912Z.json"


class BoardIndexError(Exception):
    """Fail-closed: raised by current_board when the index cannot yield
    exactly one adjudicated current board (missing/empty index, or a
    duplicate-epoch RED is outstanding)."""


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_sha256(path: str):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _git_output(repo_root: str, args):
    try:
        result = subprocess.run(
            ["git", "-C", repo_root] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    out = result.stdout.strip()
    return out if out else None


def _ts_from_path(path: str) -> str:
    m = RECEIPT_NAME_RE.match(os.path.basename(path))
    return m.group(1) if m else "UNKNOWN"


def probe_set_sha256(repo_root: str) -> str:
    """sha256 over "{relpath}:{sha256(bytes)}\n" for every git-TRACKED
    *.py directly under scripts/ember_totality/ (sorted relpaths, forward
    slashes, receipts-*/__pycache__ path components excluded). "UNKNOWN"
    if git is unavailable."""
    out = _git_output(repo_root, ["ls-files", "--", "scripts/ember_totality"])
    if out is None:
        return "UNKNOWN"
    prefix = "scripts/ember_totality/"
    relpaths = []
    for raw in out.splitlines():
        rel = raw.strip().replace("\\", "/")
        if not rel.startswith(prefix) or not rel.endswith(".py"):
            continue
        tail = rel[len(prefix):]
        if "/" in tail:
            continue  # only files directly under the directory
        if "receipts-" in tail or "__pycache__" in tail:
            continue
        relpaths.append(rel)
    relpaths.sort()
    lines = []
    for rel in relpaths:
        h = _file_sha256(os.path.join(repo_root, rel))
        if h is None:
            continue
        lines.append(f"{rel}:{h}\n")
    combined = "".join(lines).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def collect_basis(repo_root: str):
    """The basis dict of R3 spec section 3: a live snapshot of every
    freshness-relevant surface, computed NOW against repo_root."""
    governing_commit = _git_output(repo_root, ["rev-parse", "HEAD"]) or "UNKNOWN"
    goal_sha256 = _file_sha256(os.path.join(repo_root, "GOAL.md")) or "UNKNOWN"
    conditions_spec_sha256 = (
        _file_sha256(os.path.join(repo_root, "docs", "spec", "conditions-v1.md"))
        or "UNKNOWN"
    )
    receipts_head_commit = (
        _git_output(repo_root, ["log", "-1", "--format=%H", "--", "receipts/"])
        or "UNKNOWN"
    )
    subject_identity_sha256 = None
    subject_identity_source = _SUBJECT_IDENTITY_DISCLOSURE
    for rel in SUBJECT_IDENTITY_PATHS:
        candidate = os.path.join(repo_root, rel)
        if os.path.isfile(candidate):
            subject_identity_sha256 = _file_sha256(candidate)
            subject_identity_source = rel
            break
    return {
        "governing_commit": governing_commit,
        "goal_sha256": goal_sha256,
        "conditions_spec_sha256": conditions_spec_sha256,
        "probe_set_sha256": probe_set_sha256(repo_root),
        "receipts_head_commit": receipts_head_commit,
        "subject_identity_sha256": subject_identity_sha256,
        "subject_identity_source": subject_identity_source,
    }


def _unknown_basis():
    """Basis block stamped on backfilled (pre-index) historical rows -- they
    predate the index and can never be FRESH (R3 spec section 3)."""
    basis = {field: "UNKNOWN" for field in _BASIS_FIELDS_UNKNOWN_CAPABLE}
    basis["subject_identity_sha256"] = None
    basis["subject_identity_source"] = _SUBJECT_IDENTITY_DISCLOSURE
    return basis


def append_row(row, index_path=None) -> None:
    """Append one JSON line to a BOARD-INDEX.jsonl. Defaults to this repo’s
    canonical INDEX_PATH; an explicit index_path lets a caller (tests, or a
    lane-tree CLI invocation) target a different index. Never rewrites or
    reorders existing lines -- a wrong row is corrected by a later row."""
    if index_path is None:
        index_path = INDEX_PATH
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row))
        fh.write("\n")


def load_index(index_path=None):
    """Load a BOARD-INDEX.jsonl. Defaults to this repo’s canonical INDEX_PATH;
    an explicit index_path lets a caller (gen_readme_status.py --data-root) load
    a different lane tree’s index. Returns (rows, skipped) -- malformed lines
    are collected and DISCLOSED in skipped, never silently dropped (the
    _load_supersessions posture, c_invariant test_c_invariant.py #625)."""
    if index_path is None:
        index_path = INDEX_PATH
    rows = []
    skipped = []
    if not os.path.isfile(index_path):
        return rows, skipped
    with open(index_path, "r", encoding="utf-8", errors="ignore") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
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
            rows.append(row)
    return rows, skipped


def _location_class(relpath: str) -> str:
    parts = relpath.replace("\\", "/").split("/")
    if parts[0] == "receipts":
        return "receipts"
    if "receipts-parity" in parts:
        return "receipts-parity"
    return "other"


def _kept_because(relpath: str) -> str:
    if relpath == "receipts/ember-totality-20260711T103912Z.json":
        return (
            "C-FED federation-design evidence -- load-bearing, never delete "
            "(rows[C-FED].reason cites this exact path)"
        )
    return "noncanonical board-output location, preserved -- classify-without-deletion"


def classify(repo_root: str):
    """From git ls-files, every tracked ember-totality-*.json: in
    <repo_root>/scripts/ember_totality/receipts-totality -> board; elsewhere
    -> noncanonical (byte_twin_of set when a same-basename canonical row has
    the same sha256). Plus an on-disk scan of the two receipt dirs (canonical
    + receipts/) for UNLANDED (untracked) files. Nothing here ever deletes,
    moves, or rewrites a tracked receipt.

    repo_root-relative throughout (not the module-level CANONICAL_DIR
    constant) so this works against a throwaway test repo or a lane tree,
    not only this installation’s own checkout."""
    canonical_dir = _canonical_dir_for(repo_root)
    out = _git_output(repo_root, ["ls-files"])
    tracked = []
    if out is not None:
        for raw in out.splitlines():
            rel = raw.strip().replace("\\", "/")
            if rel and RECEIPT_NAME_RE.match(os.path.basename(rel)):
                tracked.append(rel)
    tracked.sort()

    canonical_prefix = (
        os.path.relpath(canonical_dir, repo_root).replace("\\", "/") + "/"
    )

    canonical_hash_by_basename = {}
    for rel in tracked:
        if rel.startswith(canonical_prefix):
            h = _file_sha256(os.path.join(repo_root, rel))
            if h is not None:
                canonical_hash_by_basename[os.path.basename(rel)] = h

    board_rows = []
    noncanonical_rows = []
    for rel in tracked:
        h = _file_sha256(os.path.join(repo_root, rel))
        if h is None:
            continue
        if rel.startswith(canonical_prefix):
            board_rows.append({"path": rel, "sha256": h})
        else:
            basename = os.path.basename(rel)
            twin_sha = canonical_hash_by_basename.get(basename)
            byte_twin_of = (
                canonical_prefix + basename if twin_sha == h else None
            )
            noncanonical_rows.append(
                {"path": rel, "sha256": h, "byte_twin_of": byte_twin_of}
            )

    tracked_set = set(tracked)
    unlanded = []
    receipts_dir = os.path.join(repo_root, "receipts")
    for scan_dir in (canonical_dir, receipts_dir):
        if not os.path.isdir(scan_dir):
            continue
        for name in sorted(os.listdir(scan_dir)):
            if not RECEIPT_NAME_RE.match(name):
                continue
            rel = os.path.relpath(
                os.path.join(scan_dir, name), repo_root
            ).replace("\\", "/")
            if rel not in tracked_set:
                unlanded.append(rel)

    return {"board": board_rows, "noncanonical": noncanonical_rows, "unlanded": unlanded}


def _supersession_pair_covers(supersession_rows, path_a, sha_a, path_b, sha_b) -> bool:
    for row in supersession_rows:
        old = row.get("old") or {}
        new = row.get("new") or {}
        pair = {
            (old.get("path"), old.get("sha256")),
            (new.get("path"), new.get("sha256")),
        }
        if (path_a, sha_a) in pair and (path_b, sha_b) in pair:
            return True
    return False


def _basis_all_known(basis) -> bool:
    if not isinstance(basis, dict):
        return False
    return all(basis.get(field) != "UNKNOWN" for field in _BASIS_FIELDS_UNKNOWN_CAPABLE)


def duplicate_epochs(index):
    """RED findings over the loaded index, three frozen rules (R3 spec section 4):

    D1 -- same basename tracked in >1 location, byte-identical -> RED unless
         a noncanonical row carries byte_twin_of (location-twin).
    D2 -- same basename, differing sha256 -> RED unless a supersession row
         covers the pair.
    D3 -- two board rows whose complete basis dicts are equal and
         non-UNKNOWN -> RED unless a supersession row names the survivor.
    """
    board_rows = [r for r in index if r.get("row_type") == "board"]
    noncanonical_rows = [r for r in index if r.get("row_type") == "noncanonical"]
    supersession_rows = [r for r in index if r.get("row_type") == "supersession"]

    findings = []

    by_basename = {}
    for r in board_rows:
        by_basename.setdefault(os.path.basename(r.get("path", "")), []).append(("board", r))
    for r in noncanonical_rows:
        by_basename.setdefault(os.path.basename(r.get("path", "")), []).append(("noncanonical", r))

    for basename, entries in by_basename.items():
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                kind_a, a = entries[i]
                kind_b, b = entries[j]
                path_a, sha_a = a.get("path"), a.get("sha256")
                path_b, sha_b = b.get("path"), b.get("sha256")
                if sha_a == sha_b:
                    twin_ok = (kind_a == "noncanonical" and a.get("byte_twin_of")) or (
                        kind_b == "noncanonical" and b.get("byte_twin_of")
                    )
                    if not twin_ok:
                        findings.append({
                            "rule": "D1",
                            "basename": basename,
                            "a": path_a,
                            "b": path_b,
                            "detail": (
                                "byte-identical same-basename pair missing a "
                                "byte_twin_of adjudication row"
                            ),
                        })
                else:
                    if not _supersession_pair_covers(supersession_rows, path_a, sha_a, path_b, sha_b):
                        findings.append({
                            "rule": "D2",
                            "basename": basename,
                            "a": path_a,
                            "b": path_b,
                            "detail": (
                                "same-basename pair with differing sha256 and no "
                                "covering supersession row"
                            ),
                        })

    for i in range(len(board_rows)):
        for j in range(i + 1, len(board_rows)):
            a, b = board_rows[i], board_rows[j]
            basis_a, basis_b = a.get("basis"), b.get("basis")
            if basis_a == basis_b and _basis_all_known(basis_a):
                path_a, sha_a = a.get("path"), a.get("sha256")
                path_b, sha_b = b.get("path"), b.get("sha256")
                if not _supersession_pair_covers(supersession_rows, path_a, sha_a, path_b, sha_b):
                    findings.append({
                        "rule": "D3",
                        "a": path_a,
                        "b": path_b,
                        "detail": (
                            "two board rows share identical non-UNKNOWN basis "
                            "with no supersession row naming a survivor"
                        ),
                    })

    return findings


def current_board(index):
    """Newest-ts board row in CANONICAL_DIR that is not the old side of
    any supersession row. Fail-closed: raises BoardIndexError if
    duplicate_epochs is non-empty or the index is missing/empty."""
    if not index:
        raise BoardIndexError("BOARD-INDEX.jsonl is missing or empty")
    findings = duplicate_epochs(index)
    if findings:
        detail = "; ".join(
            f"{f['rule']} {f.get('a')} vs {f.get('b')}: {f['detail']}" for f in findings
        )
        raise BoardIndexError(f"duplicate-epoch RED finding(s): {detail}")
    board_rows = [r for r in index if r.get("row_type") == "board"]
    superseded_old_paths = {
        (r.get("old") or {}).get("path")
        for r in index
        if r.get("row_type") == "supersession"
    }
    candidates = [r for r in board_rows if r.get("path") not in superseded_old_paths]
    if not candidates:
        raise BoardIndexError("no eligible current board row (all board rows superseded)")
    newest = max(candidates, key=lambda r: str(r.get("ts", "")))
    return newest.get("path"), newest


def freshness(row, repo_root: str):
    """{"verdict": "FRESH"|"STALE", "changed": [...]}. STALE iff any basis
    field differs from collect_basis(repo_root) now, comparing only fields
    non-UNKNOWN on both sides, EXCEPT: any UNKNOWN in the row's basis forces
    STALE with changed=["basis:UNKNOWN_PRE_INDEX"]. subject_identity compares
    only when both sides are non-null."""
    basis = row.get("basis") or {}
    if any(basis.get(field) == "UNKNOWN" for field in _BASIS_FIELDS_UNKNOWN_CAPABLE):
        return {"verdict": "STALE", "changed": ["basis:UNKNOWN_PRE_INDEX"]}

    now = collect_basis(repo_root)
    changed = []
    for field in _FRESHNESS_TRIGGER_FIELDS:
        old_v = basis.get(field)
        new_v = now.get(field)
        if old_v == "UNKNOWN" or new_v == "UNKNOWN":
            continue
        if old_v != new_v:
            changed.append(field)

    old_subj = basis.get("subject_identity_sha256")
    new_subj = now.get("subject_identity_sha256")
    if old_subj is not None and new_subj is not None and old_subj != new_subj:
        changed.append("subject_identity_sha256")

    if changed:
        return {"verdict": "STALE", "changed": changed}
    return {"verdict": "FRESH", "changed": []}


def _summary_for(repo_root: str, relpath: str):
    try:
        with open(os.path.join(repo_root, relpath), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    s = data.get("summary") or {}
    return {
        "green": s.get("green"),
        "red": s.get("red"),
        "unevaluable": s.get("unevaluable"),
        "pct_green": s.get("pct_green"),
    }


def _cmd_backfill(root: str) -> int:
    """Idempotent: appends missing board/noncanonical rows for all tracked
    receipts + the section-3 pre-ruled supersession row if absent. Re-running
    appends nothing already present (keyed on (row_type, path, sha256))."""
    index_path = _index_path_for(root)
    existing_rows, skipped = load_index(index_path)
    for s in skipped:
        print(f"SKIPPED (pre-existing malformed line): {s}")
    existing_keys = {
        (r.get("row_type"), r.get("path"), r.get("sha256"))
        for r in existing_rows
        if r.get("row_type") in ("board", "noncanonical")
    }
    existing_supersessions = {
        ((r.get("old") or {}).get("path"), (r.get("new") or {}).get("path"))
        for r in existing_rows
        if r.get("row_type") == "supersession"
    }

    result = classify(root)
    appended = 0

    for b in result["board"]:
        key = ("board", b["path"], b["sha256"])
        if key in existing_keys:
            continue
        row = {
            "row_type": "board",
            "goal_id": _ARTIFACT_GOAL_ID,
            "workstream_id": _ARTIFACT_WORKSTREAM_ID,
            "next_executed_outcome": _ARTIFACT_NEXT_EXECUTED_OUTCOME,
            "ts": _ts_from_path(b["path"]),
            "path": b["path"],
            "sha256": b["sha256"],
            "indexed_ts": _now_iso(),
            "basis": _unknown_basis(),
            "summary": _summary_for(root, b["path"]),
        }
        append_row(row, index_path)
        existing_keys.add(key)
        appended += 1

    for n in result["noncanonical"]:
        if n["path"] == _PRE_RULED_BOARD_PATH:
            continue  # promoted to the pre-ruled board-of-record row below (no duplicate)
        key = ("noncanonical", n["path"], n["sha256"])
        if key in existing_keys:
            continue
        row = {
            "row_type": "noncanonical",
            "goal_id": _ARTIFACT_GOAL_ID,
            "workstream_id": _ARTIFACT_WORKSTREAM_ID,
            "next_executed_outcome": _ARTIFACT_NEXT_EXECUTED_OUTCOME,
            "ts": _ts_from_path(n["path"]),
            "path": n["path"],
            "sha256": n["sha256"],
            "indexed_ts": _now_iso(),
            "location_class": _location_class(n["path"]),
            "kept_because": _kept_because(n["path"]),
            "byte_twin_of": n.get("byte_twin_of"),
        }
        append_row(row, index_path)
        existing_keys.add(key)
        appended += 1

    # C-prime pre-ruled board-of-record row: reference receipts/...103912Z in place as a board
    # row so current_board() derives it (current_board filters by row_type=="board" only, no dir
    # filter). Zero receipt bytes created; the binding rides this .jsonl row.
    _pr_board_sha = _file_sha256(os.path.join(root, _PRE_RULED_BOARD_PATH))
    if _pr_board_sha is not None and ("board", _PRE_RULED_BOARD_PATH, _pr_board_sha) not in existing_keys:
        row = {
            "row_type": "board",
            "goal_id": _ARTIFACT_GOAL_ID,
            "workstream_id": _ARTIFACT_WORKSTREAM_ID,
            "next_executed_outcome": _ARTIFACT_NEXT_EXECUTED_OUTCOME,
            "ts": _ts_from_path(_PRE_RULED_BOARD_PATH),
            "path": _PRE_RULED_BOARD_PATH,
            "sha256": _pr_board_sha,
            "indexed_ts": _now_iso(),
            "basis": _unknown_basis(),
            "summary": _summary_for(root, _PRE_RULED_BOARD_PATH),
            "location_class": "receipts",
            "kept_because": "historical board-of-record (2026-07-11, pre-canonicality); referenced in place, never copied into the canonical dir; self-extinguishing once a post-A fresh run writes a bound receipt into receipts-totality/",
        }
        append_row(row, index_path)
        existing_keys.add(("board", _PRE_RULED_BOARD_PATH, _pr_board_sha))
        appended += 1

    pair = (_PRE_RULED_SUPERSESSION_OLD, _PRE_RULED_SUPERSESSION_NEW)
    if pair not in existing_supersessions:
        old_sha = _file_sha256(os.path.join(root, _PRE_RULED_SUPERSESSION_OLD))
        new_sha = _file_sha256(os.path.join(root, _PRE_RULED_SUPERSESSION_NEW))
        if old_sha is not None and new_sha is not None:
            row = {
                "row_type": "supersession",
                "goal_id": _ARTIFACT_GOAL_ID,
                "workstream_id": _ARTIFACT_WORKSTREAM_ID,
                "next_executed_outcome": _ARTIFACT_NEXT_EXECUTED_OUTCOME,
                "old": {"path": _PRE_RULED_SUPERSESSION_OLD, "sha256": old_sha},
                "new": {"path": _PRE_RULED_SUPERSESSION_NEW, "sha256": new_sha},
                "reason": _PRE_RULED_SUPERSESSION_REASON,
                "ts": _now_iso(),
                "authority": _PRE_RULED_SUPERSESSION_AUTHORITY,
            }
            append_row(row, index_path)
            appended += 1
        else:
            print(
                "WARNING: pre-ruled supersession pair not both present on disk "
                f"(old sha={old_sha}, new sha={new_sha}) -- row not appended"
            )

    print(f"backfill: appended {appended} row(s)")
    return 0


def _cmd_verify(root: str) -> int:
    rows, skipped = load_index(_index_path_for(root))
    for s in skipped:
        print(f"SKIPPED: {s}")
    findings = duplicate_epochs(rows)
    if findings:
        for f in findings:
            print(f"RED: {f['rule']} {f.get('a')} vs {f.get('b')}: {f['detail']}")
        return 1
    try:
        path, _row = current_board(rows)
    except BoardIndexError as exc:
        print(f"RED: {exc}")
        return 1
    receipt_id = os.path.splitext(os.path.basename(path))[0]
    print(f"CURRENT={receipt_id}")
    return 0


def _cmd_classify(root: str) -> int:
    result = classify(root)
    print("board:")
    for b in result["board"]:
        print(f"  {b['path']}  {b['sha256'][:16]}")
    print("noncanonical:")
    for n in result["noncanonical"]:
        twin = n.get("byte_twin_of") or "-"
        print(f"  {n['path']}  {n['sha256'][:16]}  byte_twin_of={twin}")
    print("unlanded:")
    for u in result["unlanded"]:
        print(f"  {u}")
    return 0


def _cmd_freshness(root: str) -> int:
    rows, skipped = load_index(_index_path_for(root))
    for s in skipped:
        print(f"SKIPPED: {s}")
    try:
        _path, row = current_board(rows)
    except BoardIndexError as exc:
        print(f"RED: {exc}")
        return 1
    result = freshness(row, root)
    changed = ", ".join(result["changed"]) if result["changed"] else "current at index basis"
    print(f"{result['verdict']} {changed}")
    return 0 if result["verdict"] == "FRESH" else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=REPO_ROOT, help="repo root (default: this repo)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backfill", help="idempotently index all tracked board/noncanonical receipts")
    sub.add_parser("verify", help="print CURRENT=<id>, exit 0 iff adjudicated and unambiguous")
    sub.add_parser("classify", help="print board/noncanonical/UNLANDED table")
    sub.add_parser("freshness", help="print FRESH|STALE verdict for the current board")
    args = parser.parse_args()
    root = os.path.abspath(args.root)
    handlers = {
        "backfill": _cmd_backfill,
        "verify": _cmd_verify,
        "classify": _cmd_classify,
        "freshness": _cmd_freshness,
    }
    return handlers[args.command](root)


if __name__ == "__main__":
    sys.exit(main())
