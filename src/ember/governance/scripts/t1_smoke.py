import runpy
import sys

sys.argv = ["t1_probe.py", "--mode", "smoke", "--n-tasks", "30", "--k", "8",
            "--batch-size", "16"]
runpy.run_path("<local-path>",
               run_name="__main__")
