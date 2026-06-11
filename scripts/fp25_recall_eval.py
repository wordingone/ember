import runpy
import sys

# FP-25 Surface A "train-task recall" eval: the 5 certified round-2 arms
# (base/sft/mtp/grpo/control) on the EXACT 28 MBPP-train tasks they
# trained on (parsed from wcode-r2-sft.jsonl).
# Seed 16 = the r1 G1 eval seed (cross-round comparability).
# Dispatch ONLY after dry-run proves --task-ids-file filter works.

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w4_eval.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--arm", "base=",
            "--arm", f"sft={NC}/adapters/r2-q3-sft",
            "--arm", f"mtp={NC}/adapters/r2-q3-mtp",
            "--arm", f"grpo={NC}/adapters/r2-q3-grpo",
            "--arm", f"control={NC}/adapters/r2-q3-control",
            "--split", "train",
            "--task-ids-file", f"{NC}/ledger/views/fp25-recall-task-ids.txt",
            "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "16", "--tag", "fp25-recall"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/w4_eval.py", run_name="__main__")
