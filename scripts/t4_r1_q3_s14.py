import runpy
import sys

# 3B fallback four-arm heldout eval, seed 14, CHUNKED (governed, resumable,
# early-stopping). Launches ONLY on the t2-r1-q3-control receipt.
sys.argv = ["t4_chunked.py", "--round", "1", "--surface", "arc1",
            "--seed", "14", "--n-tasks", "100", "--k", "8",
            "--chunk-size", "25", "--min-tasks-stop", "50",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--tag-suffix=-q3"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t4_chunked.py",
               run_name="__main__")
