#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute a docs/ consolidation move map: git mv + link rewriting + code-referrer rewriting.

Deterministic and idempotent: re-running after a partial run only acts on moves whose
source path still exists, and every content rewrite is a no-op once applied. Phase-scoped
so phase 1 (zero live-code references) and phase 2 (code-referenced) can land as separate
commits, each independently landable.

Consumes one or more move-map JSON files (schema: {"moves": [{"from", "to", "phase",
"code_referrers": [...], "doc_referrers": [...]}, ...]}) and, per invocation:

  1. `git mv` every move in the selected phase, creating destination directories.
  2. Rewrites every markdown link/reference in tracked *.md files that targets a moved
     path: literal repo-root-relative mentions, "./" and "../" relative links (recomputed
     against the referring file's new location if it also moved), and bare basenames that
     are globally unique across the doc corpus.
  3. For phase-2 moves, rewrites the literal old path to the new path inside every file
     listed in that move's code_referrers.
  4. Emits a JSON receipt of every git-mv, every content rewrite, and every skip, plus a
     printed summary.

Immutable-receipt exemption (see --receipt-dir-pattern): historical governance receipts
under directories matching the pattern are read-only records of what was true when they
were generated. This repo's own tools/repo-guard.sh-adjacent receipt_surface_integrity.py
names `scripts/ember_totality/receipts-totality/` as a receipt surface, and sibling
`receipts-parity/`, `receipts-milestone/`, `receipts-debt-ledger/` directories are the same
kind of artifact — but the reference-graph generator's RECORD_GLOBS only exempts a literal
top-level `receipts/`, so nested `receipts-*/` families under scripts/ get swept into CODE
referrers (scripts/ prefix) even though their "reference" is a prose mention of a path
inside a frozen historical status string, not a load-bearing import. Rewriting that text
would misstate point-in-time history (a receipt from before this move truthfully said the
doc lived at the old path). This script defaults to skipping those paths and reports every
skip explicitly in the receipt and summary -- never silently.

Usage:
    python tools/docs_consolidate.py \\
        --repo-root . \\
        --move-map path/to/docs-move-map.json \\
        --reference-graph path/to/docs-reference-graph.json \\
        --phase 1 \\
        --receipt-out /path/to/phase1-receipt.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

RECEIPT_DIR_RE = re.compile(r"(^|/)receipts[^/]*/")
# Matches the reference-graph generator's RECORD_GLOBS exactly (docs_reference_graph.py):
# a *.md file under one of these top-level prefixes is classified "record", not "doc",
# EVEN THOUGH it ends in .md — the generator checks RECORD_GLOBS before the .md suffix.
# These are immutable historical/state surfaces; a mention of a moved path inside them is
# not a live doc-to-doc link and must never be rewritten.
RECORD_GLOB_PREFIXES = ("receipts/", "manifests/", "baseline/", "state/")


def sh(args: list[str], cwd: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {args}\ncwd={cwd}\nstdout={r.stdout}\nstderr={r.stderr}")
    return r.stdout


def load_moves(move_map_paths: list[str], phase: str) -> list[dict]:
    moves: list[dict] = []
    seen_from = set()
    for p in move_map_paths:
        data = json.loads(io.open(p, encoding="utf-8").read())
        for m in data["moves"]:
            if phase != "all" and str(m["phase"]) != phase:
                continue
            if m["from"] in seen_from:
                raise ValueError(f"duplicate move source across move-map files: {m['from']}")
            seen_from.add(m["from"])
            moves.append(m)
    # Longest 'from' first: irrelevant for correctness here (no from/to path is a substring
    # of another in this corpus) but kept as a defensive ordering for future move-map inputs.
    moves.sort(key=lambda m: -len(m["from"]))
    return moves


def is_receipt_referrer(path: str, extra_patterns: list[str]) -> bool:
    if RECEIPT_DIR_RE.search(path):
        return True
    return any(pat in path for pat in extra_patterns)


def git_mv(repo_root: str, src: str, dst: str, receipt: dict) -> bool:
    src_abs = Path(repo_root) / src
    dst_abs = Path(repo_root) / dst
    if not src_abs.exists():
        if dst_abs.exists():
            receipt["moves_already_done"].append({"from": src, "to": dst})
            return False
        receipt["moves_missing_source"].append({"from": src, "to": dst})
        return False
    dst_abs.parent.mkdir(parents=True, exist_ok=True)
    sh(["git", "mv", src, dst], cwd=repo_root)
    receipt["moves_executed"].append({"from": src, "to": dst})
    return True


def load_basename_uniqueness(reference_graph_path: str | None, repo_root: str) -> dict[str, int]:
    """basename -> count of docs in the ORIGINAL corpus sharing it (matches the generator)."""
    counts: dict[str, int] = {}
    if reference_graph_path:
        graph = json.loads(io.open(reference_graph_path, encoding="utf-8").read())
        paths = [r["path"] for r in graph["rows"]]
    else:
        out = sh(["git", "ls-files", "docs/", "*.md"], cwd=repo_root)
        paths = [line for line in out.splitlines() if line]
    for p in paths:
        base = posixpath.basename(p)
        counts[base] = counts.get(base, 0) + 1
    return counts


INLINE_LINK_RE = re.compile(r'(\[[^\]]*\]\()([^)\s]+)((?:\s+"[^"]*")?\))')
REF_DEF_RE = re.compile(r'^(\s{0,3}\[[^\]]+\]:\s*)(\S+)', re.MULTILINE)


def _resolve_and_rewrite(target: str, old_dir: str, new_dir: str, rename_map: dict[str, str]) -> str | None:
    """Return the rewritten link target, or None if it does not target a moved path."""
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", target):  # other URI schemes
        return None
    frag = ""
    t = target
    if "#" in t:
        t, frag = t.split("#", 1)
        frag = "#" + frag
    if t == "":
        return None
    if t.startswith("/"):
        old_repo_rel = t.lstrip("/")
        style = "root-absolute"
    elif t in rename_map:
        old_repo_rel = t
        style = "as-is"
    else:
        old_repo_rel = posixpath.normpath(posixpath.join(old_dir, t))
        style = "relative"
    new_repo_rel = rename_map.get(old_repo_rel)
    if new_repo_rel is None:
        return None
    if style == "root-absolute":
        new_t = "/" + new_repo_rel
    elif style == "as-is":
        new_t = new_repo_rel
    else:
        new_t = posixpath.relpath(new_repo_rel, start=new_dir)
    return new_t + frag


def rewrite_doc_file(
    text: str,
    referrer_path: str,
    rename_map: dict[str, str],
    basename_counts: dict[str, int],
    referrer_old_path: str,
    referrer_new_path: str,
) -> tuple[str, int, int, int]:
    """Apply passes 1-3 to one markdown file's text. Returns (new_text, p1, p2, p3 counts)."""
    p1 = p2 = p3 = 0

    # Pass 1: literal repo-root-relative full-path mentions anywhere in the text.
    for old_full, new_full in rename_map.items():
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(old_full) + r"(?![A-Za-z0-9_])")
        text, n = pattern.subn(new_full, text)
        p1 += n

    # Pass 2: markdown link syntax with relative ("./", "../", bare) or as-is targets.
    old_dir = posixpath.dirname(referrer_old_path)
    new_dir = posixpath.dirname(referrer_new_path)

    def _inline_sub(m: re.Match) -> str:
        nonlocal p2
        new_target = _resolve_and_rewrite(m.group(2), old_dir, new_dir, rename_map)
        if new_target is None:
            return m.group(0)
        p2 += 1
        return m.group(1) + new_target + m.group(3)

    text = INLINE_LINK_RE.sub(_inline_sub, text)

    def _refdef_sub(m: re.Match) -> str:
        nonlocal p2
        new_target = _resolve_and_rewrite(m.group(2), old_dir, new_dir, rename_map)
        if new_target is None:
            return m.group(0)
        p2 += 1
        return m.group(1) + new_target

    text = REF_DEF_RE.sub(_refdef_sub, text)

    # Pass 3: bare, globally-unique basenames mentioned without a directory prefix
    # (not preceded by "/" or a word character, so we never touch the tail of a
    # different, longer path).
    for old_full, new_full in rename_map.items():
        old_base = posixpath.basename(old_full)
        new_base = posixpath.basename(new_full)
        if basename_counts.get(old_base, 0) != 1:
            continue
        pattern = re.compile(r"(?<![A-Za-z0-9_./\-])" + re.escape(old_base) + r"(?![A-Za-z0-9_\-])")
        text, n = pattern.subn(new_base, text)
        p3 += n

    return text, p1, p2, p3


def rewrite_links(
    repo_root: str,
    moves: list[dict],
    basename_counts: dict[str, int],
    receipt: dict,
    frozen_referrers: frozenset[str] = frozenset(),
) -> None:
    rename_map = {m["from"]: m["to"] for m in moves}
    # old-path -> new-path for every *.md file we're about to scan, so self-relative links
    # inside a moved file resolve against its own new location.
    self_new_path = {m["from"]: m["to"] for m in moves}

    md_files = [
        line for line in sh(["git", "ls-files", "*.md"], cwd=repo_root).splitlines()
        if line and not line.startswith(RECORD_GLOB_PREFIXES)
    ]
    for f in md_files:
        abs_path = Path(repo_root) / f
        try:
            original = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            receipt["doc_rewrite_read_errors"].append(f)
            continue
        # f is the file's CURRENT (post-mv) path. If it was itself moved this phase, its
        # OLD path is whatever move produced it; otherwise old == new == f.
        referrer_old_path = next((k for k, v in self_new_path.items() if v == f), f)
        referrer_new_path = f
        new_text, p1, p2, p3 = rewrite_doc_file(
            original, f, rename_map, basename_counts, referrer_old_path, referrer_new_path
        )
        if new_text == original:
            continue
        # A frozen referrer's BYTE CONTENT is pinned elsewhere (e.g. a hash-pinned evidence
        # entry in manifests/authority/*.json) -- moving/rewriting some OTHER file that this
        # one happens to mention must never edit these bytes, even though the generic
        # link-rewrite logic would otherwise legitimately update the mention. Skip the write,
        # and disclose exactly what would have changed rather than silently dropping it.
        if f in frozen_referrers:
            receipt["frozen_referrer_skipped"].append(
                {"path": f, "literal_path_hits": p1, "markdown_link_hits": p2, "bare_basename_hits": p3}
            )
            continue
        abs_path.write_text(new_text, encoding="utf-8", newline="")
        receipt["doc_files_rewritten"].append(
            {"path": f, "literal_path_hits": p1, "markdown_link_hits": p2, "bare_basename_hits": p3}
        )


def rewrite_code_referrers(
    repo_root: str, moves: list[dict], receipt: dict, extra_receipt_patterns: list[str]
) -> None:
    for m in moves:
        if m["phase"] != 2:
            continue
        old_full, new_full = m["from"], m["to"]
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(old_full) + r"(?![A-Za-z0-9_])")
        for referrer in m.get("code_referrers", []):
            if is_receipt_referrer(referrer, extra_receipt_patterns):
                receipt["code_referrer_skipped_immutable"].append(
                    {"move_from": old_full, "move_to": new_full, "referrer": referrer}
                )
                continue
            abs_path = Path(repo_root) / referrer
            if not abs_path.exists():
                receipt["code_referrer_missing_file"].append(
                    {"move_from": old_full, "move_to": new_full, "referrer": referrer}
                )
                continue
            try:
                text = abs_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                receipt["code_referrer_missing_file"].append(
                    {"move_from": old_full, "move_to": new_full, "referrer": referrer, "reason": "unreadable"}
                )
                continue
            new_text, n = pattern.subn(new_full, text)
            if n == 0:
                receipt["code_referrer_no_match"].append(
                    {"move_from": old_full, "move_to": new_full, "referrer": referrer}
                )
                continue
            abs_path.write_text(new_text, encoding="utf-8", newline="")
            receipt["code_referrer_rewrites"].append(
                {"move_from": old_full, "move_to": new_full, "referrer": referrer, "occurrences": n}
            )


def apply_dedupe_pointer(repo_root: str, pointer_path: str, target_path: str, receipt: dict) -> None:
    """Replace pointer_path's content with a two-line pointer to target_path (both new-location,
    post-move repo-relative paths). Both files continue to exist on disk."""
    abs_pointer = Path(repo_root) / pointer_path
    if not abs_pointer.exists():
        receipt["dedupe_errors"].append(f"pointer path missing: {pointer_path}")
        return
    if not (Path(repo_root) / target_path).exists():
        receipt["dedupe_errors"].append(f"dedupe target missing: {target_path}")
        return
    depth = pointer_path.count("/")
    rel = posixpath.relpath(target_path, start=posixpath.dirname(pointer_path)) if depth else target_path
    pointer_text = (
        f"# Superseded — byte-identical duplicate\n\nSee [{posixpath.basename(target_path)}]({rel}).\n"
    )
    abs_pointer.write_text(pointer_text, encoding="utf-8", newline="")
    receipt["dedupe_applied"].append({"pointer": pointer_path, "target": target_path})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--move-map", action="append", required=True, dest="move_maps")
    ap.add_argument("--reference-graph", default=None)
    ap.add_argument("--phase", default="all", choices=["1", "2", "all"])
    ap.add_argument("--exclude-from", action="append", default=[], dest="exclude_from",
                     help="'from' path(s) to drop from the move set entirely (e.g. a file whose "
                          "byte content is pinned by an authority/evidence hash elsewhere -- "
                          "moving OR content-editing it would invalidate that pin; see "
                          "manifests/authority/*.json before overriding this for a given path)")
    ap.add_argument("--freeze-referrer", action="append", default=[], dest="freeze_referrers",
                     help="new-location path(s) whose CONTENT must never be touched by the "
                          "link-rewrite pass, even when they legitimately mention some OTHER "
                          "file that is moving (e.g. a hash-pinned evidence doc that itself "
                          "survives --exclude-from but still references a path that moves). "
                          "Would-be rewrites are disclosed in the receipt, never applied.")
    ap.add_argument("--receipt-out", required=True)
    ap.add_argument("--receipt-dir-pattern", action="append", default=[], dest="extra_receipt_patterns",
                     help="extra substrings (besides receipts*/) whose code_referrers are left untouched")
    ap.add_argument("--dedupe-pointer", default=None,
                     help="new-location path to replace with a 2-line pointer (requires --dedupe-target)")
    ap.add_argument("--dedupe-target", default=None,
                     help="new-location path the dedupe pointer should point to")
    args = ap.parse_args()

    repo_root = str(Path(args.repo_root).resolve())
    receipt = {
        "phase": args.phase,
        "moves_executed": [],
        "moves_already_done": [],
        "moves_missing_source": [],
        "doc_files_rewritten": [],
        "doc_rewrite_read_errors": [],
        "code_referrer_rewrites": [],
        "code_referrer_no_match": [],
        "code_referrer_missing_file": [],
        "code_referrer_skipped_immutable": [],
        "dedupe_applied": [],
        "dedupe_errors": [],
        "moves_excluded": [],
        "frozen_referrer_skipped": [],
    }

    moves = load_moves(args.move_maps, args.phase)
    if args.exclude_from:
        excluded = set(args.exclude_from)
        receipt["moves_excluded"] = [
            {"from": m["from"], "to": m["to"]} for m in moves if m["from"] in excluded
        ]
        moves = [m for m in moves if m["from"] not in excluded]
    basename_counts = load_basename_uniqueness(args.reference_graph, repo_root)

    for m in moves:
        git_mv(repo_root, m["from"], m["to"], receipt)

    executed_or_done = {e["from"]: e["to"] for e in receipt["moves_executed"] + receipt["moves_already_done"]}
    effective_moves = [m for m in moves if m["from"] in executed_or_done]

    rewrite_links(repo_root, effective_moves, basename_counts, receipt, frozenset(args.freeze_referrers))
    rewrite_code_referrers(repo_root, effective_moves, receipt, args.extra_receipt_patterns)

    if args.dedupe_pointer:
        if not args.dedupe_target:
            print("error: --dedupe-pointer requires --dedupe-target", file=sys.stderr)
            return 2
        apply_dedupe_pointer(repo_root, args.dedupe_pointer, args.dedupe_target, receipt)

    io.open(args.receipt_out, "w", encoding="utf-8", newline="\n").write(
        json.dumps(receipt, indent=1, ensure_ascii=False) + "\n"
    )

    print(f"phase={args.phase}")
    if receipt["moves_excluded"]:
        print(f"moves excluded (--exclude-from)={len(receipt['moves_excluded'])}: "
              f"{[e['from'] for e in receipt['moves_excluded']]}")
    print(f"moves executed={len(receipt['moves_executed'])} "
          f"already-done={len(receipt['moves_already_done'])} "
          f"missing-source={len(receipt['moves_missing_source'])}")
    print(f"doc files rewritten={len(receipt['doc_files_rewritten'])} "
          f"frozen-referrer-skipped={len(receipt['frozen_referrer_skipped'])}")
    if receipt["frozen_referrer_skipped"]:
        print("NOTE: frozen referrers had a would-be rewrite suppressed (see receipt):", file=sys.stderr)
        for e in receipt["frozen_referrer_skipped"]:
            print(f"  {e['path']}", file=sys.stderr)
    print(f"code referrers rewritten={len(receipt['code_referrer_rewrites'])} "
          f"no-match={len(receipt['code_referrer_no_match'])} "
          f"skipped-immutable-receipts={len(receipt['code_referrer_skipped_immutable'])} "
          f"missing-file={len(receipt['code_referrer_missing_file'])}")
    if receipt["dedupe_applied"]:
        print(f"dedupe pointer applied: {receipt['dedupe_applied']}")
    if receipt["moves_missing_source"]:
        print("WARNING: moves with missing source (not executed):", file=sys.stderr)
        for e in receipt["moves_missing_source"]:
            print(f"  {e['from']} -> {e['to']}", file=sys.stderr)
    if receipt["code_referrer_no_match"]:
        print("WARNING: code referrers with zero literal matches (needs manual check):", file=sys.stderr)
        for e in receipt["code_referrer_no_match"]:
            print(f"  {e['referrer']}  (move {e['move_from']} -> {e['move_to']})", file=sys.stderr)
    print(f"\nwrote {args.receipt_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
