import runpy
import sys

# W-code r1 ingest (eng #5 live run): pool the q3 k=8 floor probe + the k=24
# calibrated focused top-up (both sampled by the 3B core itself — on-policy),
# annotate phat/bits/stratum from the pooled posterior, append verified ->
# ledger/episodes.jsonl + fails -> control_pool.jsonl. CPU-only, seconds.
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w2_ingest.py", "--round", "1", "--samples",
            f"{NC}/receipts/w1-floor-q3-20260610T203401Z-samples.jsonl",
            f"{NC}/receipts/w1-floor-q3-focus-20260610T210228Z-samples.jsonl"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/w2_ingest.py", run_name="__main__")
