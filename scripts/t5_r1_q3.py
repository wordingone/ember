import os
import runpy
import sys

# K3 harm suite for the 3B round-1 verdict (core_only vs core_meta on MBPP
# sanitized/test 50). Network ON for the one-time MBPP pull. Launches ONLY
# after the t4 q3 eval sequence (GPU-serial).
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

sys.argv = ["t5_harm.py", "--round", "1",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--tag-suffix=-q3", "--batch-size", "8"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t5_harm.py",
               run_name="__main__")
