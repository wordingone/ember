"""DT1 daemon runner — invoked by train daemon (no CLI args supported).

Sets EMBER_GATE_AUTHORIZED and runs the DT1 GPU benchmark with pre-registered params.
product_path = <local-path>; cwd = <local-path> (daemon-set).
"""
import os
import sys
import argparse

os.environ["EMBER_GATE_AUTHORIZED"] = "1"

import train_delta_rule_dt1 as dt1

args = argparse.Namespace(
    run=True,
    selftest=False,
    model_size="15M",
    wall_clock_s=120,
    seeds=2,
    seq_len=512,
    batch_size=4,
    lr=1e-3,
)

result = dt1._run_benchmark(args)
dt1._write_receipt(result, args)
overall = result["overall"]
print(f"DT1_DIAGNOSTIC_DONE overall={overall}", flush=True)
