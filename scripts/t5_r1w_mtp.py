import os
import runpy
import sys

# t5 harm gate on the W-code r1 MTP adapter (decision-tree binding: any arm
# advancing to round-2 must show t5 non-regression vs base on MBPP-50 test).
# G1 paired receipt g1-paired-r1w-20260610T222435Z: MTP is the only arm UP
# vs base AND vs matched control on the gains metric — the round-2 candidate.
# adapter dir resolves to adapters/r1w-q3-mtp (r{round}{suffix}).
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

sys.argv = ["t5_harm.py", "--round", "1",
            "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
            "--tag-suffix=w-q3-mtp", "--batch-size", "8"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t5_harm.py",
               run_name="__main__")
