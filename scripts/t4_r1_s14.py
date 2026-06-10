import runpy
import sys

sys.argv = ["t4_eval.py", "--round", "1", "--seed", "14"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t4_eval.py",
               run_name="__main__")
