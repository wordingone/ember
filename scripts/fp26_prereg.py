"""fp26_prereg.py — round-3 shape prereg FREEZE (#166 / task #49).

Freezes the round-3 decision under the receipted transfer ceiling +
frontier exhaustion. Shape = (b) owned-core in-dist accumulation: v0
pretrain (NC2-own, c03-qat frozen config) -> fp-22 verify-floor world ->
accumulation rounds where eval distribution == train distribution BY
CONSTRUCTION, so the fp-25 transfer ceiling does not bind it. Kill rule ->
fallback (a) borrowed-core round-3 in the MBPP+HumanEval union world, which
keeps its own fp25b-cov-shape coverage obligation BEFORE any (a) prereg
freeze.

The emitted receipt (`fp26-prereg-<ts>.json`, prereg_frozen:true) is what
the v0 launch gate's G-prereg row checks for. The freeze is tamper-guarded:
it refuses unless every pinned premise receipt + the decision artifact match
their recorded sha AND pass receipt_check. Same fail-closed grammar as the
other prereg executors.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write          # noqa: E402
from receipt_check import validate_receipt        # noqa: E402

ROUND = 3

# ---- pinned premises (tamper guard: sha must match at freeze time) -------
DECISION_ARTIFACT = "research/fp26-round3-shape-decision.md"
DECISION_SHA = ("5ef7cc20f22168878f139af00e6ac9a75d43c758"
                "ffd2b3eb181372c50081c939")
# the two load-bearing fp-25 premise receipts (Surface-A learn, Surface-B
# ceiling) — both must receipt_check PASS and match these shas
PREMISE_RECEIPTS = {
    "surface_a_recipe_learns": {
        "name": "fp25-indist-20260611T060416Z.json",
        "sha": ("c6a318a184934744a97617f37dbe51c4"
                "7dcc9e8cbe87a6c8e746390c307a276a"),
    },
    "surface_b_transfer_ceiling": {
        "name": "fp25b-surfaceb-20260611T063604Z.json",
        "sha": ("50c24afe86dc2ebcd6c06d339ed677bc"
                "b236f26ded36ef62165d00b309d8ebd0"),
    },
}
# corpus + envelope premises (existence + receipt_check only; not sha-pinned
# because they are already pinned downstream by the launch gate / config)
SUPPORT_RECEIPTS = [
    "eng36-assembly-20260611T052337Z.json",
    "fp19-bench-20260611T024648Z.json",
    "tokenizer-freeze-20260611T060423Z.json",
]

# ---- the frozen decision (committed by this freeze) ----------------------
ROUND3_SHAPE = "b-owned-core-in-dist-accumulation"
DECISION = {
    "shape": ROUND3_SHAPE,
    "description": ("v0 owned-core pretrain (NC2-own, c03-qat frozen config) "
                    "-> fp-22 verify-floor world -> accumulation rounds; "
                    "eval distribution == train distribution by construction"),
    "why_not_re_attempt_transfer": ("fp-25 receipted that re-running transfer "
                                     "at the 98-episode budget in the same "
                                     "world is DEAD; (b)'s world is in-dist by "
                                     "design so the ceiling does not bind it"),
    "kill_rule": ("if the v0 owned core cannot clear a K1-equivalent verify "
                  "floor in the fp-22 world even with curriculum synthesis "
                  "(the NC2-own rung-level kill), DEMOTE to fallback (a)"),
    "fallback_a": {
        "shape": "borrowed-core-round3-deeper-world",
        "world": "MBPP+HumanEval union (164 untouched tasks, same harness)",
        "pre_freeze_obligation": ("a frontier-depth coverage receipt "
                                  "(fp25b-cov shape) gated BEFORE any (a) "
                                  "prereg freeze"),
    },
    "frontier_depth_obligation_for_b": (
        "the v0 world's task-pool coverage run — executable only "
        "post-v0-pretrain; a DEFERRED post-checkpoint receipt, not a launch "
        "blocker (gated as an obligation, not a precondition)"),
}

# Kai 14589 (14582 ask #2) — verbatim-scoped wording resolution
WORDING_RESOLUTION = {
    "primary_verdict": "OOD-TRANSFER-CEILING scoped to the preregistered floor",
    "scope": ("no detected >=13-21pp transfer effect on N=17 held-out frontier "
              "tasks at the 98-episode budget"),
    "must_not_propagate_as": ["no small transfer exists",
                              "architecture-level evidence"],
    "underpowered": ("UNDERPOWERED-AT-FLOOR is a CAVEAT, not the primary "
                     "verdict; the receipt reports the MDE and the claim is "
                     "budget/floor-scoped"),
    "robustness": ("the round-3 decision rests on the floor-scoped reading and "
                   "holds whether or not a sub-floor transfer effect exists, "
                   "because (b)'s world is in-dist by construction and does not "
                   "depend on transfer at all"),
    "source": "Kai 14589 (resolves 14582 ask #2)",
}

SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_premises(nc=NC):
    """Returns list of violations (empty = all pins hold). Fail-closed:
    every pinned premise must exist, receipt_check PASS (receipts), and
    match its recorded sha; the decision artifact must match DECISION_SHA."""
    v = []
    dp = f"{nc}/{DECISION_ARTIFACT}"
    if not os.path.exists(dp):
        v.append(f"decision artifact missing: {DECISION_ARTIFACT}")
    elif _sha(dp) != DECISION_SHA:
        v.append(f"decision artifact sha drift: {_sha(dp)[:12]} != "
                 f"{DECISION_SHA[:12]}")
    for key, pin in PREMISE_RECEIPTS.items():
        p = f"{nc}/receipts/{pin['name']}"
        if not os.path.exists(p):
            v.append(f"{key}: {pin['name']} not on disk")
            continue
        if _sha(p) != pin["sha"]:
            v.append(f"{key}: sha drift {_sha(p)[:12]} != {pin['sha'][:12]}")
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            v.append(f"{key}: unreadable {e}")
            continue
        f = validate_receipt(d)
        if f:
            v.append(f"{key}: receipt_check FAIL {f}")
    for name in SUPPORT_RECEIPTS:
        p = f"{nc}/receipts/{name}"
        if not os.path.exists(p):
            v.append(f"support receipt {name} not on disk")
            continue
        d = json.load(open(p, encoding="utf-8"))
        f = validate_receipt(d)
        if f:
            v.append(f"support {name}: receipt_check FAIL {f}")
    return v


def build_receipt(ts):
    return {
        "ticket": "FP26-ROUND3-PREREG",
        "ts": ts,
        "round": ROUND,
        "prereg_frozen": True,
        "decision": DECISION,
        "wording_resolution": WORDING_RESOLUTION,
        "premises": {
            "decision_artifact": {"path": DECISION_ARTIFACT,
                                  "sha256": DECISION_SHA},
            **{k: {"receipt": p["name"], "sha256": p["sha"]}
               for k, p in PREMISE_RECEIPTS.items()},
            "support_receipts": SUPPORT_RECEIPTS,
        },
        "binds": {
            "v0_pretrain": "the round-3 training dispatch this prereg authorizes",
            "fp21b_132": "retargets to the owned core's FIRST sampling round",
            "fp20c_146": "retargets to the owned core's FIRST sampling round",
            "fp24_139": "fires on real v0 checkpoints (same launch)",
        },
        "result": {"verdict": "FROZEN", "shape": ROUND3_SHAPE},
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _selftest():
    import copy
    import tempfile
    # premises hold on the live tree
    v = check_premises()
    assert v == [], v
    # receipt is well-formed + receipt_check clean + prereg_frozen
    r = build_receipt("20260101T000000Z")
    assert r["prereg_frozen"] is True
    assert validate_receipt(r) == [], validate_receipt(r)
    assert r["result"]["shape"] == ROUND3_SHAPE
    # tamper guard: a drifted decision sha refuses
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/research")
        os.makedirs(f"{td}/receipts")
        # write a decision artifact with wrong content (sha won't match)
        open(f"{td}/{DECISION_ARTIFACT}", "w").write("tampered")
        for pin in PREMISE_RECEIPTS.values():
            json.dump({"ticket": "x", "ts": "x"},
                      open(f"{td}/receipts/{pin['name']}", "w"))
        for n in SUPPORT_RECEIPTS:
            json.dump({"ticket": "x", "ts": "x"},
                      open(f"{td}/receipts/{n}", "w"))
        tv = check_premises(nc=td)
        assert any("sha drift" in x or "sha" in x for x in tv), tv
    print("FP26_PREREG_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--freeze", action="store_true",
                    help="emit the frozen prereg receipt (refuses on pin drift)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.freeze:
        print("FP26_PREREG_STAGED (pass --freeze to emit; pins + decision "
              "+ wording resolution are frozen in this file)")
        return
    v = check_premises()
    if v:
        for x in v:
            print(f"PREMISE VIOLATION: {x}")
        raise SystemExit("fp26 prereg REFUSED — premise pins do not hold")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts)
    out = f"{NC}/receipts/fp26-prereg-{ts}.json"
    checked_write(out, receipt)
    # checked-write confirm: the emitted receipt itself passes receipt_check
    reloaded = json.load(open(out, encoding="utf-8"))
    f = validate_receipt(reloaded)
    if f:
        raise SystemExit(f"emitted fp26 prereg FAILS receipt_check: {f}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP26_PREREG_FROZEN {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
