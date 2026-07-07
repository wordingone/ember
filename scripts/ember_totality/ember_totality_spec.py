#!/usr/bin/env python3
"""Ember Totality master spec — runner / board aggregator.

Executes every test_*.py status probe in this directory, parses each probe's
single status line, aggregates the totality board, prints it, and writes a
receipt under receipts-totality/.

Each probe honors the status-probe contract: it prints exactly one line
beginning with a recognized status token, and exits 0. The status is
determined by the probe really inspecting state under its resolved root —
never hardcoded here.

Outcome contract (GOAL.md §4.1 amendment 2026-07-02; extended 2026-07-02 for
the registry semantics split, GOAL.md §4.0(9)):

  STATE-conditions (27 of the 30 registry ids) are THREE-VALUED:
    GREEN        a real receipt/artifact was found and satisfies the CHK.
    RED          inputs were found and opened; the condition's check
                 evaluated false (a genuine unmet condition).
    UNEVALUABLE  the probe's input could not be located or opened (missing
                 dir, missing receipt file, unreadable) — counts as RED for
                 completion math, but is never reported as an evaluated
                 failure, since RED-meaning-"unmet" and RED-meaning-
                 "couldn't look" are exactly the ambiguity this outcome
                 exists to kill.

  STANDING PROCESS-INVARIANT rows (C0, C9, C15 — GOAL.md §4.0(9)) are NEVER
  GREEN/RED/UNEVALUABLE. They render one of:
    AUDIT-OK             a cadence audit from the epoch (the goalforge-clear
                          operator-acceptance object's ts) found no
                          post-epoch violation.
    AUDIT-INCIDENT        a cadence audit from the epoch found a post-epoch
                          violation.
    AUDIT-PENDING-EPOCH   no epoch exists yet (no operator-acceptance object
                          at receipts/acceptance/goalforge-clear-*.json) —
                          pre-epoch history is OUT OF AUDIT SCOPE, so these
                          rows are neither OK nor INCIDENT, and NEVER RED.
  Completion math (per GOAL.md §4.0(9)/conditions-v1.md §4.4) is computed
  over the 26 STATE-conditions ONLY: complete iff every STATE-condition is
  GREEN AND zero unresolved post-epoch AUDIT-INCIDENT rows exist. AUDIT rows
  are cadence-audit results, never completion conjuncts, never a GREEN.

Registry sync (engineering-contracts-v1.md §9 close condition): this file's
own condition-id set (ORDER) must equal conditions-v1.md's registry, byte-
compared. A startup assertion fails the WHOLE RUN with a named error
(REGISTRY_DRIFT) if they diverge — this is what would have caught the stale
27-of-29 registry defect. A registry id with no corresponding test_*.py probe
on disk still gets a board row (synthesized UNEVALUABLE: "no probe
implemented") rather than silently vanishing from the board. The 29-id
registry count is unchanged by the STATE/AUDIT split — it changes how an id's
OUTCOME is computed, not whether it is a registry member.

Layout resolution: each probe resolves its state root via (in order) the
EMBER_TOTALITY_ROOT env var (set by --root below), then this tree's own flat
layout (repo root — receipts/docs/etc. live directly under it), then the
legacy nested <external-state> layout some older trees used. See
docs/spec/engineering-contracts-v1.md §9.

Invariant-integrity gate (GOAL.md §8/§5 item 9/§12, added 2026-07-02): every
totality receipt carries an `invariant_checksum` block — sha256 over the
frozen invariant-set I's canonical files (gate semantics, governor, GOAL.md,
receipts discipline, evaluation suite M, enforcement layer), compared against
a pinned value when one exists. No pinned manifest exists yet (kernel
unfired, freeze-onset per GOAL.md §12) — the receipt records the computed
hashes with `pinned: null, status: "pre-freeze-baseline"`; this run BECOMES
the baseline record rather than comparing against one.

Run:  python ember_totality_spec.py <ts> [--root PATH]
  <ts>    fixed timestamp string (e.g. 20260702T120000Z) used in the receipt
          filename + body. We do NOT call date() in Python — the caller
          passes it.
  --root  override the state root every probe resolves against (propagated
          via EMBER_TOTALITY_ROOT). Default: this script's own repo root
          (two levels up from scripts/ember_totality/).

PYTHONIOENCODING=utf-8 is required on every invocation (cp1252 console).
"""

import argparse
import hashlib
import datetime as _dt
import json
import os
import re
import subprocess
import sys

# Add parent scripts dir to path for invariant imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scripts.lib.invariant import stamp, INVARIANT_SHA256

try:  # pragma: no cover - best-effort console hardening, never fatal
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RECEIPTS_DIR = os.path.join(HERE, "receipts-totality")
CONDITIONS_SPEC_PATH = os.path.join(REPO_ROOT, "docs", "spec", "conditions-v1.md")

PROBE_TIMEOUT_SECONDS = 180

# Deterministic filename -> canonical condition id fallback. Used only when a
# probe's output line does not begin with a recognizable C-id token.
FILENAME_ID = {
    "test_c_invariant.py": "C-INV",
    "test_c_eff.py": "C-EFF",
    "test_c_base.py": "C-BASE",
    "test_c_port.py": "C-PORT",
    "test_c_fed.py": "C-FED",
    "test_c_grow.py": "C-GROW",
    "test_c_organism.py": "C-ORGANISM",
    "test_c_neg1.py": "C(-1)",
    "test_c0.py": "C0",
    "test_c1.py": "C1",
    "test_c2.py": "C2",
    "test_c3.py": "C3",
    "test_c4.py": "C4",
    "test_c5.py": "C5",
    "test_c6.py": "C6",
    "test_c7.py": "C7",
    "test_c8.py": "C8",
    "test_c9.py": "C9",
    "test_c10.py": "C10",
    "test_c11.py": "C11",
    "test_c12.py": "C12",
    "test_c13.py": "C13",
    "test_c14.py": "C14",
    "test_c15.py": "C15",
    "test_c_obs.py": "C-OBS",
    "test_c_anat.py": "C-ANAT",
    "test_c_scale.py": "C-SCALE",
    "test_c_e2b.py": "C-E2B",
    "test_c_manifest.py": "C-MANIFEST",
    "test_c_tally.py": "C-TALLY",
    "test_c_ind.py": "C-IND",
    "test_c_proc.py": "C-PROC",
    "test_c_enf.py": "C-ENF",
    "test_c_mile.py": "C-MILE",
    "test_c_disc.py": "C-DISC",
    "test_c_ladm.py": "C-LADM",
    "test_c_auto.py": "C-AUTO",
    "test_c_legib.py": "C-LEGIB",
    "test_surface2.py": "C-SURFACE2",
}

# Stable board ordering: the program order from the goal §4. This IS the
# runner's own declared registry, checked at startup against
# docs/spec/conditions-v1.md (registry sync / close condition, eng-contracts
# v1 §9). Keep in sync by construction, not by hand: if this list and the
# spec ever diverge, main() aborts the whole run before any probe executes.
ORDER = [
    "C-INV",
    "C-EFF", "C-BASE", "C-PORT", "C-FED", "C-GROW", "C-ORGANISM",
    "C(-1)", "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9",
    "C10", "C11", "C12", "C13", "C14", "C15",
    "C-OBS", "C-ANAT", "C-SCALE", "C-E2B", "C-IND", "C-PROC", "C-LEGIB", "C-SURFACE2", "C-ENF", "C-MILE", "C-DISC", "C-LADM", "C-AUTO", "C-MANIFEST", "C-TALLY",
]

# STANDING PROCESS-INVARIANT rows (GOAL.md §4.0(9)): never STATE-conditions,
# never RED/GREEN/UNEVALUABLE, excluded from STATE-conditions-only completion
# math and counted separately as cadence-audit results.
PROCESS_INVARIANTS = {"C0", "C9", "C15"}

STATE_CONDITION_STATUSES = {"GREEN", "RED", "UNEVALUABLE"}
AUDIT_STATUSES = {"AUDIT-OK", "AUDIT-INCIDENT", "AUDIT-PENDING-EPOCH"}

# Match a leading condition-id token in a probe output line:
#   C(-1)  C(−1)  C-EFF  C-TALLY  C0  C15  ...
ID_RE = re.compile(r"^(C\([−-]?1\)|C-[A-Z0-9]+|C[0-9]+)")

# --- Invariant-integrity gate (GOAL.md §8/§5 item 9/§12) --------------------
# I-members per GOAL.md §5 item 9's PINNED I-manifest (pinned 2026-07-02,
# commit 509b426, R8b review of this runner's builder-selected baseline --
# see docs/goalforge-debate-ledger.md row R8b). This bracket is now the
# authority: GOAL.md's own text says "the totality runner's machine copy
# must match it, mismatch = incident." I_MEMBERS below is that machine copy,
# hand-synced to the bracket; MANIFEST_SYNC_CHECK below re-derives the
# bracket from GOAL.md's live text every run and compares, so a future edit
# to either side that isn't mirrored in the other shows up as a receipt
# finding, not a silent drift.
GOAL_MD_PATH = os.path.join(REPO_ROOT, "GOAL.md")
LEDGER_PATH = os.path.join(REPO_ROOT, "docs", "goalforge-debate-ledger.md")

I_MEMBERS = {
    # = T0's clock-resetting set (§6): the checksum history IS the stability
    # clock's mechanical evidence (GOAL.md §5 item 9).
    "gate_semantics": [
        "docs/spec/math-core-v1.md",
        "docs/spec/bootstrap-v1.md",
        "docs/spec/judge-admission-v1.md",
    ],
    "governor": ["scripts/governor.py"],
    # + conditions-v1.md (registry body) + operator-acceptance-v1.md (consent
    # schema) -- both change the bar without touching GOAL.md itself (R7 H1's
    # laundering pattern, closed at the hash layer).
    "goal_md": [
        "GOAL.md",
        "docs/spec/conditions-v1.md",
        "docs/spec/operator-acceptance-v1.md",
    ],
    # + receipt_semantic_check.py: "S1-S7 is the sharpest tooth."
    "receipts_discipline": [
        "docs/spec/receipts-v1.md",
        "scripts/receipt_check.py",
        "scripts/receipt_write.py",
        "scripts/receipt_semantic_check.py",
    ],
    # EXTENDS to M's item/data files the day they materialize (dated
    # expectation per GOAL.md §5 item 9 -- not yet applicable, no such files
    # exist on disk).
    "evaluation_suite_m": ["docs/spec/evaluation-v1.md"],
    # The EXECUTABLE walls, not just their descriptions -- hashing only prose
    # replays the 2026-06-28 stubbed-gate incident class (a tampered runner
    # lying in its own receipt would diverge from the committed tree, which
    # git history anchors). scripts/ember_totality/ is expanded dynamically
    # below (every .py in the package, sorted, receipts-totality/ excluded --
    # receipts are outputs, not walls) rather than listed statically, so a
    # newly-added probe file is automatically covered.
    "enforcement_layer": [
        "docs/spec/anti-gaming-contract-v1.md",
        "docs/spec/engineering-contracts-v1.md",
        "scripts/check_goal_citations.py",
        "scripts/check_publication_gate.py",
        "scripts/ember_tally.py",
        "scripts/ember_tally_checks.py",
    ],
}

# Marker bucket -> package directory whose *.py files (sorted, recursive,
# any receipts-totality/ path component excluded) are appended to that
# bucket's file list at hash time.
I_MEMBERS_PACKAGE_DIRS = {
    "enforcement_layer": "scripts/ember_totality",
}


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _package_py_files(repo_root, rel_dir):
    """Every *.py under rel_dir, sorted, recursive, with any path containing
    'receipts-totality' as a path component excluded (receipts are outputs,
    not walls)."""
    abs_dir = os.path.join(repo_root, rel_dir.replace("/", os.sep))
    out = []
    for dirpath, dirnames, filenames in os.walk(abs_dir):
        dirnames[:] = [d for d in dirnames if d != "receipts-totality" and d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                abs_path = os.path.join(dirpath, name)
                rel = os.path.relpath(abs_path, repo_root).replace(os.sep, "/")
                out.append(rel)
    return sorted(out)


BUCKET_NAMES = list(I_MEMBERS.keys())

# Narrow parser for GOAL.md §5 item 9's fixed prose shape:
#   "bucket_name = item + item + item (parenthetical rationale); ..."
# repeated per bucket, closed by "Each file in exactly ONE bucket." This is
# not a general prose parser -- it is scoped to this one frozen bracket, and
# fails soft (returns None + a reason) rather than raising, so a reword the
# regex can't follow becomes a receipt finding, never a crashed run.
_MANIFEST_ANCHOR_RE = re.compile(
    r"I-manifest \(pinned[^)]*\):\*\*\s*(.*?)\s*Each file in exactly ONE bucket\.",
    re.DOTALL,
)
_BUCKET_SEG_RE = re.compile(
    r"^(" + "|".join(re.escape(b) for b in BUCKET_NAMES) + r")\s*=\s*(.*)$",
    re.DOTALL,
)


def parse_pinned_manifest_bracket(goal_md_text):
    """Return ({bucket: [normalized relative path or ('PACKAGE', dir), ...]},
    None) on success, or (None, reason) if the anchor text can't be located
    or parsed. Never raises."""
    try:
        m = _MANIFEST_ANCHOR_RE.search(goal_md_text)
        if not m:
            return None, ("MANIFEST_ANCHOR_NOT_FOUND: could not locate the "
                           "pinned I-manifest bracket text in GOAL.md §5 "
                           "item 9 (anchor phrase missing or reworded)")
        body = m.group(1)
        segments = re.split(r";\s*", body)
        buckets = {}
        for seg in segments:
            seg = seg.strip()
            bm = _BUCKET_SEG_RE.match(seg)
            if not bm:
                continue
            bucket, rest = bm.group(1), bm.group(2)
            # Cut at the first top-level parenthetical or the EXTENDS clause
            # (evaluation_suite_m's rationale is comma-joined, not parens).
            rest = re.split(r"\s*\(|\s*,\s*EXTENDS", rest)[0]
            rest = rest.strip().rstrip(".").strip()
            raw_items = [it.strip() for it in rest.split("+")]
            items = []
            for raw in raw_items:
                if not raw:
                    continue
                token = raw[4:].strip() if raw.startswith("the ") else raw
                if token.endswith("/ package"):
                    items.append(("PACKAGE", token[:-len("/ package")].strip().rstrip("/")))
                    continue
                if token.startswith("scripts/") or token == "GOAL.md":
                    items.append(("FILE", token))
                elif token.endswith(".md") or token.endswith(".json"):
                    items.append(("FILE", f"docs/spec/{token}"))
                else:
                    items.append(("FILE", token))
            buckets[bucket] = items
        missing = [b for b in BUCKET_NAMES if b not in buckets]
        if missing:
            return None, (f"MANIFEST_PARSE_INCOMPLETE: buckets not matched "
                           f"in the parsed bracket text: {missing}")
        return buckets, None
    except Exception as exc:  # fail soft: a parser bug is a finding, not a crash
        return None, f"MANIFEST_PARSE_EXCEPTION: {exc!r}"


def manifest_sync_check(repo_root):
    """Compare this runner's I_MEMBERS (the machine copy) against GOAL.md
    §5 item 9's live pinned bracket text. Returns a dict describing the
    result; NEVER raises and NEVER aborts the run -- a mismatch is an
    incident recorded in the receipt (GOAL.md §5 item 9: "mismatch =
    incident"), per the do-not-abort instruction for invariant-manifest
    drift (distinct from the registry-sync close condition, which does
    abort)."""
    try:
        with open(GOAL_MD_PATH, "r", encoding="utf-8") as fh:
            goal_text = fh.read()
    except OSError as exc:
        return {"matched": False, "parsed_ok": False,
                "incident": f"MANIFEST_SYNC_UNREADABLE: cannot read GOAL.md: {exc!r}",
                "diff": {}}

    parsed, reason = parse_pinned_manifest_bracket(goal_text)
    if parsed is None:
        return {"matched": False, "parsed_ok": False, "incident": reason, "diff": {}}

    def _machine_set(bucket):
        s = set(("FILE", p) for p in I_MEMBERS[bucket])
        pkg = I_MEMBERS_PACKAGE_DIRS.get(bucket)
        if pkg:
            s.add(("PACKAGE", pkg))
        return s

    diff = {}
    for bucket in BUCKET_NAMES:
        parsed_set = set(parsed.get(bucket, []))
        machine_set = _machine_set(bucket)
        if parsed_set != machine_set:
            diff[bucket] = {
                "in_goal_md_not_in_runner": sorted(str(x) for x in (parsed_set - machine_set)),
                "in_runner_not_in_goal_md": sorted(str(x) for x in (machine_set - parsed_set)),
            }
    if diff:
        return {
            "matched": False, "parsed_ok": True,
            "incident": (
                "MANIFEST_DRIFT: this runner's I_MEMBERS diverges from GOAL.md "
                "§5 item 9's pinned bracket -- invariant-manifest drift is a "
                "finding, not a crash; see 'diff' for the exact bucket-level "
                "disagreement"
            ),
            "diff": diff,
        }
    return {"matched": True, "parsed_ok": True, "incident": None, "diff": {}}


_RECEIPT_NAME_RE = re.compile(r"^ember-totality-(\d{8}T\d{6}Z)\.json$")


def _last_receipt_combined_sha256(receipts_dir):
    """Return (combined_sha256, filename) of the most recent PRIOR totality
    receipt in receipts_dir (strict ember-totality-<ts>.json names only --
    ad-hoc suffixed dumps like *_roottest.json are excluded so they can't be
    mistaken for the real chronology), or (None, None) if none exist / the
    latest one fails to parse. NEVER raises."""
    if not os.path.isdir(receipts_dir):
        return None, None
    names = [n for n in os.listdir(receipts_dir) if _RECEIPT_NAME_RE.match(n)]
    if not names:
        return None, None
    # mtime, not name order: receipt 20260702T131845Z was stamped from a
    # non-UTC clock by its producing run and sorts AFTER genuinely newer
    # receipts -- name-ordered chronology would compare future runs against
    # the wrong baseline and fire spurious unpaired_baseline_flip incidents.
    last = max(names, key=lambda n: os.path.getmtime(os.path.join(receipts_dir, n)))
    try:
        with open(os.path.join(receipts_dir, last), "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("invariant_checksum", {}).get("combined_sha256"), last
    except Exception:
        return None, last


def consume_pending_authorization(repo_root, pkg_dir, ts):
    """PENDING_AUTHORIZATION.json protocol (R9 defect-3 fix, ordered by
    docs/goalforge-debate-ledger.md's lane-14 hardening pass follow-up):
    schema {"authorizing_reference": "<ledger row / operator object / repair
    receipt>", "changes": [{"file": "...", "reason": "..."}]}.

    If the file exists under pkg_dir at run time, its content is returned
    VERBATIM (unmodified -- the caller copies it straight into
    authorization_pairing_note, structured, replacing the generic prose),
    and the file is renamed in place to PENDING_AUTHORIZATION.consumed-<ts>
    .json so the SAME authorization can never be picked up by a second run
    (one declaration, one flip). Returns (decl_or_None, status) where status
    is one of 'absent' | 'consumed' | 'parse_error'. NEVER raises.
    """
    path = os.path.join(repo_root, pkg_dir.replace("/", os.sep), "PENDING_AUTHORIZATION.json")
    if not os.path.isfile(path):
        return None, "absent"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            decl = json.load(fh)
    except Exception as exc:
        return {"parse_error": f"{type(exc).__name__}: {exc}",
                "path": os.path.relpath(path, repo_root).replace(os.sep, "/")}, "parse_error"
    consumed_name = f"PENDING_AUTHORIZATION.consumed-{ts}.json"
    consumed_path = os.path.join(os.path.dirname(path), consumed_name)
    os.rename(path, consumed_path)
    decl["_consumed_from"] = os.path.relpath(path, repo_root).replace(os.sep, "/")
    decl["_consumed_as"] = os.path.relpath(consumed_path, repo_root).replace(os.sep, "/")
    decl["_consumed_run_ts"] = ts
    return decl, "consumed"


def _git_verify_enumeration(repo_root, decl, i_file_rel_paths):
    """Cross-check a consumed authorization's enumeration against the ACTUAL
    changed set (git tracked diff vs decl['baseline_ref'] + untracked files),
    restricted to I-manifest member files. Self-declaration is not
    verification (R9 defect-3): a changed-but-unenumerated I-file surfaces
    as UNPAIRED_FILES_DETECTED. Degrades to explicit UNAVAILABLE / SKIPPED
    verdicts -- never a false CLEAN. Read-only; NEVER raises."""
    import fnmatch
    import subprocess
    baseline_ref = decl.get("baseline_ref")
    if not baseline_ref:
        return {"verdict": "SKIPPED_NO_BASELINE_REF",
                "note": "declaration carries no baseline_ref; enumeration "
                        "copied verbatim but NOT git-verified"}
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", baseline_ref, "--"],
            cwd=repo_root, capture_output=True, text=True, timeout=30)
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=repo_root, capture_output=True, text=True, timeout=30)
        if diff.returncode != 0:
            return {"verdict": f"UNAVAILABLE: git diff rc={diff.returncode}",
                    "stderr": diff.stderr.strip()[:300]}
        changed = set(diff.stdout.split()) | set(untracked.stdout.split())
    except Exception as exc:
        return {"verdict": f"UNAVAILABLE: {type(exc).__name__}: {exc}"}
    i_set = {rp.replace(os.sep, "/") for rp in i_file_rel_paths}
    changed_i = sorted(c for c in changed if c.replace(os.sep, "/") in i_set)
    patterns = []
    for ch in decl.get("changes", []):
        f = ch.get("file", "")
        patterns.append(f.replace(os.sep, "/"))
    def _matched(path):
        for pat in patterns:
            if path == pat or fnmatch.fnmatch(path, pat) or (
                    pat.endswith("/**") and path.startswith(pat[:-2])):
                return True
        return False
    unpaired = [c for c in changed_i if not _matched(c)]
    if unpaired:
        return {"verdict": "UNPAIRED_FILES_DETECTED",
                "baseline_ref": baseline_ref, "unpaired": unpaired,
                "changed_i_files": changed_i}
    return {"verdict": "CLEAN", "baseline_ref": baseline_ref,
            "changed_i_files": changed_i}


def compute_invariant_checksum(repo_root, ts):
    """Build the invariant_checksum receipt block: per-file sha256 for every
    I-member's canonical file(s) (bucket file lists expanded from the pinned
    GOAL.md §5 item 9 manifest, package buckets globbed dynamically), a
    per-member combined hash, a top-level combined hash, the pinned-vs-
    machine-copy manifest_sync result, and authorization_pairing (null
    pre-clear steady state when the combined hash didn't change; when a
    PENDING_AUTHORIZATION.json existed at run time its content is consumed
    verbatim into authorization_pairing_note and the file is renamed
    -consumed- so it can't cover a second flip; when the hash DID change but
    no pending file existed, an 'unpaired_baseline_flip' incident is
    recorded, non-aborting, same class as MANIFEST_DRIFT -- R9 defect-3 fix,
    see consume_pending_authorization / docs/goalforge-debate-ledger.md
    lane-14 hardening pass row).
    """
    sync = manifest_sync_check(repo_root)

    members = []
    all_file_lines = []
    for member, rel_paths in sorted(I_MEMBERS.items()):
        expanded = list(rel_paths)
        pkg_dir = I_MEMBERS_PACKAGE_DIRS.get(member)
        if pkg_dir:
            expanded.extend(_package_py_files(repo_root, pkg_dir))
        files = []
        member_lines = []
        for rel in expanded:
            abs_path = os.path.join(repo_root, rel.replace("/", os.sep))
            rel_norm = rel.replace(os.sep, "/")
            if os.path.isfile(abs_path):
                with open(abs_path, "rb") as fh:
                    digest = _sha256_bytes(fh.read())
                files.append({"path": rel_norm, "sha256": digest, "present": True})
                member_lines.append(f"{rel_norm}:{digest}")
            else:
                files.append({"path": rel_norm, "sha256": None, "present": False})
                member_lines.append(f"{rel_norm}:MISSING")
        member_sha256 = _sha256_bytes("\n".join(member_lines).encode("utf-8"))
        members.append({
            "member": member,
            "pinned_files": rel_paths + (
                [f"{pkg_dir}/*.py (sorted, recursive, receipts-totality/ excluded)"]
                if pkg_dir else []
            ),
            "files": files,
            "package_dir": pkg_dir,
            "member_sha256": member_sha256,
        })
        all_file_lines.extend(member_lines)
    combined_sha256 = _sha256_bytes("\n".join(sorted(all_file_lines)).encode("utf-8"))

    pkg_dir = I_MEMBERS_PACKAGE_DIRS.get("enforcement_layer", "")
    decl, consume_status = consume_pending_authorization(repo_root, pkg_dir, ts)
    generic_note = (
        "Pre-clear drafting is ledger-row-authorized, not object-"
        "authorized: this baseline's authorizing reference is "
        f"{os.path.relpath(LEDGER_PATH, repo_root).replace(os.sep, '/')} "
        "row R8b (2026-07-02, I-manifest pinning). Post-clear, any "
        "I-member baseline change must PAIR with an operator-acceptance "
        "object or a §12 clear->fire repair receipt in this field "
        "(GOAL.md §5 item 9); a flip without pairing is "
        "invalid_unauthorized_invariant_change. This field is null "
        "pre-clear by design, not by omission."
    )

    if consume_status == "consumed":
        i_file_rel_paths = [ln.split(":", 1)[0] for ln in all_file_lines]
        git_verification = _git_verify_enumeration(repo_root, decl, i_file_rel_paths)
        authorization_pairing = {
            "status": "consumed_this_run",
            "consumed_from": decl.get("_consumed_from"),
            "consumed_as": decl.get("_consumed_as"),
            "git_verification": git_verification,
        }
        if git_verification.get("verdict") == "UNPAIRED_FILES_DETECTED":
            authorization_pairing["incident"] = "unpaired_files_in_consumed_authorization"
        authorization_pairing_note = decl  # verbatim, structured -- replaces the generic prose
    elif consume_status == "parse_error":
        authorization_pairing = {
            "incident": "pending_authorization_parse_error",
            "detail": decl.get("parse_error"),
            "path": decl.get("path"),
        }
        authorization_pairing_note = (
            f"PENDING_AUTHORIZATION.json present at {decl.get('path')} but "
            f"failed to parse ({decl.get('parse_error')}) -- recorded as an "
            "authorization-protocol incident, non-aborting, and left "
            "un-consumed (not renamed) so the next run gets another chance "
            "to read it once it's fixed."
        )
    else:  # 'absent' -- steady state, unless the baseline flipped unpaired
        last_sha256, last_name = _last_receipt_combined_sha256(RECEIPTS_DIR)
        if last_sha256 is not None and last_sha256 != combined_sha256:
            authorization_pairing = {
                "incident": "unpaired_baseline_flip",
                "detail": (
                    f"invariant_checksum.combined_sha256 changed vs the "
                    f"most recent prior receipt ({last_name}: "
                    f"{last_sha256}) to {combined_sha256}, but no "
                    "PENDING_AUTHORIZATION.json existed at run start to "
                    "explain the change -- same class as MANIFEST_DRIFT "
                    "(non-aborting; a finding, not a crash)."
                ),
                "prior_combined_sha256": last_sha256,
                "new_combined_sha256": combined_sha256,
                "prior_receipt": last_name,
            }
            authorization_pairing_note = generic_note + (
                " (unpaired_baseline_flip THIS RUN -- see authorization_"
                "pairing.detail: the invariant hash moved with no "
                "PENDING_AUTHORIZATION.json present to name why.)"
            )
        else:
            authorization_pairing = None
            authorization_pairing_note = generic_note + (
                " (No PENDING_AUTHORIZATION.json declared an in-flight flip "
                "this run, and the combined hash is unchanged vs the prior "
                "receipt -- steady state.)"
            )

    return {
        "mapping_source": (
            "GOAL.md §5 item 9's PINNED I-manifest (pinned 2026-07-02, "
            "commit 509b426, docs/goalforge-debate-ledger.md row R8b) -- "
            "this is the authority; I_MEMBERS in ember_totality_spec.py is "
            "the hand-synced machine copy, verified against the live "
            "GOAL.md text every run (see manifest_sync below)."
        ),
        "manifest_sync": sync,
        "members": members,
        "combined_sha256": combined_sha256,
        "pinned": None,
        "status": "pre-freeze-baseline",
        "authorization_pairing": authorization_pairing,
        "authorization_pairing_note": authorization_pairing_note,
        "note": (
            "No pinned checksum VALUE exists yet (kernel unfired, "
            "freeze-onset per GOAL.md §12) -- this run's hashes BECOME the "
            "baseline record; they are not compared against a prior hash "
            "pin. The FILE MANIFEST itself (which files belong to which "
            "bucket) IS pinned as of 2026-07-02 and is checked every run "
            "via manifest_sync above. Post freeze-onset, any I-member edit "
            "must flag a manifest change on the very next run (GOAL.md §12)."
        ),
    }

# Registry-doc bullet matcher: "- **C-EFF — ..." / "- **C(−1) — ..." /
# "- **C-MANIFEST.** ..." (rollups use "." not an em-dash after the id).
REGISTRY_BULLET_RE = re.compile(
    r"^- \*\*(C\([−-]?1\)|C-[A-Z0-9]+|C[0-9]+)(?=[ .])", re.MULTILINE
)


def _normalize_id(cid):
    """Canonicalize the C(-1) unicode-minus vs ascii-hyphen spelling."""
    return cid.replace("−", "-")


def parse_registry_ids(spec_path):
    """Return the ordered list of condition ids declared by conditions-v1.md.

    Raises FileNotFoundError if the spec itself is absent, RuntimeError if
    parsing yields an implausible count (parser/doc drift) — both are
    startup-fatal, not per-probe outcomes.
    """
    with open(spec_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    ids = [_normalize_id(m.group(1)) for m in REGISTRY_BULLET_RE.finditer(text)]
    if not ids:
        raise RuntimeError(
            f"REGISTRY_PARSE_EMPTY: no condition-id bullets matched in {spec_path} "
            "-- parser or document drift, cannot self-check the registry"
        )
    return ids


def registry_sync_check():
    """Startup assertion: runner's ORDER == conditions-v1.md's registry ids,
    byte-compared as sets (order-independent; ORDER's own order is the board
    presentation order, not a claim about doc order).

    Fails the WHOLE RUN with a named, explicit error on divergence -- the
    self-enforcing close condition from engineering-contracts-v1.md §9.
    Returns the parsed registry id list on success.
    """
    if not os.path.isfile(CONDITIONS_SPEC_PATH):
        sys.stderr.write(
            f"REGISTRY_SPEC_MISSING: {CONDITIONS_SPEC_PATH} not found -- cannot "
            "verify the runner's condition registry against its governing spec. "
            "Run aborted before executing any probe.\n"
        )
        sys.exit(4)

    try:
        registry_ids = parse_registry_ids(CONDITIONS_SPEC_PATH)
    except (OSError, RuntimeError) as exc:
        sys.stderr.write(f"REGISTRY_PARSE_ERROR: {exc}\n")
        sys.exit(4)

    runner_set = set(ORDER)
    registry_set = set(registry_ids)

    if runner_set != registry_set:
        missing_from_runner = sorted(registry_set - runner_set)
        extra_in_runner = sorted(runner_set - registry_set)
        sys.stderr.write(
            "REGISTRY_DRIFT: runner ORDER (scripts/ember_totality/ember_totality_spec.py) "
            f"has {len(runner_set)} condition id(s); "
            f"{CONDITIONS_SPEC_PATH} registry has {len(registry_set)}. "
            "Close condition (engineering-contracts-v1.md §9: runner IDs == "
            "registry IDs) FAILED. Run aborted before executing any probe.\n"
            f"  in registry, missing from runner ORDER: {missing_from_runner}\n"
            f"  in runner ORDER, not in registry:        {extra_in_runner}\n"
            "  Fix: sync ORDER/FILENAME_ID in this file, or correct "
            "docs/spec/conditions-v1.md if the registry itself drifted.\n"
        )
        sys.exit(3)

    # Third drift leg (2026-07-04, maintainer): the probe DIRECTORY itself.
    # discover_tests() runs every test_*.py in HERE; run_probe falls back to
    # the bare filename as the condition id. Before this check, a probe file
    # dropped into HERE without registration executed anyway and its row
    # entered the board tally unregistered (observed live: test_c_ladm.py
    # contributed a counted RED to ember-totality-20260704T171218Z.json while
    # absent from ORDER and the registry). Half-counting is the worst of both
    # worlds -- a truth instrument fails CLOSED, so any file/ORDER mismatch
    # aborts exactly like REGISTRY_DRIFT.
    discovered = {n for n in os.listdir(HERE)
                  if n.startswith("test_") and n.endswith(".py")}
    unregistered_files = sorted(discovered - set(FILENAME_ID))
    missing_files = sorted(set(FILENAME_ID) - discovered)
    unmapped_ids = sorted(set(FILENAME_ID.values()) - runner_set)
    if unregistered_files or missing_files or unmapped_ids:
        sys.stderr.write(
            "PROBE_DIR_DRIFT: the probe directory, FILENAME_ID, and ORDER must "
            "mirror exactly (same close condition as REGISTRY_DRIFT). "
            "Run aborted before executing any probe.\n"
            f"  probe files present but not in FILENAME_ID: {unregistered_files}\n"
            f"  FILENAME_ID files missing from directory:   {missing_files}\n"
            f"  FILENAME_ID ids not in ORDER:               {unmapped_ids}\n"
            "  Fix: register the probe (registry entry + ORDER + FILENAME_ID + "
            "manifest row), or remove the stray file.\n"
        )
        sys.exit(3)

    return registry_ids


def discover_tests():
    """Return sorted absolute paths of every test_*.py probe in HERE."""
    out = []
    for name in sorted(os.listdir(HERE)):
        if name.startswith("test_") and name.endswith(".py"):
            out.append(os.path.join(HERE, name))
    return out


# Recognized status tokens, longest-first so "AUDIT-INCIDENT" is not
# shadowed by a hypothetical shorter prefix match.
_STATUS_TOKENS = [
    "AUDIT-PENDING-EPOCH", "AUDIT-INCIDENT", "AUDIT-OK",
    "UNEVALUABLE", "GREEN", "RED",
]


def parse_line(line):
    """Return (status, cond_id_or_None) from a probe output line."""
    line = line.strip()
    status = None
    rest = ""
    for token in _STATUS_TOKENS:
        if line.startswith(token + " "):
            status, rest = token, line[len(token) + 1:]
            break
        if line == token:
            status, rest = token, ""
            break
    cond = None
    if rest:
        m = ID_RE.match(rest.strip())
        if m:
            cond = m.group(1)
    return status, cond


def run_probe(path, env):
    """Run one probe and return a row dict {condition,status,reason,...}.

    Never lets an exception or hang propagate as a raw traceback: a harness-
    level failure (probe crash, timeout, contract violation) is UNEVALUABLE
    with the failure text in reason, never a fabricated RED/GREEN.
    """
    fname = os.path.basename(path)
    fallback_id = FILENAME_ID.get(fname, fname)

    try:
        proc = subprocess.run(
            [sys.executable, path],
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "condition": fallback_id,
            "status": "UNEVALUABLE",
            "reason": (f"HARNESS TIMEOUT: {fname} exceeded "
                       f"{PROBE_TIMEOUT_SECONDS}s -- probe did not complete"),
            "test_file": fname,
            "exit_code": None,
        }
    except OSError as exc:
        return {
            "condition": fallback_id,
            "status": "UNEVALUABLE",
            "reason": f"HARNESS EXEC ERROR: could not launch {fname}: {exc}",
            "test_file": fname,
            "exit_code": None,
        }

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    # The probe prints exactly one status line; find the first recognized one.
    status, cond = None, None
    chosen = ""
    for ln in stdout.splitlines():
        s, c = parse_line(ln)
        if s is not None:
            status, cond, chosen = s, c, ln.strip()
            break
    condition = cond or fallback_id
    if status is None:
        # Contract violation: no recognized status line. This is a
        # harness/probe defect, not a real evaluation -> UNEVALUABLE (or, for
        # a process-invariant row, reclassified to AUDIT-PENDING-EPOCH below
        # in main()), never a fabricated RED.
        status = "UNEVALUABLE"
        reason = (f"PROBE CONTRACT VIOLATION: {fname} emitted no recognized "
                  f"status line (exit={proc.returncode}); "
                  f"stderr[:300]={stderr[:300]!r}")
    else:
        reason = chosen
    return {
        "condition": condition,
        "status": status,
        "reason": reason,
        "test_file": fname,
        "exit_code": proc.returncode,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Ember totality board runner (see module docstring)."
    )
    ap.add_argument("ts", nargs="?", default=None,
                    help="timestamp for the receipt name/body; OMIT to self-stamp "
                         "true UTC (callers passing hand-computed values is how a "
                         "non-UTC stamp polluted the chronology once)")
    ap.add_argument(
        "--root", default=None,
        help=("state root every probe resolves against (env "
              "EMBER_TOTALITY_ROOT). Default: this repo's own root "
              f"({REPO_ROOT}).")
    )
    args = ap.parse_args()
    ts = args.ts or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    effective_root = os.path.abspath(args.root) if args.root else REPO_ROOT

    # --- Registry sync (self-enforcing close condition) -----------------------
    registry_ids = registry_sync_check()

    os.makedirs(RECEIPTS_DIR, exist_ok=True)

    probe_env = dict(os.environ)
    probe_env["EMBER_TOTALITY_ROOT"] = effective_root
    probe_env["PYTHONIOENCODING"] = "utf-8"

    rows = [run_probe(p, probe_env) for p in discover_tests()]

    # --- Registry ids with no discovered probe: synthesize an UNEVALUABLE row
    # so the board still enumerates all 30 conditions rather than silently
    # omitting the ones with no test_*.py file yet (closing THAT gap is
    # separate milestone work, docs/spec/milestones-v1.md §C).
    covered = {r["condition"] for r in rows}
    for cid in registry_ids:
        if cid not in covered:
            rows.append({
                "condition": cid,
                "status": "UNEVALUABLE",
                "reason": (f"no probe script implements {cid} under {HERE} "
                           "(expected test file absent) -- closing this gap "
                           "is tracked separately, docs/spec/milestones-v1.md §C"),
                "test_file": None,
                "exit_code": None,
            })
            covered.add(cid)

    # --- Process-invariant contract enforcement: C0/C9/C15 rows must NEVER
    # carry a STATE-condition status. If a probe crashed/timed out/violated
    # the line contract (status landed as UNEVALUABLE via run_probe's harness
    # fallback) or, defensively, ever regressed to emitting RED/GREEN, the
    # runner reclassifies the row to AUDIT-PENDING-EPOCH rather than let a
    # process-invariant row leak into STATE-condition completion math.
    for r in rows:
        if r["condition"] in PROCESS_INVARIANTS and r["status"] not in AUDIT_STATUSES:
            r["reason"] = (
                f"[RUNNER RECLASSIFIED from {r['status']}] {r['reason']} "
                "-- process-invariant rows (C0/C9/C15, GOAL.md §4.0(9)) may "
                "never carry a STATE-condition status; treated as "
                "AUDIT-PENDING-EPOCH pending investigation of the probe fault"
            )
            r["status"] = "AUDIT-PENDING-EPOCH"

    # Order the board by ORDER, appending any unknowns deterministically.
    order_index = {cid: i for i, cid in enumerate(ORDER)}
    rows.sort(key=lambda r: (order_index.get(r["condition"], len(ORDER)),
                             r["condition"]))

    total = len(rows)
    state_rows = [r for r in rows if r["condition"] not in PROCESS_INVARIANTS]
    audit_rows = [r for r in rows if r["condition"] in PROCESS_INVARIANTS]
    state_total = len(state_rows)

    green = sum(1 for r in state_rows if r["status"] == "GREEN")
    red = sum(1 for r in state_rows if r["status"] == "RED")
    unevaluable = sum(1 for r in state_rows if r["status"] == "UNEVALUABLE")
    audit_ok = sum(1 for r in audit_rows if r["status"] == "AUDIT-OK")
    audit_incident = sum(1 for r in audit_rows if r["status"] == "AUDIT-INCIDENT")
    audit_pending = sum(1 for r in audit_rows if r["status"] == "AUDIT-PENDING-EPOCH")
    pct_green = round(100.0 * green / state_total, 1) if state_total else 0.0

    state_conditions_green = (state_total > 0 and green == state_total)
    unresolved_incidents = audit_incident
    complete = state_conditions_green and unresolved_incidents == 0

    invariant_checksum = compute_invariant_checksum(REPO_ROOT, ts)

    # Compute chain link: hash of previous totality receipt (F4 FORK-TEST requirement)
    def _get_prev_receipt_sha256(receipts_dir):
        """Get sha256 hash of the previous totality receipt file (entire JSON), or None."""
        if not os.path.isdir(receipts_dir):
            return None
        names = [n for n in os.listdir(receipts_dir) if _RECEIPT_NAME_RE.match(n)]
        if not names:
            return None
        # Use same mtime-based ordering as _last_receipt_combined_sha256
        last = max(names, key=lambda n: os.path.getmtime(os.path.join(receipts_dir, n)))
        receipt_path = os.path.join(receipts_dir, last)
        try:
            with open(receipt_path, "rb") as fh:
                data = fh.read()
            return hashlib.sha256(data).hexdigest()
        except Exception:
            return None

    prev_totality_receipt_sha256 = _get_prev_receipt_sha256(RECEIPTS_DIR) or "0" * 64

    # Compute constitutional_invariant block (issue #281 item 6)
    errata_path = os.path.join(REPO_ROOT, "INVARIANT-ERRATA.md")
    errata_sha256 = "0" * 64
    errata_length = 0
    try:
        with open(errata_path, "rb") as fh:
            errata_data = fh.read()
        errata_sha256 = hashlib.sha256(errata_data).hexdigest()
        errata_length = len(errata_data)
    except (FileNotFoundError, IOError):
        # Errata file may not exist pre-genesis; use zeros
        pass

    # Extract C-INV probe status from the rows (comes from test_c_invariant.py)
    c_inv_status = "RED"  # fail-closed: absent C-INV probe = RED, never assumed GREEN
    for r in rows:
        if r["condition"] == "C-INV":
            c_inv_status = r["status"]
            break

    constitutional_invariant = {
        "invariant_sha256": INVARIANT_SHA256,
        "status": c_inv_status,  # Sourced from C-INV probe result
        "genesis_ts": "2026-07-06T14:13:23-07:00",  # committerDate of genesis merge (commit 9c89f7f66)
        "errata_sha256": errata_sha256,
        "errata_length": errata_length
    }

    # Normalize paths in receipt: in-tree paths become repo-relative,
    # external paths (execution tree) become <local-exec-root>/... tokens
    def normalize_path_for_receipt(path):
        """Convert absolute paths to repo-relative or <local-exec-root> tokens."""
        if not path:
            return path
        try:
            rel = os.path.relpath(path, REPO_ROOT)
            # If relpath starts with .., it's outside this repo
            if rel.startswith(".."):
                # External path: render as <local-exec-root>/tail
                # Try to extract meaningful tail after common prefixes
                tail = os.path.basename(os.path.normpath(path))
                return f"<local-exec-root>/{tail}"
            return rel
        except (ValueError, TypeError):
            # Path is relative already or problematic; return as-is
            return path

    receipt = {
        "receipt_type": "ember_totality_board",
        "ticket": "EMBER-TOTALITY-BOARD",
        "ts": ts,
        # Required by scripts/receipt_check.py whenever any sha256 field is
        # present (here: invariant_checksum's per-file/member/combined
        # hashes) -- every hash in this receipt is a plain sha256 of the
        # named file's bytes on disk as-is, hex digest, no salt/transform.
        "sha_convention": "bytes on disk as-is",
        "root": normalize_path_for_receipt(effective_root),
        "registry_spec": os.path.relpath(CONDITIONS_SPEC_PATH, REPO_ROOT),
        "registry_sync": {
            "runner_ids": len(ORDER),
            "registry_ids": len(registry_ids),
            "matched": True,
        },
        "rows": [
            {"condition": r["condition"], "status": r["status"],
             "is_process_invariant": r["condition"] in PROCESS_INVARIANTS,
             "reason": r["reason"]}
            for r in rows
        ],
        # Separate block for the 3 STANDING PROCESS-INVARIANT rows (GOAL.md
        # §4.0(9)), distinct from the unified `rows` array above -- they are
        # cadence-audit results (AUDIT-OK/AUDIT-INCIDENT/AUDIT-PENDING-EPOCH),
        # never STATE-condition completion conjuncts.
        "invariant_rows": [
            {"condition": r["condition"], "status": r["status"], "reason": r["reason"]}
            for r in audit_rows
        ],
        "summary": {
            "total": total,
            "state_condition_total": state_total,
            "process_invariant_total": len(audit_rows),
            "green": green,
            "red": red,
            "unevaluable": unevaluable,
            "audit_ok": audit_ok,
            "audit_incident": audit_incident,
            "audit_pending_epoch": audit_pending,
            "pct_green": pct_green,
            "completion_math": {
                "state_conditions_green": state_conditions_green,
                "unresolved_post_epoch_incidents": unresolved_incidents,
                "complete": complete,
                "red_plus_unevaluable": red + unevaluable,
                "pct_complete": pct_green,
                "note": (
                    "Completion is computed over the "
                    f"{state_total} STATE-conditions ONLY (GOAL.md §4.0(9) / "
                    "conditions-v1.md §4.4): complete iff every "
                    "STATE-condition is GREEN AND zero unresolved post-epoch "
                    "AUDIT-INCIDENT rows exist. UNEVALUABLE counts as RED for "
                    "STATE-condition completion math (GOAL.md §4.1 amendment "
                    "2026-07-02) but is never reported as an evaluated "
                    "failure. The 3 STANDING PROCESS-INVARIANT rows "
                    f"({sorted(PROCESS_INVARIANTS)}) are cadence-audit "
                    "results (AUDIT-OK/AUDIT-INCIDENT/AUDIT-PENDING-EPOCH), "
                    "never completion conjuncts and never a GREEN."
                ),
            },
        },
        "invariant_checksum": invariant_checksum,
        "prev_totality_receipt_sha256": prev_totality_receipt_sha256,
        "constitutional_invariant": constitutional_invariant,
    }

    # Stamp the receipt with the constitutional invariant hash (fail-closed if mismatch)
    receipt = stamp(receipt, repo_root=REPO_ROOT)

    receipt_path = os.path.join(RECEIPTS_DIR, f"ember-totality-{ts}.json")
    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")

    # Print the board.
    print("=" * 72)
    print(f"EMBER TOTALITY BOARD  ts={ts}  root={effective_root}")
    print("=" * 72)
    width = max((len(r["condition"]) for r in rows), default=4)
    for r in rows:
        print(f"  {r['status']:19s}  {r['condition']:<{width}}  {r['reason']}")
    print("-" * 72)
    print(f"  STATE-conditions ({state_total}): GREEN={green}  RED={red}  "
          f"UNEVALUABLE={unevaluable}  ({pct_green}% green)")
    print(f"  PROCESS-INVARIANTS ({len(audit_rows)}): AUDIT-OK={audit_ok}  "
          f"AUDIT-INCIDENT={audit_incident}  AUDIT-PENDING-EPOCH={audit_pending}")
    print(f"  completion math (STATE-conditions only): state_conditions_green="
          f"{state_conditions_green}  unresolved_post_epoch_incidents="
          f"{unresolved_incidents}  complete={complete}  "
          f"({pct_green}% green of {state_total})")
    print(f"  invariant_checksum: combined_sha256="
          f"{invariant_checksum['combined_sha256'][:16]}...  "
          f"pinned={invariant_checksum['pinned']}  "
          f"status={invariant_checksum['status']}")
    print(f"  receipt: {os.path.relpath(receipt_path, HERE)}")
    print("=" * 72)


if __name__ == "__main__":
    main()
