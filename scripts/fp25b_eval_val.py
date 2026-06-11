import runpy
import sys

# fp-25 Surface-B BINDING eval, leg 2 of 2 (amendment 2): the 5 certified
# round-2 arms on the 10 validation-frontier tasks selected by
# fp25b_surfaceb.py select mode (fp25b-select-20260611T062523Z.json).
# Validation was never trained on -> union-disjoint by construction.
# Seed 23 = B_EVAL_SEED (fresh draws for all arms; see fp25b_eval_train.py).
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w4_eval.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--arm", "base=",
            "--arm", f"sft={NC}/adapters/r2-q3-sft",
            "--arm", f"mtp={NC}/adapters/r2-q3-mtp",
            "--arm", f"grpo={NC}/adapters/r2-q3-grpo",
            "--arm", f"control={NC}/adapters/r2-q3-control",
            "--split", "validation",
            "--task-ids-file", f"{NC}/ledger/views/fp25b-heldout-val-ids.txt",
            "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "23", "--tag", "fp25b-val"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/w4_eval.py", run_name="__main__")
