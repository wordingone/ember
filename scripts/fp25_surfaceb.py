"""fp25_surfaceb.py — fp-25 Surface B: held-out frontier selection + the
binding generalization verdict (#154, the CONDITIONAL-PENDING-B discharge).

FROZEN while the coverage run (daemon 06428689, tag fp25b-cov) is still in
flight — before its receipt exists, so selection can never be fitted to it.

PRE-DATA AMENDMENT (mail 14575 to the monitor; feasibility receipt in STATE
c9990c5): the original Surface-B sketch (sha1 PROBE_BUCKETS 0-9 on q3-leg
coverage) is INFEASIBLE — pooled-q3 leaves exactly 2 held-out frontier
candidates because the r2 frontier filter selected the known frontier INTO
the training union by construction. Amended construction:

  1. Theta source = ONE fresh uniform base-only coverage run over the full
     w4_eval --split train sanitized pool (k8 seed16, fp25b-cov; n_tasks
     PROVEN by the terminal coverage receipt — 120 per the w1 split
     discipline, NOT raw-MBPP 374; wording corrected per monitor audit mail
     14579) — no pooling with the partial q3 legs; base-only outcomes mean
     the eventual arm deltas carry no selection-on-outcome bias. Select
     mode gates fail-closed on the coverage receipt (ticket/split/arm/k/
     seed/tag/no-id-filter) and stamps it as the SOLE theta source.
  2. Bucket condition AMENDED OUT for the MBPP world (it passed 0
     candidates; it was designed for generator worlds where instances are
     mintable per bucket, fp-23). UNION-DISJOINTNESS is the real held-out
     guarantee and stays binding: selected ids must be disjoint from
     all_training_task_ids (sft view UNION grpo pool), asserted fail-closed.
  3. Selection rule (frozen here): theta in (THETA_LO, THETA_HI] under base
     from the fp25b-cov samples AND not in the training union AND full k
     coverage. If fewer than MIN_B_TASKS survive -> INFEASIBLE-FLAG refusal
     (escalate as a new amendment; never bind an underpowered eval
     silently).

AMENDMENT 2 (POST-DATA — declared as such; monitor mail 14580 fail-closed
the original construction): the executed fp25b-cov coverage yields exactly
7 held-out frontier tasks (120 pool - 29 union - 8 dead - 76 easy), below
the MIN_B_TASKS=15 floor. The floor refusal fired as designed. Per the
monitor's required-next #3, a new held-out SOURCE is preregistered here
BEFORE any binding B eval runs:

  CANDIDATE-POOL EXPANSION ONLY — window (0, 0.5], floor 15, k 8 all
  UNCHANGED (nothing is fitted to reach the floor):
    S1 = the 7 train-pool held-out frontier tasks (gated fp25b-cov
         receipt; monitor-reproduced ids + sha, mail 14580).
    S2 = validation-split frontier: theta in (0, 0.5] at k8 from the BASE
         rows ONLY of the committed r2w-q3 W4 receipt (validation was
         never trained on -> union-disjoint BY CONSTRUCTION).

  DECLARED BIASES + MITIGATIONS:
    a. Post-data amendment: coverage outcomes were observed first.
       Mitigation: selection RULE unchanged; only the pool expands, to
       the only other union-disjoint base-theta source that exists.
    b. Aggregate arm outcomes on validation were already observed (the
       G1 flat verdict). Mitigation: selection consults base rows only;
       the binding quantity is the per-task arm-vs-base contrast on the
       selected subset at a FRESH seed.
    c. Selection-on-base regression-to-mean (tasks picked for a low base
       draw regress up on re-draw). Mitigation: the binding 5-arm eval
       runs at NEW seed B_EVAL_SEED (!= 16) for ALL arms INCLUDING base —
       both sides freshly drawn, so the contrast is unbiased; verdict
       mode REFUSES samples whose sibling W4 receipts carry any other
       seed (draw-reuse is mechanically excluded).

  EXECUTION SHAPE: two w4_eval legs (split=train on the S1 ids; split=
  validation on the S2 ids), each all-5-arms k8 seed B_EVAL_SEED; verdict
  mode merges both samples files and gates both sibling receipts.

VERDICT (frozen): decide_generalize from fp25_indist_prereg — Surface A's
certified RECIPE-LEARNS (receipt pinned + tamper-guarded below) composes
with per-arm compare(arm, base) on the B set:
  >=1 trained arm UP vs base on the per-sample rate -> LEARNS-AND-GENERALIZES
  none UP                                            -> OOD-TRANSFER-CEILING
Receipt-scoped: LEARNS-AND-GENERALIZES conditionally green-lights the
verify-floor recipe/eval distribution for the owned-core loop; it certifies
NEITHER the foundation architecture NOR far-OOD transfer (provenance:
receipt-derived, never Fable-derived).

`--selftest` pure-logic. Modes:
  select : --coverage-samples receipts/w4-eval-fp25b-cov-<ts>-samples.jsonl
           -> writes ledger/views/fp25b-heldout-task-ids.txt + selection
              receipt (fail-closed; no GPU)
  verdict: --samples receipts/w4-eval-fp25b-<ts>-samples.jsonl
           -> the BINDING Surface-B receipt (after the 5-arm eval runs on
              the selected ids)
Without inputs main() prints the STAGED sentinel.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from g1_paired import compare  # noqa: E402 — r1/r2 pre-registered methods
from g1_r2w_verdict import load_tab  # noqa: E402
from fp25_indist_prereg import (  # noqa: E402 — frozen single sources
    ARM_SET, BASE, EVAL_K, EVAL_SEED, GRPO_POOL, RECALL_VIEW, TRAINED,
    all_training_task_ids, decide_generalize, ids_sha256,
)

# ---- frozen pins ----------------------------------------------------
THETA_LO = 0.0          # exclusive — theta==0 (dead under base) excluded
THETA_HI = 0.5          # inclusive — the frontier window the arms trained on
MIN_B_TASKS = 15        # below this the eval is underpowered -> refuse
COVERAGE_TAG = "fp25b-cov"
B_EVAL_SEED = 23        # amendment 2: binding eval seed, MUST differ from 16
                        # (kills selection-draw reuse; gated fail-closed)
# amendment-2 S2 source pin: the committed r2w-q3 validation receipt whose
# BASE rows are the validation theta source (arm rows ignored by selection)
VAL_SRC_RECEIPT = "w4-eval-r2w-q3-20260611T044559Z.json"
VAL_SRC_TAG = "r2w-q3"
VAL_SRC_SEED = 16
B_IDS_FILE = "ledger/views/fp25b-heldout-task-ids.txt"
B_IDS_TRAIN_FILE = "ledger/views/fp25b-heldout-train-ids.txt"
B_IDS_VAL_FILE = "ledger/views/fp25b-heldout-val-ids.txt"
# Surface A pin (tamper-guarded input to decide_generalize)
A_RECEIPT = "fp25-indist-20260611T060416Z.json"
A_PIN = {"verdict": "RECIPE-LEARNS",
         "arm_learns_vs_base": {"sft": True, "mtp": True, "grpo": True}}
SHA_CONVENTION = ("id-set shas = sha256 over the sorted task-id strings "
                  "joined by \\n, utf-8 (ids_sha256); file shas = sha256 "
                  "over on-disk raw bytes")

RECEIPT_REQUIRED_FIELDS = (
    "surface", "arms", "k", "seed",
    "heldout_task_ids_sha256", "sha_convention",
    "disjointness_overlap",     # must be [] — committed proof in-receipt
    "a_pin",                    # the Surface-A receipt this composes with
    "samples_file", "adapter_provenance",
)


def check_a_pin(a_receipt_path):
    """Surface A tamper guard. Returns mismatch list (empty = intact)."""
    rec = json.load(open(a_receipt_path, encoding="utf-8"))
    res = rec.get("result", {})
    out = []
    if res.get("verdict") != A_PIN["verdict"]:
        out.append({"field": "verdict", "pinned": A_PIN["verdict"],
                    "found": res.get("verdict")})
    if res.get("arm_learns_vs_base") != A_PIN["arm_learns_vs_base"]:
        out.append({"field": "arm_learns_vs_base",
                    "pinned": A_PIN["arm_learns_vs_base"],
                    "found": res.get("arm_learns_vs_base")})
    return out


def check_coverage_receipt(receipt_path):
    """Fail-closed gate on the W4 coverage receipt — the SOLE theta source
    (monitor audit 14579). Returns (receipt_dict, mismatch_list)."""
    rec = json.load(open(receipt_path, encoding="utf-8"))
    args = rec.get("args", {})
    out = []
    for field, want, got in (
            ("ticket", "W4-EVAL", rec.get("ticket")),
            ("args.split", "train", args.get("split")),
            ("args.seed", EVAL_SEED, args.get("seed")),
            ("args.tag", COVERAGE_TAG, args.get("tag")),
            ("args.arm", [f"{BASE}="], args.get("arm")),
            ("args.task_ids_file", None, args.get("task_ids_file")),
            ("k", EVAL_K, rec.get("k"))):
        if got != want:
            out.append({"field": field, "want": want, "got": got})
    return rec, out


def check_val_src_receipt(receipt_path):
    """Amendment-2 S2 gate on the pinned r2w-q3 validation receipt (the
    base-theta source for the validation frontier). Returns (rec, mism)."""
    rec = json.load(open(receipt_path, encoding="utf-8"))
    args = rec.get("args", {})
    out = []
    for field, want, got in (
            ("ticket", "W4-EVAL", rec.get("ticket")),
            ("args.split", "validation", args.get("split")),
            ("args.seed", VAL_SRC_SEED, args.get("seed")),
            ("args.tag", VAL_SRC_TAG, args.get("tag")),
            ("k", EVAL_K, rec.get("k"))):
        if got != want:
            out.append({"field": field, "want": want, "got": got})
    if f"{BASE}=" not in (args.get("arm") or []):
        out.append({"field": "args.arm", "want": f"contains {BASE}=",
                    "got": args.get("arm")})
    return rec, out


def coverage_theta(samples_path, base_only_file=True):
    """samples.jsonl -> {tid: (verified, n)} over BASE rows. With
    base_only_file=True (the fp25b-cov source) any non-base row is a
    refusal; with False (the r2w-q3 S2 source, which legitimately carries
    arm rows) non-base rows are IGNORED — selection still consumes base
    outcomes exclusively."""
    st = {}
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("arm") != BASE:
                if base_only_file:
                    raise SystemExit(f"fp25b: coverage row from arm "
                                     f"{r.get('arm')!r} — selection must be "
                                     f"base-only")
                continue
            v, n = st.get(r["tid"], (0, 0))
            st[r["tid"]] = (v + (1 if r.get("verified") else 0), n + 1)
    if not st:
        raise SystemExit(f"fp25b: no base rows in {samples_path}")
    return st


def select_heldout(theta_by_tid, union_ids):
    """The frozen selection rule. Returns (selected, report)."""
    union_norm = {int(str(t).split(":")[-1]) for t in union_ids}
    sel, dead, easy, in_union, partial = [], 0, 0, 0, 0
    for tid, (v, n) in sorted(theta_by_tid.items()):
        if n != EVAL_K:
            partial += 1
            continue
        th = v / n
        if int(str(tid).split(":")[-1]) in union_norm:
            in_union += 1
            continue
        if th <= THETA_LO:
            dead += 1
        elif th > THETA_HI:
            easy += 1
        else:
            sel.append(tid)
    report = {"coverage_tasks": len(theta_by_tid), "selected": len(sel),
              "dead_theta0": dead, "easy_theta_gt_0.5": easy,
              "in_training_union": in_union, "partial_k": partial,
              "window": f"({THETA_LO}, {THETA_HI}]", "k_required": EVAL_K,
              "min_b_tasks": MIN_B_TASKS}
    return sel, report


def check_b_eval_receipt(receipt_path):
    """Amendment-2 verdict gate on each binding-eval W4 receipt: fresh
    seed B_EVAL_SEED (draw-reuse refusal), id-filtered, all 5 arms.
    Returns (rec, mism)."""
    rec = json.load(open(receipt_path, encoding="utf-8"))
    args = rec.get("args", {})
    out = []
    for field, want, got in (
            ("ticket", "W4-EVAL", rec.get("ticket")),
            ("args.seed", B_EVAL_SEED, args.get("seed")),
            ("k", EVAL_K, rec.get("k"))):
        if got != want:
            out.append({"field": field, "want": want, "got": got})
    if args.get("split") not in ("train", "validation"):
        out.append({"field": "args.split", "want": "train|validation",
                    "got": args.get("split")})
    if not args.get("task_ids_file"):
        out.append({"field": "args.task_ids_file",
                    "want": "an id filter (the selected B ids)",
                    "got": args.get("task_ids_file")})
    have_arms = {str(s).split("=")[0] for s in (args.get("arm") or [])}
    if have_arms != set(ARM_SET):
        out.append({"field": "args.arm", "want": sorted(ARM_SET),
                    "got": sorted(have_arms)})
    return rec, out


def build_b_verdict(samples_paths, ids_file, a_receipt_path):
    """BINDING Surface-B receipt builder, fail-closed (mirrors #157's
    build_fp25_receipt discipline + the #163 sha_convention gate).
    samples_paths: 1-2 samples files (amendment 2: train leg + validation
    leg); each must have a sibling W4 receipt passing check_b_eval_receipt."""
    want_ids = []
    with open(ids_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                want_ids.append(line)
    if len(want_ids) < MIN_B_TASKS:
        raise SystemExit(f"fp25b: ids file has {len(want_ids)} < "
                         f"MIN_B_TASKS {MIN_B_TASKS}")
    a_mism = check_a_pin(a_receipt_path)
    if a_mism:
        raise SystemExit(f"fp25b: Surface-A pin mismatch {a_mism} — the B "
                         f"verdict may not compose with a drifted A")
    union = all_training_task_ids(
        f"{os.path.dirname(HERE)}/{RECALL_VIEW}",
        f"{os.path.dirname(HERE)}/{GRPO_POOL}")
    overlap = sorted({int(str(t).split(":")[-1]) for t in want_ids} &
                     {int(str(t).split(":")[-1]) for t in union})
    if overlap:
        raise SystemExit(f"fp25b: held-out ids overlap the training union "
                         f"{overlap[:5]} — disjointness violated")
    b_eval_receipts = {}
    tab = {}
    for sp in samples_paths:
        rp = sp.replace("-samples.jsonl", ".json")
        if rp == sp or not os.path.exists(rp):
            raise SystemExit(f"fp25b: no sibling W4 receipt for {sp} — the "
                             f"binding eval must be receipt-gated")
        rec, mism = check_b_eval_receipt(rp)
        if mism:
            raise SystemExit(f"fp25b: binding-eval receipt {os.path.basename(rp)} "
                             f"fails the amendment-2 gate {mism}")
        b_eval_receipts[os.path.basename(rp)] = rec["args"]["split"]
        t, _o = load_tab(sp)
        for arm, tasks in t.items():
            dst = tab.setdefault(arm, {})
            dup = set(dst) & set(tasks)
            if dup:
                raise SystemExit(f"fp25b: task overlap across legs for arm "
                                 f"{arm}: {sorted(dup)[:5]}")
            dst.update(tasks)
    for need in ARM_SET:
        if need not in tab:
            raise SystemExit(f"fp25b: missing arm {need!r}; have {sorted(tab)}")
    want_norm = {int(str(t).split(":")[-1]) for t in want_ids}
    got = {int(str(t).split(":")[-1]) for arm in tab for t in tab[arm]}
    if got != want_norm:
        raise SystemExit(f"fp25b: evaluated set != selected ids (missing "
                         f"{sorted(want_norm - got)[:5]}, extra "
                         f"{sorted(got - want_norm)[:5]})")
    for arm in tab:
        for t, vec in tab[arm].items():
            if len(vec) != EVAL_K:
                raise SystemExit(f"fp25b: k mismatch arm {arm} task {t}: "
                                 f"{len(vec)} != {EVAL_K}")
    b_cmp = {arm: compare(tab, arm, BASE) for arm in TRAINED}
    verdict = decide_generalize(A_PIN["verdict"], b_cmp)
    prov = {}
    for sp in samples_paths:
        with open(sp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("arm") and r["arm"] not in prov:
                    prov[r["arm"]] = r.get("sampler")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP25B-SURFACEB", "ts": ts, "surface": "B-heldout",
        "arms": sorted(tab), "k": EVAL_K, "seed": B_EVAL_SEED,
        "selection_src_seed": VAL_SRC_SEED,
        "heldout_task_ids_sha256": ids_sha256(want_ids),
        "heldout_task_count": len(want_ids),
        "sha_convention": SHA_CONVENTION,
        "disjointness_overlap": [],
        "a_pin": {"receipt": A_RECEIPT, **A_PIN, "verified_intact": True},
        "samples_file": [os.path.basename(p) for p in samples_paths],
        "b_eval_receipts": b_eval_receipts,
        "adapter_provenance": prov,
        "basis": ("fp-25 Surface B: held-out frontier, amendment 2 (mails "
                  "14575 + post-14580 pool expansion — S1 fp25b-cov train-"
                  "pool frontier + S2 r2w-q3 validation frontier, base-only "
                  "selection, union-disjoint, fresh-seed binding eval); "
                  "composes with the certified Surface-A RECIPE-LEARNS via "
                  "decide_generalize"),
        "blocks": b_cmp,
        "result": verdict,
    }
    missing = sorted(f for f in RECEIPT_REQUIRED_FIELDS if f not in receipt)
    if missing:
        raise SystemExit(f"fp25b: receipt missing required fields {missing}")
    return receipt


def _selftest():
    import tempfile
    # selection rule: window edges, dead/easy/union/partial routing
    theta = {600: (0, 8), 601: (4, 8), 602: (1, 8), 603: (8, 8),
             608: (2, 8),          # in union (mbpp:608 trained)
             605: (2, 4)}          # partial k -> excluded
    sel, rep = select_heldout(theta, ["mbpp:608"])
    # 0/8 dead (lo edge exclusive); 4/8=.5 in (hi edge inclusive);
    # 1/8=.125 in (interior); 8/8 out (easy)
    assert sel == [601, 602], (sel, rep)
    assert rep["dead_theta0"] == 1 and rep["easy_theta_gt_0.5"] == 1
    assert rep["in_training_union"] == 1 and rep["partial_k"] == 1

    # coverage_theta: strict mode refuses non-base rows; S2 mode filters
    # them and still consumes base rows only
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as tf:
        tf.write(json.dumps({"arm": "sft", "tid": 1, "verified": True}) + "\n")
        tf.write(json.dumps({"arm": "base", "tid": 2,
                             "verified": True}) + "\n")
        mixed = tf.name
    try:
        coverage_theta(mixed)
        raise AssertionError("non-base coverage row must refuse")
    except SystemExit:
        pass
    assert coverage_theta(mixed, base_only_file=False) == {2: (1, 1)}
    os.unlink(mixed)
    # all-arm-rows file with no base rows refuses even in S2 mode
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as tf:
        tf.write(json.dumps({"arm": "sft", "tid": 1, "verified": True}) + "\n")
        nb = tf.name
    try:
        coverage_theta(nb, base_only_file=False)
        raise AssertionError("no-base-rows file must refuse")
    except SystemExit:
        pass
    os.unlink(nb)

    # amendment-2 binding-eval receipt gate: conforming passes; stale seed
    # 16 (draw reuse), missing id filter, and missing arms are each caught
    good_b = {"ticket": "W4-EVAL", "k": EVAL_K,
              "args": {"split": "train", "seed": B_EVAL_SEED,
                       "task_ids_file": "ledger/views/x.txt",
                       "arm": [f"{BASE}=", "sft=p", "mtp=p", "grpo=p",
                               "control=p"]}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(good_b, tf)
        bp2 = tf.name
    _, mism = check_b_eval_receipt(bp2)
    assert mism == [], mism
    os.unlink(bp2)
    for mut in ({"seed": VAL_SRC_SEED}, {"task_ids_file": None},
                {"arm": [f"{BASE}=", "sft=p"]}, {"split": "test"}):
        drifted = json.loads(json.dumps(good_b))
        drifted["args"].update(mut)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as tf:
            json.dump(drifted, tf)
            dp2 = tf.name
        _, mism = check_b_eval_receipt(dp2)
        assert mism, f"b-eval drift {mut} must be caught"
        os.unlink(dp2)

    # A-pin guard: intact passes, drifted verdict caught
    good = {"result": {"verdict": "RECIPE-LEARNS",
                       "arm_learns_vs_base": {"sft": True, "mtp": True,
                                              "grpo": True}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(good, tf)
        gp = tf.name
    assert check_a_pin(gp) == []
    bad_a = {"result": {"verdict": "RECIPE-NULL",
                        "arm_learns_vs_base": {"sft": False, "mtp": False,
                                               "grpo": False}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(bad_a, tf)
        bp = tf.name
    assert check_a_pin(bp), "drifted A must be caught"
    os.unlink(gp)
    os.unlink(bp)

    # coverage-receipt gate: conforming passes, each drift caught
    good_cov = {"ticket": "W4-EVAL", "k": EVAL_K, "n_tasks": 120,
                "args": {"split": "train", "seed": EVAL_SEED,
                         "tag": COVERAGE_TAG, "arm": [f"{BASE}="],
                         "task_ids_file": None}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(good_cov, tf)
        cp = tf.name
    _, mism = check_coverage_receipt(cp)
    assert mism == [], mism
    os.unlink(cp)
    for field, bad in (("split", "validation"), ("seed", 7),
                       ("tag", "r2w-q3"), ("arm", [f"{BASE}=", "sft=x"]),
                       ("task_ids_file", "some/filter.txt")):
        drifted = json.loads(json.dumps(good_cov))
        drifted["args"][field] = bad
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as tf:
            json.dump(drifted, tf)
            dp = tf.name
        _, mism = check_coverage_receipt(dp)
        assert mism, f"drift in args.{field} must be caught"
        os.unlink(dp)

    # decide_generalize composition (imported frozen logic) sanity
    def vec(*per_task):
        return {f"t{i}": list(v) for i, v in enumerate(per_task)}
    tab = {
        "base":    vec([0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
        "sft":     vec([1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 0], [1, 1, 1, 1]),
        "mtp":     vec([1, 1, 1, 0], [1, 1, 1, 1], [1, 1, 0, 0], [1, 1, 1, 1]),
        "grpo":    vec([0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
        "control": vec([1, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
    }
    b_cmp = {arm: compare(tab, arm, "base") for arm in TRAINED}
    g = decide_generalize("RECIPE-LEARNS", b_cmp)
    assert g["verdict"] in ("LEARNS-AND-GENERALIZES", "OOD-TRANSFER-CEILING")
    assert g["provenance"].startswith("receipt-derived")

    # frozen-pin consistency
    assert (THETA_LO, THETA_HI) == (0.0, 0.5) and MIN_B_TASKS == 15
    assert EVAL_K == 8 and EVAL_SEED == 16
    assert B_EVAL_SEED != EVAL_SEED and B_EVAL_SEED != VAL_SRC_SEED
    print("FP25_SURFACEB_SELFTEST_PASS")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage-samples",
                    help="fp25b-cov samples.jsonl (S1) -> SELECT mode")
    ap.add_argument("--val-samples",
                    help="pinned r2w-q3 validation samples.jsonl (S2; "
                         "required with --coverage-samples)")
    ap.add_argument("--samples", nargs="+",
                    help="Surface-B 5-arm eval samples.jsonl (train leg + "
                         "validation leg) -> VERDICT mode")
    a, _ = ap.parse_known_args()
    NC = os.path.dirname(HERE)
    if not a.coverage_samples and not a.samples:
        print("FP25_SURFACEB_STAGED (selection rule + A-pin + verdict "
              "composition frozen in this file BEFORE the fp25b-cov receipt "
              "exists; select mode runs on the coverage samples, verdict "
              "mode on the 5-arm held-out eval)")
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if a.coverage_samples:
        cov_receipt_path = a.coverage_samples.replace("-samples.jsonl",
                                                      ".json")
        if cov_receipt_path == a.coverage_samples or \
                not os.path.exists(cov_receipt_path):
            raise SystemExit(f"fp25b: no sibling W4 coverage receipt for "
                             f"{a.coverage_samples} — the receipt is the "
                             f"sole theta source and must exist")
        cov, cov_mism = check_coverage_receipt(cov_receipt_path)
        if cov_mism:
            raise SystemExit(f"fp25b: coverage receipt fails the frozen "
                             f"gate {cov_mism} — refusing selection")
        if not a.val_samples:
            raise SystemExit("fp25b: amendment 2 requires --val-samples "
                             "(the pinned r2w-q3 validation samples) "
                             "alongside --coverage-samples")
        val_receipt_path = a.val_samples.replace("-samples.jsonl", ".json")
        if os.path.basename(val_receipt_path) != VAL_SRC_RECEIPT or \
                not os.path.exists(val_receipt_path):
            raise SystemExit(f"fp25b: --val-samples must be the samples of "
                             f"the pinned S2 receipt {VAL_SRC_RECEIPT}")
        _val, val_mism = check_val_src_receipt(val_receipt_path)
        if val_mism:
            raise SystemExit(f"fp25b: S2 validation receipt fails the gate "
                             f"{val_mism} — refusing selection")
        theta = coverage_theta(a.coverage_samples)
        if len(theta) != cov["n_tasks"]:
            raise SystemExit(f"fp25b: samples cover {len(theta)} tasks but "
                             f"receipt n_tasks={cov['n_tasks']}")
        union = all_training_task_ids(f"{NC}/{RECALL_VIEW}",
                                      f"{NC}/{GRPO_POOL}")
        sel_train, rep_train = select_heldout(theta, union)
        val_theta = coverage_theta(a.val_samples, base_only_file=False)
        sel_val, rep_val = select_heldout(val_theta, union)
        if rep_val["in_training_union"] != 0:
            raise SystemExit(f"fp25b: validation split intersects the "
                             f"training union — split discipline broken: "
                             f"{rep_val}")
        if set(sel_train) & set(sel_val):
            raise SystemExit(f"fp25b: S1/S2 id collision "
                             f"{sorted(set(sel_train) & set(sel_val))[:5]}")
        n_sel = len(sel_train) + len(sel_val)
        if n_sel < MIN_B_TASKS:
            raise SystemExit(f"fp25b: INFEASIBLE-FLAG — {n_sel} selected "
                             f"< MIN_B_TASKS {MIN_B_TASKS}; escalate as a "
                             f"new amendment, do not bind: "
                             f"S1={rep_train} S2={rep_val}")
        ids_train = [f"mbpp:{t}" for t in sel_train]
        ids_val = [f"mbpp:{t}" for t in sel_val]
        ids = ids_train + ids_val
        overlap = sorted({int(str(t).split(":")[-1]) for t in ids} &
                         {int(str(t).split(":")[-1]) for t in union})
        if overlap:
            raise SystemExit(f"fp25b: selected ids overlap the training "
                             f"union {overlap[:5]} — selection rule broken")
        for path, blob in ((B_IDS_FILE, ids), (B_IDS_TRAIN_FILE, ids_train),
                           (B_IDS_VAL_FILE, ids_val)):
            with open(f"{NC}/{path}", "w", encoding="utf-8",
                      newline="\n") as f:
                f.write("\n".join(blob) + "\n")
        import hashlib
        cov_sha = hashlib.sha256(
            open(cov_receipt_path, "rb").read()).hexdigest()
        val_sha = hashlib.sha256(
            open(val_receipt_path, "rb").read()).hexdigest()
        receipt = {"ticket": "FP25B-SELECT", "ts": ts,
                   "amendment": 2,
                   "coverage_receipt": os.path.basename(cov_receipt_path),
                   "coverage_receipt_sha256": cov_sha,
                   "coverage_n_tasks": cov["n_tasks"],
                   "coverage_samples": os.path.basename(a.coverage_samples),
                   "val_src_receipt": VAL_SRC_RECEIPT,
                   "val_src_receipt_sha256": val_sha,
                   "val_src_samples": os.path.basename(a.val_samples),
                   "theta_source": ("S1 = the gated fp25b-cov W4 receipt "
                                    "(base-only, split=train, k8, seed16, "
                                    "no id filter); S2 = BASE rows only of "
                                    "the pinned r2w-q3 validation receipt. "
                                    "No other theta source exists or is "
                                    "consulted."),
                   "selection_train": rep_train,
                   "selection_val": rep_val,
                   "selected_train": len(ids_train),
                   "selected_val": len(ids_val),
                   "selected_ids_sha256": ids_sha256(ids),
                   "sha_convention": SHA_CONVENTION,
                   "ids_file": B_IDS_FILE,
                   "ids_file_train": B_IDS_TRAIN_FILE,
                   "ids_file_val": B_IDS_VAL_FILE,
                   "b_eval_seed": B_EVAL_SEED,
                   "disjointness_overlap": overlap}
        out = f"{NC}/receipts/fp25b-select-{ts}.json"
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(receipt, f, indent=2)
        print(json.dumps(receipt, indent=2))
        print(f"FP25B_SELECT_DONE {out}")
        return
    receipt = build_b_verdict(a.samples, f"{NC}/{B_IDS_FILE}",
                              f"{NC}/receipts/{A_RECEIPT}")
    out = f"{NC}/receipts/fp25b-surfaceb-{receipt['ts']}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({"verdict": receipt["result"]["verdict"],
                      "arm_generalizes_vs_base":
                          receipt["result"]["arm_generalizes_vs_base"]},
                     indent=2))
    print(f"FP25B_SURFACEB_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
