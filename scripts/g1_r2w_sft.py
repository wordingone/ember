import runpy
import sys

# G1 eval, W-code r2, arm: sft. Validation split (43 heldout), k=8
# seed 16 (same eval seed as r1 G1 -> paired deltas + cross-round
# comparability; strict-verify stack now in-path by default, eng-24).
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w1_mbpp.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--split", "validation", "--k", "8", "--batch-size", "8",
            "--temp", "0.8", "--seed", "16", "--tag", "g1r2-sft",
            "--adapter", "/mnt/b/M/avir/leo/state/nc-ladder/adapters/r2-q3-sft"]
runpy.run_path(f"{NC}/scripts/w1_mbpp.py", run_name="__main__")
