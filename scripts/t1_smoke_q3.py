import os
import runpy
import sys

# 3B fallback chain (pre-registered: fires only if the q15 round-1 verdict
# is all-zeros / floor-unmeasurable). Governed throughput smoke + one-time
# base-weight acquisition (~6GB) — same shape as t1_smoke_q15.py.
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

sys.argv = ["t1_probe.py", "--mode", "smoke", "--n-tasks", "10", "--k", "4",
            "--batch-size", "8",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t1_probe.py",
               run_name="__main__")
