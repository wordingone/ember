import runpy
import sys

# G1 eval, W-code r1, arm: grpo. Validation split (43 heldout, K3-clean),
# k=8 seed 16 (eval seed, distinct from train-sampling seeds 14/15); same
# seed across arms -> per-task paired deltas at gate time (power.py).
NC = "<local-path>"
sys.argv = ["w1_mbpp.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--split", "validation", "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "16", "--tag", "g1-grpo",
            "--adapter", "<local-path>"]
runpy.run_path(f"{NC}/src/ember/governance/scripts/w1_mbpp.py", run_name="__main__")
