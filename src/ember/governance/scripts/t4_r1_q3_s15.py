import runpy
import sys

# 3B fallback replication seed (chunked, governed). Launches ONLY on a
# NONZERO q3 s14 receipt (GPU-serial) — replication before transfer.
sys.argv = ["t4_chunked.py", "--round", "1", "--surface", "arc1",
            "--seed", "15", "--n-tasks", "100", "--k", "8",
            "--chunk-size", "25", "--min-tasks-stop", "50",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--tag-suffix=-q3"]
runpy.run_path("<local-path>",
               run_name="__main__")
