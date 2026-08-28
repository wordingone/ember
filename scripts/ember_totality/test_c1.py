#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test — Condition C1 (status probe / TDD).

C1 — Exact historical + modern benchmark/dataset discovery.
  R: a source-backed receipt naming URLs/licenses/evaluator-forms/
     local-run-requirements/hashes + why the selected benchmark is the best
     self-improvement-by-action proxy.
  Does NOT count: passive research-text QA; "benchmark" read as "answer about
     a research artifact."
  Invalid-token: invalid_discovery_unsourced
  CHK: receipt enumerates sources with hashes and selection rationale.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> — never hardcoded.

LANE-14 HARDENING (2026-07-02, R8 probe-faithfulness audit,
docs/goalforge-debate-ledger.md row R8): the pre-hardening version treated
"no reachable artifact to re-hash" as an acceptable GREEN note -- R8 graded
this "FIXTURE-PASSABLE (C1 hash-verify leg optional)". HASH-VERIFY IS NOW
MANDATORY: a candidate can only satisfy the CHK's hash requirement by
re-deriving a claimed hash from a file that both (a) is actually reachable
UNDER this probe's resolved ROOT (the execution tree -- a path that exists
elsewhere on the machine but outside ROOT is an import owed from the live
tree, docs/domains/governance/authority/GOAL.md Execution-surface row / anti-gaming S10, never trusted as
in-tree evidence) and (b) hashes to the claimed value. The old pass-through
is removed; a receipt with only off-tree/unreachable hash paths now FAILS
this candidate and the probe keeps searching, RED if none verify.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is <local-mount-point>/ on this host (NOT /mnt<local-mount-point>/).
"""

# [PATH-REWRITE 2026-07-01] Imported from <<external>>/state/ember-totality-build/
# into the public worktree. Original path-mount candidates replaced with a single
# REPO_ROOT-relative candidate, REPO_ROOT computed from this file's own location
# (two levels up from scripts/ember_totality/), for native Windows system-python
# execution. No probe logic changed -- only path resolution. Non-existent upstream
# references are expected to emit a clean RED 'root not found' line, which is the
# correct, non-error outcome.

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import resolve_in_tree, sha256_file  # noqa: E402

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Invalid-tokens that the condition declares as NON-counting outcomes.
# C1's explicit ? token, plus encodings of the two "does NOT count" substitutes.
INVALID_TOKENS = [
    "invalid_discovery_unsourced",        # the explicit ? token
    "passive_research_text_qa",           # does NOT count: passive research-text QA
    "benchmark_as_research_artifact_answer",  # does NOT count: "benchmark" read as "answer about a research artifact"
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C1: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    # --- (A) Find the benchmark/dataset discovery receipt(s) -----------------
    # Receipt hint: receipts/*discovery*, benchmark-acquisition receipts.
    patterns = [
        os.path.join(ROOT, "receipts", "**", "*discovery*.json"),
        os.path.join(ROOT, "receipts", "**", "benchmark-discovery*.json"),
    ]
    found = set()
    for pat in patterns:
        found.update(glob.glob(pat, recursive=True))
    receipts = sorted(found)
    if not receipts:
        emit("RED", "C1: no benchmark/dataset discovery receipt found "
                    "(receipts/*discovery* absent) -> satisfying artifact ABSENT")

    # Inspect every candidate receipt; require at least ONE that fully passes CHK
    # with no invalid-token present anywhere in it.
    best_path = None
    failures = []
    for rp in receipts:
        try:
            with open(rp, "r", encoding="utf-8") as fh:
                raw = fh.read()
            data = json.loads(raw)
        except Exception as exc:  # broken receipt -> not a pass, record and continue
            failures.append(f"{os.path.basename(rp)}: unreadable ({exc})")
            continue

        # --- (B) Negative assertions: NONE of the invalid-tokens may appear ---
        lowered = raw.lower()
        hit = [t for t in INVALID_TOKENS if t.lower() in lowered]
        if hit:
            failures.append(f"{os.path.basename(rp)}: invalid-token present {hit}")
            continue

        # --- (C) Positive CHK: enumerate sources with hashes + rationale ------
        cands = data.get("candidates")
        if not isinstance(cands, list) or not cands:
            failures.append(f"{os.path.basename(rp)}: no candidates[] enumerated")
            continue

        # Each enumerated source must carry URLs, license, evaluator-form.
        urls_ok = all(
            isinstance(c.get("primary_sources"), list) and len(c["primary_sources"]) > 0
            and any(str(u).startswith("http") for u in c["primary_sources"])
            for c in cands
        )
        license_ok = all(c.get("license_or_access_basis") for c in cands)
        evalform_ok = all(c.get("task_evaluator_form") for c in cands)

        # Hashes: at least one real, content-addressable hash must be present
        # AND verifiable against an on-disk artifact where the path is reachable.
        hash_strings = []
        for c in cands:
            for k, v in c.items():
                if k.lower().endswith("sha256") and isinstance(v, str) and len(v) == 64:
                    hash_strings.append((c, k, v))
        top_sha = data.get("goal_source_sha256")
        if isinstance(top_sha, str) and len(top_sha) == 64:
            hash_strings.append((None, "goal_source_sha256", top_sha))
        has_hash = len(hash_strings) > 0

        # Selection rationale: explicit selection.why AND per-candidate fit_to_goal.
        sel = data.get("selection") or {}
        rationale_ok = bool(sel.get("why")) and all(c.get("fit_to_goal") for c in cands)

        # Verify at least one referenced artifact hash matches a real file
        # REACHABLE FROM THIS TREE (ROOT). HASH-VERIFY MANDATORY (lane-14
        # hardening, 2026-07-02): a path that resolves off-tree does not
        # count even if the file physically exists elsewhere on the
        # machine -- resolve_in_tree() rejects it, same as if it were
        # missing. No "no reachable artifact to re-hash" pass-through.
        hash_verified = False
        hash_verify_paths_tried = []
        for c, _k, claimed in hash_strings:
            if c is None:
                continue
            path = c.get("local_task_rows_path") or c.get("local_path")
            if not path:
                continue
            hash_verify_paths_tried.append(path)
            on_disk = resolve_in_tree(path, ROOT)
            if on_disk is not None and sha256_file(on_disk) == claimed.lower():
                hash_verified = True
                break

        checks = {
            "urls": urls_ok,
            "license": license_ok,
            "evaluator_form": evalform_ok,
            "has_hash": has_hash,
            "rationale": rationale_ok,
            "hash_verified": hash_verified,
        }
        missing = [k for k, ok in checks.items() if not ok]
        if missing:
            if missing == ["hash_verified"]:
                failures.append(
                    f"{os.path.basename(rp)}: CHK otherwise satisfied but "
                    f"hash_verified=False (hash-verify is MANDATORY, lane-14 "
                    f"hardening) -- claimed artifact path(s) "
                    f"{hash_verify_paths_tried[:2]} resolve off-tree/missing "
                    f"under ROOT={ROOT}, converging with docs/domains/governance/authority/GOAL.md's "
                    "Execution-surface 'Imports owed FROM the live tree' row "
                    "(anti-gaming S10 import debt) -> cannot verify in-tree")
            else:
                failures.append(f"{os.path.basename(rp)}: CHK missing {missing}")
            continue

        # This receipt passes the full CHK with a verified in-tree hash and
        # no invalid-token.
        best_path = rp
        best_n = len(cands)
        break

    if best_path is None:
        emit("RED", "C1: discovery receipt(s) present but none satisfy CHK "
                    f"cleanly (sources+hashes+rationale+MANDATORY in-tree "
                    f"hash-verify) -> {failures[:3]}")

    emit("GREEN",
         f"C1: source-backed discovery receipt "
         f"{os.path.relpath(best_path, ROOT)} enumerates {best_n} benchmarks "
         f"with URLs+licenses+evaluator-forms+hashes+selection.why; "
         f"no invalid-token present; on-disk hash VERIFIED against an "
         f"in-tree artifact (mandatory, lane-14 hardening)")


if __name__ == "__main__":
    main()
