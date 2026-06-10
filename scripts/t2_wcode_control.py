import runpy
import sys

# W-code r1 CONTROL arm (G2): matched-budget train on control_pool mbpp:*
# fails, per-task counts mirrored against arm A's bits-weighted dataset.
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["t2_wcode.py", "--control"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/t2_wcode.py", run_name="__main__")
