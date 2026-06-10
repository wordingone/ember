import runpy
import sys

# G1 eval, W-code r1, arm: a. Validation split (43 heldout, K3-clean),
# k=8 seed 16 (eval seed, distinct from train-sampling seeds 14/15); same
# seed across arms -> per-task paired deltas at gate time (power.py).
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w1_mbpp.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--split", "validation", "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "16", "--tag", "g1-a",
            "--adapter", "/mnt/b/M/avir/leo/state/nc-ladder/adapters/r1w-q3"]
runpy.run_path(f"{NC}/scripts/w1_mbpp.py", run_name="__main__")
