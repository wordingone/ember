"""w4_control_selftest.py — eng-41 (#151) control-deltas fix + repair receipt.

Kai's G1 live audit (mail 14529): w4_eval's control comparison was
guarded by a literal 'trained' arm name, so the r2 five-arm record
(base/sft/mtp/grpo/control) receipt carried base deltas but NO control
deltas — partial under STATE's decision rule. Fix = control_pairs()
single-source pairing rule (bootstrap deltas + exact block) + the
post-hoc repair tool for the in-flight run. This selftest pins both.

Checks (pure logic + fixture round-trip; no GPU, no network, no model):
  1. control_pairs: five-arm record emits exactly sft/mtp/grpo vs
     control; literal 'trained' arm is subsumed (same key as r1);
     no-control and control-only records emit nothing;
  2. w4_eval source wiring: the literal guard is gone, both the deltas
     block and the exact-method paired outcomes consume control_pairs;
  3. repair tool end-to-end on a synthetic five-arm fixture: samples
     JSONL (arm-major, k consecutive rows per task — the w4 write
     order) + a pre-fix-shaped receipt -> repair receipt carries the
     three missing control deltas; the validity cross-check (exact
     equality of recomputed base deltas + pass rates, seeded CIs) is
     exercised both passing and failing (tampered receipt -> refusal);
     already-repaired receipts are refused;
  4. repair receipts go through checked_write (schema floor enforced at
     write time — completing IS the receipt_check evidence).

Windows shim (declared): w4_eval -> t1_probe imports POSIX `resource`;
nothing sandboxed runs here.

Writes receipts/eng41-w4-control-selftest-<ts>.json. Sentinel:
ENG41_W4_CONTROL_SELFTEST_PASS.
"""
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

if os.name == "nt":
    sys.modules.setdefault("resource", types.ModuleType("resource"))

from w4_eval import control_pairs  # noqa: E402
from t4_eval import bootstrap_ci, paired_delta_ci  # noqa: E402
from receipt_write import checked_write  # noqa: E402
import w4_control_delta_repair as repair_mod  # noqa: E402


def _fixture(tmp):
    """Synthetic five-arm run: 3 tasks, k=2, arm-major samples JSONL +
    the receipt a PRE-FIX w4_eval would have written (base deltas only)."""
    order = ["t1", "t2", "t3"]
    arms = ["base", "sft", "mtp", "grpo", "control"]
    verified = {  # pass-any pattern per arm, per task
        "base":    {"t1": 0, "t2": 0, "t3": 1},
        "sft":     {"t1": 1, "t2": 1, "t3": 1},
        "mtp":     {"t1": 1, "t2": 0, "t3": 1},
        "grpo":    {"t1": 0, "t2": 1, "t3": 1},
        "control": {"t1": 0, "t2": 0, "t3": 0},
    }
    samples = os.path.join(tmp, "w4-eval-fx-samples.jsonl")
    with open(samples, "w", encoding="utf-8", newline="\n") as f:
        for arm in arms:
            for tid in order:
                hit = bool(verified[arm][tid])
                # k=2: one verified row (when passing) + one failing row
                f.write(json.dumps({"arm": arm, "tid": tid,
                                    "verified": hit, "src": "x",
                                    "sampler": "fx"}) + "\n")
                f.write(json.dumps({"arm": arm, "tid": tid,
                                    "verified": False, "src": "y",
                                    "sampler": "fx"}) + "\n")
    vec = {a: [verified[a][t] for t in order] for a in arms}
    receipt = {
        "ticket": "W4-EVAL", "ts": "20260611T000000Z",
        "args": {"arm": [f"{a}=" for a in arms], "tag": "fx"},
        "n_tasks": len(order),
        "arms": {a: {"pass_any_pct": round(100 * sum(vec[a]) / 3, 2),
                     "pass_ci95": bootstrap_ci(vec[a])} for a in arms},
        "deltas": {f"{a}_minus_base_ci95":
                   paired_delta_ci(vec[a], vec["base"])
                   for a in arms if a != "base"},
        "samples_file": os.path.basename(samples),
    }
    receipt_path = os.path.join(tmp, "w4-eval-fx.json")
    with open(receipt_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    return samples, receipt_path, vec


def main():
    checks = {}

    # 1. control_pairs semantics
    five = {n: [1, 0] for n in ("base", "sft", "mtp", "grpo", "control")}
    keys = set(control_pairs(five))
    assert keys == {"sft_minus_control_ci95", "mtp_minus_control_ci95",
                    "grpo_minus_control_ci95"}, keys
    legacy = control_pairs({"base": [1], "trained": [1], "control": [0]})
    assert set(legacy) == {"trained_minus_control_ci95"}, \
        "r1 literal key must be subsumed, not lost"
    assert control_pairs({"base": [1], "sft": [1]}) == {}
    assert control_pairs({"control": [1]}) == {}
    a, b = control_pairs(five)["sft_minus_control_ci95"]
    assert a == five["sft"] and b == five["control"], "pair order arm,control"
    checks["control_pairs"] = True

    # 2. w4_eval wiring: literal guard gone, both blocks use control_pairs
    src = open(os.path.join(HERE, "w4_eval.py"), encoding="utf-8").read()
    assert '"trained" in arm_vec' not in src, \
        "literal trained guard must be gone"
    assert src.split("def main():")[1].count("control_pairs(arm_vec)") == 2, \
        "both deltas + exact blocks must consume control_pairs"
    checks["w4_eval_wiring"] = True

    # 3. repair tool end-to-end
    with tempfile.TemporaryDirectory() as tmp:
        samples, receipt_path, vec = _fixture(tmp)
        out_path, rec = repair_mod.repair(samples, receipt_path,
                                          out_dir=tmp)
        assert os.path.exists(out_path)
        assert set(rec["deltas"]) == {"sft_minus_control_ci95",
                                      "mtp_minus_control_ci95",
                                      "grpo_minus_control_ci95"}
        for key, (x, y) in control_pairs(vec).items():
            assert rec["deltas"][key] == paired_delta_ci(x, y), key
        assert rec["crosscheck"]["base_deltas_compared"] == 4
        assert rec["crosscheck"]["pass_any_compared"] == 5
        assert rec["exact_control"] is not None, \
            "exact block must ride the repair receipt"

        # 3b. refusal: receipt already carries a control delta
        with open(receipt_path, encoding="utf-8") as f:
            r2 = json.load(f)
        r2["deltas"]["sft_minus_control_ci95"] = [0.0, 0.0]
        p2 = os.path.join(tmp, "already.json")
        with open(p2, "w", encoding="utf-8", newline="\n") as f:
            json.dump(r2, f)
        try:
            repair_mod.repair(samples, p2, out_dir=tmp)
            raise AssertionError("already-repaired receipt must refuse")
        except SystemExit:
            pass

        # 3c. refusal: tampered base delta breaks the validity cross-check
        with open(receipt_path, encoding="utf-8") as f:
            r3 = json.load(f)
        r3["deltas"]["sft_minus_base_ci95"] = [-99.0, 99.0]
        p3 = os.path.join(tmp, "tampered.json")
        with open(p3, "w", encoding="utf-8", newline="\n") as f:
            json.dump(r3, f)
        try:
            repair_mod.repair(samples, p3, out_dir=tmp)
            raise AssertionError("cross-check mismatch must refuse")
        except SystemExit:
            pass
    checks["repair_roundtrip_and_refusals"] = True

    # 4. repair writes via checked_write (schema floor at write time)
    rsrc = open(os.path.join(HERE, "w4_control_delta_repair.py"),
                encoding="utf-8").read()
    assert "checked_write(out_path, receipt)" in rsrc
    assert "from w4_eval import control_pairs" in rsrc, \
        "pairing rule must be imported, never copied"
    checks["repair_wiring"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG41-W4-CONTROL-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#151",
        "checks": checks,
        "finding": ("literal 'trained' guard meant the r2 five-arm G1 "
                    "receipt carried no control deltas (Kai mail 14529); "
                    "STATE needs arm-minus-base AND arm-minus-control "
                    "per trained arm"),
        "repair_validity": ("seeded CIs (seed=7) make recomputation "
                            "deterministic: the repair tool refuses unless "
                            "it reproduces the original base deltas + pass "
                            "rates exactly from the same samples"),
        "dispatch_note": ("repaired receipt vs post-patch rerun for the "
                          "in-flight G1 run is the gate-holder's call "
                          "(14529 names both); powered t5 must not launch "
                          "from a receipt lacking control legs"),
    }
    out = os.path.join(REPO, "receipts", f"eng41-w4-control-selftest-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("ENG41_W4_CONTROL_SELFTEST_PASS")


if __name__ == "__main__":
    main()
