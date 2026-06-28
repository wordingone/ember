import runpy
import sys

sys.argv = ["t4_eval.py", "--round", "1", "--seed", "14", "--surface", "arc2",
            "--n-tasks", "120"]
runpy.run_path("<local-path>",
               run_name="__main__")
