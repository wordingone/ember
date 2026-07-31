#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test — Condition C-CUSTODY (status probe / TDD).

C-CUSTODY — Receipts custody and integrity.
  R: Every receipt in receipts/ must be git-tracked, parseable as JSON,
     and every receipts/ path cited in verdict-bearing receipts must exist.
  CHK: Untracked, unparseable, or cited-missing receipts -> RED. All pass -> GREEN.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED ", "GREEN ", or "UNEVALUABLE ". RED/GREEN is determined by
really inspecting state under <execution-root> — never hardcoded.

Three failure shapes (issue #381):
  (a) untracked-in-canonical: any file in receipts/ not tracked by git
  (b) unparseable: any file fails json.load (utf-8, then utf-8-sig)
  (c) cited-path-missing: any receipts/ path cited in verdict-bearing receipt
                          or board receipt that doesn't exist on disk

Allowlist authority: any exception for an untracked staging receipt must come
from the separately tracked scripts/ember_totality/custody-allowlist.json
surface. A receipt's own "__allowlist_untracked" field is disclosure only and
never grants authority.

Issue #415 cure (72/72 cited_missing enumeration + four-bucket addendum +
DESIGN RULING, gh issue #415): the naive citation extractor over-reported
cited_missing on several distinct, evidence-backed false-positive shapes.
Five probe-side cures, each fixture-verified:

  1. Extraction fixes -- a trailing markdown-fence backtick or a `::field.path`
     compound-reference suffix swallowed into the greedy extraction regex is
     stripped before the existence check (_clean_citation); a citation-check
     receipt's own wrap_joined record ({"doc","ref","joined","line"} --
     scripts/check_goal_citations.py) is consumed by its RECONSTRUCTED
     `joined` value instead of re-truncating the raw `ref` fragment; a bare,
     no-extension citation that resolves as a real, git-tracked-populated
     DIRECTORY (isdir() + >=1 tracked file inside) is a directory reference,
     not a missing file.
  2. Relocation resolution -- a unique-basename index over the git-tracked
     receipts/ tree: a cited path that doesn't exist, but whose basename
     matches EXACTLY ONE tracked file elsewhere, classifies `relocated`
     (sidecar records old->new). A non-unique basename match is never
     guessed at -- it stays cited_missing.
  3. Schema-constant exemption -- an explicit, evidence-backed table of
     literal path STRINGS that are hardcoded schema-example constants baked
     into every cycle-*/statecommit-* receipt's `receipts`/`evidence` blocks
     (sandbox/gpu_governor/benchmark/wheel/observation/verifier fields, plus
     the replay/rollback/state_substrate fields whose real value is doubly
     mis-rooted under a state-substrate/ prefix that doesn't exist in this
     tree at all) -- conventional documentation, never a real per-run
     citation. Folds into the existing pattern_citation bucket (issue #415
     DESIGN RULING: "pattern already exists").
  4. documented_absent honor -- a citation-check receipt's own
     documented_absent record ({"doc","ref","marker","line"}) discloses a
     `ref` as verified-absent; the SAME probe re-flagging that exact ref as
     a fresh custody violation fights the corpus's own honest disclosure.
     Classifies `documented_absent`, non-fatal.
  5. Non-path citations -- a `{ts}`-style curly-brace placeholder (added to
     the pattern-metachar set) and one evidence-backed prose fragment that
     happens to parse as a path ("the existing receipts/ledger/view
     mechanism", every segment starting with a letter) join pattern_citation.
  7. Annex attestation (DESIGN RULING item 7) -- for a genuinely-missing
     citation whose sha256 was recorded, at some point, by ANY historical
     receipts/spend-annex/spend-annex-*.json scan (not just the newest --
     a file deleted since an OLDER scan only ever appears in that older
     snapshot), classifies `annex_attested`: weaker-but-honest evidence the
     file was once real, distinct from an unverified cited_missing claim.

Evidence-side cures (git-history file restoration for genuinely-lost
receipts; a dated disposition note for the honest residue) are DELIBERATELY
OUT OF SCOPE for this probe -- separate follow-up lanes per the DESIGN
RULING (items 6 and 8).

Issue #535 cure (twin-resolution) -- a cited path renamed with a
`-redacted-edition` suffix at landing time (repo-guard's local-path/name
scrub applied post-hoc to a file whose downstream citers were never
updated) is citation drift, not missing evidence: if
`<same-dir>/<stem>-redacted-edition<ext>` exists and is tracked at HEAD,
the citation resolves `resolved_redacted` (own sidecar bucket, disclosed,
never silently dropped) instead of `cited_missing`. Distinct from cure 2
(relocation) because the basename itself changes via a fixed suffix in the
SAME directory, not a move to a different directory -- a basename-
uniqueness index can never catch it. A cited path with no such twin still
counts `cited_missing` unchanged (negative control,
c_custody_twin_resolution_test.py). The `documented_absent` convention
(docs/custody-disposition-20260708.md) remains a prose disposition record
this probe does NOT consume programmatically -- its rows stay honestly
`cited_missing` unless resolved by a twin, a relocation, or an annex
attestation; see that doc's dated addendum for the current tree's
per-row disposition.
"""

import fnmatch
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Keep status output reproducible on default Windows CP1252 consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- Locate <execution-root> robustly ----------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT)
    if p
]
sys.path.insert(0, REPO_ROOT)
from scripts.redact_local_paths import normalize_json_paths

ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def _get_git_tracked_files(root):
    """Return set of all tracked file paths (relative to root) via git ls-files."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return set(p.replace("\\", "/") for p in result.stdout.strip().split("\n") if p)
        return set()
    except Exception:
        return set()


def _load_json_with_fallback(path):
    """Load JSON from path, trying utf-8 then utf-8-sig. Return (data, None) on success,
    (None, error_str) on failure."""
    for encoding in ["utf-8", "utf-8-sig"]:
        try:
            with open(path, "r", encoding=encoding) as fh:
                data = json.load(fh)
            return data, None
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            if encoding == "utf-8-sig":
                return None, str(e)
            continue
    return None, "Failed both utf-8 and utf-8-sig"


def _clean_citation(raw):
    """Strip closed source-location syntax from a receipt citation.

    `::field.path` names a field inside the base file. A trailing numeric
    `:line`, `:start-end`, or `:line,line` suffix names source locations,
    never filename bytes. Arbitrary nonnumeric colon suffixes remain literal
    and therefore fail closed if absent.
    """
    if "::" in raw:
        raw = raw.split("::", 1)[0]
    raw = raw.rstrip("`,;.")
    return re.sub(r":(?:\d+(?:[-,]\d+)*)?$", "", raw)


def _is_wrap_joined_record(obj):
    """True iff obj is exactly the record shape scripts/check_goal_citations.py
    appends to its `wrap_joined` list: {"doc":str, "ref":str, "joined":str,
    "line":int}. When a citation-check receipt (receipts/citation-check-*.json)
    carrying one of these is scanned by THIS probe's generic recursive
    extractor, the truncated `ref` fragment used to be re-ingested as its own
    (bogus) missing citation -- issue #415 cure 1. All four keys/types are
    required so this can't collide with an unrelated receipt shape."""
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("doc"), str)
        and isinstance(obj.get("ref"), str)
        and isinstance(obj.get("joined"), str)
        and isinstance(obj.get("line"), int)
    )


def _is_documented_absent_record(obj):
    """True iff obj is exactly the record shape check_goal_citations.py
    appends to its `documented_absent` list: {"doc":str, "ref":str,
    "marker":str, "line":int}. Issue #415 cure 4: a citation the corpus's own
    citation-check already discloses as verified-absent is an honest
    disclosure, not a fresh custody violation."""
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("doc"), str)
        and isinstance(obj.get("ref"), str)
        and isinstance(obj.get("marker"), str)
        and isinstance(obj.get("line"), int)
    )


def _extract_citations(obj, citations=None, documented_absent_refs=None):
    """Recursively extract all receipts/ paths cited in obj (dict/list).
    Returns (citations, documented_absent_refs) -- two normalized path sets.
    wrap_joined / documented_absent record shapes (see above) are consumed
    specially rather than falling through the generic per-key regex sweep."""
    if citations is None:
        citations = set()
    if documented_absent_refs is None:
        documented_absent_refs = set()

    if isinstance(obj, dict):
        if _is_wrap_joined_record(obj):
            joined = obj["joined"]
            if "receipts/" in joined:
                m = re.search(r"(receipts/[^\s\"']+)", joined)
                if m:
                    citations.add(_clean_citation(m.group(1)))
            for k, v in obj.items():
                if k in ("ref", "joined"):
                    continue  # never re-ingest the truncated fragment itself
                _extract_citations(v, citations, documented_absent_refs)
            return citations, documented_absent_refs

        if _is_documented_absent_record(obj):
            ref = obj["ref"]
            if "receipts/" in ref:
                m = re.search(r"(receipts/[^\s\"']+)", ref)
                if m:
                    documented_absent_refs.add(_clean_citation(m.group(1)))
            for k, v in obj.items():
                if k == "ref":
                    continue
                _extract_citations(v, citations, documented_absent_refs)
            return citations, documented_absent_refs

        for k, v in obj.items():
            # Look for fields that might cite receipt paths -- KEYS as well as
            # values (issue #437: a per-path map keyed by the receipt path
            # itself, e.g. {"receipts/x.json": true}, hid its citation from a
            # value-only scan for three days before it surfaced by accident).
            if isinstance(k, str) and "receipts/" in k:
                m = re.search(r"(receipts/[^\s\"']+)", k)
                if m:
                    citations.add(_clean_citation(m.group(1)))
            if isinstance(v, str) and "receipts/" in v:
                # Extract path starting from receipts/
                m = re.search(r"(receipts/[^\s\"']+)", v)
                if m:
                    citations.add(_clean_citation(m.group(1)))
            _extract_citations(v, citations, documented_absent_refs)
    elif isinstance(obj, list):
        for item in obj:
            _extract_citations(item, citations, documented_absent_refs)

    return citations, documented_absent_refs


# Characters that mark a cited string as a regex/glob literal rather than a
# concrete file path (issue #410): `*` and `?` (glob), `[` `]` (char class),
# `(` `)` (grouping / prose parenthetical), `<` `>` (placeholder), `\` (regex
# escape), `+` (quantifier / glob-alt). `{` `}` added (issue #415 cure 5): a
# `{ts}`-style curly-brace template placeholder is the identical shape as
# `<named>`, just a different bracket style.
_CITATION_METACHARS = frozenset("*?[]()<>\\+{}")

# Evidence-backed allowlist of prose fragments that parse as a path (every
# segment starts with a letter, so the punctuation heuristic below can't
# catch them) but are not citations at all (issue #415 cure 5). Explicit and
# narrow on purpose -- never a broad heuristic that could hide a genuine miss.
_KNOWN_PROSE_FRAGMENTS = frozenset({
    # "Specify ground truth source: ... (b) the existing receipts/ledger/view
    # mechanism (already local)." -- receipts/c52-adversarial-pass-20260612T175700Z.json:63.
    # Names a mechanism, not a file; issue #415 enumeration bucket (c) row 15.
    "receipts/ledger/view",
    # Historical prose says "receipts/custody corrections merged to master";
    # this is a subsystem phrase, not a receipt or directory reference.
    # Exact-only: similarly named concrete files remain checkable.
    "receipts/custody",
})

# Literal path strings that are hardcoded schema-example constants baked
# into every receipts/ember-mvp/*/cycle-20260617T000000Z-0001.json fixture's
# `receipts` / `evidence` blocks (confirmed identical across the 3 sibling
# receipts under receipts/ember-mvp/{kaggle-external-heldout-script-wheel,
# cycle-official-runner-bound, core-loop-attempt-1}-20260618/) -- conventional
# documentation of a naming convention, never a real per-run artifact path.
# The replay/rollback/state_substrate entries are the SAME convention for a
# theoretical "state-substrate/" companion tree that was never built in this
# repo at all (no state-substrate/ directory exists anywhere) -- the greedy
# extractor's mis-rooting (matching "receipts/" as a substring inside
# "state-substrate/receipts/...") produces exactly these truncated strings,
# which is why they're listed in their post-extraction (mis-rooted) form,
# not their real, doubly-nonexistent full value. Issue #415 cure 3.
SCHEMA_CONSTANT_VALUES = frozenset({
    "receipts/observations/obs-20260617T000000Z-0001.json",   # "observation" field
    "receipts/sandbox/cycle-20260617T000000Z-0001.json",      # "sandbox" field
    "receipts/governor/cycle-20260617T000000Z-0001.json",     # "gpu_governor" / "governor" field
    "receipts/benchmark/cycle-20260617T000000Z-0001.json",    # "benchmark" field
    "receipts/wheel/cycle-20260617T000000Z-0001.json",        # "wheel" field
    "receipts/verifier/cycle-20260617T000000Z-0001.json",     # "verifier" field
    "receipts/replay/statecommit-20260617T000000Z-0001.json",     # "replay" field, mis-rooted
    "receipts/rollback/statecommit-20260617T000000Z-0001.json",   # "rollback" field, mis-rooted
    "receipts/commits/statecommit-20260617T000000Z-0001.json",    # "state_substrate" field, mis-rooted
})


def _classify_citation(path):
    """Classify a receipts/ citation string as "concrete" (a real, checkable
    file path) or "pattern" (a regex/glob literal or a prose fragment swept
    in by the citation-extraction regex). Only "concrete" citations are
    checked for existence / counted toward cited_missing."""
    if path in _KNOWN_PROSE_FRAGMENTS:
        return "pattern"
    if any(ch in _CITATION_METACHARS for ch in path):
        return "pattern"
    if path.endswith("/"):
        # bare directory reference (e.g. "receipts/") -- not a checkable file
        return "pattern"
    for seg in path.split("/"):
        if seg and not re.match(r"^[A-Za-z0-9_]", seg):
            # a real path segment never starts with punctuation; a segment
            # like "-style" is a prose fragment (e.g. "a receipts/-style gate"),
            # not a cited path
            return "pattern"
    return "concrete"


def _is_tracked_populated_dir(root, git_tracked_normalized, rel_path):
    """True iff rel_path is a real directory on disk under root AND at least
    one git-tracked file lives under it (issue #415 cure 1: a bare,
    no-extension citation that names a real, populated directory is a
    directory reference, not a missing file -- checked with isdir(), not
    isfile())."""
    full = os.path.join(root, rel_path)
    if not os.path.isdir(full):
        return False
    prefix = rel_path.rstrip("/") + "/"
    return any(p.startswith(prefix) for p in git_tracked_normalized)


def _build_basename_index(git_tracked_normalized):
    """basename -> sorted list of distinct git-tracked receipts/ paths
    carrying that basename (issue #415 cure 2). Scoped to receipts/ so a
    same-named script or doc elsewhere in the tree can never be mistaken for
    a relocated receipt."""
    index = {}
    for p in git_tracked_normalized:
        if not p.startswith("receipts/"):
            continue
        base = p.rsplit("/", 1)[-1]
        index.setdefault(base, set()).add(p)
    return {base: sorted(paths) for base, paths in index.items()}


def _resolve_relocation(cited_path, basename_index):
    """Return the new path if cited_path's basename matches EXACTLY ONE
    tracked receipts/ file elsewhere in the tree, else None. A non-unique
    basename match is never guessed at (issue #415 cure 2)."""
    base = os.path.basename(cited_path)
    candidates = basename_index.get(base, [])
    if len(candidates) == 1 and candidates[0] != cited_path:
        return candidates[0]
    return None


def _resolve_redaction_twin(cited_path, git_tracked_normalized):
    """Return the redacted-edition twin path if cited_path is absent but a
    `<same-dir>/<stem>-redacted-edition<ext>` file exists AND is tracked at
    HEAD, else None (issue #535 twin-resolution rule).

    Evidence: at first landing, several receipts were renamed with the
    `-redacted-edition` suffix (repo-guard's local-path/name scrub applied
    post-hoc), e.g. `receipts/ceff-RESOLVED-20260703T124623Z-import-edition.json`
    -> `...-import-edition-redacted-edition.json`. Downstream citers still
    cite the pre-rename filename, so the checker resolves every renamed
    target as missing even though the (redacted) content is present and
    tracked. This is citation drift from a rename, not lost evidence --
    distinct from `relocated` (issue #415 cure 2, a basename move to a new
    DIRECTORY) because here the basename itself changes via a fixed,
    convention-bound suffix in the SAME directory, so a basename-uniqueness
    index can never catch it.

    Only ever matches same-directory, same-stem + exactly the
    `-redacted-edition` suffix -- never a fuzzy/near-name guess."""
    stem, ext = os.path.splitext(cited_path)
    if not ext:
        return None
    twin = f"{stem}-redacted-edition{ext}"
    if twin in git_tracked_normalized:
        return twin
    return None


def _load_all_spend_annex_rows(root):
    """path -> {"sha256":..., "annex_source":...}, merged across EVERY
    receipts/spend-annex/spend-annex-*.json snapshot (not just the newest --
    a file deleted since an OLDER scan only ever appears in that older
    snapshot; test_c_neg1.py's newest-only lookup serves a different,
    anti-staleness purpose and would miss exactly the historical rows this
    cure exists to surface). Sorted ascending so a later snapshot's row for
    the same path wins on conflict -- deterministic, no wall-clock read.
    Issue #415 cure 7 (annex attestation)."""
    by_path = {}
    pattern = os.path.join(root, "receipts", "spend-annex", "spend-annex-*.json")
    for annex_path in sorted(glob.glob(pattern)):
        try:
            with open(annex_path, "r", encoding="utf-8-sig") as fh:
                annex = json.load(fh)
        except Exception:
            continue
        if not isinstance(annex, dict) or not isinstance(annex.get("rows"), list):
            continue
        rel_source = os.path.relpath(annex_path, root).replace("\\", "/")
        for row in annex["rows"]:
            if (isinstance(row, dict) and isinstance(row.get("path"), str)
                    and isinstance(row.get("sha256"), str)):
                by_path[row["path"]] = {"sha256": row["sha256"], "annex_source": rel_source}
    return by_path


ALLOWLIST_AUTHORITY_REL = "scripts/ember_totality/custody-allowlist.json"
ALLOWLIST_SCHEMA_VERSION = "ember-c-custody-allowlist-v1"

# This probe is bound to exactly one goal/workstream (see the file header).
# An allowlist authority file is honored ONLY when its declared identity
# matches this binding exactly -- a copied/mismatched allowlist (wrong
# workstream, or missing one of the three identity fields) grants NO
# authority, even if its schema_version and patterns are otherwise valid.
ALLOWLIST_BOUND_GOAL_ID = "EMBER-02"
ALLOWLIST_BOUND_WORKSTREAM_ID = "EMBER-02A"
ALLOWLIST_BOUND_NEXT_EXECUTED_OUTCOME = (
    "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
)


def _read_committed_blob(root, rel_path):
    """Return the raw bytes of rel_path as recorded in the HEAD commit (via
    `git show HEAD:<path>`), or None if it cannot be read there (not tracked
    at HEAD, no HEAD yet, etc). This bypasses the mutable working tree
    entirely -- an uncommitted edit to a tracked authority file can never
    change what this probe reads, since `git show` reads the committed blob
    regardless of working-tree state (round-2 repair, PR951 clause 1: the
    prior version read the working-tree file after only checking `git
    ls-files`, so an uncommitted edit could authorize receipts)."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=root,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return None


def _parse_json_bytes_with_fallback(raw_bytes):
    """Same fallback contract as _load_json_with_fallback but for bytes
    already read (e.g. from `git show`) rather than a file path."""
    for encoding in ["utf-8", "utf-8-sig"]:
        try:
            return json.loads(raw_bytes.decode(encoding)), None
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            if encoding == "utf-8-sig":
                return None, str(e)
            continue
    return None, "Failed both utf-8 and utf-8-sig"


def _get_allowlist_from_tracked_authority(root, tracked_files):
    """Load basename patterns only from the separately tracked authority file,
    read at its COMMITTED HEAD blob -- never the working-tree bytes.

    Fail-closed on ANY schema deviation: wrong/missing schema_version, any of
    the three required identity fields (goal_id, workstream_id,
    next_executed_outcome) missing or not matching this probe's own bound
    workstream, or a non-list/non-string pattern set. Round-2 repair
    (PR951): the prior version validated only schema_version + pattern
    string-ness, so an allowlist authored for a DIFFERENT workstream (or one
    missing an identity field) was silently honored here.
    """
    if ALLOWLIST_AUTHORITY_REL not in tracked_files:
        return set()
    raw = _read_committed_blob(root, ALLOWLIST_AUTHORITY_REL)
    if raw is None:
        return set()
    try:
        data, _ = _parse_json_bytes_with_fallback(raw)
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    if data.get("schema_version") != ALLOWLIST_SCHEMA_VERSION:
        return set()
    if data.get("goal_id") != ALLOWLIST_BOUND_GOAL_ID:
        return set()
    if data.get("workstream_id") != ALLOWLIST_BOUND_WORKSTREAM_ID:
        return set()
    if data.get("next_executed_outcome") != ALLOWLIST_BOUND_NEXT_EXECUTED_OUTCOME:
        return set()
    patterns = data.get("allowed_receipt_basenames", [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        return set()
    return set(patterns)


def _validate_allowlist_pattern(pattern):
    """Fail-closed pre-match validation of a single allowlist pattern
    (round-2 repair, PR951 clause 2). This allowlist only ever needs to
    express a basename glob using "*"/"?" wildcards -- path separators,
    parent-directory traversal, and bracket/brace constructs are not
    supported syntax here, so a pattern using any of them is rejected
    outright (grants no authority) rather than falling through to
    fnmatch with an ambiguous or surprising interpretation.

    Returns True iff pattern is safe to hand to fnmatch."""
    if not isinstance(pattern, str) or not pattern:
        return False
    if "/" in pattern or "\\" in pattern:
        return False
    if ".." in pattern:
        return False
    if "[" in pattern or "]" in pattern or "{" in pattern or "}" in pattern:
        return False
    return True


def _is_match_pattern(basename, patterns):
    """Check if basename matches any pattern in patterns, using glob
    semantics (fnmatch, case-sensitive) -- but only after each pattern
    passes _validate_allowlist_pattern. An invalid pattern is dropped
    before matching and disclosed on stderr; it grants no authority.

    Round-2 repair (PR951): the prior version hand-translated patterns
    containing "*"/"?" into a regex via naive string substitution and fed
    them to re.match -- a malformed pattern (e.g. an unbalanced "[") produced
    an invalid regex that raised uncaught, crashing main(). fnmatch.translate
    never raises on malformed glob input (an unterminated "[" degrades to a
    literal bracket rather than an open character class), so matching is
    fail-closed by construction: a malformed pattern simply fails to match
    anything it wasn't exactly meant to, it never crashes the probe and it
    never silently authorizes an unrelated receipt. The pre-match validation
    above adds a second, independent fail-closed layer: separator/traversal/
    bracket-or-brace patterns are rejected before fnmatch ever sees them.
    """
    safe_patterns = []
    for pattern in patterns:
        if _validate_allowlist_pattern(pattern):
            safe_patterns.append(pattern)
        else:
            print(
                f"C-CUSTODY: rejecting unsafe allowlist pattern (no authority "
                f"granted): {pattern!r}",
                file=sys.stderr,
            )
    return any(fnmatch.fnmatchcase(basename, pattern) for pattern in safe_patterns)


def _get_last_landing_time(root):
    """Return the commit timestamp (seconds since epoch) of the most recent master commit
    touching receipts/ or scripts/ember_totality/receipts-*. Returns None if no such commit found."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", "receipts/", "scripts/ember_totality/receipts-*"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except Exception:
        pass
    return None


def _write_sidecar(root, receipt_obj):
    """Write receipt_obj to receipts-custody/<timestamp>.json, fsync'd.
    Returns the relative path to the sidecar file."""
    sidecar_dir = os.path.join(root, "scripts", "ember_totality", "receipts-custody")
    os.makedirs(sidecar_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sidecar_path = os.path.join(sidecar_dir, f"custody-{ts}.json")

    normalized, _ = normalize_json_paths(receipt_obj, Path(root))
    with open(sidecar_path, "w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())

    return os.path.relpath(sidecar_path, root).replace("\\", "/")


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-CUSTODY: execution root not found")

    receipts_dir = os.path.join(ROOT, "receipts")
    if not os.path.isdir(receipts_dir):
        emit("RED", "C-CUSTODY: receipts/ directory not found")

    # --- (A) Enumerate all receipts/ files -------
    patterns = [
        os.path.join(receipts_dir, "*.json"),
        os.path.join(receipts_dir, "**", "*.json"),
    ]
    found_files = set()
    for pat in patterns:
        found_files.update(glob.glob(pat, recursive=True))

    if not found_files:
        emit("GREEN", "C-CUSTODY: receipts/ empty (nothing to custody-check)")

    # --- (B) Get git tracking info -------
    git_tracked = _get_git_tracked_files(ROOT)

    # Normalize paths for comparison (git uses forward slashes)
    git_tracked_normalized = set(p.replace("\\", "/") for p in git_tracked)
    allowlist = _get_allowlist_from_tracked_authority(ROOT, git_tracked_normalized)

    # --- (C) Compute last_landing for age-window classification -------
    last_landing_ts = _get_last_landing_time(ROOT)

    # --- (D) Check three failure shapes -------
    failures = []
    pending_landing = []
    citations_to_verify = set()
    documented_absent_refs = set()

    for fpath in sorted(found_files):
        rel_path = os.path.relpath(fpath, ROOT).replace("\\", "/")
        basename = os.path.basename(fpath)

        # Shape (a): Untracked check. Authority is loaded once from the
        # separately tracked surface; a receipt cannot self-whitelist.
        if rel_path not in git_tracked_normalized:
            if not _is_match_pattern(basename, allowlist):
                # A non-allowlisted receipt is always a custody failure. Keep
                # age classification as disclosure, but never bypass the RED gate.
                file_mtime = os.path.getmtime(fpath)
                if last_landing_ts is not None and file_mtime > last_landing_ts:
                    pending_landing.append(f"UNTRACKED: {rel_path} (mtime={int(file_mtime)})")
                failures.append(f"UNTRACKED: {rel_path}")

        # Shape (b): Unparseable check
        data, json_error = _load_json_with_fallback(fpath)
        if data is None:
            failures.append(f"UNPARSEABLE: {rel_path} ({json_error})")
            continue

        # Shape (c): Extract citations for later verification
        _extract_citations(data, citations_to_verify, documented_absent_refs)

    # --- (E) Check cited paths exist -- issue #415 cure ladder -------
    basename_index = _build_basename_index(git_tracked_normalized)
    annex_rows_by_path = _load_all_spend_annex_rows(ROOT)

    missing_citations = []
    pattern_citations = []
    relocated_citations = []
    documented_absent_citations = []
    annex_attested_citations = []
    redacted_twin_citations = []

    for cited_path in sorted(citations_to_verify):
        if _classify_citation(cited_path) == "pattern":
            pattern_citations.append(f"PATTERN: {cited_path}")
            continue

        full_path = os.path.join(ROOT, cited_path)
        if os.path.isfile(full_path):
            # Resolves outright -- covers backtick/::-suffix-stripped and
            # wrap_joined-consumed citations, which now check out cleanly.
            continue

        # Issue #535 twin-resolution: the cited file was renamed with a
        # `-redacted-edition` suffix at landing time; the renamed twin is
        # present and tracked, so this is citation drift, not missing
        # evidence. Checked before the relocation/annex cures below since
        # it is a more specific, higher-confidence match (exact same-dir,
        # same-stem, fixed-suffix rule) than a basename-uniqueness guess.
        redacted_twin = _resolve_redaction_twin(cited_path, git_tracked_normalized)
        if redacted_twin:
            redacted_twin_citations.append({"old": cited_path, "new": redacted_twin})
            continue

        # Cure 1 tail: bare, no-extension citation naming a real, populated
        # tracked directory (not a missing file).
        if _is_tracked_populated_dir(ROOT, git_tracked_normalized, cited_path):
            pattern_citations.append(
                f"PATTERN (bare-directory, tracked-populated): {cited_path}")
            continue

        # Cure 3: hardcoded schema-example constant -- conventional
        # documentation, never a real per-run citation.
        if cited_path in SCHEMA_CONSTANT_VALUES:
            pattern_citations.append(f"PATTERN (schema-constant): {cited_path}")
            continue

        # Cure 4: the corpus's own citation-check already discloses this ref
        # as verified-absent -- honor the honest disclosure.
        if cited_path in documented_absent_refs:
            documented_absent_citations.append(cited_path)
            continue

        # Cure 2: unique-basename relocation match.
        relocated_to = _resolve_relocation(cited_path, basename_index)
        if relocated_to:
            relocated_citations.append({"old": cited_path, "new": relocated_to})
            continue

        # Cure 7: a historical spend-annex snapshot recorded this exact
        # path's sha256 at some earlier scan time -- weaker-but-honest
        # evidence it was once real.
        annex_row = annex_rows_by_path.get(cited_path)
        if annex_row:
            annex_attested_citations.append({
                "path": cited_path,
                "sha256": annex_row["sha256"],
                "annex_source": annex_row["annex_source"],
            })
            continue

        missing_citations.append(cited_path)

    # cited_missing is the TRUE, uncapped total -- never truncated in either
    # the count or the listed offenders (issue #415 acceptance).
    if missing_citations:
        failures.extend([f"CITED-MISSING: {p}" for p in missing_citations])

    # --- (F) Emit result -------
    if failures:
        # Create a custody receipt with findings
        receipt_obj = {
            "ticket": "C-CUSTODY-CHK",
            "ts": datetime.now(timezone.utc).isoformat(),
            "failures": failures,
            "failure_count": len(failures),
            "pending_landing_count": len(pending_landing),
            "offenders": {
                "untracked": [f for f in failures if f.startswith("UNTRACKED:")],
                "unparseable": [f for f in failures if f.startswith("UNPARSEABLE:")],
                "cited_missing": [f for f in failures if f.startswith("CITED-MISSING:")],
                "pattern_citation": pattern_citations,
                "relocated": relocated_citations,
                "documented_absent": documented_absent_citations,
                "annex_attested": annex_attested_citations,
                "resolved_redacted": redacted_twin_citations,
            },
            "pending_landing": pending_landing,
        }
        sidecar_path = _write_sidecar(ROOT, receipt_obj)
        emit("RED", f"C-CUSTODY: {len(failures)} custody violation(s) detected; "
                    f"untracked={len(receipt_obj['offenders']['untracked'])} "
                    f"unparseable={len(receipt_obj['offenders']['unparseable'])} "
                    f"cited_missing={len(receipt_obj['offenders']['cited_missing'])} "
                    f"pattern={len(pattern_citations)} "
                    f"relocated={len(relocated_citations)} "
                    f"documented_absent={len(documented_absent_citations)} "
                    f"annex_attested={len(annex_attested_citations)} "
                    f"resolved_redacted={len(redacted_twin_citations)} "
                    f"pending_landing={len(pending_landing)}; "
                    f"sidecar={sidecar_path}")

    # GREEN: write sidecar even on success (zero-offender receipt)
    receipt_obj = {
        "ticket": "C-CUSTODY-CHK",
        "ts": datetime.now(timezone.utc).isoformat(),
        "failures": [],
        "failure_count": 0,
        "pending_landing_count": 0,
        "offenders": {
            "untracked": [],
            "unparseable": [],
            "cited_missing": [],
            "pattern_citation": pattern_citations,
            "relocated": relocated_citations,
            "documented_absent": documented_absent_citations,
            "annex_attested": annex_attested_citations,
            "resolved_redacted": redacted_twin_citations,
        },
        "pending_landing": [],
    }
    sidecar_path = _write_sidecar(ROOT, receipt_obj)
    emit("GREEN", f"C-CUSTODY: all receipts in receipts/ are git-tracked, "
                  f"parseable as JSON, and cited paths exist "
                  f"({len(found_files)} files checked, 0 violations); "
                  f"pattern={len(pattern_citations)} "
                  f"relocated={len(relocated_citations)} "
                  f"documented_absent={len(documented_absent_citations)} "
                  f"annex_attested={len(annex_attested_citations)} "
                  f"resolved_redacted={len(redacted_twin_citations)} "
                  f"pending_landing={len(pending_landing)}; "
                  f"sidecar={sidecar_path}")


if __name__ == "__main__":
    main()
