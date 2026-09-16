#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1945: exact-semantics A/B for document-reduced weight gradients.

Frozen question:
Can the current four per-document BF16 dW matmuls plus three ordered BF16 adds
be replaced by one grouped Triton launch while preserving the measured
descending reduction semantics and producing a factor-sized device-time win?

This is a component microbenchmark only. It grants no throughput, learning,
Evaluation, hour, or #1945 terminal credit.

Retention criterion, frozen before execution:
  * every tested candidate gradient is bitwise equal to the current reference
  * median speedup across tested attention sites is >= 1.50x
"""
import argparse
import hashlib
import io
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

_SIBLING = os.path.dirname(os.path.abspath(__file__))
if _SIBLING not in sys.path:
    sys.path.insert(0, _SIBLING)

import grouped_launcher_geometry_arm as arm

SCHEMA = "ember-1945-document-dw-grouped-ab-v1"
OPERAND_SHA256 = "e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76"
ORDER = "descending"
FACTOR_BAR = 1.50
ROUNDS = 24
CALLS = 16
WARM = 3


def stats(xs):
    ys = sorted(xs)
    return {
        "n": len(ys),
        "median": statistics.median(ys),
        "min": ys[0],
        "max": ys[-1],
        "mean": statistics.fmean(ys),
    }


def time_calls(torch, fn, calls):
    for _ in range(WARM):
        fn()
    torch.cuda.synchronize()
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    for _ in range(calls):
        fn()
    end.record()
    torch.cuda.synchronize()
    return start.elapsed_time(end) * 1000.0 / calls


def run(args):
    import torch
    import triton

    sys.path.insert(0, os.path.join(args.root, "src"))
    from ember.model import ember_v0_grouped_capture as grouped

    cap = arm.check_device(
        torch.cuda.is_available(),
        torch.cuda.device_count(),
        torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None,
    )

    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    operand_sha = arm.pin_operand(args.operands, OPERAND_SHA256)
    kernel_path = os.path.join(args.root, arm.KERNEL_REL).replace("\\", "/")
    kernel_sha, _ = arm.read_kernel_source(kernel_path)

    data = torch.load(args.operands, map_location="cpu", weights_only=True)
    attention = data["attention"]

    site_receipts = {}
    all_exact = True
    speedups = []

    for site_name in sorted(attention):
        record = attention[site_name]
        chunks = record["chunks"]
        if len(chunks) != 4:
            raise RuntimeError("%s has %d chunks, expected 4" % (site_name, len(chunks)))

        cuda_chunks = [
            {
                "input": c["input"].cuda().contiguous(),
                "upstream": c["upstream"].cuda().contiguous(),
            }
            for c in chunks
        ]
        actual = record["actual_gradient"].cuda()

        # Current production/reference semantics:
        # document 4, then 3, then 2, then 1; each partial and add remains BF16.
        def reference():
            total = None
            for c in reversed(cuda_chunks):
                partial = c["upstream"].transpose(0, 1) @ c["input"]
                total = partial if total is None else total + partial
            return total

        ref_once = reference()
        if not torch.equal(ref_once, actual):
            diff = (ref_once.float() - actual.float())
            raise RuntimeError(
                "%s current descending reference no longer matches saved actual gradient: "
                "%d unequal, rel_l2=%g"
                % (
                    site_name,
                    int(torch.count_nonzero(diff)),
                    float(diff.norm()) / max(float(actual.float().norm()), 1e-30),
                )
            )

        # Candidate sees the documents physically concatenated in the measured descending
        # order. _weights then walks four 1024-row chunks in increasing memory order.
        # That is logically document 4 -> 3 -> 2 -> 1.
        rev = list(reversed(cuda_chunks))
        dy = torch.cat([c["upstream"] for c in rev], dim=0).contiguous()
        x = torch.cat([c["input"] for c in rev], dim=0).contiguous()

        m = dy.shape[0]
        k = dy.shape[1]   # output features; first dY^T dimension
        n = x.shape[1]    # input features
        if m != 4096:
            raise RuntimeError("%s has %d rows, expected 4096" % (site_name, m))

        offsets = torch.tensor([m], device="cuda", dtype=torch.int32)
        ends = torch.tensor(
            [[1024, 2048, 3072, 4096]], device="cuda", dtype=torch.int32
        ).contiguous()
        out = torch.empty((1, k, n), device="cuda", dtype=torch.bfloat16)

        def candidate():
            grouped._weights[
                (triton.cdiv(k, arm.BM), triton.cdiv(n, arm.BN), 1)
            ](
                dy,
                x,
                offsets,
                out,
                ends,
                k,
                n,
                *dy.stride(),
                *x.stride(),
                BM=arm.BM,
                BN=arm.BN,
                BK=arm.BK,
                NC=4,
                num_warps=arm.NUM_WARPS,
            )
            return out[0]

        cand_once = candidate()
        torch.cuda.synchronize()

        exact = bool(torch.equal(cand_once, ref_once))
        delta = cand_once.float() - ref_once.float()
        rel_l2 = float(delta.norm()) / max(float(ref_once.float().norm()), 1e-30)
        unequal = int(torch.count_nonzero(delta))
        all_exact = all_exact and exact

        samples = {"reference": [], "candidate": []}
        for r in range(args.rounds):
            order = ("reference", "candidate") if r % 2 == 0 else ("candidate", "reference")
            for label in order:
                fn = reference if label == "reference" else candidate
                samples[label].append(time_calls(torch, fn, args.calls))

        measured = {name: stats(vals) for name, vals in samples.items()}
        ref_med = measured["reference"]["median"]
        cand_med = measured["candidate"]["median"]
        speedup = ref_med / cand_med
        speedups.append(speedup)

        site_receipts[site_name] = {
            "geometry": {
                "rows": m,
                "dY_features": k,
                "input_features": n,
                "documents": [1024, 1024, 1024, 1024],
                "order": ORDER,
                "dtype": "bfloat16",
            },
            "numerical": {
                "bitwise_equal": exact,
                "unequal_elements": unequal,
                "relative_l2": rel_l2,
            },
            "per_call_us": measured,
            "speedup": speedup,
            "raw_per_round_us": samples,
        }

        del cuda_chunks, actual, ref_once, rev, dy, x, offsets, ends, out, cand_once
        torch.cuda.empty_cache()

    median_speedup = statistics.median(speedups)
    retained = bool(all_exact and median_speedup >= FACTOR_BAR)

    try:
        source_commit = subprocess.check_output(
            ["git", "-C", args.root, "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        source_commit = None

    return {
        "schema": SCHEMA,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hypothesis": (
            "one grouped BF16 dW kernel can preserve the measured four-document "
            "descending reduction semantics while replacing 4 matmul launches + "
            "3 add launches with a factor-sized device-time reduction"
        ),
        "frozen_retention_criterion": {
            "all_sites_bitwise_equal": True,
            "median_speedup_gte": FACTOR_BAR,
        },
        "claim_boundary": (
            "saved-operand component A/B only; zero applied positions, zero optimizer "
            "updates, no governed-step/hour/learning/Evaluation/#1945 terminal credit"
        ),
        "applied_positions": 0,
        "optimizer_updates": 0,
        "all_sites_bitwise_equal": all_exact,
        "median_speedup": median_speedup,
        "factor_candidate_retained": retained,
        "sites": site_receipts,
        "protocol": {
            "rounds": args.rounds,
            "calls_per_round": args.calls,
            "warmup_calls": WARM,
            "arm_order": "alternating by round",
            "timer": "CUDA event pair around repeated calls",
        },
        "binding": {
            "source_commit": source_commit,
            "operands": args.operands,
            "operand_sha256": operand_sha,
            "grouped_kernel": kernel_path,
            "grouped_kernel_sha256": kernel_sha,
            "torch": torch.__version__,
            "triton": triton.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(0),
            "capability": list(cap),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[4]))
    ap.add_argument("--operands", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument("--calls", type=int, default=CALLS)
    args = ap.parse_args()

    receipt = run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")

    print("all bitwise equal:", receipt["all_sites_bitwise_equal"])
    print("median speedup:    %.4fx" % receipt["median_speedup"])
    print("factor retained:   ", receipt["factor_candidate_retained"])
    for name, row in receipt["sites"].items():
        print(
            "%-42s exact=%-5s ref=%8.3fus cand=%8.3fus speedup=%6.3fx"
            % (
                name,
                row["numerical"]["bitwise_equal"],
                row["per_call_us"]["reference"]["median"],
                row["per_call_us"]["candidate"]["median"],
                row["speedup"],
            )
        )
    print("receipt:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
