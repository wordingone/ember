import os
import runpy
import sys

# Small-core round-1 re-stage (post-crash redesign 2026-06-10): governed
# throughput smoke for Qwen2.5-Coder-1.5B-Instruct — receipts gens/h + peak
# VRAM under the resource governor (EMBER_VRAM_FRACTION cap + margin assert
# + decode_pacer) before committing the round-1 chain to this core.
#
# One-time base-weight ACQUISITION (~3.1GB): network explicitly ON for this
# run only — t1_probe os.environ.setdefault("HF_HUB_OFFLINE","1") respects a
# pre-set "0". Every later run re-engages offline (weights then cached).
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

sys.argv = ["t1_probe.py", "--mode", "smoke", "--n-tasks", "10", "--k", "4",
            "--batch-size", "8",
            "--model", "Qwen/Qwen2.5-Coder-1.5B-Instruct"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t1_probe.py",
               run_name="__main__")
