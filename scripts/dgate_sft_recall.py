import os
import runpy
import sys

# D-gate FIRST INSTANCE (persistence-gates addendum 2026-06-11): the
# Surface-A RECIPE-LEARNS claim — "+75.9pp recall gain is carried by the
# sft adapter FILE." Surface = the 28 trained tasks (fp25-recall view),
# k8 seed16 = the Surface-A receipt protocol, seed-matched legs.
# EMBER_GATE_AUTHORIZED set here BY THE GATED DISPATCH (Leo, after diff
# review + selftest): this shim IS the authorized launch path; the
# interlock continues to block ad-hoc invocations.
os.environ["EMBER_GATE_AUTHORIZED"] = "1"
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["d_gate.py", "--live",
            "--artifact", f"{NC}/adapters/r2-q3-sft/adapter_model.safetensors",
            "--split", "train",
            "--task-ids-file", f"{NC}/ledger/views/fp25-recall-task-ids.txt",
            "--n-tasks", "0", "--k", "8", "--seed", "16",
            "--surface", "fp25-recall-28-trained"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/d_gate.py", run_name="__main__")
