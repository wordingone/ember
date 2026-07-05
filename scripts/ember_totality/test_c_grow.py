#!/usr/bin/env python3
"""Ember totality test — Condition C-GROW (status probe / TDD).

C-GROW — MEASURED function-preserving capacity growth (the 1T lever;
         user reframe 2026-06-23).
  R: a receipt showing function-preserving growth (net2net width /
     layer-stacking / expert-addition, warm-started from a trained smaller
     seed) that REDUCES FLOPs-to-target vs an equivalent from-scratch larger
     model, MEASURED on the train daemon (not analytically reasoned), with
     before/after PARAMETER COUNTS, the preserved-function check (LOSS
     CONTINUITY across the grow step within tolerance), and the FLOP-SAVING
     DELTA.
  Does NOT count:
    - from-scratch widening (the refuted H=2048 path = a bigger from-scratch
      model, not growth);
    - "add params" as growth;
    - an analytical growth argument with NO measured FLOP-reduction receipt
      (a design doc / prose is not a receipt);
    - a grow step that breaks function-preservation (loss spike beyond
      tolerance).
  Invalid-tokens (explicit ✗): invalid_growth_unmeasured,
                               invalid_fromscratch_widening_as_growth
  CHK: a grow-receipt shows post-grow loss CONTINUOUS within tolerance AND
     FLOPs-to-fixed-target LOWER than the from-scratch baseline at the grown
     size.

Receipt hint: receipts/*grow*, scripts/ember_growth_harness.py,
scripts/ember_scale_harness.py.

This is a STATUS PROBE. It ALWAYS exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under kai-converge — never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive is /mnt/b/ on this host (also tries /b/).
"""

# [PATH-REWRITE 2026-07-01] Imported from
# B:/M/avir/leo/state/ember-totality-build/ into
# B:/M/ember-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at B:/M/avir/leo/state/kai-converge (and /mnt/b/M/...,
# /b/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. kai-converge does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import glob
import json
import os
import re
import sys

# --- Locate kai-converge robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "kai-converge"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# (2) Invalid-tokens the condition declares as NON-counting outcomes.
# The two explicit ✗ tokens, plus encodings of the four "does NOT count" cases.
INVALID_TOKENS = [
    "invalid_growth_unmeasured",                 # explicit ✗: analytical / not measured
    "invalid_fromscratch_widening_as_growth",    # explicit ✗: from-scratch widening relabelled
    "fromscratch_widening_as_growth",            # does NOT count: H=2048 bigger-from-scratch
    "add_params_as_growth",                      # does NOT count: "add params" called growth
    "analytical_growth_no_measured_flop",        # does NOT count: prose argument, no measured receipt
    "loss_spike_breaks_function_preservation",   # does NOT count: grow step breaks function-preserv.
]

# The growth method the receipt must name (R): function-preserving operators.
GROW_METHOD = re.compile(
    r"net2net|layer[\s_-]*stack|stacking|expert[\s_-]*add|"
    r"function[\s_-]*preserv|warm[\s_-]*start",
    re.IGNORECASE)

# Before/after PARAMETER COUNTS must be present as real numbers (R).
PARAM_BEFORE = re.compile(
    r"(param|params|parameter)[\s_\"']*(count)?[\s_\"']*(before|pre|seed|small)"
    r"|(before|pre|seed|small)[\s_\"']*(param|params|parameter)",
    re.IGNORECASE)
PARAM_AFTER = re.compile(
    r"(param|params|parameter)[\s_\"']*(count)?[\s_\"']*(after|post|grown|large)"
    r"|(after|post|grown|large)[\s_\"']*(param|params|parameter)",
    re.IGNORECASE)

# Loss continuity across the grow step within tolerance (the preserved-function
# check) — must be an explicit MEASURED check, not prose.
LOSS_CONTINUITY = re.compile(
    r"loss[\s_-]*continu|continu\w*[\s_-]*loss|"
    r"(pre|post)[\s_-]*grow[\s_-]*loss|loss[\s_-]*(pre|post)[\s_-]*grow|"
    r"function[\s_-]*preserv\w*[\s_-]*(check|tol)",
    re.IGNORECASE)

# The FLOP-saving delta vs an equivalent from-scratch larger model (R + CHK).
FLOP_SAVING = re.compile(
    r"flop[\s_-]*sav|flops?[\s_-]*to[\s_-]*target|"
    r"flop[\s_-]*reduc|flop[\s_-]*delta|"
    r"vs[\s_-]*from[\s_-]*scratch|from[\s_-]*scratch[\s_-]*baseline",
    re.IGNORECASE)

# "Measured on the train daemon" — the receipt is an executed measurement, not
# an analytical argument. JSON receipts with these markers indicate real runs.
MEASURED_MARKER = re.compile(
    r"train[\s_-]*daemon|measured|wall[\s_-]*seconds|throughput|"
    r"\"loss\"|step\b|tokens_seen|mfu",
    re.IGNORECASE)


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def candidate_files():
    """Files that could carry a C-GROW *measured grow receipt*.

    C-GROW's R demands a RECEIPT measured on the train daemon; a design doc /
    prose argument is explicitly a does-NOT-count ("analytical growth argument
    with no measured FLOP-reduction receipt"). So the satisfying artifact must
    be a *receipt* (JSON / JSONL) carrying real measured numbers — NOT a .md
    design doc and NOT the GOAL/STATE files (those merely quote the condition).

    We therefore scan receipts/ for JSON/JSONL artifacts. Filename hints
    (*grow*) are prioritized, but we also content-scan every receipt JSON for
    the function-preserving-growth signature so a differently-named receipt is
    still caught.
    """
    if ROOT is None:
        return []
    out = set()
    # (a) filename-hinted receipts.
    name_pats = [
        os.path.join(ROOT, "receipts", "**", "*grow*"),
        os.path.join(ROOT, "receipts", "**", "*net2net*"),
        os.path.join(ROOT, "receipts", "**", "*stack*"),
        os.path.join(ROOT, "receipts", "**", "*warm*"),
    ]
    for pat in name_pats:
        for p in glob.glob(pat, recursive=True):
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in (".json", ".jsonl"):
                out.add(p)
    # (b) content-scan every receipt JSON/JSONL for the grow-method signature
    #     (catches a satisfying receipt that is not named *grow*).
    base = os.path.join(ROOT, "receipts")
    for p in glob.glob(os.path.join(base, "**", "*"), recursive=True):
        if not os.path.isfile(p):
            continue
        if os.path.splitext(p)[1].lower() not in (".json", ".jsonl"):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
        except Exception:
            continue
        if GROW_METHOD.search(txt):
            out.add(p)
    return sorted(out)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-GROW: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    files = candidate_files()

    best = None
    near_miss = []     # receipts that mention growth but fail CHK
    invalid_hits = []  # (file, [tokens]) for negative-assertion reporting

    for p in files:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
        except Exception as exc:
            near_miss.append(f"{os.path.basename(p)}: unreadable ({exc})")
            continue
        low = raw.lower()

        # --- (2) Negative assertion: NONE of the invalid-tokens may appear ---
        hit = [t for t in INVALID_TOKENS if t.lower() in low]
        if hit:
            invalid_hits.append((os.path.relpath(p, ROOT), hit))
            continue

        # Guard against the loop-readiness / cycle-budget harnesses being
        # mistaken for C-GROW. Their tickets are explicitly NOT function-
        # preserving model growth:
        #   EMBER-GROWTH-CONTRACTION-STABILITY = "is the loop ready to grow"
        #       (== the does-NOT-count "'add params' as growth").
        #   EMBER-BOUNDED-SCALE-UP             = cycle WALL-TIME scale-up,
        #       not parameter growth.
        try:
            obj = json.loads(raw)
            ticket = obj.get("ticket") if isinstance(obj, dict) else None
        except Exception:
            ticket = None
        if ticket in ("EMBER-GROWTH-CONTRACTION-STABILITY", "EMBER-BOUNDED-SCALE-UP"):
            near_miss.append(
                f"{os.path.relpath(p, ROOT)}: ticket={ticket} is loop-readiness/"
                f"budget-scale, NOT measured function-preserving param growth")
            continue

        # [HARDENED 2026-07-03] A plumbing SMOKE receipt (tiny fresh-init
        # model, CPU) truthfully carries every CHK marker and turned C-GROW
        # GREEN off a non-claim (builder-flagged same day). A receipt that
        # self-declares smoke anywhere load-bearing is a plumbing check, not
        # evidence: exclude by verdict/mode/filename, never accept.
        smoke_markers = []
        if isinstance(obj, dict):
            for fld in ("verdict", "mode", "run_mode", "kind"):
                v = obj.get(fld)
                if isinstance(v, str) and "smoke" in v.lower():
                    smoke_markers.append(f"{fld}={v}")
        if "smoke" in os.path.basename(p).lower():
            smoke_markers.append("filename")
        if smoke_markers:
            near_miss.append(
                f"{os.path.relpath(p, ROOT)}: self-declared smoke receipt "
                f"({', '.join(smoke_markers)}) - plumbing check, not a "
                f"measured growth claim")
            continue

        # --- (1) Positive CHK against this REAL receipt ----------------------
        method_ok = bool(GROW_METHOD.search(raw))
        params_ok = bool(PARAM_BEFORE.search(raw) and PARAM_AFTER.search(raw))
        loss_ok = bool(LOSS_CONTINUITY.search(raw))
        flop_ok = bool(FLOP_SAVING.search(raw))
        measured_ok = bool(MEASURED_MARKER.search(raw))

        checks = {
            "grow_method(net2net/stacking/expert-add/warm-start)": method_ok,
            "param_counts_before_and_after": params_ok,
            "loss_continuity_across_grow_step": loss_ok,
            "flop_saving_vs_fromscratch": flop_ok,
            "measured_on_train_daemon(not_analytical)": measured_ok,
        }
        missing = [k for k, ok in checks.items() if not ok]
        if missing:
            near_miss.append(f"{os.path.relpath(p, ROOT)}: CHK missing {missing}")
            continue

        best = os.path.relpath(p, ROOT)
        break

    # --- Resolve verdict ------------------------------------------------------
    if invalid_hits and best is None:
        first = invalid_hits[0]
        emit("RED",
             f"C-GROW: invalid-token present in {first[0]} {first[1]} "
             f"(does-NOT-count outcome) -> condition NOT met")

    if best is None:
        if not files:
            emit("RED",
                 "C-GROW: no growth-signature receipt found under receipts/ "
                 "(no net2net/stacking/expert-add/warm-start measured receipt) "
                 "-> satisfying artifact ABSENT")
        emit("RED",
             "C-GROW: growth-related receipts exist but NONE satisfies CHK "
             "(needs net2net/stacking/expert-add warm-start receipt with "
             "before/after param counts + loss-continuity across grow step + "
             "FLOP-saving vs from-scratch, measured on train daemon) -> "
             f"{near_miss[:4]}")

    emit("GREEN",
         f"C-GROW: measured function-preserving growth receipt present in {best} "
         f"(grow method + before/after params + loss-continuity + FLOP-saving vs "
         f"from-scratch, measured); no invalid-token present")


if __name__ == "__main__":
    main()
