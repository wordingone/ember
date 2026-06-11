import runpy
import sys

# Round-2 W matched-budget control arm (mirrors the sft arm's per-task
# counts; prereg §1.2). Launches ONLY on the sft receipt. GPU-serial.
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["t2_r2w.py", "--leo-gate-token", "r2-prereg-20260611-leo",
            "--arm", "control"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/t2_r2w.py", run_name="__main__")
