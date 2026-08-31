#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_goal_citations.py — standing citation gate for the goalforge rebuild.

Extracts every path-like reference to docs/, scripts/, receipts/, configs/,
config/, or paper/ found in docs/domains/governance/authority/GOAL.md, docs/roadmap/PROBLEMS.md, and every file in
docs/spec/, then verifies each one exists under the repo root.

Reference shapes recognized (per spec):
  - @-prefixed:       @docs/spec/math-core-v1.md
  - backtick-quoted:  `scripts/check_goal_citations.py`
    (the path may appear anywhere inside the backtick span, e.g.
    `python src/ember/governance/scripts/governor.py --selftest` still yields src/ember/governance/scripts/governor.py)

Templated placeholders (containing < > { } or a glob *) are extracted but
SKIPPED as non-concrete (e.g. `receipts/tally-<ts>.json`,
`receipts/bootstrap-falsifier-*.json`) — never reported missing.

v2 hardening (2026-07-02), three defect classes engineered away WITHOUT
weakening the gate — every non-concrete or non-local classification below
still requires a positive, checkable signal; bare silence still fails:

  1. Line-wrap false positives — this corpus hard-wraps prose at ~100 cols
     (and hand-draws ASCII diagrams in fenced blocks), so a single path is
     sometimes split across two source lines: `docs/spec/curriculum-` +
     `dataset-v1.md` on the next line. A raw candidate that (a) is missing,
     (b) is immediately followed in the source by a newline, and (c) looks
     like a truncated fragment (ends in `-`/`_`, or ends mid-directory with
     no extension in its final segment and no trailing `/`) is joined with
     the leading path-safe run on the continuation line and re-checked. A
     fragment that still resolves nowhere after joining stays a miss.

  2. Documented-absent citations — the convention `absent as of <date>`,
     `verified absent`, or `build target` (also its `TO BUILD` synonym, used
     interchangeably throughout this corpus for the identical claim) inside
     the same paragraph as a citation means the doc is HONESTLY citing a
     known-missing path. Reported as `documented_absent`, non-fatal. Bare
     absence with no adjacent marker in the same paragraph still fails —
     this is per-citation-site, not per-path: the same missing path cited
     elsewhere without the marker still fails there.

  3. Cross-tree citations — paths that exist under a reference tree (e.g.
     <reference-tree>, passed via --cross-tree) but not this worktree. Reported as
     `cross_tree`, non-fatal. Read-only stat against the reference tree only.

Known-absent refs (documented-as-absent intentionally) can also be
allowlisted in scripts/citation_allowlist.txt — one path per line, each line
MUST carry a trailing "# reason" comment; lines without one are ignored as
malformed.

v3 anchor layer (2026-07-02): a fourth check layer, "anchors", closes a hole
the path-existence checks above are blind to — a citation can name a real
file and still misattribute WHERE in that file the cited content lives
(e.g. `@docs/spec/math-core-v1.md §7` when the claim actually sits in §3).
For every `@<path>` citation followed, within ~80 chars and the same
paragraph, by a `§<ref>` (ref = `<n>`, `<n>(<m>)`, or `<n>.<m>`), the
checker resolves <path> and verifies the target actually declares that
section: a markdown heading is read as declaring <n> if it leads with <n>
(optionally §-prefixed, terminated by `.`, `)`, whitespace, or end-of-line
— covers `## 5. Title`, `## A. Title`, `### 5a. Title`, and a bare
`### 4.2`) or contains `§<n>` anywhere in its text. `§<n>(<m>)` resolves on
`§<n>` presence alone (the `(<m>)` is a list-item pointer, never counted).
`§<n>.<m>` resolves on an exact `<n>.<m>` heading OR a bare `<n>` heading.
A `§` with no `@<path>` within the window is a same-document cross-
reference, not a citation, and is not checked — nor is a citation whose
<path> does not resolve locally (the existence checks above already report
that). Failures print `anchor-miss: <file>:<line> -> <path> §<ref> (file
has sections: <ids>)` and flip `pass=False`; a same-line
`<!-- anchor-ok -->` comment suppresses one citation (escape hatch for
prose the parser misreads) and is counted, never silently dropped. This
layer has its own escape hatch and does not consult
scripts/citation_allowlist.txt (that allowlist is path-existence-scoped).

v4 row-id layer (2026-07-02): a fifth check layer, "row-id", catches a
different citation defect than anchors above -- paper/sections/*.md and
paper/outline.md cite paper/claims-evidence-map.md rows by number ("row 18",
"rows 5, 9", "row 1-3"). A citation can name a row that simply does not
exist in the map's CURRENT table (stale after a row is removed/renumbered, or
a typo). This layer counts the map's actual table rows (leading `| N |`
cells) and verifies every id named by every "row"/"rows" citation in those
files -- including each endpoint of a hyphen range and each item of a
comma list -- resolves to a real row. Fails CLOSED: if the map itself is
missing or has no parseable table rows, every citation found in the target
docs is still reported under `row_id_missing` (never a silent pass) with
that failure as its reason.

Output: JSON receipt to receipts/citation-check-<UTCstamp>.json plus a human
summary on stdout. Exits 1 if any non-allowlisted, non-templated, non-joined,
non-documented-absent, non-cross-tree reference is missing under the repo
root, any non-suppressed anchor citation's section is missing from its
resolved target, or any row-id citation names a row absent from
claims-evidence-map.md's current table (pass iff `missing`, `anchor_missing`,
and `row_id_missing` are all empty).

Stdlib only. No network. No git commands (--cross-tree is a plain read-only
filesystem stat against a caller-supplied path, never a git operation).
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "citation_allowlist.txt"
RECEIPTS_DIR = REPO_ROOT / "receipts"

SOURCE_FILES = ["docs/domains/governance/authority/GOAL.md", "docs/roadmap/PROBLEMS.md"]
SOURCE_GLOB_DIRS = ["docs/spec"]

PREFIXES = ("baseline/", "docs/", "scripts/", "receipts/", "configs/", "config/", "paper/")
PREFIX_ALT = "|".join(re.escape(p) for p in PREFIXES)
# '*' included so glob patterns (receipts/foo-*.json) extract as ONE
# candidate instead of truncating at the '*' — then routed to the
# templated-placeholder bucket below, exactly like <ts>/{n} placeholders.
PATH_CHARSET = r"[A-Za-z0-9_./{}<>*-]"
CANDIDATE_RE = re.compile(rf"(?:{PREFIX_ALT}){PATH_CHARSET}+")
AT_REF_RE = re.compile(rf"@((?:{PREFIX_ALT}){PATH_CHARSET}*)")
BACKTICK_SPAN_RE = re.compile(r"`([^`]*)`")
TEMPLATE_CHARS = set("<>{}*")

# Documented-absent convention markers. \s+ (not a literal space) so a
# wrapped marker phrase — e.g. "**absent as of\n2026-07-01**" — still
# matches. "TO BUILD" / "to build" / "not yet built" are this corpus's other
# common synonyms for "build target" (used interchangeably for the identical
# claim); treated as equivalent.
ABSENT_MARKER_RES = [
    re.compile(r"absent\s+as\s+of\s+\S+", re.IGNORECASE),
    re.compile(r"verified\s+absent", re.IGNORECASE),
    re.compile(r"build\s+target", re.IGNORECASE),
    re.compile(r"to\s+build", re.IGNORECASE),
    re.compile(r"not\s+yet\s+built", re.IGNORECASE),
]

CONTINUATION_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./{}<>*-"
)
MAX_WRAP_SKIP = 24  # cap on non-path chars skipped when hunting for a continuation

# --- v3 anchor layer -------------------------------------------------------
# A section ref id is either a digit run with an optional single trailing
# letter and optional ".digits" (5, 5a, 4.2) or a single bare letter (A, C —
# milestones-v1.md's top-level lettered sections). The trailing group is the
# optional "(m)" list-item pointer, kept only for display — never resolved.
_SECTION_ID = r"[0-9]+[A-Za-z]?(?:\.[0-9]+)?|[A-Za-z]"
ANCHOR_REF_RE = re.compile(rf"§\s*({_SECTION_ID})(\([0-9]+(?:\s*,\s*[0-9]+)*\))?")
ANCHOR_WINDOW_CHARS = 80
ANCHOR_OK_MARKER = "<!-- anchor-ok -->"

HEADING_LINE_RE = re.compile(r"^#{1,4}[ \t]*(.*)$", re.MULTILINE)
# A heading DECLARES an id if it leads with that id (lookahead requires the
# id be immediately terminated by '.', ')', whitespace, or end-of-line, so
# an ordinary word like "Completion" in "## Completion criteria" can never
# match) or contains "§<id>" anywhere in its text.
HEADING_LEAD_ID_RE = re.compile(rf"^(?:§\s*)?({_SECTION_ID})(?=[.)\s]|$)")
HEADING_INLINE_SEC_RE = re.compile(rf"§\s*({_SECTION_ID})")


def resolve_sources():
    """Deterministic, sorted list of (relative_posix_path, Path) to scan."""
    sources = []
    for rel in SOURCE_FILES:
        p = REPO_ROOT / rel
        if p.is_file():
            sources.append((rel, p))
    for rel_dir in SOURCE_GLOB_DIRS:
        d = REPO_ROOT / rel_dir
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.is_file():
                    rel = p.relative_to(REPO_ROOT).as_posix()
                    sources.append((rel, p))
    sources.sort(key=lambda t: t[0])
    return sources


def clean_candidate(raw):
    """Strip trailing sentence punctuation a path can never legitimately end in."""
    s = raw
    while s.endswith("."):
        s = s[:-1]
    return s


def is_templated(s):
    return any(ch in TEMPLATE_CHARS for ch in s)


def looks_like_wrap_fragment(cleaned):
    """True if a cleaned (missing) candidate looks truncated by a line wrap:
    ends in '-'/'_' (word-break), or ends mid-directory (no '.' in the final
    path segment, and no trailing '/' — a genuine directory ref is exempt)."""
    if not cleaned:
        return False
    if cleaned.endswith("-") or cleaned.endswith("_"):
        return True
    if cleaned.endswith("/"):
        return False
    last_seg = cleaned.rsplit("/", 1)[-1]
    return "." not in last_seg


def _hard_wrapped_continuation(text, after):
    """Strategy A: the fragment is immediately followed (past only trailing
    same-line spaces/tabs) by a hard newline, then the real continuation —
    plain prose word-wrap. Returns the continuation string, or None."""
    i = after
    while i < len(text) and text[i] in (" ", "\t"):
        i += 1
    if i >= len(text) or text[i] != "\n":
        return None
    i += 1
    skipped = 0
    while i < len(text) and text[i] not in CONTINUATION_CHARS:
        if text[i] == "\n":
            return None  # blank line / paragraph break — no continuation
        i += 1
        skipped += 1
        if skipped > MAX_WRAP_SKIP:
            return None
    j = i
    while j < len(text) and text[j] in CONTINUATION_CHARS:
        j += 1
    return text[i:j] or None


def _column_aligned_continuation(text, after, token_start):
    """Strategy B: the fragment is followed on the SAME line by unrelated
    content (a different cell of a hand-drawn ASCII table inside a fenced
    diagram — this corpus's box-diagram convention), but the true
    continuation sits at the SAME column on the very next line. Returns the
    continuation string, or None."""
    if token_start is None:
        return None
    line_start = text.rfind("\n", 0, token_start) + 1
    col = token_start - line_start
    next_nl = text.find("\n", after)
    if next_nl == -1:
        return None
    target = next_nl + 1 + col
    if target >= len(text) or text[target] not in CONTINUATION_CHARS:
        return None
    k = target
    while k < len(text) and text[k] in CONTINUATION_CHARS:
        k += 1
    return text[target:k] or None


def try_wrap_join(text, raw_match_end, raw_candidate, token_start=None):
    """If `raw_candidate` (as matched, pre-clean) looks like a line-wrapped
    fragment, hunt its continuation (plain hard-wrap, or same-column on the
    next line for a fenced ASCII diagram) and join. Returns the cleaned
    joined candidate, or None if not eligible / no usable continuation."""
    cleaned = clean_candidate(raw_candidate)
    if not looks_like_wrap_fragment(cleaned):
        return None
    continuation = (
        _hard_wrapped_continuation(text, raw_match_end)
        or _column_aligned_continuation(text, raw_match_end, token_start)
    )
    if not continuation:
        return None
    return clean_candidate(raw_candidate + continuation)


def paragraph_bounds(text, pos):
    """Return (start, end) char offsets of the blank-line-delimited paragraph
    containing offset `pos`."""
    start = text.rfind("\n\n", 0, pos)
    start = 0 if start == -1 else start + 2
    end = text.find("\n\n", pos)
    end = len(text) if end == -1 else end
    return start, end


def find_absent_marker(text, pos):
    """Search the paragraph containing `pos` for a documented-absent marker.
    Returns the matched marker text, or None."""
    start, end = paragraph_bounds(text, pos)
    window = text[start:end]
    for pat in ABSENT_MARKER_RES:
        m = pat.search(window)
        if m:
            return m.group(0)
    return None


def line_number(text, pos):
    return text.count("\n", 0, pos) + 1


def line_span(text, pos):
    """(start, end) char offsets of the source line containing `pos`."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return start, end


def extract_section_ids(text):
    """Return the set of section ids a document's markdown headings declare
    (liberal — see HEADING_LEAD_ID_RE / HEADING_INLINE_SEC_RE)."""
    ids = set()
    for m in HEADING_LINE_RE.finditer(text):
        heading = m.group(1).strip()
        if not heading:
            continue
        lead = HEADING_LEAD_ID_RE.match(heading)
        if lead:
            ids.add(lead.group(1))
        for im in HEADING_INLINE_SEC_RE.finditer(heading):
            ids.add(im.group(1))
    return ids


def anchor_resolves(section_ids, base_id):
    """§<n> / §<n>(<m>) resolve iff <n> is a declared id. §<n>.<m> resolves
    on an exact '<n>.<m>' id OR a bare '<n>' id (the (m) pointer is never
    resolved against — it is a list item, not a heading)."""
    if base_id in section_ids:
        return True
    if "." in base_id:
        return base_id.split(".", 1)[0] in section_ids
    return False


def _section_sort_key(s):
    m = re.match(r"^([0-9]+)", s)
    if m:
        return (0, int(m.group(1)), s)
    return (1, 0, s)


INTERVENING_FILENAME_RE = re.compile(r"`[^`]*\.md[^`]*`")
TIGHT_BIND_CHARS = 3  # "@path §n" — the classic one-space-gap direct citation


def extract_anchor_citations(text):
    """Return a list of dicts, one per '@<path> ... §<ref>' citation found
    in `text` — every § occurrence within ANCHOR_WINDOW_CHARS of the end of
    the nearest PRECEDING @-path (same paragraph) is bound to that path. A §
    with no @-path within the window is a same-document cross-reference,
    not a citation, and is skipped.

    Two disambiguation guards (real-corpus false positives, 2026-07-02):
    a LOOSE (non-adjacent) § is dropped, rather than mis-bound, when either
    is true — it names a genuinely different document, not this checker's
    business to guess at:
      1. the same base_id was already TIGHT-bound (adjacent, "@path §n") to
         a DIFFERENT path earlier in the same paragraph — a repeated bare
         section number almost always back-references THAT citation, not
         whichever @-path happens to be nearest (e.g. "@math-core.md §0
         governs (...map @milestones.md §A); the one clause not in §0" —
         the second §0 means math-core, not milestones);
      2. a backtick-quoted bare filename mention (`` `foo.md` ``, no @ and
         no directory — this corpus's own non-@ citation shorthand) sits
         between the candidate @-path and the §, naming a third document
         the § more plausibly belongs to.
    """
    events = []
    for m in AT_REF_RE.finditer(text):
        raw = m.group(1)
        if raw and not is_templated(raw):
            events.append((m.start(1), "at", clean_candidate(raw), m.end(1)))
    for m in ANCHOR_REF_RE.finditer(text):
        events.append((m.start(), "sec", m.group(1), m.group(2) or "", m.end()))
    events.sort(key=lambda e: e[0])

    citations = []
    last_at = None  # (path, end_pos)
    tight_seen = {}  # base_id -> path, reset at each paragraph break
    prev_end = 0  # end of the previously processed event, any kind
    for ev in events:
        if "\n\n" in text[prev_end:ev[0]]:
            tight_seen = {}
        prev_end = max(prev_end, ev[0])

        if ev[1] == "at":
            last_at = (ev[2], ev[3])
            prev_end = max(prev_end, ev[3])
            continue
        pos, _, base_id, paren, _end = ev
        prev_end = max(prev_end, pos + 1)
        if last_at is None:
            continue
        path, at_end = last_at
        gap = pos - at_end
        if gap < 0 or gap > ANCHOR_WINDOW_CHARS:
            continue
        between = text[at_end:pos]
        if "\n\n" in between:
            continue  # paragraph break — different sentence, not this citation

        if gap <= TIGHT_BIND_CHARS:
            tight_seen[base_id] = path
        else:
            prior = tight_seen.get(base_id)
            if prior is not None and prior != path:
                continue  # guard 1
            if INTERVENING_FILENAME_RE.search(between):
                continue  # guard 2

        line_start, line_end = line_span(text, pos)
        citations.append({
            "path": path,
            "base_id": base_id,
            "ref_display": base_id + paren,
            "line": line_number(text, pos),
            "suppressed": ANCHOR_OK_MARKER in text[line_start:line_end],
        })
    return citations


def scan_doc_anchors(rel_doc, text, section_ids_cache=None):
    """Returns dict with checked/missing/suppressed counters for the anchor
    layer. `section_ids_cache` (path -> set(ids)|None) is shared across docs
    in a single run so a target file's headings are parsed once."""
    if section_ids_cache is None:
        section_ids_cache = {}
    result = {"checked": 0, "missing": [], "suppressed": 0}

    for c in extract_anchor_citations(text):
        path = c["path"]
        if path not in section_ids_cache:
            target = REPO_ROOT / path
            if target.is_file():
                section_ids_cache[path] = extract_section_ids(
                    target.read_text(encoding="utf-8", errors="replace"))
            else:
                section_ids_cache[path] = None  # doesn't resolve locally;
                # the path-existence layer already reports this — not
                # double-counted here.
        section_ids = section_ids_cache[path]
        if section_ids is None:
            continue

        if c["suppressed"]:
            result["suppressed"] += 1
            continue

        result["checked"] += 1
        if not anchor_resolves(section_ids, c["base_id"]):
            result["missing"].append({
                "doc": rel_doc, "path": path, "ref": c["ref_display"],
                "line": c["line"],
                "sections_found": sorted(section_ids, key=_section_sort_key),
            })

    return result


# --- v4 row-id layer --------------------------------------------------------
# See the module docstring's "v4 row-id layer" paragraph.

CLAIMS_MAP_REL = "paper/claims-evidence-map.md"
ROW_ID_SOURCE_FILES = ["paper/outline.md"]
ROW_ID_SOURCE_GLOB_DIRS = ["paper/sections"]

MAP_TABLE_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|", re.MULTILINE)
ROW_CITATION_RE = re.compile(
    r"\brows?\s+((?:\d+(?:\s*-\s*\d+)?)(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)", re.IGNORECASE)


def parse_valid_row_ids(map_text):
    """Return the set of row numbers actually present in claims-evidence-map.md's
    table (leading '| N |' cells). Empty set if none parse."""
    return {int(m.group(1)) for m in MAP_TABLE_ROW_RE.finditer(map_text)}


def _expand_row_token(token):
    """'1-3' -> [1, 2, 3]; '9' -> [9]. A reversed range ('5-3') is normalized
    (min..max) rather than silently dropped."""
    token = token.strip()
    if "-" in token:
        a, b = token.split("-", 1)
        lo, hi = sorted((int(a.strip()), int(b.strip())))
        return list(range(lo, hi + 1))
    return [int(token)]


def extract_row_citations(text):
    """Return a list of (line_number, raw_match_text, [ids]) for every
    'row N' / 'rows N, M' / 'row N-M' citation found in `text`."""
    out = []
    for m in ROW_CITATION_RE.finditer(text):
        ids = []
        for tok in m.group(1).split(","):
            ids.extend(_expand_row_token(tok))
        out.append((line_number(text, m.start()), m.group(0), ids))
    return out


def check_row_id_consistency(repo_root):
    """Scan paper/sections/*.md + paper/outline.md for claims-evidence-map.md row
    citations and verify each cited row id exists in the map's current table.
    Returns a dict with checked/missing/map_rows_found/map_error. Fails CLOSED:
    an unreadable/unparseable map still reports every citation found in the
    target docs as row_id_missing, never a silent pass."""
    map_path = repo_root / CLAIMS_MAP_REL
    result = {"checked": 0, "missing": [], "map_rows_found": 0, "map_error": None}

    map_text = None
    if map_path.is_file():
        try:
            map_text = map_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            result["map_error"] = f"{type(e).__name__}: {e}"
    else:
        result["map_error"] = f"{CLAIMS_MAP_REL} not found"

    valid_ids = parse_valid_row_ids(map_text) if map_text is not None else set()
    result["map_rows_found"] = len(valid_ids)
    if map_text is not None and not valid_ids and result["map_error"] is None:
        result["map_error"] = f"{CLAIMS_MAP_REL} has no parseable table rows"

    targets = []
    for rel in ROW_ID_SOURCE_FILES:
        p = repo_root / rel
        if p.is_file():
            targets.append((rel, p))
    for rel_dir in ROW_ID_SOURCE_GLOB_DIRS:
        d = repo_root / rel_dir
        if d.is_dir():
            for p in sorted(d.glob("*.md")):
                targets.append((p.relative_to(repo_root).as_posix(), p))
    targets.sort(key=lambda t: t[0])

    for rel_doc, path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, raw, ids in extract_row_citations(text):
            for rid in ids:
                result["checked"] += 1
                if rid not in valid_ids:
                    result["missing"].append({
                        "doc": rel_doc, "line": line_no, "cited": rid, "context": raw,
                        "reason": result["map_error"] or
                                  "row not found in claims-evidence-map.md's current table",
                    })

    return result


def extract_candidates(text):
    """Return (candidates, templated) where candidates is a list of
    (raw_candidate, match_start, match_end, token_start) for every concrete
    (non-templated) candidate found via @-prefix or backtick span, in source
    order, and templated is the set of cleaned templated/glob candidates seen
    (for the receipt's templated_skipped count). Positions are absolute
    offsets into `text`. `token_start` is the position of the leading '@'
    for @-refs (used for column-aligned diagram wrap-join), else None."""
    candidates = []
    templated = set()

    for m in AT_REF_RE.finditer(text):
        raw = m.group(1)
        if not raw:
            continue
        start, end = m.start(1), m.end(1)
        if is_templated(raw):
            templated.add(clean_candidate(raw))
        else:
            candidates.append((raw, start, end, m.start()))

    for span_m in BACKTICK_SPAN_RE.finditer(text):
        span_start = span_m.start(1)
        span_text = span_m.group(1)
        for cm in CANDIDATE_RE.finditer(span_text):
            raw = cm.group(0)
            start = span_start + cm.start()
            end = span_start + cm.end()
            if is_templated(raw):
                templated.add(clean_candidate(raw))
            else:
                candidates.append((raw, start, end, None))

    return candidates, templated


def load_allowlist():
    entries = {}
    malformed = 0
    if ALLOWLIST_PATH.is_file():
        for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "#" not in stripped:
                malformed += 1
                continue
            path_part, _, reason = stripped.partition("#")
            path_part = path_part.strip()
            reason = reason.strip()
            if not path_part or not reason:
                malformed += 1
                continue
            entries[path_part] = reason
    return entries, malformed


def scan_doc(rel_doc, text, allowlist, cross_tree_root):
    """Returns dict with per-doc classified results and counters."""
    raw_candidates, templated = extract_candidates(text)

    # Group all occurrences by cleaned string, in document order. A ref cited
    # more than once in the same doc is classified per-doc, not per-site: if
    # ANY occurrence resolves (wrap-join) or carries an adjacent marker, the
    # doc counts as having honestly disclosed it there — but an entirely
    # unmarked, unresolved citation still fails even if some OTHER document
    # elsewhere marks the same path (per-citation-site across docs, per-ref
    # within a doc).
    occurrences = {}
    for raw, start, end, token_start in raw_candidates:
        cleaned = clean_candidate(raw)
        if not cleaned:
            continue
        occurrences.setdefault(cleaned, []).append((raw, start, end, token_start))

    result = {
        "checked": 0,
        "allowlisted": 0,
        "templated_skipped": len(templated),
        "missing": [],
        "documented_absent": [],
        "cross_tree": [],
        "wrap_joined": [],
        "stale_absent_marker": [],
    }

    for cleaned in sorted(occurrences):
        if cleaned in allowlist:
            result["allowlisted"] += 1
            continue
        result["checked"] += 1

        target = REPO_ROOT / cleaned
        if target.exists():
            # Stale-absent-marker detection (receipts-v1 cross-cutting finding,
            # 2026-07-02): a ref that RESOLVES but still carries an "absent as
            # of / TO BUILD / verified absent"-class marker is a stale claim --
            # the doc asserts non-existence of a path that now exists. Reported
            # as stale_absent_marker, non-fatal (warn class), so honest dated
            # markers get refreshed instead of lingering as false statements.
            # Tight binding only: the marker must sit in the immediate
            # after-ref window ("`path` (absent as of ...)" / "`path` -- TO
            # BUILD"), never paragraph-scoped -- paragraph markers usually
            # belong to a DIFFERENT ref and would flood this with noise.
            _stale_re = re.compile(
                r"absent as of|verified absent|TO\s+BUILD|not yet built"
                r"|does not exist|build target", re.I)
            for raw, start, end, token_start in occurrences[cleaned]:
                # Wrap-tolerant window (F8 class, 2026-07-02): the anti-gaming
                # escape was a wrapped verified-absent marker -- the phrase split
                # across a hard wrap, and a newline-bounded window missed it.
                # Join up to 160 chars across newlines. Exemption: text that
                # RESOLVES the absence claim in the preceding context (the
                # deliberate preserved-historical pattern) is not stale.
                window = text[end:end + 160].replace(chr(10), " ")
                pre = text[max(0, start - 300):start]
                if re.search(r"RESOLVED|past tense|authoring-time|at authoring"
                             r"|superseded|was true only", pre, re.I):
                    continue
                m = _stale_re.search(window)
                if m:
                    result["stale_absent_marker"].append({
                        "doc": rel_doc, "ref": cleaned, "marker": m.group(0),
                        "line": line_number(text, start),
                    })
                    break
            continue

        sites = occurrences[cleaned]
        first_start = sites[0][1]
        classified = False

        for raw, start, end, token_start in sites:
            joined = try_wrap_join(text, end, raw, token_start)
            if joined is not None and (REPO_ROOT / joined).exists():
                result["wrap_joined"].append({
                    "doc": rel_doc, "ref": cleaned, "joined": joined,
                    "line": line_number(text, start),
                })
                classified = True
                break

        if classified:
            continue

        for raw, start, end, token_start in sites:
            marker = find_absent_marker(text, start)
            if marker:
                result["documented_absent"].append({
                    "doc": rel_doc, "ref": cleaned, "marker": marker,
                    "line": line_number(text, start),
                })
                classified = True
                break

        if classified:
            continue

        if cross_tree_root is not None:
            cross_path = cross_tree_root / cleaned
            if cross_path.exists():
                result["cross_tree"].append({
                    "doc": rel_doc, "ref": cleaned,
                    "cross_tree_path": str(cross_path),
                    "line": line_number(text, first_start),
                })
                continue

        result["missing"].append({
            "doc": rel_doc, "ref": cleaned, "line": line_number(text, first_start),
        })

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cross-tree", default=None,
                     help="Reference tree root to check missing refs against "
                          "(read-only; e.g. <reference-tree>). Hits reported as "
                          "cross_tree, non-fatal.")
    ap.add_argument("--selftest", action="store_true",
                     help="Run built-in unit checks for the v2 hardening and "
                          "v3 anchor-layer behaviors and exit (no receipt "
                          "written).")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()

    cross_tree_root = Path(args.cross_tree).resolve() if args.cross_tree else None

    sources = resolve_sources()
    allowlist, allowlist_malformed = load_allowlist()

    totals = {"checked": 0, "allowlisted": 0, "templated_skipped": 0}
    missing = []
    documented_absent = []
    stale_absent = []
    cross_tree = []
    wrap_joined = []
    anchor_cache = {}
    anchor_checked = 0
    anchor_suppressed = 0
    anchor_missing = []

    for rel_doc, path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        r = scan_doc(rel_doc, text, allowlist, cross_tree_root)
        totals["checked"] += r["checked"]
        totals["allowlisted"] += r["allowlisted"]
        totals["templated_skipped"] += r["templated_skipped"]
        missing.extend(r["missing"])
        documented_absent.extend(r["documented_absent"])
        stale_absent.extend(r.get("stale_absent_marker", []))
        cross_tree.extend(r["cross_tree"])
        wrap_joined.extend(r["wrap_joined"])

        ar = scan_doc_anchors(rel_doc, text, anchor_cache)
        anchor_checked += ar["checked"]
        anchor_suppressed += ar["suppressed"]
        anchor_missing.extend(ar["missing"])

    row_id_result = check_row_id_consistency(REPO_ROOT)
    row_id_missing = sorted(row_id_result["missing"], key=lambda m: (m["doc"], m["line"]))

    missing.sort(key=lambda m: (m["doc"], m["ref"]))
    documented_absent.sort(key=lambda m: (m["doc"], m["ref"]))
    cross_tree.sort(key=lambda m: (m["doc"], m["ref"]))
    wrap_joined.sort(key=lambda m: (m["doc"], m["ref"]))
    anchor_missing.sort(key=lambda m: (m["doc"], m["line"]))
    passed = len(missing) == 0 and len(anchor_missing) == 0 and len(row_id_missing) == 0

    receipt = {
        "tool": "check_goal_citations",
        "version": 4,
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "repo_root": str(REPO_ROOT),
        "cross_tree_root": str(cross_tree_root) if cross_tree_root else None,
        "sources_scanned": [rel for rel, _ in sources],
        "checked": totals["checked"],
        "missing": missing,
        "documented_absent": documented_absent,
        "stale_absent_marker": stale_absent,
        "cross_tree": cross_tree,
        "wrap_joined": wrap_joined,
        "allowlisted": totals["allowlisted"],
        "templated_skipped": totals["templated_skipped"],
        "allowlist_malformed_lines": allowlist_malformed,
        "anchor_checked": anchor_checked,
        "anchor_missing": anchor_missing,
        "anchor_suppressed": anchor_suppressed,
        "row_id_checked": row_id_result["checked"],
        "row_id_missing": row_id_missing,
        "row_id_map_rows_found": row_id_result["map_rows_found"],
        "row_id_map_error": row_id_result["map_error"],
        "pass": passed,
    }

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = RECEIPTS_DIR / f"citation-check-{receipt['timestamp']}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    print(f"check_goal_citations v4: {len(sources)} docs scanned, {totals['checked']} refs checked, "
          f"{totals['allowlisted']} allowlisted, {totals['templated_skipped']} templated-skipped, "
          f"{len(wrap_joined)} wrap-joined, {len(documented_absent)} documented-absent, "
          f"{len(stale_absent)} stale-absent-marker, "
          f"{len(cross_tree)} cross-tree, "
          f"{anchor_checked} anchors checked, {anchor_suppressed} anchor-suppressed, "
          f"{row_id_result['checked']} row-ids checked ({row_id_result['map_rows_found']} map rows)")
    if missing:
        print(f"MISSING ({len(missing)}):")
        for m in missing:
            print(f"  {m['doc']}:{m['line']}: {m['ref']}")
    else:
        print("MISSING: none")
    if anchor_missing:
        print(f"ANCHOR-MISS ({len(anchor_missing)}):")
        for m in anchor_missing:
            print(f"anchor-miss: {m['doc']}:{m['line']} -> {m['path']} §{m['ref']} "
                  f"(file has sections: {', '.join(m['sections_found'])})")
    else:
        print("ANCHOR-MISS: none")
    if row_id_missing:
        print(f"ROW-ID-MISS ({len(row_id_missing)}):")
        for m in row_id_missing:
            print(f"row-id-miss: {m['doc']}:{m['line']}: '{m['context']}' -> row {m['cited']} "
                  f"({m['reason']})")
    else:
        print("ROW-ID-MISS: none")
    print(f"receipt: {receipt_path.relative_to(REPO_ROOT).as_posix()}")
    print(f"pass={passed}")

    return 0 if passed else 1


def run_selftest():
    """Unit checks for the three hardening behaviors. Writes nothing under
    the repo; uses in-memory fixtures under a scratch temp dir only."""
    import tempfile
    failures = []

    def check(name, cond):
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {name}")
        if not cond:
            failures.append(name)

    global REPO_ROOT
    orig_root = REPO_ROOT
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "docs" / "spec").mkdir(parents=True)
        (root / "receipts").mkdir()
        (root / "scripts").mkdir()
        (root / "scripts" / "existing_probe.py").write_text("x", encoding="utf-8")
        (root / "docs" / "spec" / "curriculum-dataset-v1.md").write_text("x", encoding="utf-8")
        (root / "receipts" / "gate-stats-346-20260612T202900Z.json").write_text("{}", encoding="utf-8")
        (root / "docs" / "spec" / "anchor-target-v1.md").write_text(
            "# Anchor target v1\n"
            "\n"
            "## 1. First section\n"
            "\n"
            "## 4. Fourth section\n"
            "\n"
            "### 4.2 Compound-numbered subsection\n"
            "\n"
            "## 5. Fifth section\n"
            "\n"
            "### 5a. Fifth section, sub a\n"
            "\n"
            "## A. Lettered section (milestones-v1-style)\n",
            encoding="utf-8",
        )
        (root / "docs" / "spec" / "other-target-v1.md").write_text(
            "# Other target v1\n"
            "\n"
            "## A. Other heading\n",
            encoding="utf-8",
        )
        REPO_ROOT = root

        # --- Class 1: line-wrap join ---
        text1 = (
            "see the curriculum spec\n"
            "@docs/spec/curriculum-\n"
            "dataset-v1.md for details\n"
        )
        r1 = scan_doc("t1.md", text1, {}, None)
        check("wrap-join resolves split @-ref across a hard line break",
              len(r1["wrap_joined"]) == 1 and r1["wrap_joined"][0]["joined"] == "docs/spec/curriculum-dataset-v1.md")
        check("wrap-join leaves nothing in missing for the resolved ref",
              len(r1["missing"]) == 0)

        text1b = (
            "a receipt exists: `receipts/gate-stats-346-\n"
            "20260612T202900Z.json` (verified present)\n"
        )
        r1b = scan_doc("t1b.md", text1b, {}, None)
        check("wrap-join resolves split backtick-span ref across a hard line break",
              len(r1b["wrap_joined"]) == 1)

        # docs/domains/governance/authority/GOAL.md's actual ASCII box-diagram shape: the fragment is followed
        # on the SAME line by an unrelated table cell, and the true
        # continuation sits at the SAME column on the next line.
        text1d = (
            "```\n"
            "   curriculum/corpus ---+                         |\n"
            "   @docs/spec/curriculum- |    episodes (unrelated cell)   |\n"
            "   dataset-v1.md          v                        |\n"
            "```\n"
        )
        r1d = scan_doc("t1d.md", text1d, {}, None)
        check("wrap-join resolves column-aligned ASCII-diagram split across a fenced block",
              len(r1d["wrap_joined"]) == 1 and r1d["wrap_joined"][0]["joined"] == "docs/spec/curriculum-dataset-v1.md")

        text1c = (
            "cites `receipts/totally-fake-\n"
            "nonexistent-thing.json` here\n"
        )
        r1c = scan_doc("t1c.md", text1c, {}, None)
        check("wrap-join that STILL resolves nowhere stays a true miss",
              len(r1c["missing"]) == 1 and len(r1c["wrap_joined"]) == 0)

        # --- Class 2: documented-absent ---
        text2 = (
            "the closure receipt `receipts/nope-really-gone.json` is\n"
            "verified absent from this worktree as of this session.\n"
        )
        r2 = scan_doc("t2.md", text2, {}, None)
        check("marker 'verified absent' within paragraph classifies documented_absent",
              len(r2["documented_absent"]) == 1 and len(r2["missing"]) == 0)

        text2b = (
            "`scripts/not_built_yet.py` (threshold-degeneracy, **build target**,\n"
            "absent as of 2026-07-01)\n"
        )
        r2b = scan_doc("t2b.md", text2b, {}, None)
        check("marker 'build target' + 'absent as of' both fire, still one documented_absent entry",
              len(r2b["documented_absent"]) == 1)

        text2c = (
            "`scripts/proofs/bootstrap_threshold_sweep.py` pattern.\n"
            "\n"
            "Next paragraph, unrelated, mentions absent as of 2026-01-01 nothing.\n"
        )
        r2c = scan_doc("t2c.md", text2c, {}, None)
        check("marker in a DIFFERENT paragraph does NOT launder a bare citation",
              len(r2c["missing"]) == 1 and len(r2c["documented_absent"]) == 0)

        # --- Class 2d: wrap-tolerant INVERSE stale (F8, 2026-07-02) ---
        # marker phrase split across a hard wrap after an EXISTING path
        text2d = (
            "`scripts/existing_probe.py` -- **verified" + chr(10) +
            "absent** from scripts/ (recursive find)." + chr(10)
        )
        r2d = scan_doc("t2d.md", text2d, {}, None)
        check("wrapped 'verified\nabsent' after an EXISTING ref fires stale_absent_marker",
              len(r2d["stale_absent_marker"]) == 1)

        text2e = (
            "Phantoms found at authoring (ALL THREE RESOLVED 2026-07-02, past tense):" + chr(10) +
            "`scripts/existing_probe.py` -- **verified" + chr(10) +
            "absent** at the time." + chr(10)
        )
        r2e = scan_doc("t2e.md", text2e, {}, None)
        check("RESOLVED/past-tense context exempts preserved historical absence text",
              len(r2e["stale_absent_marker"]) == 0)

        # --- Class 3: cross-tree ---
        with tempfile.TemporaryDirectory() as td2:
            cross_root = Path(td2)
            (cross_root / "receipts").mkdir()
            (cross_root / "receipts" / "cgrow-run-20260628T062609Z").mkdir()
            text3 = "see `receipts/cgrow-run-20260628T062609Z/` for the run\n"
            r3 = scan_doc("t3.md", text3, {}, cross_root)
            check("cross-tree hit classifies cross_tree, not missing",
                  len(r3["cross_tree"]) == 1 and len(r3["missing"]) == 0)

            r3b = scan_doc("t3.md", text3, {}, None)
            check("without --cross-tree the same ref is a true miss",
                  len(r3b["missing"]) == 1)

        # --- glob/template extension (supports class 1/2 by not false-flagging globs) ---
        text4 = "receipt pattern `receipts/bootstrap-falsifier-*.json` covers all runs\n"
        r4 = scan_doc("t4.md", text4, {}, None)
        check("glob-wildcard ref is templated-skipped, never reported missing",
              r4["templated_skipped"] == 1 and len(r4["missing"]) == 0)

        # --- per-doc multi-occurrence: a LATER marked site rescues an EARLIER bare one ---
        text5 = (
            "no `scripts/w1_swe.py` exists anywhere in this repo yet.\n"
            "\n"
            "**Script (new, not yet built):** `scripts/w1_swe.py`, cloned from elsewhere.\n"
        )
        r5 = scan_doc("t5.md", text5, {}, None)
        check("a later marked occurrence of the same ref rescues an earlier bare one in the same doc",
              len(r5["documented_absent"]) == 1 and len(r5["missing"]) == 0)

        text5b = (
            "no `scripts/never_marked.py` exists anywhere in this repo.\n"
            "\n"
            "It is cited again here: `scripts/never_marked.py` with no caveat at all.\n"
        )
        r5b = scan_doc("t5b.md", text5b, {}, None)
        check("a ref with NO marked occurrence anywhere in the doc still fails",
              len(r5b["missing"]) == 1 and len(r5b["documented_absent"]) == 0)

        # --- v3: anchor layer (section-granular citation checking) ---
        # target fixture headings: 1, 4, 4.2, 5, 5a, A

        # (a) valid anchor passes
        ta = "see @docs/spec/anchor-target-v1.md §1 for the definition\n"
        ra = scan_doc_anchors("ta.md", ta, {})
        check("valid §<n> anchor resolves and is counted checked",
              ra["checked"] == 1 and len(ra["missing"]) == 0)

        # (b) wrong anchor fails, with the found-sections list in the report
        tb = "see @docs/spec/anchor-target-v1.md §99 for the definition\n"
        rb = scan_doc_anchors("tb.md", tb, {})
        check("wrong §<n> anchor is reported anchor-missing with sections_found populated",
              len(rb["missing"]) == 1
              and rb["missing"][0]["ref"] == "99"
              and set(rb["missing"][0]["sections_found"]) == {"1", "4", "4.2", "5", "5a", "A"})

        # (c) §n(m) resolves on §n presence alone — the (m) is a list item, never counted
        tc = "gate @docs/spec/anchor-target-v1.md §5(4) fires the bits formula\n"
        rc = scan_doc_anchors("tc.md", tc, {})
        check("§<n>(<m>) resolves when §<n> exists, ignoring the (m) list-item pointer",
              rc["checked"] == 1 and len(rc["missing"]) == 0)

        tc2 = "gate @docs/spec/anchor-target-v1.md §99(4) does not fire\n"
        rc2 = scan_doc_anchors("tc2.md", tc2, {})
        check("§<n>(<m>) still fails when §<n> itself is absent",
              len(rc2["missing"]) == 1 and rc2["missing"][0]["ref"] == "99(4)")

        # (d) <!-- anchor-ok --> suppression, same line as the citation
        td = "see @docs/spec/anchor-target-v1.md §99 for the definition <!-- anchor-ok -->\n"
        rd = scan_doc_anchors("td.md", td, {})
        check("<!-- anchor-ok --> on the citation line suppresses the miss and is counted",
              rd["suppressed"] == 1 and rd["checked"] == 0 and len(rd["missing"]) == 0)

        # (e) §<n>.<m> resolves on an EXACT compound heading
        te = "see @docs/spec/anchor-target-v1.md §4.2 for the compound case\n"
        re_ = scan_doc_anchors("te.md", te, {})
        check("§<n>.<m> resolves against an exact '<n>.<m>' heading",
              re_["checked"] == 1 and len(re_["missing"]) == 0)

        # (f) §<n>.<m> falls back to a bare §<n> heading when no exact compound exists
        tf = "see @docs/spec/anchor-target-v1.md §4.9 for the fallback case\n"
        rf = scan_doc_anchors("tf.md", tf, {})
        check("§<n>.<m> resolves against a bare '<n>' heading when '<n>.<m>' itself is absent",
              rf["checked"] == 1 and len(rf["missing"]) == 0)

        # (g) a citation to a path that doesn't resolve locally is skipped by
        # this layer entirely -- the existence checks already report it
        tg = "see @docs/spec/does-not-exist-v1.md §1 for the definition\n"
        rg = scan_doc_anchors("tg.md", tg, {})
        check("anchor layer skips citations whose path does not resolve locally",
              rg["checked"] == 0 and len(rg["missing"]) == 0)

        # (h) a bare §-ref with no @-path in the window is a same-doc
        # cross-reference, not a citation -- never checked
        th = "as covered in §1 above, the same idea applies here too.\n"
        rh = scan_doc_anchors("th.md", th, {})
        check("a bare §<n> with no preceding @-path is not treated as a citation",
              rh["checked"] == 0 and len(rh["missing"]) == 0)

        # (i) a §-ref past a paragraph break is a different sentence -- out
        # of window even though the raw char count could be under 80
        ti = "see @docs/spec/anchor-target-v1.md for the spec.\n\n§99 unrelated later heading\n"
        ri = scan_doc_anchors("ti.md", ti, {})
        check("a §<n> across a paragraph break from the @-path is not bound to it",
              ri["checked"] == 0 and len(ri["missing"]) == 0)

        # (j) multiple §-refs chained off ONE @-path (math-core-v1.md's real
        # shape: "@path §3, ... §10, ... §3" all bind to the same nearest path)
        tj = ("estimator @docs/spec/anchor-target-v1.md §1, its validity §5, "
              "the pin §1 (2026-07-02) restated\n")
        rj = scan_doc_anchors("tj.md", tj, {})
        check("multiple §-refs within window of one @-path all bind to it and all resolve",
              rj["checked"] == 3 and len(rj["missing"]) == 0)

        # (k) guard 1 — real-corpus false positive (docs/domains/governance/authority/GOAL.md 2026-07-02): a
        # repeated bare §<n> that was already TIGHT-bound to an EARLIER path
        # must not be reattributed to a more-recent, different path just
        # because it's nearer. other-target-v1.md has §A but no §1.
        tk = (
            "@docs/spec/anchor-target-v1.md §1 governs the mapping "
            "(also @docs/spec/other-target-v1.md §A); the one clause not in §1 stands.\n"
        )
        rk = scan_doc_anchors("tk.md", tk, {})
        check("a bare §<n> already tight-bound to an earlier path is not reattributed "
              "to a nearer path lacking that section (no false anchor-miss)",
              rk["checked"] == 2 and len(rk["missing"]) == 0)

        # (l) guard 2 — real-corpus false positive (engineering-contracts-v1.md
        # 2026-07-02): a backtick-quoted bare filename mention between an
        # @-path and a later loose § names a third document — don't bind.
        tl = (
            "cite @docs/spec/anchor-target-v1.md for reasons. Board condition "
            "IDs only (`other-target-v1.md` §77); more text.\n"
        )
        rl = scan_doc_anchors("tl.md", tl, {})
        check("an intervening backtick-quoted bare filename blocks mis-binding "
              "a loose § to an unrelated earlier @-path",
              rl["checked"] == 0 and len(rl["missing"]) == 0)

        # --- v4: row-id consistency layer ---
        (root / "paper" / "sections").mkdir(parents=True)
        (root / "paper" / "claims-evidence-map.md").write_text(
            "# map\n\n| # | Claim | Strength | Evidence | Missing |\n|---|---|---|---|---|\n"
            "| 1 | a | PROVEN | x | y |\n| 2 | b | PROVEN | x | y |\n| 3 | c | PROVEN | x | y |\n",
            encoding="utf-8",
        )

        (root / "paper" / "outline.md").write_text(
            "see row 1 and rows 2, 3 for evidence\n", encoding="utf-8")
        r_row_ok = check_row_id_consistency(root)
        check("row-id: all-valid single + comma-list citations produce zero missing",
              len(r_row_ok["missing"]) == 0 and r_row_ok["checked"] == 3
              and r_row_ok["map_rows_found"] == 3)

        (root / "paper" / "outline.md").write_text(
            "see row 1 and rows 2, 9 for evidence, also row 5-7\n", encoding="utf-8")
        r_row_bad = check_row_id_consistency(root)
        check("row-id: out-of-range single id (9) and every id in an out-of-range "
              "hyphen range (5-7) are individually reported missing",
              {m["cited"] for m in r_row_bad["missing"]} == {9, 5, 6, 7})

        (root / "paper" / "outline.md").write_text("see row 1\n", encoding="utf-8")
        (root / "paper" / "sections" / "01-introduction.md").write_text(
            "see row 2 here, and row 99 there\n", encoding="utf-8")
        r_row_sections = check_row_id_consistency(root)
        check("row-id: paper/sections/*.md files are scanned alongside outline.md",
              r_row_sections["checked"] == 3
              and [m["cited"] for m in r_row_sections["missing"]] == [99])

        # fail-closed: map missing entirely -> every citation still reported
        (root / "paper" / "claims-evidence-map.md").unlink()
        (root / "paper" / "sections" / "01-introduction.md").write_text(
            "see row 2 here\n", encoding="utf-8")
        r_row_nomap = check_row_id_consistency(root)
        check("row-id: missing claims-evidence-map.md still reports every citation as "
              "missing (fail-closed, never a silent pass)",
              len(r_row_nomap["missing"]) == 2  # outline's row 1 + section's row 2
              and r_row_nomap["map_error"] is not None
              and all(m["reason"] == r_row_nomap["map_error"] for m in r_row_nomap["missing"]))

    REPO_ROOT = orig_root

    print(f"\nselftest: {'ALL PASS' if not failures else f'{len(failures)} FAILED'}")
    for f in failures:
        print(f"  FAILED: {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
