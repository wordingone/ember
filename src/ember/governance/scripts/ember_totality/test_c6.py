#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Totality status-probe for Ember goal condition C6 (Reproducible reusable recipe).

Authoritative condition text (<spec>, line 106):
  C6 - Reproducible reusable recipe.
    R: commands, code/file hashes, data hashes, env, seeds, artifact paths,
       rerun command; output is a reusable method/model/plan/solver/protocol.
    Does NOT count: a task-specific answer.
    invalid-token: invalid_not_reusable
    CHK: rerun command reproduces the score or names a deterministic mismatch.

Gloss (from the spawn brief): reproducible reusable recipe = commands / hashes /
env / seeds / paths / rerun command; the rerun reproduces the score.
Receipt hint: recipe receipt + rerun verification.

Two halves of the CHK, BOTH required for GREEN:
  (R)   the recipe must be COMPLETE -- a real receipt carrying commands,
        code/file hashes, data hashes, env, seeds, artifact paths, and a rerun
        command, whose produced artifact is a REUSABLE method (not a per-task
        answer);  AND
  (CHK) the rerun must be VERIFIED to reproduce the score (or to name a
        deterministic mismatch). The mere PRESENCE of a rerun_command string is
        the recipe DEFINITION, not its verification -- "rerun command reproduces
        the score" demands an executed-rerun reproduction record.

This is a STATUS PROBE:
  - exit code is ALWAYS 0
  - it prints exactly one line: "RED <reason>" or "GREEN <reason>"
  - RED/GREEN is determined by REALLY inspecting receipts under
    <<external>>/state/<external-state> -- never hardcoded.

C6 SCOPE NOTE (deliberate): C6's only does-NOT-count is "a task-specific answer"
(invalid_not_reusable). C6 does NOT itself re-litigate held-out leakage (C2),
equal budget (C3), or the SYMBOLIC_PROXY guard (C14) -- those live in their own
conditions. This probe therefore encodes ONLY C6's invalid-token, and judges C6
strictly on (recipe complete + reusable, not task-specific) + (rerun reproduces
the score or names a deterministic mismatch), exactly as the R + CHK state.
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

import json
import os
import glob
import re
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
EXTERNAL_STATE = next(
    (p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                 os.path.join(REPO_ROOT, "<external-state>"))
     if p and os.path.isdir(p)),
    os.path.join(REPO_ROOT, "<external-state>"),
)
RECEIPTS = os.path.join(EXTERNAL_STATE, "receipts")

# [ISSUE #683 class extension] execution-binding helpers for the
# deterministic-mismatch CHK path (see _valid_mismatch_record below).
GIT_TIMEOUT_SECONDS = 15
SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def _run_git(args, cwd):
    """Run a git subprocess rooted at cwd. Returns (returncode, stdout, stderr);
    returncode is None on any exception so callers always get a uniform
    execution-binding-failure shape -- this is a status probe and must always
    exit 0 on its own."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
        return None, "", str(exc)


def _git_object_type(cwd, sha):
    """git cat-file -t <sha> -> the object type string, or None if the sha
    does not resolve to a real git object under cwd's repo."""
    if not isinstance(sha, str) or not sha.strip():
        return None
    rc, out, _err = _run_git(["cat-file", "-t", sha], cwd)
    return out.strip() if rc == 0 else None

# C6's only does-NOT-count invalid token (encoded as a negative assertion below).
C6_INVALID_TOKENS = ["invalid_not_reusable"]

# A recipe receipt is "reusable, not a task-specific answer" iff its produced
# artifact is shared across tasks rather than a per-task hand answer. The D3
# candidate receipts record this directly via these flags.
TASK_SPECIFIC_FLAGS = [
    # (block, key, the value that means "task-specific answer" == invalid_not_reusable)
    ("static_registry_exclusion", "static_per_task_answer_table", True),
    ("static_registry_exclusion", "task_id_branches_in_c_source", True),
    ("manual_solution_exclusion", "manual_per_task_solution", True),
]

# Required recipe fields per C6.R, grouped so the reason string can name what is missing.
# Each entry: (human label, predicate(receipt_dict) -> bool present).
def _has_commands(d):
    # per-arm official_execution[...]["command"] arrays are the executable commands.
    rows = d.get("per_task_rows") or []
    for r in rows:
        oe = r.get("official_execution") or {}
        for arm in oe.values():
            if isinstance(arm, dict) and arm.get("command"):
                return True
    return False


def _has_code_file_hashes(d):
    return bool(d.get("arm_solution_sha256")) or bool(
        (d.get("reproducibility") or {}).get("solution_hashes")
    )


def _has_data_hashes(d):
    # data hashes: per-task docker image digests, fresh-rows hash, or goal source hash.
    if d.get("fresh_rows_sha256") or d.get("goal_source_sha256"):
        return True
    for r in (d.get("per_task_rows") or []):
        if r.get("image_digest") or r.get("inspect_sha256"):
            return True
    return False


def _has_env(d):
    repro = d.get("reproducibility") or {}
    if "docker_required" in repro:
        return True
    # an external official container image is the declared env.
    for r in (d.get("per_task_rows") or []):
        if r.get("image"):
            return True
    return False


def _has_seeds(d):
    # seed policy is declared in equal_budget (seed/attempt/budget policy block).
    eb = d.get("equal_budget")
    return isinstance(eb, dict) and len(eb) > 0


def _has_artifact_paths(d):
    return bool(d.get("arm_solution_paths")) or bool(d.get("fresh_rows_path"))


def _has_rerun_command(d):
    return bool((d.get("reproducibility") or {}).get("rerun_command"))


RECIPE_FIELDS = [
    ("commands", _has_commands),
    ("code/file hashes", _has_code_file_hashes),
    ("data hashes", _has_data_hashes),
    ("env", _has_env),
    ("seeds", _has_seeds),
    ("artifact paths", _has_artifact_paths),
    ("rerun command", _has_rerun_command),
]

# [ISSUE #740 bypass-closure] No key name is EVER sufficient alone. The prior
# RERUN_VERIFICATION_KEYS list (rerun_verified / rerun_reproduced /
# reproduced_score / reproduction_verdict / rerun_reproduction / rerun_match)
# let a receipt author write `{"reproducibility": {"rerun_verified": true}}`
# with zero real rerun evidence and pass this CHK -- a single self-attested
# boolean bypassing every other check, live despite PR #741's hardening of
# the sibling deterministic_mismatch path. Removed outright (panel
# 2026-07-02's principle -- "a bare flag/string is an unexecuted claim" --
# now applies to the truthy-key list itself, not just deterministic_mismatch).
# An executed-rerun record counts ONLY via a structured, execution-bound
# record: see _valid_reproduction_record (the "reproduces the score" half of
# the CHK) and _valid_mismatch_record (the "names a deterministic mismatch"
# half) below -- both resolve real rerun-receipt files and recompute hashes,
# never trust a self-reported flag.


def status(color, reason):
    """Single-line status emit; STATUS PROBE always exits 0."""
    print(f"{color} {reason}")
    raise SystemExit(0)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def is_pass_verdict(d):
    v = str(d.get("verdict", "")).upper()
    return "PASS" in v and "BLOCKED" not in v and "DRYRUN" not in v


def task_specific_flag_hit(d):
    """Return a reason string if any task-specific (invalid_not_reusable) flag is set,
    else None. Recomputed from the real receipt flags, never a stored verdict."""
    for block, key, bad_val in TASK_SPECIFIC_FLAGS:
        b = d.get(block) or {}
        if isinstance(b, dict) and b.get(key) == bad_val:
            return f"{block}.{key}={bad_val}"
    # also catch the literal token if a receipt declares it as an active code
    codes = [str(c) for c in (d.get("invalid_codes") or [])]
    for c in codes:
        if "invalid_not_reusable" in c:
            return f"literal invalid_not_reusable in invalid_codes ({c})"
    return None


def _cause_cites_resolvable_commit_sha(cause_text, cwd):
    """True iff cause_text names >=1 commit sha (40-hex or >=7-hex short) that
    resolves via `git cat-file -t <sha>` == commit under cwd's repo. Returns
    (bool, [resolved shas])."""
    if not isinstance(cause_text, str):
        return False, []
    resolved = [c for c in SHA_RE.findall(cause_text) if _git_object_type(cwd, c) == "commit"]
    return bool(resolved), resolved


def _resolve_receipt_path(rel_path, repo_root, citing_dir):
    """Resolve a rerun-receipt path candidate, tried repo-root-relative first,
    then relative to the citing receipt's own directory. Returns an absolute
    path if a real file is found on either candidate, else None."""
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    norm = rel_path.replace("\\", "/")
    candidates = [os.path.join(repo_root, norm)]
    if citing_dir:
        candidates.append(os.path.join(citing_dir, norm))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _load_rerun_receipts(reruns, repo_root, citing_dir):
    """Resolve + parse every rerun_receipts/reruns entry as real JSON files.
    Returns (records, problems): records is [(rel_path, parsed_dict), ...]
    for every entry that resolved and parsed; problems names every entry that
    did not (missing file on either candidate root, or unparseable JSON)."""
    records, problems = [], []
    for rel in reruns:
        resolved = _resolve_receipt_path(rel, repo_root, citing_dir)
        if resolved is None:
            problems.append(f"{rel!r} does not resolve to an existing file "
                             f"(tried repo-root-relative and citing-receipt-dir-relative)")
            continue
        try:
            with open(resolved, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
        except Exception as exc:
            problems.append(f"{rel!r} resolved to {resolved!r} but failed to parse as JSON: {exc}")
            continue
        records.append((rel, parsed))
    return records, problems


def _arm_hashes_agree_pairwise(records):
    """Recompute rep1-vs-rep2 (and any further reruns) agreement DIRECTLY from
    each resolved rerun receipt's OWN arm_solution_sha256 map -- never from
    the parent receipt's summary of them. Returns (True, None) if every
    record's map agrees with every other record's on every shared arm key,
    else (False, reason)."""
    hash_maps = []
    for rel, parsed in records:
        h = parsed.get("arm_solution_sha256")
        if not isinstance(h, dict) or not h:
            return False, f"{rel!r} has no arm_solution_sha256 map to compare"
        hash_maps.append((rel, h))
    if len(hash_maps) < 2:
        return False, "fewer than 2 rerun entries carry an arm_solution_sha256 map"
    base_rel, base_map = hash_maps[0]
    for rel, h in hash_maps[1:]:
        shared = set(base_map) & set(h)
        if not shared:
            return False, f"{base_rel!r} and {rel!r} share no common arm keys"
        for arm in shared:
            if base_map[arm] != h[arm]:
                return False, (f"arm {arm!r} solution hash disagrees between {base_rel!r} "
                               f"({base_map[arm]!r}) and {rel!r} ({h[arm]!r})")
    return True, None


def _valid_mismatch_record(v, citing_path=None):
    """A deterministic-mismatch claim satisfies the CHK only as a FULLY
    execution-bound structured record -- ALL of:
      (a) every rerun_receipts/reruns entry resolves to an existing file
          (repo-root-relative or citing-receipt-directory-relative) and
          parses as JSON;
      (b) the resolved rerun files' OWN arm_solution_sha256 maps agree
          pairwise on every shared arm -- recomputed directly from the
          parsed files, never trusted from the parent receipt's summary;
      (c) the cause text names >=1 commit sha (40-hex or >=7-hex short) that
          resolves via `git cat-file -t <sha>` == commit.
    Returns (True, detail_string) on success, (False, reason_string) on any
    failure -- a bare cause-truthiness + reruns-len>=2 check is NOT enough
    (issue #683 class: an unverified claim must never pass a status probe)."""
    if not isinstance(v, dict):
        return False, "deterministic_mismatch is not a structured record (dict)"
    cause = v.get("cause") or v.get("named_cause")
    if not cause:
        return False, "deterministic_mismatch has no cause/named_cause"
    reruns = v.get("rerun_receipts") or v.get("reruns") or []
    if not isinstance(reruns, list) or len(reruns) < 2:
        return False, "deterministic_mismatch needs >=2 rerun_receipts/reruns entries"

    citing_dir = os.path.dirname(citing_path) if citing_path else None
    records, problems = _load_rerun_receipts(reruns, REPO_ROOT, citing_dir)
    if problems or len(records) < 2:
        return False, f"rerun entries failed to resolve/parse: {problems or 'fewer than 2 parsed OK'}"

    agree, disagree_reason = _arm_hashes_agree_pairwise(records)
    if not agree:
        return False, f"rerun arm_solution_sha256 recomputation disagrees: {disagree_reason}"

    sha_ok, resolved_shas = _cause_cites_resolvable_commit_sha(cause, REPO_ROOT)
    if not sha_ok:
        return False, "cause text names no commit sha resolvable via git cat-file -t"

    return True, (f"recomputed: {len(records)} rerun receipts resolved+parsed, "
                  f"arm_solution_sha256 agree pairwise across all, cause cites "
                  f"resolvable commit(s) {resolved_shas}")


def _valid_reproduction_record(d, citing_path=None):
    """The 'rerun command reproduces the score' half of the CHK, structured and
    execution-bound (issue #740 bypass-closure -- the equivalent-rigor sibling
    of _valid_mismatch_record's 'names a deterministic mismatch' half). Looks
    for a rerun_receipts/reruns list directly in the reproducibility block or
    at top level (NOT nested in deterministic_mismatch -- that is the other
    half). Satisfies the CHK only as ALL of:
      (a) every listed entry resolves to an existing file (repo-root-relative
          or citing-receipt-directory-relative) and parses as JSON;
      (b) each resolved rerun file carries its OWN arm_solution_sha256 map;
      (c) that map agrees with the CITING (parent) receipt's OWN
          arm_solution_sha256 map on every shared arm -- recomputed by
          cross-file comparison against a document the rerun did not also
          author, never a same-document boolean/string claim.
    Returns (True, detail_string) on success, (False, reason_string) on any
    failure -- absence of a rerun list, an unresolvable entry, or a hash
    disagreement are all rejects, never a silent pass."""
    repro = d.get("reproducibility") or {}
    reruns = (repro.get("rerun_receipts") or repro.get("reruns")
              or d.get("rerun_receipts") or d.get("reruns"))
    if not isinstance(reruns, list) or not reruns:
        return False, "no rerun_receipts/reruns list present (reproduction path)"

    citing_dir = os.path.dirname(citing_path) if citing_path else None
    records, problems = _load_rerun_receipts(reruns, REPO_ROOT, citing_dir)
    if problems or not records:
        return False, f"rerun entries failed to resolve/parse: {problems or 'no records parsed'}"

    parent_hashes = d.get("arm_solution_sha256")
    if not isinstance(parent_hashes, dict) or not parent_hashes:
        return False, "citing receipt has no arm_solution_sha256 to reproduce against"

    for rel, parsed in records:
        h = parsed.get("arm_solution_sha256")
        if not isinstance(h, dict) or not h:
            return False, f"{rel!r} has no arm_solution_sha256 map to compare"
        shared = set(parent_hashes) & set(h)
        if not shared:
            return False, f"{rel!r} shares no common arm keys with the citing receipt"
        for arm in shared:
            if parent_hashes[arm] != h[arm]:
                return False, (f"arm {arm!r} solution hash disagrees between citing "
                                f"receipt ({parent_hashes[arm]!r}) and rerun {rel!r} "
                                f"({h[arm]!r})")

    return True, (f"recomputed: {len(records)} rerun receipt(s) resolved+parsed, "
                  f"arm_solution_sha256 agree with citing receipt on all shared arms")


def find_rerun_verification(d, citing_path=None):
    """Return the reproduction record value if a real executed-rerun verification
    exists, else None. An executed-rerun record counts ONLY via a structured,
    execution-bound record -- never a bare boolean/string flag naming itself
    verified (issue #740 bypass-closure). The CHK's two valid shapes:
    _valid_reproduction_record ("reproduces the score") or
    _valid_mismatch_record ("names a deterministic mismatch")."""
    repro = d.get("reproducibility") or {}

    ok, detail = _valid_reproduction_record(d, citing_path=citing_path)
    if ok:
        return f"reproduction(structured: {detail})"

    for src, label in ((repro, "reproducibility."), (d, "")):
        v = src.get("deterministic_mismatch")
        ok, detail = _valid_mismatch_record(v, citing_path=citing_path)
        if ok:
            n = len(v.get("rerun_receipts") or v.get("reruns"))
            return (f"{label}deterministic_mismatch(structured: "
                    f"cause={v.get('cause') or v.get('named_cause')!r}, reruns={n}, {detail})")
    return None


def main():
    # ---- locate REAL recipe receipts (D3 generalized-candidate receipts carry the
    #      reproducibility block: commands/hashes/env/seeds/paths/rerun_command) ----
    if not os.path.isdir(RECEIPTS):
        status("RED", f"no receipts dir at {RECEIPTS}")

    recipe_paths = sorted(
        glob.glob(os.path.join(RECEIPTS, "**", "d3-generalized-candidate-receipt.json"),
                  recursive=True)
    )
    if not recipe_paths:
        status("RED", "no d3-generalized-candidate-receipt.json recipe receipts found "
                      "(C6 recipe artifact absent)")

    # Among recipe receipts, consider only PASS-verdict ones with a complete recipe and
    # NO task-specific (invalid_not_reusable) flag -- those are eligible to satisfy C6.
    # For each eligible recipe, the CHK still requires a rerun-reproduction record.
    eligible = []          # (path, d) -- PASS verdict, complete recipe, reusable
    complete_count = 0     # recipes that are complete + reusable (regardless of verdict)
    flagged = []           # (name, reason) -- task-specific flag hit (invalid_not_reusable)
    incomplete = []        # (name, missing_fields)

    for path in recipe_paths:
        try:
            d = load_json(path)
        except Exception:
            continue
        name = os.path.relpath(path, EXTERNAL_STATE)

        # (2) Negative assertion: NONE of C6's does-NOT-count invalid-tokens may match.
        ts_hit = task_specific_flag_hit(d)
        if ts_hit:
            flagged.append((name, ts_hit))
            continue

        # (R) recipe completeness
        missing = [label for label, pred in RECIPE_FIELDS if not pred(d)]
        if missing:
            incomplete.append((name, missing))
            continue

        complete_count += 1
        if is_pass_verdict(d):
            eligible.append((path, d))

    if not eligible:
        # Report the most informative real reason for the absence.
        if flagged:
            # If EVERY recipe is task-specific, the invalid-token genuinely matched.
            if not incomplete and complete_count == 0:
                name, why = flagged[0]
                status("RED", f"all recipe receipts task-specific: {name} {why} "
                              f"-> invalid_not_reusable matched (C6 does-NOT-count)")
        if incomplete:
            name, miss = incomplete[0]
            status("RED", f"no eligible recipe: e.g. {name} missing recipe fields {miss} "
                          f"(C6.R incomplete)")
        status("RED", "recipe receipts exist but none are a complete, reusable, "
                      "PASS-verdict recipe (C6.R unmet)")

    # (1) Positive CHK: for an eligible reusable recipe, the rerun command must have
    #     been VERIFIED to reproduce the score (or to name a deterministic mismatch).
    #     The presence of a rerun_command string alone is the recipe DEFINITION, not
    #     its reproduction -- the CHK demands an executed-rerun reproduction record.
    verified = None
    for path, d in eligible:
        rv = find_rerun_verification(d, citing_path=path)
        if rv is not None:
            verified = (os.path.relpath(path, EXTERNAL_STATE), d, rv)
            break

    if verified is None:
        # The recipe DEFINITION exists and is reusable, but no rerun-reproduction
        # record exists anywhere -> the CHK's "rerun reproduces the score" is unproven.
        example = os.path.relpath(eligible[-1][0], EXTERNAL_STATE)
        repro_keys = sorted((eligible[-1][1].get("reproducibility") or {}).keys())
        status("RED",
               f"recipe DEFINITION present & reusable in {len(eligible)} PASS receipt(s) "
               f"(e.g. {example}: reproducibility keys={repro_keys}), but NO structured, "
               f"execution-bound reproduction record (neither _valid_reproduction_record "
               f"nor _valid_mismatch_record; a bare self-reported flag is never sufficient) "
               f"-> C6 CHK 'rerun command reproduces the score or names a deterministic "
               f"mismatch' UNPROVEN")

    name, d, rv = verified
    rerun_cmd = (d.get("reproducibility") or {}).get("rerun_command", "")
    status("GREEN",
           f"C6 satisfied by {name}: complete reusable recipe (commands/hashes/env/seeds/"
           f"paths/rerun_command present, no invalid_not_reusable flag) AND rerun "
           f"reproduction verified ({rv}); rerun_command={rerun_cmd!r}")


if __name__ == "__main__":
    main()
