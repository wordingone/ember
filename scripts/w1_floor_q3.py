import os
import runpy
import sys

# W-code world admission probe, 3B base (the active verdict core). Network
# ON for the one-time MBPP pull if q15 probe hasn't cached it. GPU-serial:
# launch only in an idle window.
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

sys.argv = ["w1_mbpp.py", "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--split", "train", "--k", "8", "--batch-size", "8",
            "--tag", "q3"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/w1_mbpp.py",
               run_name="__main__")
