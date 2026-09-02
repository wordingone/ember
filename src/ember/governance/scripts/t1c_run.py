import runpy
import sys

# t1c: contamination probe, defaults (50 continuation tasks x 3 arms +
# 20 id-recall). GPU-serial: fire in the round-1 eval window.
sys.argv = ["t1c_contamination.py"]
runpy.run_path(
    "<local-path>",
    run_name="__main__")
