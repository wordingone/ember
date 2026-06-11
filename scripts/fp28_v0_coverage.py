"""fp28_v0_coverage.py — v0-world frontier-depth coverage executor
(#199): the fp-26 (b) deferred obligation, STAGED FAIL-CLOSED.

fp-26 froze, for shape (b): "the v0 world's task-pool coverage run —
executable only post-v0-pretrain; a DEFERRED post-checkpoint receipt,
not a launch blocker (gated as an obligation, not a precondition)."
This file is that obligation's executor, built BEFORE checkpoints exist
so discharge is mechanical the moment checkpoint-1 lands — and built
fail-closed so it cannot run early (early execution would un-freeze the
probe surface the floor protocol depends on).

Two halves:

1. CANONICAL PROBE-SET MATERIALIZER (`--materialize`). fp-23 froze the
   rule prose ("first 100 instances of buckets 0-9 under generator seed
   23, materialized once and sha-stamped") but no executable draw order.
   Frozen here: random.Random(fp23.GENERATOR_SEED); per instance draw
   op = rng.choice(L1_OPS), length = rng.randint(*INPUT_LEN), values =
   [rng.randint(*INPUT_VAL) ...]; keep iff fp23.bucket(op, repr(values))
   in PROBE_BUCKETS; stop at PROBE_N. Expected outputs come from the
   reference implementations below (fp-23 verification semantics:
   reference executes, candidate must exact-match repr). The emitted
   probes/l1-probe-set-seed23.json IS the single source — the eng eval
   harness consumes this file; it never re-materializes.

2. COVERAGE EXECUTOR (`--emit`). Consumes a REAL checkpoint-probe eval
   receipt (per-task pass counts over the probe set) and partitions the
   pool with the fp-25b theta conventions: DEAD theta==0, EASY
   theta>0.5, FRONTIER 0<theta<=0.5. Refuses unless the eval receipt
   receipt_checks clean, carries the required binding fields (checkpoint
   sha, probe-set sha matching the canonical file, adapter_none_assert,
   per-task results for exactly the canonical task ids), and the
   governor block is present. No GPU here — the model run that produces
   the eval receipt is the eng harness's (eng-48 lineage).

`--selftest` pure-logic: materializer determinism (byte-identical
re-run), bucket/grammar/count invariants, reference-op correctness,
partition logic, and every refusal branch on synthetic fixtures.
"""
import argparse
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write               # noqa: E402
from receipt_check import validate_receipt             # noqa: E402
import fp23_probe_prereg as fp23                       # noqa: E402

PROBE_SET_PATH = "probes/l1-probe-set-seed23.json"
# fp-25b partition conventions (fp25b receipts: dead theta=0, easy >0.5)
THETA_EASY = 0.5
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")
# binding fields the eval receipt must carry (subset of fp-23's schema
# plus the coverage-specific bindings)
EVAL_REQUIRED_FIELDS = (
    "ticket", "ts", "checkpoint_sha256", "probe_set_sha256",
    "adapter_none_assert", "governor", "k", "per_task",
)


# ---- frozen L1 reference implementations (fp-23 grammar, 10 ops) -----
def _ref(op, xs):
    if op == "reverse":
        return list(reversed(xs))
    if op == "sort_asc":
        return sorted(xs)
    if op == "sort_desc":
        return sorted(xs, reverse=True)
    if op == "filter_even":
        return [x for x in xs if x % 2 == 0]
    if op == "filter_odd":
        return [x for x in xs if x % 2 == 1]
    if op == "sum_fold":
        return sum(xs)
    if op == "min_fold":
        return min(xs)
    if op == "max_fold":
        return max(xs)
    if op == "dedup_stable":
        seen, out = set(), []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    if op == "count_distinct":
        return len(set(xs))
    raise ValueError(f"op outside frozen grammar: {op}")


def materialize_probe_set():
    """The canonical draw order, frozen (see docstring). Deterministic:
    same bytes on every run on every platform."""
    rng = random.Random(fp23.GENERATOR_SEED)
    instances = []
    while len(instances) < fp23.PROBE_N:
        op = rng.choice(fp23.L1_OPS)
        n = rng.randint(*fp23.INPUT_LEN)
        xs = [rng.randint(*fp23.INPUT_VAL) for _ in range(n)]
        if fp23.bucket(op, repr(xs)) in fp23.PROBE_BUCKETS:
            instances.append({
                "task_id": f"l1-p{len(instances):03d}",
                "op": op,
                "input": xs,
                "bucket": fp23.bucket(op, repr(xs)),
                "expected_repr": repr(_ref(op, xs)),
            })
    return {
        "name": "l1-probe-set",
        "generator_seed": fp23.GENERATOR_SEED,
        "probe_buckets": "0-9",
        "n": fp23.PROBE_N,
        "draw_order": ("random.Random(seed); op=choice(L1_OPS); "
                       "len=randint(INPUT_LEN); vals=[randint(INPUT_VAL)]; "
                       "keep iff bucket(op, repr(vals)) in PROBE_BUCKETS"),
        "verification": "candidate output repr must exact-match "
                        "expected_repr (fp-23 semantics)",
        "instances": instances,
    }


def _canon_bytes(obj):
    return json.dumps(obj, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def probe_set_sha(ps):
    return hashlib.sha256(_canon_bytes(ps)).hexdigest()


def check_eval_receipt(ev, canonical_sha, canonical_ids):
    """Findings list (empty = the eval receipt may drive coverage)."""
    f = list(validate_receipt(ev))
    for field in EVAL_REQUIRED_FIELDS:
        if field not in ev:
            f.append(f"missing field: {field}")
    if f:
        return f
    if ev["probe_set_sha256"] != canonical_sha:
        f.append("probe_set_sha256 != canonical probe set (the eval ran on "
                 "a different surface)")
    if ev["adapter_none_assert"] is not True:
        f.append("adapter_none_assert must be literally true (coverage is "
                 "the BASE core's, never an adapter's)")
    per_task = ev["per_task"]
    ids = sorted(t.get("task_id") for t in per_task)
    if ids != sorted(canonical_ids):
        f.append("per_task ids != canonical probe-set ids (missing or "
                 "extra tasks)")
        return f
    k = ev["k"]
    for t in per_task:
        p = t.get("pass_count")
        if not isinstance(p, int) or not (0 <= p <= k):
            f.append(f"{t.get('task_id')}: pass_count must be int in "
                     f"[0,{k}], got {p!r}")
    return f


def partition(per_task, k):
    """fp-25b theta conventions on per-task pass rates."""
    out = {"dead": [], "easy": [], "frontier": []}
    for t in per_task:
        theta = t["pass_count"] / k
        if theta == 0.0:
            out["dead"].append(t["task_id"])
        elif theta > THETA_EASY:
            out["easy"].append(t["task_id"])
        else:
            out["frontier"].append(t["task_id"])
    return out


def build_receipt(ts, ev, parts, canonical_sha):
    return {
        "ticket": "FP28-V0-COVERAGE",
        "ts": ts,
        "issue": 199,
        "obligation": ("fp-26 (b) deferred frontier-depth coverage — "
                       "discharged on a real checkpoint"),
        "checkpoint_sha256": ev["checkpoint_sha256"],
        "probe_set_sha256": canonical_sha,
        "eval_receipt_ticket": ev["ticket"],
        "k": ev["k"],
        "n_tasks": len(ev["per_task"]),
        "partition": {
            "dead_theta": 0.0, "easy_theta_gt": THETA_EASY,
            "dead": sorted(parts["dead"]),
            "easy": sorted(parts["easy"]),
            "frontier": sorted(parts["frontier"]),
        },
        "result": {"verdict": "COVERAGE-RECEIPTED",
                   "frontier_depth": len(parts["frontier"]),
                   "dead": len(parts["dead"]),
                   "easy": len(parts["easy"])},
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _selftest():
    # materializer: deterministic, exactly N, buckets in 0-9, grammar ops
    a, b = materialize_probe_set(), materialize_probe_set()
    assert _canon_bytes(a) == _canon_bytes(b), "materializer not deterministic"
    inst = a["instances"]
    assert len(inst) == fp23.PROBE_N
    assert all(t["bucket"] in fp23.PROBE_BUCKETS for t in inst)
    assert all(t["op"] in fp23.L1_OPS for t in inst)
    assert len({t["task_id"] for t in inst}) == fp23.PROBE_N
    # reference ops: spot semantics
    assert _ref("reverse", [1, 2, 3]) == [3, 2, 1]
    assert _ref("dedup_stable", [3, 1, 3, 2, 1]) == [3, 1, 2]
    assert _ref("count_distinct", [5, 5, 7]) == 2
    assert _ref("filter_even", [1, 2, 3, 4]) == [2, 4]
    # expected_repr round-trips through the reference
    for t in inst[:20]:
        assert t["expected_repr"] == repr(_ref(t["op"], t["input"]))
    sha = probe_set_sha(a)
    ids = [t["task_id"] for t in inst]
    # partition logic
    k = 16
    pt = [{"task_id": "d", "pass_count": 0},
          {"task_id": "e", "pass_count": 9},
          {"task_id": "f", "pass_count": 8},
          {"task_id": "g", "pass_count": 1}]
    parts = partition(pt, k)
    assert parts == {"dead": ["d"], "easy": ["e"],
                     "frontier": ["f", "g"]}, parts
    # refusal branches
    base_ev = {"ticket": "x", "ts": "x", "checkpoint_sha256": "c" * 64,
               "probe_set_sha256": sha, "adapter_none_assert": True,
               "governor": {"vram_fraction": 0.8}, "k": 16,
               "per_task": [{"task_id": i, "pass_count": 1} for i in ids],
               "sha_convention": SHA_CONVENTION}
    assert check_eval_receipt(base_ev, sha, ids) == [], \
        check_eval_receipt(base_ev, sha, ids)
    assert any("probe_set_sha256" in x for x in check_eval_receipt(
        dict(base_ev, probe_set_sha256="0" * 64), sha, ids))
    assert any("adapter_none_assert" in x for x in check_eval_receipt(
        dict(base_ev, adapter_none_assert=False), sha, ids))
    assert any("ids" in x for x in check_eval_receipt(
        dict(base_ev, per_task=base_ev["per_task"][:50]), sha, ids))
    assert any("missing field" in x for x in check_eval_receipt(
        {k_: v for k_, v in base_ev.items() if k_ != "governor"}, sha, ids))
    bad = dict(base_ev, per_task=(base_ev["per_task"][:-1]
                                  + [{"task_id": ids[-1],
                                      "pass_count": 99}]))
    assert any("pass_count" in x for x in check_eval_receipt(bad, sha, ids))
    # coverage receipt clean
    parts_full = partition(base_ev["per_task"], 16)
    r = build_receipt("20260101T000000Z", base_ev, parts_full, sha)
    assert validate_receipt(r) == [], validate_receipt(r)
    assert r["result"]["frontier_depth"] == 100  # all pass_count=1, k=16
    print("FP28_V0_COVERAGE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--materialize", action="store_true",
                    help="write the canonical probe set + print its sha")
    ap.add_argument("--emit", metavar="EVAL_RECEIPT",
                    help="discharge the coverage obligation against a real "
                         "checkpoint eval receipt")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if a.materialize:
        ps = materialize_probe_set()
        out = f"{NC}/{PROBE_SET_PATH}"
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(_canon_bytes(ps))
        print(f"FP28_PROBE_SET_MATERIALIZED {PROBE_SET_PATH} "
              f"sha256={probe_set_sha(ps)}")
        return
    if not a.emit:
        print("FP28_V0_COVERAGE_STAGED (refuses until a real checkpoint "
              "eval receipt exists; --materialize writes the canonical "
              "probe set)")
        return
    # fail-closed: canonical probe set must exist and match the live
    # materializer (no drift between the committed file and the code)
    psp = f"{NC}/{PROBE_SET_PATH}"
    if not os.path.exists(psp):
        raise SystemExit("FP28_REFUSED: canonical probe set not on disk — "
                         "run --materialize first")
    on_disk = open(psp, "rb").read()
    live = materialize_probe_set()
    if on_disk != _canon_bytes(live):
        raise SystemExit("FP28_REFUSED: committed probe set != live "
                         "materializer output (drift)")
    sha = probe_set_sha(live)
    ids = [t["task_id"] for t in live["instances"]]
    try:
        ev = json.load(open(a.emit, encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"FP28_REFUSED: unreadable eval receipt: {e}")
    f = check_eval_receipt(ev, sha, ids)
    if f:
        for x in f:
            print(f"EVAL RECEIPT VIOLATION: {x}")
        raise SystemExit("FP28_REFUSED — eval receipt does not bind")
    parts = partition(ev["per_task"], ev["k"])
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts, ev, parts, sha)
    out = f"{NC}/receipts/fp28-v0-coverage-{ts}.json"
    checked_write(out, receipt)
    reloaded = json.load(open(out, encoding="utf-8"))
    fr = validate_receipt(reloaded)
    if fr:
        raise SystemExit(f"emitted coverage receipt FAILS receipt_check: {fr}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP28_COVERAGE_RECEIPTED {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
