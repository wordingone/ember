import runpy
import sys

sys.argv = ["t4_eval.py", "--round", "1", "--seed", "14"]
runpy.run_path("<local-path>",
               run_name="__main__")
