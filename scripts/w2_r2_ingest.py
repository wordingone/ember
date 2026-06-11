import runpy
import sys

# W-code r2 ingest (round-2 accumulation step, prereg §1.1): the q3-r2mtp
# k=8 ext-verified sampling pass (sampled WITH adapters/r1w-q3-mtp — the r1
# gains-winner; on-policy accumulation). Appends verified -> episodes.jsonl,
# fails-with-src -> control_pool.jsonl, stamps dedup sidecars (sidecar-only
# writes; main files byte-append-only). CPU-only, seconds.
NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.argv = ["w2_ingest.py", "--round", "2", "--samples",
            f"{NC}/receipts/w1-floor-q3-r2mtp-20260611T030332Z-samples.jsonl"]
sys.path.insert(0, f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/w2_ingest.py", run_name="__main__")
