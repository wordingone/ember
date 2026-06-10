import runpy
import sys

# Contamination probe targeting the ACTIVE round-1 core (1.5B re-stage,
# post-crash redesign): raw-prefix continuation membership + ID-recall on
# the base the q15 verdict serves from. Governed via t1_probe.load_model.
# GPU-serial: fire in a round-1 eval idle window, never beside a live job.
sys.argv = ["t1c_contamination.py",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t1c_contamination.py",
               run_name="__main__")
