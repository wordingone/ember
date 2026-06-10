import runpy
import sys

# Replication seed for the small-core round-1 verdict (chunked, governed).
# Launches ONLY on the s14 receipt (GPU-serial).
sys.argv = ["t4_chunked.py", "--round", "1", "--surface", "arc1",
            "--seed", "15", "--n-tasks", "100", "--k", "8",
            "--chunk-size", "25", "--min-tasks-stop", "50",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "--tag-suffix=-q15"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t4_chunked.py",
               run_name="__main__")
