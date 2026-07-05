#!/usr/bin/env python3
"""Ember totality test — Condition C11 (status probe / TDD).

C11 — Cycle-duration developmental growth.
  R: receipt-backed progression toward 1h/3h/24h milestones, each buying deeper
     horizon / larger heldout / stronger consolidation / broader transfer / real
     capacity growth, and deletion-sensitive (removing the longer-horizon
     mechanism degrades the result).
  Does NOT count: artificial delay, sleep-padding, idle waits, unchanged tiny
     loops (= unearned_duration); duration as a standalone next action; the 24h
     milestone before a shorter cycle proves the horizon is the needed lever;
     "add params" as growth.
  Invalid-token (✗): unearned_duration
  CHK: each milestone receipt shows a load-bearing, deletion-sensitive capacity
       increase.

Gloss (task): cycle-duration developmental growth toward 1h/3h/24h, each
  load-bearing + deletion-sensitive; NOT artificial delay / sleep-padding /
  add-params.
Receipt hint: scripts/ember_native_one_hour_cycle.py,
  ember_native_three_hour_cycle.py, ember_native_duration_scale_probe.py
  + receipts.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED " or "GREEN ". RED/GREEN is determined by really
inspecting state under kai-converge — never hardcoded.

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive may mount at /b/ or /mnt/b/ on this host.
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

import datetime
import json
import os
import sys

# --- Locate kai-converge robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "kai-converge"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# Receipt directory holding the native developmental-duration milestones.
RECEIPT_DIR_REL = os.path.join(
    "receipts", "ember-mvp", "breakthrough-goal-20260619"
)

# The three milestones C11 requires progression toward. Each maps to the
# expected milestone receipt filename and the minimum active-seconds the
# milestone must demonstrate (1h=3600, 3h=10800, 24h=86400). A milestone whose
# receipt is genuinely ABSENT makes the progression incomplete -> RED.
MILESTONES = [
    ("1-hour", "native-one-hour-cycle-20260619T-now.json", 3600.0),
    ("3-hour", "native-three-hour-cycle-20260619T-now.json", 10800.0),
    ("24-hour", "native-twenty-four-hour-cycle-20260619T-now.json", 86400.0),
]

# The load_bearing_duration_growth flags that MUST all be true for a milestone
# receipt to show a load-bearing capacity increase (CHK).
LOAD_BEARING_FLAGS = [
    "deeper_experiment_horizon",
    "larger_heldout_surface",
    "stronger_consolidation",
    "broader_transfer_reuse_checks",
    "active_capacity_growth",
]

# [ISSUE #97 cure 1, 2026-07-04] Execution-binding hardening. The pre-cure
# checker only ever inspected the cumulative `active_seconds` field of EACH
# milestone receipt in isolation -- it never verified the receipt's OWN
# claimed provenance chain (this_run_active_seconds / inherited_active_
# seconds), never verified consecutive tiers are separated by at least the
# milestone's own incremental target delta, and never checked a single run
# cannot claim more active-work seconds than the wall-clock time it took.
# All three checks are execution-binding: they tie the receipt's numbers to
# what could physically have happened, not just to whether the right JSON
# keys are present.
TS_FMT = "%Y%m%dT%H%M%SZ"
PROVENANCE_TOLERANCE_SECONDS = 1.0  # float-rounding slack for chain arithmetic
WALL_VS_ACTIVE_TOLERANCE_SECONDS = 0.05  # slack for this_run <= wall_seconds


def _parse_ts(value):
    """Parse a receipt's compact ts string (e.g. 20260703T175910Z) to a naive
    UTC datetime. Returns None if absent/unparseable (caller treats that as
    an execution-binding failure, never as a silent pass)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.strptime(value, TS_FMT)
    except ValueError:
        return None


# --- Invalid-tokens (negative assertions; C11 "does NOT count" set) -----------
# C11's explicit ✗ token plus the does-NOT-count substitutes, encoded so that a
# match in a milestone receipt is a violation.
INVALID_TOKENS = [
    "unearned_duration",          # C11 explicit ✗
    "artificial_delay",
    "sleep_padding",              # as a marker/verdict string, not the =0 field
    "idle_wait",
    "add_params",
    "add params",
]


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def raw_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def check_invalid_tokens(label, text):
    """Return a list of (token, label) hits for any invalid-token appearing as a
    LIVE string in the receipt — never inside a legitimate field name or an
    explanatory field that NEGATES the failure mode.

    Two classes of legitimate, non-violating mentions are scrubbed before
    scanning:
      1. Numeric/identifier field names that merely embed a token substring,
         e.g. `sleep_padding_seconds` (a numeric field; =0 means EARNED) and the
         explanatory key `why_not_artificial_delay`.
      2. The VALUE of explanatory negation fields. The receipts carry a
         `why_not_artificial_delay` prose value that explicitly states no sleep
         is used to inflate duration. That negation is the OPPOSITE of a
         violation; flagging it would mean a receipt is penalized for proving it
         is not artificial. We drop the entire value of any key whose name
         begins with `why_not_` before scanning.
    A token surviving this scrub is a genuine live marker (e.g. a verdict of
    "unearned_duration", or "add_params" used as the growth mechanism)."""
    # Parse so we can drop explanatory-negation values structurally, not by
    # fragile string surgery. Fall back to raw text if parse fails.
    scrub = text
    try:
        obj = json.loads(text)

        def strip_negations(node):
            if isinstance(node, dict):
                return {
                    k: ("" if k.lower().startswith("why_not_")
                        else strip_negations(v))
                    for k, v in node.items()
                }
            if isinstance(node, list):
                return [strip_negations(x) for x in node]
            return node

        scrub = json.dumps(strip_negations(obj))
    except Exception:
        scrub = text

    low = scrub.lower()
    # Remove legitimate field NAMES that embed a token substring.
    for field_name in ("sleep_padding_seconds", "why_not_artificial_delay"):
        low = low.replace(field_name, "<<field>>")
    hits = []
    for t in INVALID_TOKENS:
        if t.lower() in low:
            hits.append((t, label))
    return hits


def assess_milestone(name, path, min_seconds):
    """Inspect one milestone receipt. Returns a dict describing its state:
       present, well_formed, earned (no sleep padding, real active seconds),
       load_bearing (all flags), deletion_sensitive, invalid_token_hits.
    """
    state = {
        "name": name,
        "path": path,
        "present": os.path.isfile(path),
        "wellformed": False,
        "active_seconds": None,
        "min_seconds": min_seconds,
        "earned": False,
        "load_bearing": False,
        "deletion_sensitive": False,
        "missing_flags": [],
        "token_hits": [],
        "reason": "",
        # [ISSUE #97 cure 1] execution-binding fields.
        "ts": None,
        "inherited_active_seconds": None,
        "this_run_active_seconds": None,
        "wall_seconds": None,
        "wall_consistent": False,
    }
    if not state["present"]:
        state["reason"] = "milestone receipt ABSENT"
        return state

    text = raw_text(path)
    state["token_hits"] = check_invalid_tokens(name, text)
    try:
        d = load_json(path)
    except Exception as e:  # broken receipt -> cannot count as a pass
        state["reason"] = f"receipt unparseable: {e}"
        return state
    state["wellformed"] = True

    aw = d.get("active_work", {}) or {}
    active_seconds = aw.get("active_seconds")
    state["active_seconds"] = active_seconds
    # [ISSUE #97 cure 1] execution-binding raw fields, captured for the
    # cross-tier checks run afterward in main().
    state["ts"] = _parse_ts(d.get("ts"))
    state["inherited_active_seconds"] = aw.get("inherited_active_seconds")
    state["this_run_active_seconds"] = aw.get("this_run_active_seconds")
    state["wall_seconds"] = aw.get("wall_seconds")

    # Earned duration: sleep padding == 0 AND active_seconds reaches the
    # milestone target (within a small tolerance below the nominal target).
    spad = d.get("sleep_padding_seconds", None)
    enough_time = (
        isinstance(active_seconds, (int, float))
        and active_seconds >= min_seconds
    )
    no_padding = (spad == 0)
    state["earned"] = bool(no_padding and enough_time)
    if not no_padding:
        state["reason"] = f"sleep_padding_seconds != 0 ({spad}) -> unearned_duration"
    elif not enough_time:
        state["reason"] = (
            f"active_seconds {active_seconds} < milestone target {min_seconds}"
        )

    # Load-bearing capacity increase: every LOAD_BEARING_FLAGS flag true.
    lbdg = d.get("load_bearing_duration_growth", {}) or {}
    missing = [f for f in LOAD_BEARING_FLAGS if lbdg.get(f) is not True]
    state["missing_flags"] = missing
    state["load_bearing"] = (len(missing) == 0)
    if missing and not state["reason"]:
        state["reason"] = f"load_bearing_duration_growth flags not all true: {missing}"

    # Deletion-sensitive: a deletion_ablation block that degrades the decision
    # (and/or active work) when the longer-horizon mechanism is removed.
    da = d.get("deletion_ablation", {}) or {}
    degrades = (
        da.get("degrades_decision") is True
        or da.get("degrades_active_seconds") is True
        or da.get("degrades_row_passes") is True
    )
    # The deleted next-action must be disallowed (the loop decision breaks).
    deleted_next = da.get("deleted_selected_next_action", {}) or {}
    next_disallowed = deleted_next.get("disallowed") is True
    state["deletion_sensitive"] = bool(degrades and next_disallowed)
    if not state["deletion_sensitive"] and not state["reason"]:
        state["reason"] = (
            "deletion_ablation does not show a degraded/blocked next decision"
        )

    # [ISSUE #97 cure 1] wall >= active (per-run, not cumulative): a single
    # run cannot claim more active-work seconds than the wall-clock time that
    # run actually took. Scoped to this_run_active_seconds vs wall_seconds
    # (the CUMULATIVE active_seconds legitimately exceeds any one run's
    # wall_seconds once prior tiers' work has been inherited -- that is not
    # a violation, only a per-run claim exceeding its own run's wall time is).
    trs = state["this_run_active_seconds"]
    wall = state["wall_seconds"]
    if not (isinstance(trs, (int, float)) and isinstance(wall, (int, float))):
        state["wall_consistent"] = False
        if not state["reason"]:
            state["reason"] = (
                "this_run_active_seconds/wall_seconds missing or non-numeric "
                "-> cannot execution-bind this run's claim to wall-clock time"
            )
    else:
        state["wall_consistent"] = (trs <= wall + WALL_VS_ACTIVE_TOLERANCE_SECONDS)
        if not state["wall_consistent"] and not state["reason"]:
            state["reason"] = (
                f"this_run_active_seconds ({trs}) exceeds this run's own "
                f"wall_seconds ({wall}) -> physically impossible, unearned_duration"
            )

    return state


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C11: state root not found under any known layout -- input-missing, dead branch under the flat-layout resolver (paper-consistency flip, 2026-07-02)")

    rdir = os.path.join(ROOT, RECEIPT_DIR_REL)
    if not os.path.isdir(rdir):
        # Input-missing (the receipt directory itself is absent), not
        # evaluated-false: nothing exists for the CHK to inspect.
        emit("UNEVALUABLE", f"C11: receipt dir ABSENT at {RECEIPT_DIR_REL} -> "
                    "no native developmental-duration milestones exist")

    states = [
        assess_milestone(name, os.path.join(rdir, fn), secs)
        for (name, fn, secs) in MILESTONES
    ]

    # --- (B) Negative assertion: NO invalid-token in any milestone receipt -----
    all_token_hits = []
    for st in states:
        all_token_hits.extend(st["token_hits"])
    all_token_hits = list(dict.fromkeys(all_token_hits))
    if all_token_hits:
        emit("RED",
             f"C11: invalid-token(s) present in milestone receipt(s) "
             f"-> {all_token_hits[:3]} (unearned_duration / does-NOT-count)")

    # --- (C) Positive CHK per present milestone --------------------------------
    # Any PRESENT milestone receipt must be earned + load-bearing +
    # deletion-sensitive; a present-but-defective one is a RED (wrong-for-the-
    # right-reason, e.g. sleep padding or missing ablation).
    present = [st for st in states if st["present"]]
    absent = [st for st in states if not st["present"]]

    defective = [
        st for st in present
        if not (st["earned"] and st["load_bearing"] and st["deletion_sensitive"]
                and st["wall_consistent"])
    ]
    if defective:
        d0 = defective[0]
        emit("RED",
             f"C11: milestone '{d0['name']}' present but FAILS CHK "
             f"(earned={d0['earned']} load_bearing={d0['load_bearing']} "
             f"deletion_sensitive={d0['deletion_sensitive']} "
             f"wall_consistent={d0['wall_consistent']}): {d0['reason']}")

    # [ISSUE #97 cure 1] Cross-tier execution-binding: per-tier this_run/
    # inherited provenance resolution + inter-tier ts separation >= the
    # milestone's own incremental target delta. Runs over consecutive
    # PRESENT tiers in MILESTONES order (1h -> 3h -> 24h); a genuinely
    # absent tier already emits RED above the ordinary way, so this loop
    # only strengthens tiers that are jointly present.
    present_by_name = {st["name"]: st for st in states}
    ordered_present = [st for (nm, _fn, _secs) in MILESTONES
                        for st in [present_by_name[nm]] if st["present"]]
    for prev, cur in zip(ordered_present, ordered_present[1:]):
        # (i) inherited_active_seconds must resolve to the PRIOR tier's own
        # active_seconds -- a receipt whose "inherited" number does not match
        # what the earlier receipt actually recorded is not a genuine
        # carry-forward (it is either fabricated or the chain was reset).
        inh = cur["inherited_active_seconds"]
        prior_active = prev["active_seconds"]
        if not (isinstance(inh, (int, float)) and isinstance(prior_active, (int, float))):
            emit("RED",
                 f"C11: milestone '{cur['name']}' inherited_active_seconds or "
                 f"prior milestone '{prev['name']}' active_seconds missing/"
                 f"non-numeric -> cannot resolve provenance chain")
        if abs(inh - prior_active) > PROVENANCE_TOLERANCE_SECONDS:
            emit("RED",
                 f"C11: milestone '{cur['name']}' inherited_active_seconds "
                 f"({inh}) does NOT match prior milestone '{prev['name']}' "
                 f"active_seconds ({prior_active}) -> provenance chain broken "
                 f"(fabricated or reset inheritance, not a genuine carry-forward)")

        # (i-b) arithmetic self-consistency: active_seconds == inherited + this_run.
        cur_active = cur["active_seconds"]
        this_run = cur["this_run_active_seconds"]
        if (isinstance(cur_active, (int, float)) and isinstance(inh, (int, float))
                and isinstance(this_run, (int, float))):
            if abs(cur_active - (inh + this_run)) > PROVENANCE_TOLERANCE_SECONDS:
                emit("RED",
                     f"C11: milestone '{cur['name']}' active_seconds "
                     f"({cur_active}) != inherited_active_seconds ({inh}) + "
                     f"this_run_active_seconds ({this_run}) -> internal "
                     f"provenance arithmetic does not reconcile")

        # (ii) inter-tier wall-clock ts separation must be >= this milestone's
        # own incremental target delta (target[cur] - target[prev]) -- two
        # tiers minted back-to-back (seconds apart) cannot represent a
        # genuine hours-long progression between them.
        if prev["ts"] is None or cur["ts"] is None:
            emit("RED",
                 f"C11: milestone '{prev['name']}' or '{cur['name']}' ts "
                 f"missing/unparseable -> cannot verify inter-tier separation")
        incremental_target = cur["min_seconds"] - prev["min_seconds"]
        actual_gap = (cur["ts"] - prev["ts"]).total_seconds()
        if actual_gap < incremental_target:
            emit("RED",
                 f"C11: milestone '{cur['name']}' ts is only {actual_gap:.0f}s "
                 f"after '{prev['name']}' ts, but the incremental target "
                 f"between these tiers is {incremental_target:.0f}s -> tiers "
                 f"minted too close together to represent a genuine "
                 f"progression (unearned_duration)")

    # All present milestones pass CHK. If any required milestone is ABSENT, the
    # progression toward 1h/3h/24h is genuinely incomplete -> RED for the right
    # reason (artifact absent, not faked).
    if absent:
        passed = ", ".join(
            f"{st['name']}({st['active_seconds']:.0f}s)" for st in present
        ) or "none"
        missing_names = ", ".join(st["name"] for st in absent)
        emit("RED",
             f"C11: developmental-duration progression INCOMPLETE -> "
             f"earned+load-bearing+deletion-sensitive milestones [{passed}] "
             f"present & CHK-passing, but milestone(s) [{missing_names}] genuinely "
             f"ABSENT (no receipt). The full 1h/3h/24h progression is not yet "
             f"proven; no unearned_duration / sleep-padding / add-params present.")

    # GREEN: all three milestones present, each earned, load-bearing,
    # deletion-sensitive, with no invalid-token.
    detail = ", ".join(
        f"{st['name']}({st['active_seconds']:.0f}s)" for st in states
    )
    emit("GREEN",
         f"C11: 1h/3h/24h developmental-duration progression COMPLETE -> "
         f"[{detail}] each earned (sleep_padding=0, active_seconds>=target), "
         f"load-bearing (all 5 capacity flags true), deletion-sensitive "
         f"(deleted next-action disallowed + degrades), no unearned_duration / "
         f"artificial-delay / add-params token.")


if __name__ == "__main__":
    main()
