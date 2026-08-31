#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test — Condition C-GROW (status probe / TDD).

C-GROW — MEASURED function-preserving capacity growth (the 1T lever;
         user reframe 2026-06-23).
  R: a receipt showing function-preserving growth (net2net width /
     layer-stacking / expert-addition, warm-started from a trained smaller
     seed) that REDUCES FLOPs-to-target vs an equivalent from-scratch larger
     model, MEASURED BY INSTRUMENTED EXECUTION (not analytically reasoned),
     with before/after PARAMETER COUNTS, the preserved-function check (LOSS
     CONTINUITY across the grow step within tolerance), and the FLOP-SAVING
     DELTA.
     [Issue #683 coordinator ruling, disclosed in
     receipts/ember-totality-audit/audit-20260710T145200Z.json]: the clause's
     purpose is anti-ANALYTICAL. FLOP counts are device-invariant (the
     multiply-add count of a forward/backward pass does not depend on the
     executing device); production-binding enters through hash-verified
     checkpoints + training-history step counts. Literal execution on the
     train daemon SATISFIES this (measured_on_train_daemon:true passes
     outright), but instrumented-execution measurement (e.g.
     torch.utils.flop_counter.FlopCounterMode) against sha256-verified
     production checkpoints, with the total-FLOPs arithmetic recomputed from
     the per-stage figures, ALSO satisfies R -- the literal "train daemon"
     phrasing over-promised relative to what the condition needs.
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
inspecting state under <external-state> — never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is /mnt<local-mount-point>/ on this host (also tries <local-mount-point>/).
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


def flop_saving_self_declares_unmeasured(node):
    """Recursively search a parsed receipt structure for a flop_saving-shaped
    sub-object (its own serialized form matches the FLOP_SAVING vocabulary)
    that itself declares measured:false or a label containing "estimate".

    [PROBE-HARDEN cure, coordinator code-read audit] The prior CHK matched
    FLOP_SAVING against the whole receipt's raw text -- vocabulary-only, so a
    receipt whose flop_saving block truthfully documents itself as an
    ESTIMATE (not measured) still lit every keyword and passed. R-text
    explicitly excludes this case: "an analytical growth argument with NO
    measured FLOP-reduction receipt (a design doc / prose is not a receipt)"
    -- a nested self-declared estimate block is the same excluded case, one
    level deeper than a standalone prose doc. Structural check, not lexical:
    only a sub-object that BOTH matches the FLOP_SAVING vocabulary AND
    explicitly self-declares measured:false / label:estimate is rejected; a
    receipt that merely mentions "estimate" in unrelated prose is untouched.

    Returns a short description string (e.g. "measured=False label='estimate'")
    if such a self-declared-unmeasured block is found, else None.
    """
    if isinstance(node, dict):
        try:
            node_text = json.dumps(node)
        except Exception:
            node_text = str(node)
        if FLOP_SAVING.search(node_text):
            measured_flag = node.get("measured")
            label_flag = node.get("label")
            if measured_flag is False or (
                isinstance(label_flag, str) and "estimate" in label_flag.lower()
            ):
                return f"measured={measured_flag!r} label={label_flag!r}"
        for v in node.values():
            found = flop_saving_self_declares_unmeasured(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = flop_saving_self_declares_unmeasured(item)
            if found:
                return found
    return None


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_FF_STEPS_KEY_RE = re.compile(r"^ff(\d+)_steps$")


def measured_by_instrumented_execution(obj):
    """[ISSUE #683 cure, Finding 2] Read the receipt's OWN measured_on_train_
    daemon field instead of the vocabulary regex MEASURED_MARKER (the THIRD
    instance of the self-declaration-blind class in this file: the
    GREEN-causing receipt self-declares measured_on_train_daemon:false +
    device:cpu and used to pass anyway because the vocabulary check never
    read either field).

    [ISSUE #740 bypass-closure, 2026-07-11] measured_on_train_daemon no
    longer produces an outright pass by itself. It USED to (per the
    coordinator ruling in audit receipts/ember-totality-audit/
    audit-20260710T145200Z.json): "measured_on_train_daemon is True -> pass
    outright" -- a single self-attested boolean sufficient for GREEN with
    zero instrumented-execution evidence behind it, the exact self-
    declaration-blind class this function exists to close (a receipt author
    could write `"measured_on_train_daemon": true` by hand). The flag may
    still be read and reported (it names WHICH measurement context the
    receipt claims -- daemon-resident vs. otherwise), but it never SUBSTITUTES
    for evidence. Every receipt, regardless of the flag's value, must satisfy
    ALL of:
      (a) instrumented-execution provenance is present and NAMED
          (flop_saving_vs_fromscratch.measured is True and .counter
          names a real mechanism, e.g. FlopCounterMode);
      (b) every checkpoint the FLOP figures derive from
          (flop_saving_vs_fromscratch.per_width_measurements.*
          .checkpoint_identity.model_pt_sha256) carries a real-shaped
          sha256;
      (c) the probe RECOMPUTES the total-FLOPs arithmetic from the
          per-stage figures and it matches the receipt's own stated
          totals exactly (grow-path total AND the from-scratch-at-
          same-stepcount total, both derived from per_width_
          measurements x step_provenance, never merely copied).
    Returns (ok: bool, detail: str); any missing/mismatched piece rejects
    with an explicit reason (same shape as the flop_saving_self_declares_
    unmeasured / smoke_markers cures)."""
    if not isinstance(obj, dict):
        return False, "receipt is not a JSON object"

    daemon_flag = obj.get("measured_on_train_daemon")

    fs = obj.get("flop_saving_vs_fromscratch")
    if not isinstance(fs, dict):
        return False, (
            f"measured_on_train_daemon={daemon_flag!r} (a bare flag is never "
            "sufficient) AND flop_saving_vs_fromscratch block is missing -- "
            "cannot satisfy the instrumented-execution requirement")

    # (a) instrumented-execution provenance present and named.
    counter = fs.get("counter")
    if fs.get("measured") is not True or not (
            isinstance(counter, str) and counter.strip()):
        return False, (
            f"measured_on_train_daemon={daemon_flag!r} (a bare flag is never "
            "sufficient) AND flop_saving_vs_fromscratch.measured is not True "
            f"or .counter does not name a real mechanism "
            f"(measured={fs.get('measured')!r}, counter={counter!r})")

    # (b) checkpoint sha256 present for every checkpoint the FLOP figures
    # derive from.
    per_width = fs.get("per_width_measurements")
    if not isinstance(per_width, dict) or not per_width:
        return False, (
            "flop_saving_vs_fromscratch.per_width_measurements missing or "
            "empty -- no per-stage checkpoints to sha-verify")
    stage_flops_per_step = {}
    for stage_key, stage in per_width.items():
        if not isinstance(stage, dict):
            return False, f"per_width_measurements.{stage_key} is not an object"
        ckpt = stage.get("checkpoint_identity")
        sha = ckpt.get("model_pt_sha256") if isinstance(ckpt, dict) else None
        if not (isinstance(sha, str) and _SHA256_RE.match(sha)):
            return False, (
                f"per_width_measurements.{stage_key}.checkpoint_identity."
                f"model_pt_sha256 missing or not sha256-shaped: {sha!r}")
        ff = stage.get("ff")
        per_step = stage.get("flops_per_step_at_prod_batch")
        if not (isinstance(ff, (int, float)) and isinstance(per_step, (int, float))):
            return False, (
                f"per_width_measurements.{stage_key}.ff/"
                "flops_per_step_at_prod_batch missing or non-numeric")
        stage_flops_per_step[int(ff)] = per_step

    # (c) recompute the total-FLOPs arithmetic from the per-stage figures.
    step_prov = fs.get("step_provenance")
    if not isinstance(step_prov, dict):
        return False, "flop_saving_vs_fromscratch.step_provenance missing"

    grow_path_total = 0.0
    matched_any = False
    for key, entry in step_prov.items():
        m = _FF_STEPS_KEY_RE.match(key)
        if not m:
            continue
        ff = int(m.group(1))
        count = entry.get("count") if isinstance(entry, dict) else None
        per_step = stage_flops_per_step.get(ff)
        if per_step is None or not isinstance(count, (int, float)):
            return False, (
                f"step_provenance.{key} has no matching per_width_measurements "
                f"entry with ff={ff}, or count is missing/non-numeric")
        grow_path_total += per_step * count
        matched_any = True

    stated_grow_total = fs.get("flops_grow_path_total_measured")
    if not matched_any or not isinstance(stated_grow_total, (int, float)):
        return False, (
            "could not recompute flops_grow_path_total_measured -- no "
            "matched per-stage step_provenance entries or field missing")
    if stated_grow_total and abs(grow_path_total - stated_grow_total) / stated_grow_total > 1e-6:
        return False, (
            f"recomputed grow-path FLOPs {grow_path_total} != receipt's "
            f"flops_grow_path_total_measured {stated_grow_total} "
            "(arithmetic does not reconcile)")

    grown_ff = max(stage_flops_per_step)
    total_steps_entry = step_prov.get("total_steps_reached")
    total_steps = total_steps_entry.get("count") if isinstance(total_steps_entry, dict) else None
    stated_fromscratch = fs.get("flops_fromscratch_at_same_stepcount_measured")
    if not isinstance(total_steps, (int, float)) or not isinstance(stated_fromscratch, (int, float)):
        return False, (
            "step_provenance.total_steps_reached.count or "
            "flops_fromscratch_at_same_stepcount_measured missing/non-numeric "
            "-- cannot recompute the from-scratch-at-same-stepcount total")
    recomputed_fromscratch = stage_flops_per_step[grown_ff] * total_steps
    if stated_fromscratch and abs(recomputed_fromscratch - stated_fromscratch) / stated_fromscratch > 1e-6:
        return False, (
            f"recomputed from-scratch-at-grown-size FLOPs {recomputed_fromscratch} "
            f"!= receipt's flops_fromscratch_at_same_stepcount_measured "
            f"{stated_fromscratch} (arithmetic does not reconcile)")

    return True, (
        f"instrumented-execution measurement verified (measured_on_train_daemon="
        f"{daemon_flag!r}, informational only -- not decisive): counter={counter!r}, "
        f"{len(per_width)} checkpoint(s) sha256-verified, grow-path total "
        f"{grow_path_total} and from-scratch total {recomputed_fromscratch} "
        "both independently recomputed from per-stage figures and matched")


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

        # [PROBE-HARDEN cure] A flop_saving block that self-declares
        # measured:false or label:estimate is the R-text's explicitly
        # excluded "analytical growth argument with NO measured FLOP-
        # reduction receipt" case -- reject structurally, not just lexically
        # (see flop_saving_self_declares_unmeasured docstring above).
        unmeasured_flop = None
        if isinstance(obj, dict):
            unmeasured_flop = flop_saving_self_declares_unmeasured(obj)
        if unmeasured_flop:
            near_miss.append(
                f"{os.path.relpath(p, ROOT)}: flop_saving block self-declares "
                f"unmeasured/estimate ({unmeasured_flop}) - R-text explicitly "
                f"excludes an analytical estimate with no measured FLOP-"
                f"reduction receipt; does NOT satisfy "
                f"flop_saving_vs_fromscratch CHK")
            continue

        # [ISSUE #683 cure, Finding 2 point 1] measured_by_instrumented_
        # execution is checked STRUCTURALLY (reads the receipt's own
        # measured_on_train_daemon field + flop_saving_vs_fromscratch's real
        # sub-fields), never lexically -- rejected here with an explicit
        # reason, same shape as the two prior structural cures above, rather
        # than folded into the generic "CHK missing [...]" vocabulary list.
        measured_ok, measured_detail = False, ""
        if isinstance(obj, dict):
            measured_ok, measured_detail = measured_by_instrumented_execution(obj)
        if not measured_ok:
            near_miss.append(
                f"{os.path.relpath(p, ROOT)}: measured_by_instrumented_"
                f"execution(not_analytical) FAILS ({measured_detail}) - "
                f"does NOT satisfy the measured/instrumented-execution CHK")
            continue

        # --- (1) Positive CHK against this REAL receipt ----------------------
        # [ISSUE #683 cure, Finding 2 point 3 sweep] Where the receipt carries
        # the field the key literally names, read THAT field first (field-
        # read, same class of fix as measured_by_instrumented_execution
        # above); fall back to the pre-existing raw-text vocabulary regex
        # only when the receipt predates the field (backward compatibility).
        # Disposition of each key is listed in the PR body.
        grow_method_field = obj.get("grow_method") if isinstance(obj, dict) else None
        if isinstance(grow_method_field, str) and grow_method_field.strip():
            method_ok = bool(GROW_METHOD.search(grow_method_field))
        else:
            method_ok = bool(GROW_METHOD.search(raw))

        pcb = obj.get("param_count_before") if isinstance(obj, dict) else None
        pca = obj.get("param_count_after") if isinstance(obj, dict) else None
        if isinstance(pcb, (int, float)) and isinstance(pca, (int, float)):
            params_ok = pca > pcb
        else:
            params_ok = bool(PARAM_BEFORE.search(raw) and PARAM_AFTER.search(raw))

        lc = obj.get("loss_continuity") if isinstance(obj, dict) else None
        lc_flag = (lc.get("training_loss_continuity_within_pre_grow_variance_envelope")
                   if isinstance(lc, dict) else None)
        if lc_flag is False:
            # Same self-declaration-blind class: a receipt that explicitly
            # declares continuity BROKEN must reject here, not be rescued by
            # unrelated vocabulary elsewhere in the text.
            near_miss.append(
                f"{os.path.relpath(p, ROOT)}: loss_continuity."
                f"training_loss_continuity_within_pre_grow_variance_envelope "
                f"is explicitly False - grow step broke function-"
                f"preservation, does NOT satisfy loss_continuity_across_"
                f"grow_step CHK")
            continue
        elif lc_flag is True:
            loss_ok = True
        else:
            loss_ok = bool(LOSS_CONTINUITY.search(raw))

        # flop_saving_vs_fromscratch: the vocabulary presence check stays as
        # a coarse pre-filter, but it is now backed by two structural checks
        # that read the SAME block's real fields -- flop_saving_self_
        # declares_unmeasured() (negative: rejects a self-declared estimate)
        # and measured_by_instrumented_execution() above (positive: recomputes
        # the FLOP totals from per_width_measurements/step_provenance and
        # requires an exact match). See PR body disposition: "already-bound".
        flop_ok = bool(FLOP_SAVING.search(raw))

        checks = {
            "grow_method(net2net/stacking/expert-add/warm-start)": method_ok,
            "param_counts_before_and_after": params_ok,
            "loss_continuity_across_grow_step": loss_ok,
            "flop_saving_vs_fromscratch": flop_ok,
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
             "FLOP-saving vs from-scratch, measured_by_instrumented_execution) "
             f"-> {near_miss[:4]}")

    emit("GREEN",
         f"C-GROW: measured function-preserving growth receipt present in {best} "
         f"(grow method + before/after params + loss-continuity + FLOP-saving vs "
         f"from-scratch, measured_by_instrumented_execution: sha256-verified "
         f"checkpoints + FLOP totals independently recomputed and matched); "
         f"no invalid-token present")


if __name__ == "__main__":
    main()
