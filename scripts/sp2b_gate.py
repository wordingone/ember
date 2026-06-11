"""sp2b_gate.py — executable gate for the sp-2 owned-core persistence
receipts (#210): P-own-resume (per daemon restart during the governed
pretrain) and D-round (round-gate adapter quarantine vs the owned base).

The shapes were frozen prose in research/sp2-owned-core-persistence-
gates.md; this makes them executable BEFORE the first receipt exists, so
#210's fire is mechanical (the eng emitter binds to validate_* here —
never re-derives the shape). Same staged-fail-closed pattern as fp-28.

Verdicts are findings lists (empty = the receipt satisfies the frozen
shape). Gate-time audit obligations that need bytes (sha-chain
re-derivation from the checkpoint manifest) are NAMED as required
fields here and re-derived by the auditor at fire time — the boolean
asserts are the emitter's claim, never the verdict's evidence.
"""
import argparse
import json
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from receipt_check import validate_receipt             # noqa: E402

P_OWN_RESUME_REQUIRED = (
    "ticket",                    # P-OWN-RESUME
    "ts",
    "run_dir",
    "verify_resume_verdict",     # must be exactly "SAFE_RESUME"
    "resume_ckpt_dir",
    "resume_step",
    "ckpt_sha_chain_assert",     # true (re-derived by auditor at fire time)
    "rng_restored_assert",       # true
    "pid_before",
    "pid_after",                 # must differ from pid_before
    "last_pre_loss",
    "first_post_loss",           # both finite floats (logged boundary pair)
    "governor",
    "sha_convention",
)

D_ROUND_REQUIRED = (
    "ticket",                    # D-ROUND
    "ts",
    "round",
    "base_checkpoint_sha256",
    "adapter_path",
    "adapter_sha256_before",     # byte-identity across quarantine
    "adapter_sha256_after",      # must equal before
    "eval_split",                # must name buckets 90-99
    "seed",
    "gain_with",                 # adapter present
    "gain_without",              # quarantined: must be 0.0 exactly
    "base_pass_vector_match",    # true: quarantined leg == base pass-vector
    "governor",
    "sha_convention",
)


def _finite(x):
    return isinstance(x, (int, float)) and x == x and abs(x) != float("inf")


def validate_p_own_resume(r):
    f = list(validate_receipt(r))
    for k in P_OWN_RESUME_REQUIRED:
        if k not in r:
            f.append(f"missing field: {k}")
    if f:
        return f
    if r["verify_resume_verdict"] != "SAFE_RESUME":
        f.append("verify_resume_verdict must be SAFE_RESUME — a "
                 "RESTART_FROM_SCRATCH is its own receipt + STATE event, "
                 "never a P-gate pass")
    for a in ("ckpt_sha_chain_assert", "rng_restored_assert"):
        if r[a] is not True:
            f.append(f"{a} must be literally true")
    if r["pid_before"] == r["pid_after"]:
        f.append("pid_before == pid_after — no process boundary crossed")
    for k in ("last_pre_loss", "first_post_loss"):
        if not _finite(r[k]):
            f.append(f"{k} must be a finite number, got {r[k]!r}")
    return f


def validate_d_round(r):
    f = list(validate_receipt(r))
    for k in D_ROUND_REQUIRED:
        if k not in r:
            f.append(f"missing field: {k}")
    if f:
        return f
    if r["adapter_sha256_before"] != r["adapter_sha256_after"]:
        f.append("adapter byte-identity broken across quarantine "
                 "(sha before != after)")
    if r["gain_without"] != 0.0:
        f.append(f"gain_without must be 0.0 exactly (adapter absent => "
                 f"base behavior at fixed seed), got {r['gain_without']!r}")
    if r["base_pass_vector_match"] is not True:
        f.append("base_pass_vector_match must be literally true (and is "
                 "re-derived by the auditor from the eval rows)")
    if "90" not in str(r["eval_split"]) or "99" not in str(r["eval_split"]):
        f.append(f"eval_split must name the round-gate buckets 90-99, "
                 f"got {r['eval_split']!r}")
    return f


def _selftest():
    good_p = {"ticket": "P-OWN-RESUME", "ts": "x", "run_dir": "runs/v0",
              "verify_resume_verdict": "SAFE_RESUME",
              "resume_ckpt_dir": "ck/00100", "resume_step": 100,
              "ckpt_sha_chain_assert": True, "rng_restored_assert": True,
              "pid_before": 11, "pid_after": 22,
              "last_pre_loss": 2.31, "first_post_loss": 2.30,
              "governor": {"vram_fraction": 0.8}, "sha_convention": "x"}
    assert validate_p_own_resume(good_p) == [], validate_p_own_resume(good_p)
    assert any("SAFE_RESUME" in x for x in validate_p_own_resume(
        dict(good_p, verify_resume_verdict="RESTART_FROM_SCRATCH")))
    assert any("pid" in x for x in validate_p_own_resume(
        dict(good_p, pid_after=11)))
    assert any("finite" in x for x in validate_p_own_resume(
        dict(good_p, first_post_loss="nan?")))
    assert any("missing field" in x for x in validate_p_own_resume(
        {k: v for k, v in good_p.items() if k != "governor"}))
    good_d = {"ticket": "D-ROUND", "ts": "x", "round": "own-r1",
              "base_checkpoint_sha256": "a" * 64,
              "adapter_path": "adapters/own-r1-sft",
              "adapter_sha256_before": "b" * 64,
              "adapter_sha256_after": "b" * 64,
              "eval_split": "buckets 90-99 N=100 seed 23",
              "seed": 31, "gain_with": 0.25, "gain_without": 0.0,
              "base_pass_vector_match": True,
              "governor": {"vram_fraction": 0.8}, "sha_convention": "x"}
    assert validate_d_round(good_d) == [], validate_d_round(good_d)
    assert any("byte-identity" in x for x in validate_d_round(
        dict(good_d, adapter_sha256_after="c" * 64)))
    assert any("gain_without" in x for x in validate_d_round(
        dict(good_d, gain_without=0.01)))
    assert any("90-99" in x for x in validate_d_round(
        dict(good_d, eval_split="buckets 0-9")))
    print("SP2B_GATE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--p-resume", metavar="RECEIPT")
    ap.add_argument("--d-round", metavar="RECEIPT")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not (a.p_resume or a.d_round):
        print("SP2B_GATE_STAGED (--p-resume / --d-round validate a live "
              "receipt against the frozen sp-2 shapes)")
        return
    path = a.p_resume or a.d_round
    r = json.load(open(path, encoding="utf-8"))
    f = (validate_p_own_resume if a.p_resume else validate_d_round)(r)
    if f:
        for x in f:
            print(f"SHAPE VIOLATION: {x}")
        raise SystemExit("SP2B_GATE_FAIL")
    print("SP2B_GATE_PASS")


if __name__ == "__main__":
    main()
