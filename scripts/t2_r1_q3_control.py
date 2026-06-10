import runpy
import sys

# 3B fallback matched-budget control arm. Launches ONLY on the t2-r1-q3
# receipt (GPU-serial).
sys.argv = ["t2_round.py", "--round", "1", "--control",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--tag-suffix=-q3"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t2_round.py",
               run_name="__main__")
