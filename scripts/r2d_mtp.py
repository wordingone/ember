import runpy
import sys

# Round-2 W MTP arm (r1 default-recipe winner) via the #112 wrapper ->
# t2_mtp (regenerates the W view itself, bits-caps). GPU-serial.
NC = "<local-path>"
sys.argv = ["t2_r2_mtp.py", "--the lead-gate-token", "r2-prereg-20260611-the lead"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/t2_r2_mtp.py", run_name="__main__")
