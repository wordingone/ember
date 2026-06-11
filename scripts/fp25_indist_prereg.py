"""fp25_indist_prereg.py — round-2 OOD-null DECOMPOSITION, FROZEN BEFORE the
in-distribution eval receipt exists (#154, successor to the round-2 G1 null
#153).

Round-2 G1 (receipt g1-r2w-verdict-20260611T050209Z) returned NO advancing
arm on MBPP validation-43: sft/mtp/grpo FLAT vs base AND vs the matched-
compute control, point estimates near-zero. PROVENANCE: the receipt proves
no separation at THIS gate and matched-control parity-or-down at the current
G1 MDE scale (n=43, k=8); it does NOT exclude small effects below that MDE,
and it is not an absence-of-all-effect claim. The arms trained on a NARROW
slice — 28 frontier MBPP-train tasks, 98 verified examples (theta in (0,0.5]) —
while G1 evaluated the FULL MBPP-validation-43. A null there has two
explanations the G1 receipt cannot separate:

  (a) learned-but-no-transfer: the arms fit the frontier-train distribution,
      it just doesn't carry to full-validation at this data scale (expected;
      the LOOP works — informative).
  (b) didn't-learn: 98 verified examples produced no learning at all
      (recipe / data-scale / scale problem — a deeper red flag).

This is decisive for the owned-core (NC2) plan: the owned 0.37B core is
evaluated IN-distribution (its verify-floor world IS its eval distribution by
construction, fp-22/fp-23), on a corpus orders larger than 98 examples. If the
verify-floor recipe demonstrably LEARNS in-distribution, the owned-core loop
has a green light on the mechanism and the validation null is a generalization
ceiling. If it is flat even in-distribution, the recipe needs diagnosis BEFORE
paying the v0 pretrain cost (break-the-wall: diagnose, do not abandon).

DISCRIMINATING EXPERIMENT — two surfaces, same 5 certified arms
(base/sft/mtp/grpo/control already on disk), same paired methods as r1/r2
(g1_paired.compare -> Newcombe feed + 10k paired bootstrap seed-16 per-sample
rate, the BINDING gains metric):

  Surface A — TRAIN-TASK RECALL (the memorization floor, fully constructible
    now). Eval the arms on the EXACT 28 frontier MBPP-train tasks they trained
    on (the unique `task` ids in ledger/views/wcode-r2-sft.jsonl), k=8 seed-16,
    verified by each task's own MBPP asserts (t1_probe sandbox). This is the
    WEAKEST learning signal (memorization), so its PRESENCE is necessary-not-
    sufficient — but its ABSENCE is decisive: if 98 verified episodes cannot
    lift even the 28 tasks they were drawn from, the recipe did not learn.
    => the primary NULL-DETECTOR.

  Surface B — IN-DISTRIBUTION HELD-OUT (the generalization test; named
    secondary, fires only if A shows learning). Frontier-difficulty MBPP tasks
    (theta in (0,0.5] under base) drawn from a split DISJOINT from the 28
    train ids (sha1-bucket on task id; held-out bucket asserted disjoint from
    the train-id set, fail-closed). Same eval. Distinguishes MEMORIZE (A up,
    B flat) from GENERALIZE (A up, B up).

FROZEN DECISION TABLE (recipe-level, per the prereg all-FLAT branch). Every
owned-core implication below is RECEIPT-DERIVED from the fp-25 eval receipt,
NOT Fable-derived, and is a conditional experiment consequence, never an
architecture certification:

  | Surface A (recall) | Surface B (held-out) | verdict             | owned-core consequence |
  |--------------------|----------------------|---------------------|------------------------|
  | no arm UP vs base  | (not run)            | RECIPE-NULL         | v0 pretrain GATED until diagnosed |
  | >=1 arm UP vs base | >=1 arm UP vs base   | LEARNS-AND-GENERALIZES | conditionally green-lights the verify-floor recipe/eval distribution for the owned-core loop |
  | >=1 arm UP vs base | no arm UP vs base    | OOD-TRANSFER-CEILING | recipe learns in-dist; validation null EXPLAINED as a data-scale/transfer ceiling |

  - RECIPE-NULL: the recipe did not fit its own training distribution; round-3
    is a recipe/data-scale DIAGNOSIS, not more of the same. Owned-core v0
    pretrain is GATED until diagnosed (break-the-wall — the wall is "98
    verified examples moved nothing"; fork the recipe / raise the data scale /
    change the objective, do not abandon).
  - LEARNS-AND-GENERALIZES: IF fp-25 shows in-distribution held-out lift on a
    split disjoint from EVERY r2 training view, it conditionally green-lights
    the verify-floor recipe + eval distribution for the owned-core loop. It
    does NOT certify the foundation architecture and does NOT establish OOD
    transfer — both remain open, separately gated.
  - OOD-TRANSFER-CEILING: the recipe learns in-distribution but does not yet
    generalize beyond the training slice at 98 examples; the MBPP-validation
    null is then a data-scale/transfer ceiling, benign for the owned core
    (whose in-dist corpus is orders larger) but flagged as data-scale, not a
    mechanism win.

Surface A is the memorization floor BY DESIGN (it evaluates the training tasks
themselves) — so its PRESENCE is necessary-not-sufficient and its ABSENCE is
the decisive null. Surface B is the only held-out claim, and its split MUST be
proven disjoint from EVERY r2 training view (sft view ids UNION grpo pool ids),
hash-stamped, fail-closed (heldout_disjoint below). Surface A also reports each
trained arm vs CONTROL (did VERIFICATION matter for fitting the training tasks)
— informational, not the recipe gate.

Same freeze discipline as fp-15/fp-23/fp-20c: the split, the methods, the
schema, and decide() are pinned here BEFORE the in-dist eval receipt exists, so
they can never be fitted to the number they judge. `--selftest` is pure-logic.
main() executes decide() on a real in-dist eval samples file (w4_eval format,
the 28 recall tasks); without one it prints the STAGED sentinel.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from g1_paired import compare  # noqa: E402  (r1/r2 pre-registered methods)
from g1_r2w_verdict import load_tab  # noqa: E402  (same samples reconstruction)

# ---- frozen pins ----------------------------------------------------
ARM_SET = ("base", "sft", "mtp", "grpo", "control")
TRAINED = ("sft", "mtp", "grpo")
BASE = "base"
CONTROL = "control"
EVAL_K = 8                     # r2 G1 k
EVAL_SEED = 16                 # r1/r2 G1 seed (binding bootstrap seed)
RECALL_VIEW = "ledger/views/wcode-r2-sft.jsonl"  # train-task source (Surface A)
RECALL_TASK_FIELD = "task"     # unique values = the 28 trained tasks
EXPECTED_RECALL_TASKS = 28     # asserted at eval time (sft view = 28 tasks)
# Every r2 training view whose task ids Surface B's held-out split must avoid.
# sft view = sft/mtp arms' tasks; grpo pool = grpo arm's tasks. Their UNION is
# the full set of tasks any r2 arm trained on (control mirrors the sft tasks).
TRAINING_VIEWS = ("ledger/views/wcode-r2-sft.jsonl",)
GRPO_POOL = "ledger/views/grpo-r2-tasks.json"  # grpo arm task ids
PROBE_BUCKETS = range(0, 10)   # Surface B held-out 10% (sha1 bucket on task id)
TRAIN_BUCKETS = range(10, 100)
FRONTIER_THETA = (0.0, 0.5)    # Surface B difficulty bounds under base;
# the window is (lo, hi] open-low/closed-high — encoded in frontier_ok().

RECEIPT_REQUIRED_FIELDS = (
    "surface",                 # "A-recall" | "B-heldout"
    "arms", "k", "seed",
    "recall_task_ids_sha256",  # sha of the sorted 28-id set (Surface A)
    "samples_file",
    "adapter_provenance",      # arm -> adapter path (base = none)
)


def recall_task_ids(view_path):
    """The 28 trained task ids = unique `task` values in the sft view.
    Deterministic, sorted; the eval restricts to exactly these."""
    ids = set()
    with open(view_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            tid = r.get(RECALL_TASK_FIELD)
            if tid is not None:
                ids.add(tid)
    return sorted(ids)


def ids_sha256(ids):
    """Stable sha of the sorted id set — stamped in the receipt + asserted."""
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def bucket(task_id):
    """Surface B held-out split — sha1, deterministic across platforms."""
    h = hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()
    return int(h, 16) % 100


def grpo_pool_task_ids(pool_path):
    """grpo arm task ids — tolerant of list / {"tasks":[...]} / dict-keyed
    json, extracting the same mbpp:NNN ids the grpo arm trained on."""
    obj = json.load(open(pool_path, encoding="utf-8"))
    if isinstance(obj, dict):
        if "tasks" in obj and isinstance(obj["tasks"], list):
            obj = obj["tasks"]
        else:
            obj = list(obj.keys())
    ids = set()
    for it in obj:
        if isinstance(it, str):
            ids.add(it)
        elif isinstance(it, dict):
            for k in (RECALL_TASK_FIELD, "task_id", "tid", "id"):
                if k in it:
                    ids.add(it[k])
                    break
    return sorted(ids)


def all_training_task_ids(sft_view, grpo_pool):
    """UNION of every r2 training view's task ids (sft/mtp tasks via the sft
    view + grpo pool tasks). Surface B's held-out split must be disjoint from
    THIS set, not just the sft view — Kai provenance obligation (14545)."""
    return sorted(set(recall_task_ids(sft_view)) | set(grpo_pool_task_ids(grpo_pool)))


def heldout_disjoint(heldout_ids, train_ids):
    """Surface B precondition: held-out set shares NO task with the UNION of
    every r2 training view (pass all_training_task_ids() as train_ids).
    Returns the offending overlap (empty = disjoint, fail-closed)."""
    return sorted(set(heldout_ids) & set(train_ids))


def frontier_ok(theta):
    """Surface B difficulty gate: theta in (0.0, 0.5]."""
    lo, hi = 0.0, 0.5
    return lo < theta <= hi


def _arm_flag(cmp):
    """Binding gains flag = the per-sample-rate bootstrap flag (the primary
    metric; the Newcombe feed is reported alongside in the block)."""
    return cmp["sample"]["flag"]


def decide_recall(tab):
    """Surface A recipe-level verdict. Each trained arm vs base (binding
    per-sample rate) + vs control (informational). RECIPE-NULL iff NO trained
    arm is UP vs base on its own training tasks."""
    for need in ARM_SET:
        if need not in tab:
            return {"error": f"missing arm {need!r}; have {sorted(tab)}"}
    blocks, arm_learns = {}, {}
    for arm in TRAINED:
        vb = compare(tab, arm, BASE)
        vc = compare(tab, arm, CONTROL)
        blocks[f"{arm}_minus_base"] = vb
        blocks[f"{arm}_minus_control"] = vc
        arm_learns[arm] = (_arm_flag(vb) == "UP")
    any_learns = any(arm_learns.values())
    verdict = "RECIPE-LEARNS" if any_learns else "RECIPE-NULL"
    return {
        "surface": "A-recall",
        "verdict": verdict,
        "provenance": "receipt-derived (fp-25 eval), not Fable-derived",
        "arm_learns_vs_base": arm_learns,
        "owned_core_gate": (
            "CONDITIONAL-PENDING-B — the mechanism fires in-distribution at "
            "Surface A; a green-light for the owned-core loop is CONDITIONAL "
            "on Surface B held-out lift (split disjoint from EVERY r2 training "
            "view) and certifies NEITHER the foundation architecture NOR OOD "
            "transfer — both remain separately gated"
            if any_learns else
            "BLOCKED — recipe did not fit its own training tasks; diagnose "
            "recipe/data-scale before v0 pretrain (break-the-wall, not "
            "abandon)"),
        "next": ("Surface B (held-out frontier, disjoint from all training "
                 "views) resolves generalize-vs-OOD-transfer-ceiling"
                 if any_learns else
                 "round-3 = recipe/data-scale diagnosis; fp-25 successor names "
                 "the diagnosis axis"),
        "blocks": blocks,
    }


def decide_generalize(a_verdict, b_compare_by_arm):
    """Surface B composition — only meaningful when Surface A = RECIPE-LEARNS.
    b_compare_by_arm: {arm: compare(arm, base)} on the held-out frontier set."""
    if a_verdict != "RECIPE-LEARNS":
        return {"verdict": "N/A", "note": "Surface B fires only after A learns"}
    any_gen = any(_arm_flag(c) == "UP" for c in b_compare_by_arm.values())
    return {
        "surface": "B-heldout",
        "verdict": "LEARNS-AND-GENERALIZES" if any_gen else "OOD-TRANSFER-CEILING",
        "provenance": "receipt-derived (fp-25 eval), not Fable-derived",
        "arm_generalizes_vs_base": {a: (_arm_flag(c) == "UP")
                                    for a, c in b_compare_by_arm.items()},
        "validation_null_reading": (
            "data-scale effect, not a mechanism failure" if any_gen else
            "EXPLAINED as a data-scale/transfer ceiling; benign for the owned "
            "core (its in-dist corpus is orders larger) but flagged as "
            "data-scale at 98 examples, not a mechanism win"),
    }


def validate_receipt(rec):
    """Schema floor: every required field present (else the eval is not a
    fp-25 probe). Returns sorted missing-field list (empty = valid)."""
    return sorted(f for f in RECEIPT_REQUIRED_FIELDS if f not in rec)


def _norm_tid(x):
    """w4_eval writes integer tids; the sft view stores 'mbpp:NNN'. Normalize
    either to the integer id so the Surface-A task-set assert is format-robust
    regardless of which side carries the prefix."""
    return int(str(x).split(":")[-1])


def adapter_provenance(samples_path):
    """arm -> sampler string (model[+adapter]) from the eval samples rows —
    records what was ACTUALLY evaluated per arm, in file (= arm) order."""
    prov = {}
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            arm = r.get("arm")
            if arm and arm not in prov:
                prov[arm] = r.get("sampler")
    return prov


def build_fp25_receipt(samples_path, recall_view, surface, ts):
    """BINDING Surface-A receipt builder, fail-closed (Kai 14548/14551). Only
    Surface A (train-task recall) has a binding executor; Surface B held-out
    needs its own disjointness-proven executor and is refused here. Asserts,
    in order: surface == A; the recall view yields exactly EXPECTED_RECALL_TASKS
    ids; the EVALUATED task set equals those ids (a wrong samples file cannot
    mint a plausible receipt); every (arm,task) carries exactly EVAL_K samples
    (k bound from the data); the verdict computes; the receipt carries every
    RECEIPT_REQUIRED_FIELD (validate_receipt). Returns the receipt dict."""
    if surface != "A-recall":
        raise SystemExit("fp25: only Surface A (train-task recall) has a "
                         "binding executor; Surface B held-out needs its own "
                         "disjointness-proven executor (staged) — refused "
                         "fail-closed")
    recall_ids = recall_task_ids(recall_view)
    if len(recall_ids) != EXPECTED_RECALL_TASKS:
        raise SystemExit(f"fp25: recall view has {len(recall_ids)} tasks, "
                         f"expected {EXPECTED_RECALL_TASKS} ({recall_view})")
    tab, _order = load_tab(samples_path)
    want = {_norm_tid(t) for t in recall_ids}
    got = {_norm_tid(t) for arm in tab for t in tab[arm]}
    if got != want:
        raise SystemExit(
            f"fp25: evaluated task set != the {len(want)} recall tasks "
            f"(missing {sorted(want - got)[:5]}, extra {sorted(got - want)[:5]})")
    for arm in tab:
        for t, vec in tab[arm].items():
            if len(vec) != EVAL_K:
                raise SystemExit(f"fp25: k mismatch arm {arm} task {t}: "
                                 f"{len(vec)} samples != EVAL_K {EVAL_K}")
    verdict = decide_recall(tab)
    if "error" in verdict:
        raise SystemExit(f"fp25: {verdict['error']}")
    receipt = {
        "ticket": "FP25-INDIST", "ts": ts,
        "surface": "A-recall",
        "arms": sorted(tab),
        "k": EVAL_K, "seed": EVAL_SEED,
        "recall_task_ids_sha256": ids_sha256(recall_ids),
        "recall_task_count": len(recall_ids),
        "samples_file": os.path.basename(samples_path),
        "adapter_provenance": adapter_provenance(samples_path),
        "basis": ("round-2 OOD-null decomposition: train-task recall (the "
                  "EXACT 28 frontier MBPP-train tasks) as the memorization "
                  "floor / null-detector; g1_paired per-sample-rate binding"),
        "result": verdict,
    }
    missing = validate_receipt(receipt)
    if missing:
        raise SystemExit(f"fp25: receipt missing required fields {missing}")
    return receipt


def _selftest():
    # recall-id extraction + sha determinism on a synthetic view
    import tempfile
    rows = [{"task": f"mbpp:{i}", "verified": True} for i in (1, 1, 2, 3, 3, 3)]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as tf:
        for r in rows:
            tf.write(json.dumps(r) + "\n")
        vp = tf.name
    ids = recall_task_ids(vp)
    assert ids == ["mbpp:1", "mbpp:2", "mbpp:3"], ids
    assert ids_sha256(ids) == ids_sha256(list(reversed(ids)))  # order-free
    os.unlink(vp)

    # bucket determinism + Surface B disjointness guard (vs the training UNION)
    assert bucket("mbpp:608") == bucket("mbpp:608")
    assert heldout_disjoint(["a", "b"], ["b", "c"]) == ["b"]
    assert heldout_disjoint(["a"], ["b", "c"]) == []

    # grpo pool loader (list / {"tasks":[...]} / dict-keyed) + training UNION
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as gf:
        json.dump(["mbpp:700", "mbpp:701"], gf)
        gp_list = gf.name
    assert grpo_pool_task_ids(gp_list) == ["mbpp:700", "mbpp:701"]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as gf:
        json.dump({"tasks": [{"task": "mbpp:701"}, {"task": "mbpp:702"}]}, gf)
        gp_obj = gf.name
    assert grpo_pool_task_ids(gp_obj) == ["mbpp:701", "mbpp:702"]
    # union folds sft ids with grpo ids, dedup across the overlap (mbpp:701)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as sf:
        for t in ("mbpp:700", "mbpp:700", "mbpp:610"):
            sf.write(json.dumps({"task": t, "verified": True}) + "\n")
        sv = sf.name
    union = all_training_task_ids(sv, gp_obj)
    assert union == ["mbpp:610", "mbpp:700", "mbpp:701", "mbpp:702"], union
    # a held-out candidate colliding with the grpo half is caught
    assert heldout_disjoint(["mbpp:702", "mbpp:999"], union) == ["mbpp:702"]
    for p in (gp_list, gp_obj, sv):
        os.unlink(p)

    # frontier window (open-low, closed-high)
    assert frontier_ok(0.5) and frontier_ok(0.01)
    assert not frontier_ok(0.0) and not frontier_ok(0.51)

    # decide_recall: synthetic tab. base weak, sft strong on its train tasks
    # (-> LEARNS); grpo == base (no recall). 4 tasks, k=4.
    def vec(*per_task):
        return {f"t{i}": list(v) for i, v in enumerate(per_task)}
    tab = {
        "base":    vec([0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
        "control": vec([1, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
        "sft":     vec([1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 0], [1, 1, 1, 1]),
        "mtp":     vec([1, 1, 1, 0], [1, 1, 1, 1], [1, 1, 0, 0], [1, 1, 1, 1]),
        "grpo":    vec([0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
    }
    a = decide_recall(tab)
    assert a["verdict"] == "RECIPE-LEARNS", a
    assert a["arm_learns_vs_base"]["sft"] is True
    assert a["arm_learns_vs_base"]["grpo"] is False
    assert a["owned_core_gate"].startswith("CONDITIONAL-PENDING-B")
    assert a["provenance"].startswith("receipt-derived")

    # all-flat tab -> RECIPE-NULL + BLOCKED gate
    flat = {k: tab["base"] for k in ARM_SET}
    a2 = decide_recall(flat)
    assert a2["verdict"] == "RECIPE-NULL", a2
    assert a2["owned_core_gate"].startswith("BLOCKED")

    # missing-arm guard
    assert "error" in decide_recall({k: tab[k] for k in ("base", "sft")})

    # Surface B composition
    b_up = {arm: compare(tab, arm, "base") for arm in TRAINED}
    g = decide_generalize("RECIPE-LEARNS", b_up)
    assert g["verdict"] in ("LEARNS-AND-GENERALIZES", "OOD-TRANSFER-CEILING"), g
    assert decide_generalize("RECIPE-NULL", b_up)["verdict"] == "N/A"

    # schema floor
    miss = validate_receipt({"surface": "A-recall"})
    assert "samples_file" in miss and "recall_task_ids_sha256" in miss
    assert validate_receipt({f: 1 for f in RECEIPT_REQUIRED_FIELDS}) == []

    # BINDING executor (Surface A): synthetic 28-task recall view + samples.
    # Proves the receipt carries every required field, the task-set + k asserts
    # bind, B-heldout is refused, and a wrong samples file cannot mint one.
    rids = [f"mbpp:{1000 + i}" for i in range(EXPECTED_RECALL_TASKS)]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as vf:
        for t in rids:
            vf.write(json.dumps({"task": t, "verified": True}) + "\n")
        view_p = vf.name

    def _mk_samples(task_ids, k=EVAL_K):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as sf:
            for arm in ARM_SET:
                strong = arm in ("sft", "mtp")
                for t in task_ids:
                    for j in range(k):
                        ok = strong or (j == 0)
                        sf.write(json.dumps({"arm": arm, "tid": _norm_tid(t),
                                             "verified": bool(ok),
                                             "sampler": f"M+{arm}"}) + "\n")
            return sf.name

    sp = _mk_samples(rids)
    rec = build_fp25_receipt(sp, view_p, "A-recall", "20260611T000000Z")
    assert validate_receipt(rec) == [], rec
    assert rec["arms"] == sorted(ARM_SET)
    assert rec["k"] == EVAL_K and rec["seed"] == EVAL_SEED
    assert rec["recall_task_count"] == EXPECTED_RECALL_TASKS
    assert set(rec["adapter_provenance"]) == set(ARM_SET)

    def _refuses(samples, view, surface):
        try:
            build_fp25_receipt(samples, view, surface, "t")
        except SystemExit:
            return True
        return False
    assert _refuses(sp, view_p, "B-heldout")          # B has no binding executor
    assert _refuses(_mk_samples(rids[:-1]), view_p, "A-recall")  # wrong task set
    assert _refuses(_mk_samples(rids, k=EVAL_K - 1), view_p, "A-recall")  # k mismatch
    os.unlink(view_p)
    os.unlink(sp)
    print("FP25_INDIST_PREREG_SELFTEST_PASS")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", help="Surface-A in-dist eval samples.jsonl "
                                       "(w4_eval format, the 28 recall tasks)")
    ap.add_argument("--surface", default="A-recall",
                    choices=("A-recall", "B-heldout"))
    ap.add_argument("--recall-view", default=None,
                    help="override the recall view path (default RECALL_VIEW "
                         "under the nc-ladder root)")
    a, _ = ap.parse_known_args()
    if not a.samples:
        print("FP25_INDIST_PREREG_STAGED (no in-distribution eval receipt "
              "exists yet; split + methods + decide() frozen in this file — "
              "the binding executor runs when the 28-task recall eval lands)")
        return
    NC = os.path.dirname(HERE)
    view = a.recall_view or f"{NC}/{RECALL_VIEW}"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_fp25_receipt(a.samples, view, a.surface, ts)
    out = f"{NC}/receipts/fp25-indist-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    verdict = receipt["result"]
    print(json.dumps({"verdict": verdict["verdict"],
                      "arm_learns_vs_base": verdict["arm_learns_vs_base"],
                      "owned_core_gate": verdict["owned_core_gate"]}, indent=2))
    print(f"FP25_INDIST_PREREG_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
