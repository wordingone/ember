"""One-off orchestration for #175 governed small-footprint retry.

Does NOT modify fp35_fused_muon_kernel_ab.py (harness_sha stays identical to the
frozen spec). Monkeypatches module globals to a smaller shape before calling main(),
then enriches the resulting receipt with the binding telemetry schema (nvidia-smi
sample path, bench start/end UTC, reproduce-stderr path).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fp35_fused_muon_kernel_ab as m  # noqa: E402

# Small-footprint override (see preregistration.md) — frozen file untouched
m.HIDDEN = 512
m.LAYERS = 4
m.FFN = 2048
m.SEQ = 512
# BATCH, HEADS, VOCAB, SEEDS, WARMUP_REPS, BENCH_REPS, VRAM_FRACTION, MARGIN_GIB,
# PACE_S all left at frozen defaults.

NC = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts", "muon-ab-retry-20260705")
REPRODUCE_LOG = os.path.join(RECEIPTS, "reproduce-20260705T232815Z.log")
SAMPLE_FILE = os.path.join(RECEIPTS, "nvidia-smi-samples.csv")

bench_start_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"RETRY_BENCH_START_UTC {bench_start_utc}", flush=True)

receipt = m.main()

bench_end_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"RETRY_BENCH_END_UTC {bench_end_utc}", flush=True)

enriched = {
    "ticket": "MUON_FUSED_AB_SMALLFOOT_RETRY",
    "parent_issue_repo": "wordingone/ember",
    "parent_issue": 175,
    "retry_ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    "shape_override": {
        "hidden": m.HIDDEN, "layers": m.LAYERS, "ffn": m.FFN, "seq": m.SEQ,
        "batch": m.BATCH, "heads": m.HEADS, "vocab": m.VOCAB,
        "note": "small-footprint per #175 item 3 (VRAM did not fit c03 scale this window)",
    },
    "underlying_receipt": receipt,
    "telemetry": {
        "nvidia_smi_sample_path": SAMPLE_FILE,
        "bench_start_utc": bench_start_utc,
        "bench_end_utc": bench_end_utc,
        "reproduce_stderr_path": REPRODUCE_LOG,
        "preregistration_path": os.path.join(RECEIPTS, "preregistration.md"),
    },
}

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
out_path = os.path.join(RECEIPTS, f"muon-ab-smallfoot-retry-{ts}.json")
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(enriched, f, indent=2)
print(f"SMALLFOOT_RETRY_ENRICHED_RECEIPT {out_path}", flush=True)
