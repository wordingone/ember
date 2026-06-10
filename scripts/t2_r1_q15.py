import runpy
import sys

# Round-1 RE-STAGE on the small core (post-crash redesign 2026-06-10):
# identical 1,909-episode ledger dataset (--train-only — episodes are
# task->program text, core-agnostic), adapter tag -q15 so the 7B artifacts
# (adapters/r1, r1-control) stay untouched. Weights cached by the
# 268db1d2 smoke; runs offline.
# NOTE: --tag-suffix=-q15 must be one token — argparse parses a separate
# "-q15" as an unknown flag (c2f5720e failed exactly there).
sys.argv = ["t2_round.py", "--round", "1", "--train-only",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "--tag-suffix=-q15"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t2_round.py",
               run_name="__main__")
