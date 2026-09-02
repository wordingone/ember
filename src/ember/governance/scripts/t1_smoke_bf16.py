import runpy
import sys

sys.argv = ["t1_probe.py", "--mode", "smoke", "--n-tasks", "30", "--k", "8",
            "--batch-size", "16",
            "--model", "unsloth/Qwen2.5-Coder-7B-Instruct"]
runpy.run_path("<local-path>",
               run_name="__main__")
