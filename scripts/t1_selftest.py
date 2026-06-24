import runpy
import sys

sys.argv = ["t1_probe.py", "--mode", "selftest"]
runpy.run_path("<local-path>",
               run_name="__main__")
