import runpy
import sys

# W-code round-1 FOCUSED TOP-UP at 3B (GPU-serial, governed): resample only
# the dead/frontier/mid tasks (prior rate <= 0.75 in the k=8 probe) at k=24,
# seed 15, with the calibration elicitation pass (eng #6). Easy tasks keep
# their 8 probe samples; GPU goes where the bits are (formalization S3b).
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w1_mbpp.py",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--split", "train", "--k", "24", "--batch-size", "8",
            "--temp", "0.8", "--seed", "15", "--tag", "q3-focus",
            "--calibrate",
            "--focus-from",
            f"{NC}/receipts/w1-floor-q3-20260610T203401Z-samples.jsonl",
            "--focus-max-rate", "0.75"]
runpy.run_path(f"{NC}/scripts/w1_mbpp.py", run_name="__main__")
