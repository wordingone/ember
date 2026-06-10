import runpy
import sys

# Small-core round-1 four-arm heldout eval, seed 14, CHUNKED (post-crash
# redesign — resumable, early-stopping, governed). Launches ONLY on the
# t2-r1-q15-control receipt (GPU-serial). Resume = relaunch this wrapper.
sys.argv = ["t4_chunked.py", "--round", "1", "--surface", "arc1",
            "--seed", "14", "--n-tasks", "100", "--k", "8",
            "--chunk-size", "25", "--min-tasks-stop", "50",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "--tag-suffix=-q15"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t4_chunked.py",
               run_name="__main__")
