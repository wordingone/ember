import runpy
import sys

sys.argv = ["t1_probe.py", "--mode", "selftest"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t1_probe.py",
               run_name="__main__")
