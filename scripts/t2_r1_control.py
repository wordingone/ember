import runpy
import sys

# Round-1 CONTROL arm: matched-budget SFT on confirmed-FAIL programs from
# ledger/control_pool.jsonl, per-task counts mirroring the verified dataset.
sys.argv = ["t2_round.py", "--round", "1", "--control"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t2_round.py",
               run_name="__main__")
