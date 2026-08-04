#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ember totality test -- Condition C11 (status probe / TDD).

C11 -- Experience-horizon capability delta (duration-as-wall-clock is a timer,
  not a lever).
  R: across increasing experience-horizon scales (short<medium<long *novel*
     problems learned and consolidated into resident weights), each longer
     horizon -- via real learning updates (pre!=post parameter hashes; gradient
     steps Merkle-bound to the novel problem ids) -- produces a measured
     held-out capability delta the shorter horizon does not reach, and the
     long-horizon consolidation is load-bearing (deleting it degrades
     long-horizon capability back toward the SHORT-HORIZON level). Capability is
     proven by live re-execution of sampled solutions, never trusted arrays.
  Does NOT count: wall-clock duration; CPU re-hash of repeated rows; fabricated
     outcome booleans; identical pre/post checkpoints; deletion vs the untrained
     base instead of the short-horizon checkpoint.
  Invalid-tokens (?): unearned_duration, clock_in_disguise, fabricated_outcomes,
     novelty_spoof, deletion_uses_wrong_baseline
  CHK: this file -- 9 recomputed checks, no trusted scalars.

Spec: docs/c11-experience-horizon-spec.md (authored under issue #107; it is the
machine-checkable form of the conditions-v1.md C11 row and this probe implements
it check-for-check).

[ISSUE #107, 2026-08-03] This probe previously evaluated the RETIRED 1h/3h/24h
wall-clock re-earn contract, so C11 reported UNEVALUABLE because a receipt
directory belonging to a superseded condition was absent -- UNEVALUABLE for the
wrong reason. It now evaluates the live experience-horizon contract. The
evidence itself is still future work (it needs the owned 3B substrate under
EMBER-05), so the honest current output remains UNEVALUABLE -- but now naming
the real receipts and the per-check gaps of the contract actually in force.

This is a STATUS PROBE. It always exits 0 and prints exactly one line beginning
with "RED ", "GREEN " or "UNEVALUABLE ". The verdict is determined by really
inspecting state under the resolved root -- never hardcoded.
"""

import hashlib
import json
import os
import sys

# --- Root resolution (unchanged convention: EMBER_TOTALITY_ROOT overrides) ----
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT)
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# The canonical spec this probe implements. Resolved against REPO_ROOT (this
# file's own repository), NOT the possibly-overridden evidence ROOT: a control
# fixture root supplies receipts, never the version-controlled contract.
SPEC_REL = os.path.join("docs", "c11-experience-horizon-spec.md")

RECEIPT_DIR_REL = os.path.join("receipts", "ember-mvp", "c11-experience-horizon")

HORIZONS = ["short", "medium", "long"]
HORIZON_FILES = {
    "short": "horizon-short.json",
    "medium": "horizon-medium.json",
    "long": "horizon-long.json",
}
DELETION_FILE = "deletion.json"

# Pre-registered noise floor for the held-out capability delta between adjacent
# horizons (spec v1, CHK-5). A gap at or below this is not a delta.
NOISE_FLOOR = 0.02

DELETION_ARMS = ["short", "long", "long_minus_consolidation"]

INVALID_TOKENS = [
    "unearned_duration",
    "clock_in_disguise",
    "fabricated_outcomes",
    "novelty_spoof",
    "deletion_uses_wrong_baseline",
]

# Duration-shaped fields stripped for the CHK-9 invariance re-derivation.
DURATION_KEYS_EXACT = {"wall_seconds", "duration_s", "elapsed_s", "active_seconds"}

PASS, FAIL, GAP = "PASS", "FAIL", "GAP"


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


# --- helpers -----------------------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def strip_hash_prefix(value):
    if isinstance(value, str) and ":" in value:
        return value.split(":", 1)[1]
    return value


def merkle_root(leaf_hexes):
    """Pairwise sha256 over hex-string concatenation, odd node promoted.
    Declared in the spec as the merkle_leaf_recipe's companion tree rule."""
    if not leaf_hexes:
        return None
    level = list(leaf_hexes)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(hashlib.sha256((level[i] + level[i + 1]).encode()).hexdigest())
            else:
                nxt.append(level[i])
        level = nxt
    return level[0]


def problem_ids(receipt):
    return ((receipt.get("novel_problems") or {}).get("problem_ids")) or []


def heldout_items(receipt):
    return ((receipt.get("heldout") or {}).get("items")) or []


def recompute_score(items):
    """Mean of the per-item pass flags, recomputed from rows. Returns None when
    there are no rows to compute from (a gap, never a 0.0 that reads as a
    measured floor)."""
    if not items:
        return None
    passed = 0
    for it in items:
        if isinstance(it, dict) and it.get("passed") is True:
            passed += 1
    return passed / float(len(items))


def strip_durations(node):
    """Return a deep copy with every duration-shaped field removed (CHK-9)."""
    if isinstance(node, dict):
        return {
            k: strip_durations(v) for k, v in node.items()
            if not (k in DURATION_KEYS_EXACT or k.endswith("_seconds"))
        }
    if isinstance(node, list):
        return [strip_durations(x) for x in node]
    return node


def present_horizons(receipts):
    return [h for h in HORIZONS if receipts.get(h) is not None]


# --- the nine checks ---------------------------------------------------------
# Each returns (status, detail). GAP means the check's own claim-bearing input
# is absent (nothing has been claimed) -- distinct from FAIL, which means a
# present claim does not hold.

def chk1_horizon_ordering(receipts):
    """Ordering key is the count of distinct consolidated novel problems.
    No duration field participates."""
    missing = [h for h in HORIZONS if receipts.get(h) is None]
    if missing:
        return GAP, f"horizon receipt(s) absent: {missing}"
    counts = {}
    for h in HORIZONS:
        ids = problem_ids(receipts[h])
        if not ids:
            return GAP, f"'{h}' carries no novel_problems.problem_ids"
        counts[h] = len(set(ids))
    if not (counts["short"] < counts["medium"] < counts["long"]):
        return FAIL, (f"novel-problem counts not strictly increasing "
                      f"(short={counts['short']} medium={counts['medium']} "
                      f"long={counts['long']}) -> clock_in_disguise")
    return PASS, (f"novel-problem counts short={counts['short']} < "
                  f"medium={counts['medium']} < long={counts['long']}")


def chk2_novelty_integrity(receipts):
    """No repeated rows, no pretrain overlap, longer horizon strictly supersets
    the shorter one's experience."""
    if not present_horizons(receipts):
        return GAP, "no horizon receipt present"
    sets = {}
    for h in HORIZONS:
        r = receipts.get(h)
        if r is None:
            continue
        ids = problem_ids(r)
        if not ids:
            return GAP, f"'{h}' carries no novel_problems.problem_ids"
        if len(set(ids)) != len(ids):
            dupes = len(ids) - len(set(ids))
            return FAIL, (f"'{h}' problem_ids contains {dupes} repeated row(s) "
                          f"-> re-hashing repeated rows is not new experience "
                          f"(novelty_spoof)")
        overlap = (r.get("novel_problems") or {}).get("pretrain_overlap_ids")
        if overlap is None:
            return GAP, f"'{h}' does not declare novel_problems.pretrain_overlap_ids"
        if overlap:
            return FAIL, (f"'{h}' declares {len(overlap)} pretrain-corpus "
                          f"overlap id(s) -> not novel (novelty_spoof)")
        sets[h] = set(ids)
    for shorter, longer in (("short", "medium"), ("medium", "long")):
        if shorter in sets and longer in sets:
            if not sets[shorter] < sets[longer]:
                return FAIL, (f"'{longer}' problem-id set is not a strict superset "
                              f"of '{shorter}' -> the longer horizon did not learn "
                              f"everything the shorter one did plus more "
                              f"(novelty_spoof)")
    if len(sets) < len(HORIZONS):
        return GAP, f"only {sorted(sets)} present; superset chain incomplete"
    return PASS, "no repeats, no pretrain overlap, short < medium < long id sets"


def chk3_real_parameter_change(receipts):
    """pre != post per horizon; post hashes pairwise distinct across horizons."""
    if not present_horizons(receipts):
        return GAP, "no horizon receipt present"
    posts = {}
    for h in HORIZONS:
        r = receipts.get(h)
        if r is None:
            continue
        lu = r.get("learning_update") or {}
        pre = strip_hash_prefix(lu.get("pre_param_hash"))
        post = strip_hash_prefix(lu.get("post_param_hash"))
        if not pre or not post:
            return GAP, (f"'{h}' missing learning_update.pre_param_hash/"
                         f"post_param_hash")
        if pre == post:
            return FAIL, (f"'{h}' pre_param_hash == post_param_hash -> the "
                          f"checkpoint is identical, no learning update happened")
        posts[h] = post
    dupes = [h for h in posts if list(posts.values()).count(posts[h]) > 1]
    if dupes:
        return FAIL, (f"horizons {sorted(dupes)} share an identical "
                      f"post_param_hash -> the horizons are the same checkpoint")
    if len(posts) < len(HORIZONS):
        return GAP, f"only {sorted(posts)} present; cross-horizon distinctness incomplete"
    return PASS, "pre!=post per horizon and all three post hashes distinct"


def chk4_merkle_binding(receipts):
    """Recompute the Merkle root over the receipt's own gradient-step leaves and
    require every leaf's problem_id to be in that horizon's novel id set."""
    if not present_horizons(receipts):
        return GAP, "no horizon receipt present"
    checked = []
    for h in HORIZONS:
        r = receipts.get(h)
        if r is None:
            continue
        lu = r.get("learning_update") or {}
        steps = lu.get("gradient_steps")
        claimed = strip_hash_prefix(lu.get("merkle_root"))
        if not steps or not claimed:
            return GAP, (f"'{h}' missing learning_update.gradient_steps/"
                         f"merkle_root")
        ids = set(problem_ids(r))
        leaves = []
        for st in steps:
            if not isinstance(st, dict) or "step" not in st or "problem_id" not in st:
                return FAIL, (f"'{h}' gradient_steps carries a row without "
                              f"step/problem_id -> steps cannot be bound to "
                              f"novel problems")
            pid = st["problem_id"]
            if pid not in ids:
                return FAIL, (f"'{h}' gradient step {st['step']} cites "
                              f"problem_id '{pid}' which is not in this "
                              f"horizon's novel id set -> gradient steps are "
                              f"not Merkle-bound to the novel problems")
            leaves.append(hashlib.sha256(f"{st['step']}:{pid}".encode()).hexdigest())
        recomputed = merkle_root(leaves)
        if recomputed != claimed:
            return FAIL, (f"'{h}' merkle_root {claimed[:12]}.. does not match the "
                          f"root recomputed from its own {len(leaves)} gradient-step "
                          f"leaves ({str(recomputed)[:12]}..)")
        checked.append(f"{h}({len(leaves)} steps)")
    if len(checked) < len(HORIZONS):
        return GAP, f"only {checked} present; Merkle binding incomplete"
    return PASS, f"recomputed roots match claimed roots: {', '.join(checked)}"


def chk5_heldout_delta(receipts):
    """Recompute each horizon's held-out score from its rows; require strictly
    increasing beyond the pre-registered noise floor."""
    missing = [h for h in HORIZONS if receipts.get(h) is None]
    if missing:
        return GAP, f"horizon receipt(s) absent: {missing}"
    scores = {}
    for h in HORIZONS:
        items = heldout_items(receipts[h])
        s = recompute_score(items)
        if s is None:
            return GAP, f"'{h}' carries no heldout.items to recompute a score from"
        claimed = (receipts[h].get("heldout") or {}).get("claimed_score")
        if isinstance(claimed, (int, float)) and abs(claimed - s) > 1e-9:
            return FAIL, (f"'{h}' claimed_score {claimed} != score {s:.4f} "
                          f"recomputed from its own {len(items)} held-out rows")
        scores[h] = s
    gaps = {
        "medium-short": scores["medium"] - scores["short"],
        "long-medium": scores["long"] - scores["medium"],
    }
    small = [k for k, v in gaps.items() if v <= NOISE_FLOOR]
    if small:
        return FAIL, (f"held-out delta {small} at or below the pre-registered "
                      f"noise floor {NOISE_FLOOR} "
                      f"(short={scores['short']:.4f} medium={scores['medium']:.4f} "
                      f"long={scores['long']:.4f}) -> the longer horizon does not "
                      f"reach a capability the shorter one misses")
    return PASS, (f"recomputed held-out short={scores['short']:.4f} < "
                  f"medium={scores['medium']:.4f} < long={scores['long']:.4f}, "
                  f"each gap > {NOISE_FLOOR}")


def chk6_heldout_contamination(receipts):
    """Held-out item ids must not intersect any horizon's training ids."""
    if not present_horizons(receipts):
        return GAP, "no horizon receipt present"
    trained = set()
    held = set()
    for h in HORIZONS:
        r = receipts.get(h)
        if r is None:
            continue
        trained |= set(problem_ids(r))
        items = heldout_items(r)
        if not items:
            return GAP, f"'{h}' carries no heldout.items"
        for it in items:
            if not isinstance(it, dict) or "item_id" not in it:
                return FAIL, f"'{h}' held-out row without an item_id"
            held.add(it["item_id"])
    if not trained or not held:
        return GAP, "training or held-out id set empty; contamination not computable"
    overlap = trained & held
    if overlap:
        return FAIL, (f"{len(overlap)} held-out item(s) also appear as trained "
                      f"novel problems (e.g. {sorted(overlap)[:3]}) -> the "
                      f"capability delta is measured on trained problems")
    return PASS, (f"{len(held)} held-out ids disjoint from {len(trained)} "
                  f"trained novel-problem ids")


def chk7_live_reexecution(receipts):
    """Every held-out row carries execution evidence and the pass flags agree
    with the recomputed exit-code outcome."""
    if not present_horizons(receipts):
        return GAP, "no horizon receipt present"
    total = 0
    for h in HORIZONS:
        r = receipts.get(h)
        if r is None:
            continue
        items = heldout_items(r)
        if not items:
            return GAP, f"'{h}' carries no heldout.items"
        for it in items:
            ex = (it or {}).get("execution")
            if not isinstance(ex, dict):
                return FAIL, (f"'{h}' held-out row '{it.get('item_id')}' carries a "
                              f"passed flag with NO execution block -> asserted "
                              f"outcome, nothing was re-executed "
                              f"(fabricated_outcomes)")
            for field in ("executor", "exit_code", "stdout_sha256"):
                if ex.get(field) in (None, ""):
                    return FAIL, (f"'{h}' held-out row '{it.get('item_id')}' "
                                  f"execution block missing '{field}' -> the "
                                  f"re-execution is not evidenced "
                                  f"(fabricated_outcomes)")
            if not isinstance(ex.get("exit_code"), int):
                return FAIL, (f"'{h}' held-out row '{it.get('item_id')}' exit_code "
                              f"is not an integer -> no live re-execution")
            dur = ex.get("duration_s")
            if dur is not None and not (isinstance(dur, (int, float)) and dur > 0):
                return FAIL, (f"'{h}' held-out row '{it.get('item_id')}' "
                              f"duration_s={dur!r} -> nothing ran")
            derived = (ex["exit_code"] == 0)
            if bool(it.get("passed")) != derived:
                return FAIL, (f"'{h}' held-out row '{it.get('item_id')}' passed="
                              f"{it.get('passed')!r} disagrees with its own "
                              f"exit_code {ex['exit_code']} -> the pass flag is "
                              f"not what the execution produced "
                              f"(fabricated_outcomes)")
            total += 1
    if total == 0:
        return GAP, "no held-out rows to re-derive from"
    return PASS, (f"{total} held-out rows carry execution evidence agreeing with "
                  f"their pass flags")


def chk8_deletion_baseline(receipts):
    """Deletion is measured against the SHORT-HORIZON checkpoint and drags long
    capability back toward it."""
    d = receipts.get("deletion")
    if d is None:
        return GAP, "deletion.json absent"
    short = receipts.get("short")
    long_r = receipts.get("long")
    if short is None or long_r is None:
        return GAP, "horizon-short/horizon-long absent; deletion baseline not resolvable"

    short_post = strip_hash_prefix(((short.get("learning_update") or {})
                                    .get("post_param_hash")))
    baseline = strip_hash_prefix(d.get("baseline_checkpoint_hash"))
    if not baseline or not short_post:
        return GAP, "baseline_checkpoint_hash or horizon-short post_param_hash missing"
    if baseline != short_post:
        return FAIL, (f"deletion baseline_checkpoint_hash {baseline[:12]}.. is not "
                      f"the short-horizon checkpoint {short_post[:12]}.. -> "
                      f"deletion_uses_wrong_baseline")

    arms = d.get("arms") or {}
    missing = [a for a in DELETION_ARMS if a not in arms]
    if missing:
        return GAP, f"deletion arms absent: {missing}"
    hashes = [strip_hash_prefix((arms[a] or {}).get("checkpoint_hash"))
              for a in DELETION_ARMS]
    if any(not h for h in hashes):
        return GAP, "one or more deletion arms carry no checkpoint_hash"
    if len(set(hashes)) != len(hashes):
        return FAIL, ("deletion arms share a checkpoint_hash -> the arms are not "
                      "distinct checkpoints")

    scores = {}
    for a in DELETION_ARMS:
        s = recompute_score((arms[a] or {}).get("items") or [])
        if s is None:
            return GAP, f"deletion arm '{a}' carries no items to recompute a score from"
        scores[a] = s
    lo, dele, sh = scores["long"], scores["long_minus_consolidation"], scores["short"]
    if not (lo > dele):
        return FAIL, (f"deleting the long-horizon consolidation did not degrade "
                      f"capability (long={lo:.4f}, deleted={dele:.4f}) -> the "
                      f"consolidation is not load-bearing")
    if abs(dele - sh) >= abs(dele - lo):
        return FAIL, (f"deleted arm {dele:.4f} is not closer to the short-horizon "
                      f"level {sh:.4f} than to the long-horizon level {lo:.4f} -> "
                      f"the degradation does not return toward the short horizon")
    return PASS, (f"baseline is the short-horizon checkpoint; recomputed "
                  f"long={lo:.4f} > deleted={dele:.4f}, and deleted sits closer "
                  f"to short={sh:.4f} than to long")


CORE_CHECKS = [
    ("CHK-1", "horizon ordering by novel-problem count", chk1_horizon_ordering),
    ("CHK-2", "novelty integrity", chk2_novelty_integrity),
    ("CHK-3", "real parameter change", chk3_real_parameter_change),
    ("CHK-4", "gradient steps Merkle-bound to novel problem ids", chk4_merkle_binding),
    ("CHK-5", "held-out capability delta strictly increasing", chk5_heldout_delta),
    ("CHK-6", "held-out contamination", chk6_heldout_contamination),
    ("CHK-7", "live re-execution of sampled solutions", chk7_live_reexecution),
    ("CHK-8", "deletion against the short-horizon checkpoint", chk8_deletion_baseline),
]


def run_core_checks(receipts):
    return [(cid, name) + tuple(fn(receipts)) for (cid, name, fn) in CORE_CHECKS]


def scan_invalid_tokens(receipts):
    """Live invalid-token sweep. Values of explanatory negation keys are dropped
    first -- a receipt stating why it is NOT unearned_duration is the opposite of
    a violation."""
    def scrub(node):
        if isinstance(node, dict):
            return {
                k: ("" if (k.lower().startswith("why_not_")
                           or k.lower().startswith("does_not_count"))
                    else scrub(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [scrub(x) for x in node]
        return node

    blob = json.dumps(scrub({k: v for k, v in receipts.items()
                             if v is not None})).lower()
    return [t for t in INVALID_TOKENS if t in blob]


def chk9_duration_invariance(receipts, core_results):
    """Re-derive CHK-1..CHK-8 with every duration-shaped field stripped and
    require the identical verdict, plus a live invalid-token sweep."""
    tokens = scan_invalid_tokens(receipts)
    if tokens:
        return FAIL, (f"invalid-token(s) live in the receipt set: {tokens} -> "
                      f"the receipts stamp themselves with a does-NOT-count verdict")
    if not present_horizons(receipts) and receipts.get("deletion") is None:
        return GAP, "no receipt present; duration-invariance not derivable"
    stripped = {k: (strip_durations(v) if v is not None else None)
                for k, v in receipts.items()}
    after = run_core_checks(stripped)
    drifted = [
        f"{cid}({before[2]}->{status})"
        for (cid, _n, status, _d), before in zip(after, core_results)
        if status != before[2]
    ]
    if drifted:
        return FAIL, (f"stripping duration fields changed {drifted} -> wall-clock "
                      f"duration was load-bearing in the verdict "
                      f"(unearned_duration)")
    return PASS, ("verdict identical with every duration field stripped; no "
                  "invalid-token present")


# --- main --------------------------------------------------------------------

def main():
    if ROOT is None:
        emit("UNEVALUABLE",
             "C11: state root not found under any known layout -- input-missing")

    spec_path = os.path.join(REPO_ROOT, SPEC_REL)
    if not os.path.isfile(spec_path):
        emit("RED",
             f"C11: canonical spec {SPEC_REL} ABSENT from the repository -> the "
             f"contract conditions-v1.md names is not version-controlled; the "
             f"checker has no authority to evaluate against (issue #107)")

    rdir = os.path.join(ROOT, RECEIPT_DIR_REL)
    receipts = {}
    for h in HORIZONS:
        p = os.path.join(rdir, HORIZON_FILES[h])
        try:
            receipts[h] = load_json(p) if os.path.isfile(p) else None
        except Exception as e:
            emit("RED", f"C11: {HORIZON_FILES[h]} present but unparseable: {e}")
    p = os.path.join(rdir, DELETION_FILE)
    try:
        receipts["deletion"] = load_json(p) if os.path.isfile(p) else None
    except Exception as e:
        emit("RED", f"C11: {DELETION_FILE} present but unparseable: {e}")

    absent = ([HORIZON_FILES[h] for h in HORIZONS if receipts[h] is None]
              + ([DELETION_FILE] if receipts["deletion"] is None else []))

    if len(absent) == len(HORIZONS) + 1:
        emit("UNEVALUABLE",
             f"C11: experience-horizon receipt set entirely ABSENT under "
             f"{RECEIPT_DIR_REL} ({absent}) -> no capability-delta claim has been "
             f"made yet; all 9 checks of {SPEC_REL} pending-evidence. The "
             f"short/medium/long real-learning run needs the owned 3B substrate "
             f"(EMBER-05). Wall-clock duration is NOT a pass path.")

    results = run_core_checks(receipts)
    results.append(("CHK-9", "duration invariance / invalid-token sweep")
                   + tuple(chk9_duration_invariance(receipts, results)))

    failed = [(cid, name, detail) for (cid, name, st, detail) in results if st == FAIL]
    gaps = [(cid, name, detail) for (cid, name, st, detail) in results if st == GAP]
    passed = [cid for (cid, _n, st, _d) in results if st == PASS]

    if failed:
        cid, name, detail = failed[0]
        others = [c for (c, _n, _d) in failed[1:]]
        emit("RED",
             f"C11: {cid} ({name}) FAILS -> {detail}"
             + (f"; also failing: {others}" if others else "")
             + f" [{len(passed)}/9 checks pass]")

    if gaps:
        listed = "; ".join(f"{cid} {name}: {detail}" for (cid, name, detail) in gaps[:4])
        more = f" (+{len(gaps) - 4} more)" if len(gaps) > 4 else ""
        emit("UNEVALUABLE",
             f"C11: contract evaluated, {len(passed)}/9 checks pass, "
             f"{len(gaps)} pending-evidence -> {listed}{more}. "
             f"Partial receipts present under {RECEIPT_DIR_REL} ({absent} absent); "
             f"no check that could be evaluated failed.")

    emit("GREEN",
         "C11: experience-horizon capability delta PROVEN -- all 9 recomputed "
         f"checks of {SPEC_REL} pass: novel-problem counts strictly increasing, "
         "no repeats/pretrain overlap, real pre!=post parameter change with "
         "distinct checkpoints, gradient steps Merkle-bound to the novel problem "
         "ids, recomputed held-out delta short<medium<long beyond the "
         f"{NOISE_FLOOR} noise floor, held-out uncontaminated, every row live "
         "re-executed, deletion measured against the short-horizon checkpoint "
         "degrading long capability back toward it, and the verdict unchanged "
         "with all duration fields stripped.")


if __name__ == "__main__":
    main()
