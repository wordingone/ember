"""w2_r2_sample.py — round-2 W-code sampling dispatch wrapper.

Pinned to research/round2-prereg.md §1.1 verbatim (pre-launch amendment
a-commit): q3 + r1w-q3-mtp adapter, train split, k=8, ext-verify,
calibrate, seed 18, tag q3-r2mtp. Daemon-wrapper shape (runpy + argv
injection), same as the t4_r1_* / g1_r1w_* precedents.

This is the ACCUMULATION step: sampling with the round-1 gains-winner.
Verified rows are harvestable by w2_ingest (which appends the ledger +
the eng-25 sidecar stamps); this wrapper itself writes ONLY the w1
receipt + sample file — the ledger is untouched until the gated ingest.
"""
import runpy
import sys
import os

NC = "/mnt/b/M/avir/leo/state/nc-ladder"

sys.argv = [
    "w1_mbpp.py",
    "--model", "Qwen/Qwen2.5-Coder-3B-Instruct",
    "--adapter", f"{NC}/adapters/r1w-q3-mtp",
    "--split", "train",
    "--k", "8",
    "--ext-verify",
    "--calibrate",
    "--seed", "18",
    "--tag", "q3-r2mtp",
]
os.chdir(f"{NC}/scripts")
runpy.run_path(f"{NC}/scripts/w1_mbpp.py", run_name="__main__")
