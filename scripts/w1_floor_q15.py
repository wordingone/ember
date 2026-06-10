import os
import runpy
import sys

# W-code world admission probe, 1.5B base (smallest-core-first): measured
# floor F on MBPP sanitized/train, k=8. Network ON for the one-time MBPP
# pull (dataset not yet cached; t5 never ran). GPU-serial: launch only in
# an idle window (never beside a live eval/train).
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

sys.argv = ["w1_mbpp.py", "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "--split", "train", "--k", "8", "--batch-size", "8",
            "--tag", "q15"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/w1_mbpp.py",
               run_name="__main__")
