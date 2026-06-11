import runpy
import sys

# Round-2 W GRPO arm (verifier reward, theta=0.5 frontier window, stats
# from the round-2 w1 floor receipts) via the #112 wrapper. GPU-serial.
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["t2_r2_grpo.py", "--leo-gate-token", "r2-prereg-20260611-leo"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/t2_r2_grpo.py", run_name="__main__")
