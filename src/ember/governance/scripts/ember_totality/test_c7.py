#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test — Condition C7 (status probe / TDD).

C7 — Self-growing operator is load-bearing.
  R: Ember's prospective receipt-trained operator (not Codex/manual) selects/
     routes the next loop action; a deletion/ablation test shows removal
     degrades/blocks that next-loop decision.
  Does NOT count: a score-only loop, a manually selected rerun, a retrospective
     classifier, or a critic that scores receipt-regularity after the fact
     without prospective next-cycle conditioning.
  Invalid-token: invalid_operator_not_loadbearing
  CHK: deleted-operator receipt shows degraded next-decision on
       held-out / out-of-closure tasks.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under <external-state> — never hardcoded.

What a GREEN here actually requires (receipts-only, no self-attestation):
  1. A real c7-selftest receipt exists with verdict==PASS and
     proves_load_bearing==true.
  2. The receipt's held_out_slices are out-of-closure (>=1) and the
     degenerate/deleted-arm slice is the closure slice {0} — i.e. the
     deletion is tested on tasks the deleted operator was NOT trained for
     (the "degraded next-decision on held-out" requirement).
  3. The receipt's operator_constants_hash equals the LIVE operator's
     canonical_hash (imported from the real c7_selftest module). This binds
     the receipt to the live, un-tampered operator definition — a stale or
     forged receipt whose hash no longer matches the code FAILS.
  4. The live operator is genuinely PROSPECTIVE (the regime_operator source
     declares "fires before the cycle it governs"), defeating the
     retrospective-classifier / after-the-fact-critic substitutes.
  5. NONE of the C7 does-NOT-count invalid-tokens appear in the receipt.
  6. LANE-14 HARDENING (2026-07-02, R8 probe-faithfulness audit,
     docs/goalforge-debate-ledger.md row R8): EVIDENCE-IN-RECEIPT. R8 graded
     the pre-hardening version "SELF-ATTESTED (C7 trusts a
     proves_load_bearing boolean behind a real constants-hash tamper
     defense)" -- the hash-binding proves the receipt matches the live
     OPERATOR DEFINITION, but proves nothing about the DELETION TEST'S
     OUTCOME, which was reduced to one bare boolean before being written
     (src/ember/governance/scripts/ember_phase5_c7/c7_selftest.py's run_c7_deletion_test()
     computes real_trained_pass_rate / real_deleted_pass_rate /
     degenerate_deleted_pass_rate internally, then run_selftest() discards
     all three before writing the receipt -- exactly the kind of "trust the
     boolean" gap this hardening closes). GREEN now additionally requires
     the receipt to CARRY the per-arm next-decision pass-rate numbers
     (real_trained_pass_rate, real_deleted_pass_rate) and this probe
     RECOMPUTES degradation = real_trained_pass_rate - real_deleted_pass_rate
     > 0 itself, never trusting proves_load_bearing as sufficient evidence
     on its own. A receipt carrying only the boolean (today's real
     receipts) FAILS this leg.

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
import importlib.util
import json
import os
import re
import sys

# --- Locate <external-state> robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Invalid-tokens that the condition declares as NON-counting outcomes.
# C7's explicit ? token, plus encodings of the four "does NOT count" substitutes.
INVALID_TOKENS = [
    "invalid_operator_not_loadbearing",   # the explicit ? token
    "score_only_loop",                    # does NOT count: a score-only loop
    "manually_selected_rerun",            # does NOT count: a manually selected rerun
    "retrospective_classifier",           # does NOT count: a retrospective classifier
    "after_the_fact_critic",              # does NOT count: critic scoring after the fact
                                          #   w/o prospective next-cycle conditioning
    # The deletion-test's own NON-counting verdict, if it ever surfaced in a
    # selftest receipt, must not be claimed as load-bearing:
    "not_load_bearing",
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def live_operator_canonical_hash():
    """Import the REAL c7_selftest module and return the live operator's
    canonical_hash(). This is the same hash the receipt records, so it binds
    the receipt to the live (un-tampered) operator-constants definition.
    Returns (hash_or_None, error_or_None)."""
    if ROOT is None:
        return None, "root not found"
    pkg = os.path.join(ROOT, "scripts", "ember_phase5_c7")
    selftest_py = os.path.join(pkg, "c7_selftest.py")
    if not os.path.isfile(selftest_py):
        return None, f"c7_selftest.py absent at {selftest_py}"
    # Make the package importable.
    for p in (os.path.join(ROOT, "scripts"), pkg):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        # Load under the module's REAL name and register it in sys.modules
        # BEFORE exec_module — the module's @dataclass machinery resolves type
        # forward-refs via sys.modules.get(cls.__module__), which is None if the
        # module is loaded anonymously.
        spec = importlib.util.spec_from_file_location("c7_selftest", selftest_py)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["c7_selftest"] = mod
        spec.loader.exec_module(mod)
        return mod.OperatorConstants.canonical_hash(), None
    except Exception as exc:  # noqa: BLE001 - any import failure => cannot bind
        return None, f"import/canonical_hash failed: {exc}"


def operator_is_prospective():
    """Structural negative against the retrospective-classifier substitute:
    the live regime_operator must declare itself PROSPECTIVE (fires before the
    cycle it governs). Returns (bool, detail)."""
    if ROOT is None:
        return False, "root not found"
    src = os.path.join(ROOT, "scripts", "ember_phase5_c7", "regime_operator.py")
    if not os.path.isfile(src):
        return False, "regime_operator.py absent"
    try:
        with open(src, "r", encoding="utf-8") as fh:
            text = fh.read().lower()
    except Exception as exc:  # noqa: BLE001
        return False, f"unreadable ({exc})"
    prospective = "prospective" in text and re.search(
        r"fires before the cycle", text) is not None
    return bool(prospective), ("declares prospective+fires-before-cycle"
                               if prospective else "no prospective declaration")


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C7: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    # --- (A) Find the C7 self-growth-operator receipt(s) ---------------------
    # Receipt hint: src/ember/governance/scripts/ember_phase5_c7/c7_selftest.py writes
    # receipts/c7-selftest-<ts>.json; the operator-ablation result is inside it
    # (proves_load_bearing, held_out_slices, degenerate_slice).
    patterns = [
        os.path.join(ROOT, "receipts", "**", "c7-selftest-*.json"),
        os.path.join(ROOT, "receipts", "**", "c7_deletion_test_*.json"),
    ]
    found = set()
    for pat in patterns:
        found.update(glob.glob(pat, recursive=True))
    receipts = sorted(found)
    if not receipts:
        emit("RED", "C7: no c7-selftest / operator-ablation receipt found "
                    "(receipts/c7-selftest-* absent) -> satisfying artifact ABSENT")

    # --- Bind to the LIVE operator + prospective structural check ------------
    live_hash, hash_err = live_operator_canonical_hash()
    prospective, prosp_detail = operator_is_prospective()

    # Inspect every candidate receipt newest-first; require at least ONE that
    # fully passes the CHK with no invalid-token present anywhere in it.
    best = None
    failures = []
    for rp in sorted(receipts, reverse=True):
        base = os.path.basename(rp)
        try:
            with open(rp, "r", encoding="utf-8") as fh:
                raw = fh.read()
            data = json.loads(raw)
        except Exception as exc:  # broken receipt -> not a pass
            failures.append(f"{base}: unreadable ({exc})")
            continue

        # --- (B) Negative assertions: NONE of the invalid-tokens may appear --
        lowered = raw.lower()
        hit = [t for t in INVALID_TOKENS if t.lower() in lowered]
        # Allow the literal "not_load_bearing" ONLY when it is the degenerate-
        # arm's expected NON-counting verdict described alongside a positive
        # load-bearing verdict — but the c7-selftest receipt schema does not
        # store arm verdict strings, so any appearance here is a real hit.
        if hit:
            failures.append(f"{base}: invalid-token present {hit}")
            continue

        # --- (C) Positive CHK ----------------------------------------------
        verdict = str(data.get("verdict", "")).upper()
        proves = data.get("proves_load_bearing")
        held = data.get("held_out_slices")
        degen = data.get("degenerate_slice")
        rcpt_hash = data.get("operator_constants_hash")

        if verdict != "PASS":
            failures.append(f"{base}: verdict={verdict!r} != PASS")
            continue
        if proves is not True:
            failures.append(f"{base}: proves_load_bearing={proves!r} not True")
            continue
        # Held-out must be out-of-closure (every slice >= 1) and non-empty.
        if not (isinstance(held, list) and held and all(
                isinstance(s, int) and s >= 1 for s in held)):
            failures.append(f"{base}: held_out_slices={held!r} not all >=1")
            continue
        # Degenerate / deleted arm must be the closure slice {0} (the deleted
        # operator is only trained on slice 0; degradation is measured on the
        # >=1 held-out it never learned).
        if not (isinstance(degen, list) and 0 in degen):
            failures.append(f"{base}: degenerate_slice={degen!r} missing 0")
            continue
        # Receipt must be bound to the LIVE operator (tamper / stale defense).
        if not (isinstance(rcpt_hash, str) and len(rcpt_hash) == 64):
            failures.append(f"{base}: operator_constants_hash absent/short")
            continue
        if live_hash is None:
            failures.append(f"{base}: cannot bind (live hash error: {hash_err})")
            continue
        if rcpt_hash.lower() != live_hash.lower():
            failures.append(
                f"{base}: operator_constants_hash {rcpt_hash[:12]}.. != live "
                f"{live_hash[:12]}.. (stale/forged receipt)")
            continue
        # Structural prospective check (defeats retrospective-classifier subst.)
        # LANE-14 note: kept as the existing keyword/regex check over
        # regime_operator.py's source (source declares "prospective" +
        # "fires before the cycle") rather than replaced with a genuine
        # AST/call-graph structural check -- a real structural proof that
        # firing precedes the cycle it governs would require modeling this
        # codebase's call ordering, which is not cheaply possible here. Per
        # the hardening instruction's else-branch, the keyword check is
        # RETAINED and the numeric-evidence requirement below is ADDED on
        # top of it, not instead of it.
        if not prospective:
            failures.append(f"{base}: operator not prospective ({prosp_detail})")
            continue

        # --- LANE-14 HARDENING: EVIDENCE-IN-RECEIPT ---------------------------
        # proves_load_bearing alone is a bare boolean (R8: SELF-ATTESTED).
        # Require the receipt to CARRY the per-arm next-decision pass rates
        # and RECOMPUTE degradation from them -- never trust the boolean.
        trained_rate = data.get("real_trained_pass_rate")
        deleted_rate = data.get("real_deleted_pass_rate")
        if trained_rate is None or deleted_rate is None:
            failures.append(
                f"{base}: proves_load_bearing=true but receipt carries NO "
                f"per-arm next-decision numeric evidence "
                f"(real_trained_pass_rate={trained_rate!r}, "
                f"real_deleted_pass_rate={deleted_rate!r}) -- "
                "EVIDENCE-IN-RECEIPT requires the numeric scores, a boolean "
                "alone is not admissible (lane-14 hardening)")
            continue
        try:
            trained_rate_f = float(trained_rate)
            deleted_rate_f = float(deleted_rate)
        except (TypeError, ValueError):
            failures.append(f"{base}: real_trained_pass_rate/real_deleted_pass_rate "
                            f"not numeric ({trained_rate!r}, {deleted_rate!r})")
            continue
        degradation = trained_rate_f - deleted_rate_f
        if not (degradation > 0.0):
            failures.append(
                f"{base}: recomputed degradation={degradation:+.4f} "
                f"(trained={trained_rate_f:.4f} deleted={deleted_rate_f:.4f}) "
                "not >0 -- the numeric evidence does NOT show the deleted "
                "arm degrading vs the trained arm on held-out")
            continue

        best = (rp, held, degen, rcpt_hash, trained_rate_f, deleted_rate_f, degradation)
        break

    if best is None:
        emit("RED", "C7: c7-selftest receipt(s) present but none satisfy CHK "
                    f"cleanly -> {failures[:3]}")

    rp, held, degen, rcpt_hash, trained_rate_f, deleted_rate_f, degradation = best
    emit("GREEN",
         f"C7: load-bearing self-growth operator proven by "
         f"{os.path.relpath(rp, ROOT)} (verdict=PASS, proves_load_bearing=true, "
         f"held_out_slices={held} out-of-closure vs deleted-arm slice {degen}); "
         f"operator_constants_hash bound to LIVE operator ({rcpt_hash[:12]}..); "
         f"operator PROSPECTIVE ({prosp_detail}); EVIDENCE-IN-RECEIPT: "
         f"real_trained_pass_rate={trained_rate_f:.4f} "
         f"real_deleted_pass_rate={deleted_rate_f:.4f} recomputed "
         f"degradation={degradation:+.4f} > 0; no invalid-token present")


if __name__ == "__main__":
    main()
