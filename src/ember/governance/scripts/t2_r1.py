import glob
import runpy
import sys

# Round 1: ingest the newest t1-full harvest, then train ember-r1 from the
# FULL ledger (1,909 seed episodes + harvest). Fails loudly if no t1-full
# samples exist yet — launch order is gated on the t1-full receipt.
samples = sorted(glob.glob(
    "<local-path>"))[-1]
sys.argv = ["t2_round.py", "--round", "1", "--from-samples", samples]
runpy.run_path("<local-path>",
               run_name="__main__")
