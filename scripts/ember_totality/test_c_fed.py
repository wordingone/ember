#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test — Condition C-FED (status probe / TDD).

C-FED — federation design (free compute, egress-gated; user reframe 2026-06-23).
  R: a DESIGN-ONLY federation organ (checkpoint portability across substrates,
     work-sharding, receipt-merge) for Kaggle/Colab/HF, with an explicit
     EGRESS MANIFEST naming exactly what data would leave the PC, to whom,
     per-avenue.
  Does NOT count:
    - any actual egress of Ember data/weights/code without the user's explicit
      per-avenue go (escalation set);
    - a federation claim with no egress manifest;
    - treating free compute as already-authorized.
  Invalid-token (explicit ✗): invalid_unapproved_egress
  CHK: federation design + egress manifest present; a check proves ZERO
     outbound transfer occurred without a recorded per-avenue user approval.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> — never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is <local-mount-point>/ on this host (NOT /mnt<local-mount-point>/).
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import glob
import hashlib
import os
import re
import subprocess
import sys

from evidence_scan_hygiene import is_board_render_output

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Invalid-tokens that the condition declares as NON-counting outcomes.
# C-FED's explicit ✗ token, plus encodings of the three "does NOT count" cases.
INVALID_TOKENS = [
    "invalid_unapproved_egress",          # the explicit ✗ token
    "actual_egress_without_per_avenue_go",  # does NOT count: real egress w/o user per-avenue approval
    "federation_claim_without_egress_manifest",  # does NOT count: federation claim, no egress manifest
    "free_compute_treated_as_authorized",  # does NOT count: free compute treated as already-authorized
]

# The federation DESIGN organ must name these three mechanisms (R).
DESIGN_MECHANISMS = [
    r"checkpoint[\s_-]*portab",   # checkpoint portability across substrates
    r"work[\s_-]*shard",          # work-sharding
    r"receipt[\s_-]*merge",       # receipt-merge
]

# Free-compute avenues the design + egress manifest must address (R).
AVENUES = ["kaggle", "colab", r"\bhf\b|huggingface|hugging face"]

# Words that, in word-boundary form, indicate a genuine federation/egress doc.
# (NOTE: a plain substring search for "egress" is a TRAP — it matches the
#  middle of "regression". This test uses word boundaries to avoid that.)
WORD_FEDERATION = re.compile(r"\bfederation\b|\bfederat\w*\b", re.IGNORECASE)
WORD_EGRESS = re.compile(r"\begress\b", re.IGNORECASE)

# An "egress manifest" must enumerate, per avenue, WHAT leaves and TO WHOM.
EGRESS_MANIFEST_PHRASE = re.compile(
    r"egress[\s_-]*manifest", re.IGNORECASE)

# A recorded per-avenue user approval marker (the CHK's "recorded approval").
APPROVAL_MARKER = re.compile(
    r"per[\s_-]*avenue.*approv|approv.*per[\s_-]*avenue|user[\s_-]*approv",
    re.IGNORECASE)

# [ISSUE #749 cure, docs/charter/probe-authoring-contract.md checklist item 2] Every
# text/regex keyword check above operates on THIS FILE'S OWN raw bytes -- a
# candidate could satisfy every keyword clause by simply being a freshly-dropped
# untracked (or working-tree-only-edited) file that never went through this
# repo's real commit/review path. Sha-pin the winning candidate to a REAL git
# commit at HEAD: the working-tree bytes actually keyword-matched above must be
# byte-identical to what is committed at HEAD for that same path. A candidate
# that is untracked, or whose working copy has drifted from the committed blob,
# cannot satisfy CHK -- "correct strings, no resolvable git-provenanced artifact"
# is exactly the self-attestation shape this cure exists to close.
GIT_TIMEOUT_SECONDS = 15


def _git_blob_sha256_at_head(root, abs_path):
    """sha256 hexdigest of `abs_path`'s content AS COMMITTED AT HEAD (never the
    working-tree copy), or (None, note) if it cannot be resolved. note is one
    of 'untracked' (git ran fine, no HEAD blob for this path) or
    'git_unavailable' (git missing / not a repo / call failed / timeout)."""
    try:
        rel = os.path.relpath(abs_path, root).replace("\\", "/")
    except ValueError:
        return None, "git_unavailable"
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], cwd=root,
            capture_output=True, timeout=GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None, "git_unavailable"
    if proc.returncode != 0:
        return None, "untracked"
    return hashlib.sha256(proc.stdout).hexdigest(), "ok"


def _sha_pin_candidate(root, abs_path):
    """Verify `abs_path` is git-tracked at HEAD AND its on-disk (working-tree)
    bytes are byte-identical to the committed HEAD blob. Returns (ok: bool,
    detail: str). This is the execution-binding conjunct: it never trusts that
    the file's CONTENT satisfies CHK unless that exact content is also the
    real, reviewed, committed artifact -- an untracked or locally-modified
    forgery fails here even if every keyword clause above matched."""
    try:
        with open(abs_path, "rb") as fh:
            working_bytes = fh.read()
    except OSError as e:
        return False, f"working-tree file unreadable: {e}"
    working_sha = hashlib.sha256(working_bytes).hexdigest()
    committed_sha, note = _git_blob_sha256_at_head(root, abs_path)
    if committed_sha is None:
        return False, f"no committed HEAD blob for this path ({note}) -- not a real git artifact"
    if working_sha != committed_sha:
        return False, (
            f"working-tree sha256 {working_sha[:12]}.. != committed-at-HEAD sha256 "
            f"{committed_sha[:12]}.. -- content keyword-matched is NOT the reviewed/"
            f"committed artifact")
    return True, f"working-tree bytes == committed-at-HEAD blob (sha256 {working_sha[:12]}..)"


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def candidate_files():
    """Files that could carry a C-FED federation-design + egress-manifest
    artifact. Receipt hint: receipts/*fed*, federation design doc, egress
    manifest. We scan dedicated artifact surfaces, NOT the GOAL/STATE files
    (those merely quote the condition text — quoting the goal is not a receipt).

    [ISSUE #97 cure 7, 2026-07-04] receipts/ember-totality-audit/** is
    excluded from candidacy too, defense-in-depth alongside
    negative_scan_files(): an audit report quoting the real federation
    design doc's own terms verbatim (checkpoint-portability/work-sharding/
    kaggle/colab/hf/egress-manifest/approval) could otherwise satisfy every
    positive CHK clause by QUOTATION and become the misattributed `best`
    artifact -- same failure class the spec names for C-PORT's candidate
    discovery."""
    out = set()
    # Dedicated receipt/design surfaces by filename hint.
    name_pats = [
        os.path.join(ROOT, "receipts", "**", "*fed*"),
        os.path.join(ROOT, "receipts", "**", "*egress*"),
        os.path.join(ROOT, "receipts", "**", "*federation*"),
        os.path.join(ROOT, "docs", "**", "*fed*"),
        os.path.join(ROOT, "docs", "**", "*egress*"),
        os.path.join(ROOT, "docs", "**", "*federation*"),
    ]
    for pat in name_pats:
        for p in glob.glob(pat, recursive=True):
            if (
                os.path.isfile(p)
                and not _under_meta_audit_family(p)
                and not is_board_render_output(p)
            ):
                out.add(p)
    # Content-based: any md/json/txt under docs|receipts that actually contains
    # a word-boundary "egress" or "federation" (defeats the regression trap).
    for sub in ("docs", "receipts"):
        base = os.path.join(ROOT, sub)
        for p in glob.glob(os.path.join(base, "**", "*"), recursive=True):
            if not os.path.isfile(p):
                continue
            if os.path.splitext(p)[1].lower() not in (".md", ".json", ".txt"):
                continue
            if _under_meta_audit_family(p):
                continue
            if is_board_render_output(p):
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
            except Exception:
                continue
            if WORD_FEDERATION.search(txt) or WORD_EGRESS.search(txt):
                out.add(p)
    return sorted(out)


# [ISSUE #97 cure 7, 2026-07-04] The #89 board-integrity audit's own receipt
# family DESCRIBES attacks/violation-token findings verbatim (it quotes what
# it inspected) -- it never COMMITS one. Scanning it as ordinary evidence
# flipped C-FED RED on 2026-07-04 (audit-20260704T144656Z.json, which quotes
# "invalid_unapproved_egress" as a finding string, was matched as if it were
# a real disqualifying admission). Audit receipts are receipts ABOUT the
# board and may cite any token; they are never evidence FOR a condition.
META_AUDIT_FAMILY_DIRNAME = "ember-totality-audit"


def _under_meta_audit_family(path):
    """True if META_AUDIT_FAMILY_DIRNAME appears anywhere in path's directory
    components (receipts/ember-totality-audit/** -- any depth, not just a
    direct child), matching the spec's ** exclusion exactly."""
    norm = path.replace("\\", "/")
    parts = norm.split("/")
    return META_AUDIT_FAMILY_DIRNAME in parts[:-1]  # exclude the filename itself


def negative_scan_files():
    """Negative INVALID_TOKENS scan source: receipts/ only (the evidence
    surface), never docs/. [ECHO-FIX 2026-07-03, gh issue #18] docs/
    necessarily carries governing/definitional text -- the registry that
    DEFINES each token, a design doc's own required falsifier catalog quoting
    the registry verbatim, and archived registry snapshots -- none of which is
    evidence a real disqualifying artifact exists. A genuine disqualifying
    admission (an actual unapproved transfer) would manifest as a receipt,
    never as design-doc prose describing what to avoid. (Same repair class as
    test_c_obs.py's evidence-surface fix, landed earlier the same day.)

    [ISSUE #97 cure 7, 2026-07-04] receipts/ember-totality-audit/** (the
    meta-audit receipt family) is excluded -- see META_AUDIT_FAMILY_DIRNAME
    comment above."""
    out = set()
    base = os.path.join(ROOT, "receipts")
    for q in glob.glob(os.path.join(base, "**", "*"), recursive=True):
        if not os.path.isfile(q):
            continue
        if os.path.splitext(q)[1].lower() not in (".md", ".json", ".txt"):
            continue
        if _under_meta_audit_family(q):
            continue
        if is_board_render_output(q):
            continue
        out.add(q)
    return sorted(out)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-FED: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    files = candidate_files()

    # --- Evaluate each candidate for a real federation-design + egress-manifest.
    best = None
    near_miss = []   # files that mention the topic but don't satisfy CHK
    invalid_hits = []  # (file, [tokens]) for negative-assertion reporting

    # --- (2) Negative assertions, evidence surfaces only (receipts/) --------
    # [ECHO-FIX 2026-07-03] see negative_scan_files() docstring.
    for p in negative_scan_files():
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
        except Exception:
            continue
        low = raw.lower()
        hit = [t for t in INVALID_TOKENS if t.lower() in low]
        if hit:
            invalid_hits.append((os.path.relpath(p, ROOT), hit))

    for p in files:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
        except Exception as exc:
            near_miss.append(f"{os.path.basename(p)}: unreadable ({exc})")
            continue
        low = raw.lower()

        # --- (1) Positive CHK against this REAL artifact ----------------------
        # (a) federation DESIGN organ names all three mechanisms.
        mech_ok = all(re.search(m, raw, re.IGNORECASE) for m in DESIGN_MECHANISMS)
        # (b) addresses the free-compute avenues.
        avenue_ok = all(re.search(a, raw, re.IGNORECASE) for a in AVENUES)
        # (c) an explicit egress MANIFEST is present (named as such).
        manifest_ok = bool(EGRESS_MANIFEST_PHRASE.search(raw))
        # (d) the CHK's transfer-gate: a recorded per-avenue user-approval marker
        #     OR an explicit, recorded statement that ZERO outbound transfer
        #     occurred (design-only, nothing has left). Either satisfies
        #     "zero outbound transfer without a recorded per-avenue approval."
        zero_transfer_recorded = bool(
            re.search(r"zero[\s_-]*outbound|no[\s_-]*outbound|design[\s_-]*only|"
                      r"nothing\s+(?:has\s+)?(?:left|leaves)\s+the\s+pc",
                      raw, re.IGNORECASE))
        approval_ok = bool(APPROVAL_MARKER.search(raw)) or zero_transfer_recorded

        # [ISSUE #749 cure] execution-binding conjunct: the candidate's bytes
        # must be the real, committed-at-HEAD artifact -- never independently
        # sufficient alone (AND-composed with every keyword clause above), but
        # decisive: a candidate that satisfies every keyword clause on
        # untracked/drifted bytes still fails CHK.
        sha_pin_ok, sha_pin_detail = _sha_pin_candidate(ROOT, p)

        checks = {
            "design_mechanisms(checkpoint-portab/work-shard/receipt-merge)": mech_ok,
            "avenues(kaggle/colab/hf)": avenue_ok,
            "egress_manifest_named": manifest_ok,
            "transfer_gate(per-avenue-approval or recorded zero-egress)": approval_ok,
            "git_provenance(committed at HEAD, working bytes match committed blob)": sha_pin_ok,
        }
        missing = [k for k, ok in checks.items() if not ok]
        if missing:
            detail_suffix = f" ({sha_pin_detail})" if not sha_pin_ok else ""
            near_miss.append(f"{os.path.relpath(p, ROOT)}: CHK missing {missing}{detail_suffix}")
            continue

        best = os.path.relpath(p, ROOT)
        best_sha_pin_detail = sha_pin_detail
        break

    # --- Resolve verdict ------------------------------------------------------
    # [HARDENED 2026-07-03] an explicit does-NOT-count token on the evidence
    # surface is a hard fail for the CONDITION, never suppressed by a clean
    # positive artifact elsewhere in the tree (negative-control-caught: the
    # old 'and best is None' let a genuine violation receipt coexist with a
    # GREEN design doc).
    if invalid_hits:
        first = invalid_hits[0]
        emit("RED",
             f"C-FED: invalid-token present in {first[0]} {first[1]} "
             f"(does-NOT-count outcome) -> condition NOT met")

    if best is None:
        if not files:
            emit("RED",
                 "C-FED: no federation-design / egress-manifest artifact found "
                 "under docs/ or receipts/ (word-boundary egress|federation absent; "
                 "'regression' substring excluded) -> satisfying artifact ABSENT")
        emit("RED",
             "C-FED: federation/egress text exists but no artifact satisfies CHK "
             "(needs checkpoint-portability + work-sharding + receipt-merge design "
             "for kaggle/colab/hf + a named egress manifest + recorded "
             f"per-avenue-approval/zero-egress) -> {near_miss[:3]}")

    emit("GREEN",
         f"C-FED: federation design + egress manifest present in {best} "
         f"(checkpoint-portability/work-sharding/receipt-merge for kaggle/colab/hf; "
         f"egress manifest named; per-avenue approval or recorded zero-egress); "
         f"git-provenance sha-pinned ({best_sha_pin_detail}); no invalid-token present")


if __name__ == "__main__":
    main()
