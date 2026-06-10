import runpy
import sys

# Matched-budget control arm for the small-core round-1 re-stage:
# same control_pool, same example counts per task as the -q15 core arm.
# Launches ONLY on the t2-r1-q15 receipt (GPU-serial).
sys.argv = ["t2_round.py", "--round", "1", "--control",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "--tag-suffix=-q15"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t2_round.py",
               run_name="__main__")
