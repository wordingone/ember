import runpy
import sys

# Round-2 W sft arm DRY-RUN preflight (CPU-only): regenerate views, theta
# filter, dataset build, receipt — no training. Gate token per prereg §3.
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["t2_r2w.py", "--leo-gate-token", "r2-prereg-20260611-leo",
            "--arm", "sft", "--dry-run"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/t2_r2w.py", run_name="__main__")
