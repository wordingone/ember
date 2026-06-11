import runpy
import sys

# Round-2 W sft arm (prereg §1.2, corrected data path via t2_r2w).
# Launches ONLY after the dry-run receipt gates. GPU-serial.
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["t2_r2w.py", "--leo-gate-token", "r2-prereg-20260611-leo",
            "--arm", "sft"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/t2_r2w.py", run_name="__main__")
