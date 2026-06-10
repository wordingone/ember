import runpy
import sys

# ember-r1: train from the existing 1,909-episode seed ledger (t3-seed-v2),
# no acquisition pass. Headroom throttle active (EMBER_THROTTLE_S).
sys.argv = ["t2_round.py", "--round", "1", "--train-only"]
runpy.run_path("/mnt/b/M/avir/leo/state/nc-ladder/scripts/t2_round.py",
               run_name="__main__")
