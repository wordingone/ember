"""t2_grpo_tasklist_selftest.py — eng #142 task-list plumb wiring receipt.

Kai's live r2 audit (mails 14512/14511): t2_r2_grpo computed and receipted
a theta/frontier filter, but t2_grpo never consumed it — build_prompt_rows
took every MBPP train problem, so the filter was informational, not
load-bearing. The fix routes the wrapper's selected task-key list through
--task-list and makes the terminal receipt honest (round / gate presence /
wrapper linkage / selection block with hash / verbatim basis). Pool
semantics are PINNED (prereg §5, mail 14514): theta (0,0.5] live-frontier
strictly, no dead/ledger-absent tasks in round-2.

Checks (pure logic + source-wiring asserts; no GPU, no torch):
  1. select_problems restricts the pool and accounts missing keys;
     load_task_list refuses empty/non-list files (t2_grpo._selftest also
     covers these — duplicated here so this receipt stands alone);
  2. t2_grpo source: new argparse surface present; selection applied
     BEFORE problems_by_id / build_prompt_rows; fail-closed on empty
     selection; receipt carries round / gate_token_present /
     wrapper_receipt / selection_basis / task_selection and no hardcoded
     round literal;
  3. t2_r2_grpo source (text-only — importing it trips the gate-token
     interlock): writes the selected key list, hashes it, records the
     prereg-§5 pin in the basis, and delegates with --task-list/--round/
     --wrapper-receipt/--gate-token-present/--selection-basis.

Writes receipts/eng142-tasklist-selftest-<ts>.json. Sentinel:
T2_GRPO_TASKLIST_SELFTEST_PASS.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def main():
    checks = {}
    import t2_grpo as tg

    # 1. selection logic
    probs = [{"id": 11}, {"id": 12}, {"id": 13}]
    sel, missing = tg.select_problems(probs, ["mbpp:12", "mbpp:404"])
    assert [p["id"] for p in sel] == [12] and missing == ["mbpp:404"]
    with tempfile.TemporaryDirectory() as td:
        tl = os.path.join(td, "tasks.json")
        with open(tl, "w", encoding="utf-8") as f:
            json.dump(["mbpp:11", "mbpp:13"], f)
        assert tg.load_task_list(tl) == ["mbpp:11", "mbpp:13"]
        nonlist = os.path.join(td, "bad.json")
        with open(nonlist, "w", encoding="utf-8") as f:
            json.dump({"not": "a list"}, f)
        try:
            tg.load_task_list(nonlist)
            raise AssertionError("non-list task file must refuse")
        except SystemExit:
            pass
    checks["selection_logic"] = True

    # 2. t2_grpo source wiring
    src = open(os.path.join(HERE, "t2_grpo.py"), encoding="utf-8").read()
    for flag in ("--task-list", "--round", "--wrapper-receipt",
                 "--gate-token-present", "--selection-basis"):
        assert f'"{flag}"' in src, f"argparse missing {flag}"
    main_src = src.split("def main():")[1].split("def _selftest():")[0]
    sel_pos = main_src.index("select_problems(")
    byid_pos = main_src.index("problems_by_id = {")
    rows_pos = main_src.index("build_prompt_rows(problems, stats)")
    assert sel_pos < byid_pos < rows_pos, \
        "selection must precede the reward map and prompt rows"
    assert "selected 0 problems" in main_src, "empty-selection fail-closed"
    for field in ('"round": args.round',
                  '"gate_token_present": args.gate_token_present',
                  '"wrapper_receipt": args.wrapper_receipt',
                  '"selection_basis": args.selection_basis',
                  '"task_selection": task_selection'):
        assert field in main_src, f"receipt field wiring missing: {field}"
    assert '"round": 1,' not in main_src, "hardcoded round literal must go"
    checks["t2_grpo_wiring"] = True

    # 3. wrapper source (text-only)
    wsrc = open(os.path.join(HERE, "t2_r2_grpo.py"), encoding="utf-8").read()
    for piece in ('"--task-list", task_list_path',
                  '"--round", "2"',
                  '"--wrapper-receipt", receipt_path',
                  '"--gate-token-present"',
                  '"--selection-basis", selection_basis',
                  "grpo-r2-tasks.json",
                  "task_list_sha256",
                  "live-frontier strictly"):
        assert piece in wsrc, f"wrapper wiring missing: {piece}"
    checks["wrapper_wiring"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG142-TASKLIST-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#142",
        "checks": checks,
        "sha_convention": ("sha256 over on-disk raw bytes "
                           "(binary read, no line-ending normalization) — "
                           "the convention the task-list hash is pinned "
                           "against"),
        "default_path_unchanged": ("no --task-list = legacy full-pool "
                                   "behavior (every MBPP train problem, "
                                   "stratum repetition only)"),
        "pool_pin": ("prereg §5 (mail 14514): theta (0,0.5] live-frontier "
                     "strictly; dead-task GRPO = named round-3 candidate"),
        "quarantine_note": ("adapter r2-q3-grpo stays PRE-GATE/QUARANTINED "
                            "until rerun on the load-bearing selection — "
                            "dispatch is the gate-holder's call"),
    }
    out = os.path.join(REPO, "receipts", f"eng142-tasklist-selftest-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("T2_GRPO_TASKLIST_SELFTEST_PASS")


if __name__ == "__main__":
    main()
