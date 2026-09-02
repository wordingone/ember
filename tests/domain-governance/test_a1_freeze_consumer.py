#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_a1_freeze_consumer.py -- ember #631 deliverable 5 negative+positive tests.

Reproduce-first for defect #5 ("no decisive consumer applies the freeze"): the FAIL
half is that before src/ember/governance/scripts/a1_freeze_consumer.py, no executable surface bound the
freeze pointer + amendment (an executable-search finds zero consumers). The PASS half
is this fail-closed consumer: it REFUSES on time-order violation, missing lineage, and
split-sha drift, and ADMITS the happy path with per-dataset effective_filtered_sha256
that visibly differs from the unfiltered content for contaminated datasets.

Run:  python tests/domain-governance/test_a1_freeze_consumer.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import glob

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _hash(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def resolve_eval_suite_dir():
    """Locate a sha-complete eval-suite-v1 copy: env override, else glob the repo's
    (gitignored) data/ dir for one whose seven splits match the frozen shas. Returns
    the path or None (the data-dependent positive test then SKIPs)."""
    env = os.environ.get("A1_EVAL_SUITE_DIR")
    freeze = json.load(open(os.path.join(REPO, "receipts/eval-suite-freeze/eval-suite-freeze-v1.json")))
    want = {d["name"]: d["test_split_sha256"] for d in freeze["datasets"]
            if d.get("test_split_sha256") not in (None, "PIN-PENDING")}
    dirmap = {"MMLU-Pro": "MMLU-Pro", "GSM8K": "GSM8K", "MATH-500": "MATH-500",
              "ARC-Challenge": "ARC-Challenge", "HumanEval+": "HumanEvalplus",
              "MBPP": "MBPP", "HellaSwag": "HellaSwag"}
    roots = [REPO, os.path.dirname(REPO)]
    try:
        gcd = subprocess.run(["git", "-C", REPO, "rev-parse", "--git-common-dir"],
                             capture_output=True, text=True, check=True).stdout.strip()
        main_tree = os.path.dirname(os.path.abspath(os.path.join(REPO, gcd)))
        roots.append(main_tree)  # main worktree holds the (gitignored) data/ dir
    except Exception:
        pass
    cands = [env] if env else []
    for base in roots:
        cands += sorted(glob.glob(os.path.join(base, "data", "eval-suite-v1*")))
    for c in cands:
        if not c or not os.path.isdir(c):
            continue
        ok = True
        for name, exp in want.items():
            p = os.path.join(c, dirmap[name], "test.jsonl")
            if not os.path.exists(p) or _hash(p) != exp:
                ok = False
                break
        if ok:
            return c
    return None


SCAN_DIR = resolve_eval_suite_dir()

DECL = "receipts/eval-suite-freeze/a1-freeze-declaration-20260709T233050Z.json"
POINTER = "receipts/eval-suite-freeze/EVAL-FREEZE-HASH"
AMEND = "receipts/eval-suite-freeze/a1-freeze-exclusion-amendment-20260709T234148Z.json"
FREEZE = "receipts/eval-suite-freeze/eval-suite-freeze-v1.json"
LINEAGE = "tests/fixtures/domain-governance/a1-lineage-manifest-example.json"


def run(extra, out):
    # negatives 1-3 refuse before the split check, so a placeholder dir is fine there
    suite = SCAN_DIR or os.path.join(REPO, "data", "_no_eval_suite_")
    cmd = [sys.executable, os.path.join(REPO, "scripts", "a1_freeze_consumer.py"),
           "--declaration", DECL, "--pointer-file", POINTER, "--amendment", AMEND,
           "--freeze-receipt", FREEZE, "--eval-suite-dir", suite,
           "--build-ref", "HEAD", "--out", out]
    cmd += extra
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="a1_consumer_test_")
    out = os.path.join(tmp, "admission.json")
    failures = []

    # 1. NEGATIVE: launch_ts BEFORE freeze_ts -> REFUSE[TIME_ORDER]
    r = run(["--launch-ts", "2026-07-01T00:00:00Z", "--lineage-manifest", LINEAGE], out)
    if r.returncode == 0 or "TIME_ORDER" not in (r.stderr + r.stdout):
        failures.append(f"time-order not refused: rc={r.returncode} {r.stderr.strip()[:120]}")
    else:
        print("PASS negative time-order:", r.stderr.strip().splitlines()[-1][:90])

    # 2. NEGATIVE: missing lineage manifest -> REFUSE[LINEAGE_MISSING]
    r = run(["--launch-ts", "2026-07-10T06:00:00Z",
             "--lineage-manifest", os.path.join(tmp, "nope.json")], out)
    if r.returncode == 0 or "LINEAGE_MISSING" not in (r.stderr + r.stdout):
        failures.append(f"missing-lineage not refused: rc={r.returncode}")
    else:
        print("PASS negative missing-lineage:", r.stderr.strip().splitlines()[-1][:90])

    # 3. NEGATIVE: lineage with an UNSCANNED input -> REFUSE[LINEAGE_UNSCANNED]
    bad_lin = os.path.join(tmp, "bad_lineage.json")
    json.dump({"checkpoint_lineage": "x", "training_inputs":
               [{"corpus": "mystery-corpus", "scanned": False}]}, open(bad_lin, "w"))
    r = run(["--launch-ts", "2026-07-10T06:00:00Z", "--lineage-manifest", bad_lin], out)
    if r.returncode == 0 or "LINEAGE_UNSCANNED" not in (r.stderr + r.stdout):
        failures.append(f"unscanned-lineage not refused: rc={r.returncode}")
    else:
        print("PASS negative unscanned-lineage:", r.stderr.strip().splitlines()[-1][:90])

    # 4. NEGATIVE: split sha drift -> REFUSE[SPLIT_SHA_DRIFT] (tampered eval-suite dir)
    tdir = os.path.join(tmp, "suite")
    os.makedirs(os.path.join(tdir, "MMLU-Pro"))
    with open(os.path.join(tdir, "MMLU-Pro", "test.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"tampered": true}\n')
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "a1_freeze_consumer.py"),
         "--declaration", DECL, "--pointer-file", POINTER, "--amendment", AMEND,
         "--freeze-receipt", FREEZE, "--eval-suite-dir", tdir, "--build-ref", "HEAD",
         "--launch-ts", "2026-07-10T06:00:00Z", "--lineage-manifest", LINEAGE, "--out", out],
        cwd=REPO, capture_output=True, text=True)
    if r.returncode == 0 or "SPLIT_SHA_DRIFT" not in (r.stderr + r.stdout):
        failures.append(f"split-drift not refused: rc={r.returncode}")
    else:
        print("PASS negative split-drift:", r.stderr.strip().splitlines()[-1][:90])

    # 5. POSITIVE: happy path -> ADMITTED, effective hashes differ from unfiltered
    if SCAN_DIR is None:
        print("SKIP positive admit: no sha-verified eval-suite-v1 dir found "
              "(set A1_EVAL_SUITE_DIR); negatives 1-4 cover the fail-closed paths")
        r = None
    else:
        r = run(["--launch-ts", "2026-07-10T06:00:00Z", "--lineage-manifest", LINEAGE], out)
    if r is None:
        pass
    elif r.returncode != 0:
        failures.append(f"happy path refused: rc={r.returncode} {r.stderr.strip()[:160]}")
    else:
        rec = json.load(open(out))
        if rec["verdict"] != "ADMITTED":
            failures.append("happy path not ADMITTED")
        pd = rec["effective_filtered_suite"]["per_dataset"]
        # contaminated datasets must show filtering changes content
        for ds in ("MMLU-Pro", "HumanEval+", "MBPP", "HellaSwag"):
            if not pd[ds]["filtering_changes_content"]:
                failures.append(f"{ds}: filtering did not change content (unfiltered==filtered)")
        # clean datasets: no exclusions
        for ds in ("GSM8K", "MATH-500", "ARC-Challenge"):
            if pd[ds]["n_excluded"] != 0:
                failures.append(f"{ds}: unexpected exclusions")
        if rec["effective_filtered_suite"]["n_excluded_total"] != 147:
            failures.append("total excluded != 147")
        print("PASS positive admit: excluded_total=147, contaminated datasets filtered, "
              f"pointer_ancestor={rec['freeze_binding']['pointer_is_ancestor_of_build_ref']}")

    for fn in os.listdir(tmp):
        try:
            os.remove(os.path.join(tmp, fn))
        except OSError:
            pass

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nA1_FREEZE_CONSUMER_TESTS_PASS (4 negative + 1 positive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
