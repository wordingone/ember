import runpy
import sys

# Round-1 CONTROL arm: matched-budget SFT on confirmed-FAIL programs from
# receipts/ledger/control_pool.jsonl, per-task counts mirroring the verified dataset.
sys.argv = ["t2_round.py", "--round", "1", "--control"]
runpy.run_path("<local-path>",
               run_name="__main__")
