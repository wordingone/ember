#!/usr/bin/env python3
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
# <local-mount-point>/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import json
import os
import glob

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
EXTERNAL_STATE = next(
    (p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                 os.path.join(REPO_ROOT, "<external-state>"))
     if p and os.path.isdir(p)),
    os.path.join(REPO_ROOT, "<external-state>"),
)
RECEIPTS = os.path.join(EXTERNAL_STATE, "receipts")

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

# Keys that, if present and truthy in the reproducibility block (or anywhere in the
# receipt), would constitute an executed-rerun reproduction record (the CHK's
# "rerun reproduces the score OR names a deterministic mismatch").
RERUN_VERIFICATION_KEYS = [
    "rerun_verified",
    "rerun_reproduced",
    "reproduced_score",
    "reproduction_verdict",
    "rerun_reproduction",
    "rerun_match",
]
# deterministic_mismatch is NOT in the truthy list: a bare flag/string is an
# unexecuted claim (panel 2026-07-02). It counts only as a structured record
# carrying its own evidence -- see _valid_mismatch_record.


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


def _valid_mismatch_record(v):
    """A deterministic-mismatch claim satisfies the CHK only as a structured
    record with a named reproducible cause plus >=2 independent rerun entries
    that agree with each other (bounding the claimed nondeterminism)."""
    if not isinstance(v, dict):
        return False
    cause = v.get("cause") or v.get("named_cause")
    reruns = v.get("rerun_receipts") or v.get("reruns") or []
    return bool(cause) and isinstance(reruns, list) and len(reruns) >= 2


def find_rerun_verification(d):
    """Return the reproduction record value if a real executed-rerun verification
    exists, else None. Looks in the reproducibility block and at top level."""
    repro = d.get("reproducibility") or {}
    for k in RERUN_VERIFICATION_KEYS:
        if k in repro and repro.get(k) not in (None, "", False):
            return f"reproducibility.{k}={repro.get(k)!r}"
        if k in d and d.get(k) not in (None, "", False):
            return f"{k}={d.get(k)!r}"
    for src, label in ((repro, "reproducibility."), (d, "")):
        v = src.get("deterministic_mismatch")
        if _valid_mismatch_record(v):
            n = len(v.get("rerun_receipts") or v.get("reruns"))
            return (f"{label}deterministic_mismatch(structured: "
                    f"cause={v.get('cause') or v.get('named_cause')!r}, reruns={n})")
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
        rv = find_rerun_verification(d)
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
               f"(e.g. {example}: reproducibility keys={repro_keys}), but NO executed-rerun "
               f"reproduction record (none of {RERUN_VERIFICATION_KEYS}) -> C6 CHK 'rerun "
               f"command reproduces the score or names a deterministic mismatch' UNPROVEN")

    name, d, rv = verified
    rerun_cmd = (d.get("reproducibility") or {}).get("rerun_command", "")
    status("GREEN",
           f"C6 satisfied by {name}: complete reusable recipe (commands/hashes/env/seeds/"
           f"paths/rerun_command present, no invalid_not_reusable flag) AND rerun "
           f"reproduction verified ({rv}); rerun_command={rerun_cmd!r}")


if __name__ == "__main__":
    main()
