#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1945 shared SwiGLU document-dW grouped A/B.

Tests 12 production document-reduced weight gradients:
4 shared layers x {up, gate, down}.

Reference:
four per-document BF16 dW matmuls + three descending BF16 adds.

Candidate:
one grouped Triton _weights launch with four explicit BF16
partial/accumulation boundaries.

Component experiment only. No training/throughput/hour credit.
"""
import argparse
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

SCHEMA = "ember-1945-shared-document-dw-grouped-ab-v1"
OPERAND_SHA256 = "e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76"
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
    s = torch.cuda.Event(enable_timing=True)
    e = torch.cuda.Event(enable_timing=True)
    s.record()
    for _ in range(calls):
        fn()
    e.record()
    torch.cuda.synchronize()
    return s.elapsed_time(e) * 1000.0 / calls


def run(args):
    import torch
    import torch.nn.functional as F
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

    results = {}
    exact_all = True
    speedups = []

    for layer_name in sorted(data["shared"]):
        record = data["shared"][layer_name]
        up_w, gate_w, down_w = [w.cuda() for w in record["weights"]]

        # Reconstruct projection-specific backward operands per document.
        docs = []
        for c in record["chunks"]:
            x = c["input"].cuda().contiguous()
            dy_out = c["upstream"].cuda().contiguous()

            # Production forward arithmetic.
            up = F.linear(x, up_w)
            gate = F.linear(x, gate_w)
            silu_gate = F.silu(gate)
            hidden = silu_gate * up

            # Backward into hidden from the down projection.
            d_hidden = dy_out @ down_w

            # Use autograd for SiLU's exact PyTorch backward arithmetic rather
            # than hand-installing a derivative expression.
            gate_leaf = gate.detach().requires_grad_(True)
            silu_leaf = F.silu(gate_leaf)
            d_gate = torch.autograd.grad(
                silu_leaf,
                gate_leaf,
                grad_outputs=d_hidden * up,
                retain_graph=False,
                create_graph=False,
            )[0].detach().contiguous()

            d_up = (d_hidden * silu_gate).detach().contiguous()

            docs.append({
                "up": (x, d_up),
                "gate": (x, d_gate),
                "down": (hidden.detach().contiguous(), dy_out),
            })

        for projection in ("up", "gate", "down"):
            pairs = [d[projection] for d in docs]

            def reference():
                total = None
                for inp, upstream in reversed(pairs):
                    partial = upstream.transpose(0, 1) @ inp
                    total = partial if total is None else total + partial
                return total

            ref_once = reference()

            # Candidate receives documents physically in descending order so its
            # increasing chunk loop is logically doc4 -> doc3 -> doc2 -> doc1.
            rev = list(reversed(pairs))
            inp = torch.cat([p[0] for p in rev], dim=0).contiguous()
            upstream = torch.cat([p[1] for p in rev], dim=0).contiguous()

            m = upstream.shape[0]
            k = upstream.shape[1]
            n = inp.shape[1]
            if m != 4096:
                raise RuntimeError("%s.%s rows=%d" % (layer_name, projection, m))

            offsets = torch.tensor([m], device="cuda", dtype=torch.int32)
            ends = torch.tensor(
                [[1024, 2048, 3072, 4096]],
                device="cuda",
                dtype=torch.int32,
            ).contiguous()
            out = torch.empty((1, k, n), device="cuda", dtype=torch.bfloat16)

            def candidate():
                grouped._weights[
                    (triton.cdiv(k, arm.BM), triton.cdiv(n, arm.BN), 1)
                ](
                    upstream,
                    inp,
                    offsets,
                    out,
                    ends,
                    k,
                    n,
                    *upstream.stride(),
                    *inp.stride(),
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
            diff = cand_once.float() - ref_once.float()
            unequal = int(torch.count_nonzero(diff))
            rel_l2 = float(diff.norm()) / max(float(ref_once.float().norm()), 1e-30)

            exact_all = exact_all and exact

            samples = {"reference": [], "candidate": []}
            for r in range(args.rounds):
                order = (
                    ("reference", "candidate")
                    if r % 2 == 0
                    else ("candidate", "reference")
                )
                for label in order:
                    fn = reference if label == "reference" else candidate
                    samples[label].append(time_calls(torch, fn, args.calls))

            measured = {k0: stats(v0) for k0, v0 in samples.items()}
            speedup = (
                measured["reference"]["median"]
                / measured["candidate"]["median"]
            )
            speedups.append(speedup)

            name = "%s.%s.weight" % (layer_name, projection)
            results[name] = {
                "geometry": {
                    "rows": m,
                    "upstream_features": k,
                    "input_features": n,
                    "documents": [1024, 1024, 1024, 1024],
                    "order": "descending",
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

            del ref_once, rev, inp, upstream, offsets, ends, out, cand_once
            torch.cuda.empty_cache()

        del docs, up_w, gate_w, down_w
        torch.cuda.empty_cache()

    median_speedup = statistics.median(speedups)

    source_commit = subprocess.check_output(
        ["git", "-C", args.root, "rev-parse", "HEAD"],
        text=True,
    ).strip()

    return {
        "schema": SCHEMA,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "frozen_question": (
            "Can the grouped chunked BF16 dW kernel replace the current "
            "four-matmul plus three-add document reduction for all 12 shared "
            "SwiGLU projections without changing a bit?"
        ),
        "frozen_retention_criterion": {
            "all_12_bitwise_equal": True
        },
        "claim_boundary": (
            "saved-operand component A/B only; zero applied positions and "
            "optimizer updates; no governed throughput/hour/learning/Evaluation credit"
        ),
        "applied_positions": 0,
        "optimizer_updates": 0,
        "all_12_bitwise_equal": exact_all,
        "median_speedup": median_speedup,
        "candidate_semantically_admissible": exact_all,
        "sites": results,
        "protocol": {
            "rounds": args.rounds,
            "calls_per_round": args.calls,
            "warmup_calls": WARM,
            "arm_order": "alternating by round",
            "timer": "CUDA events",
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

    print("all 12 bitwise equal:", receipt["all_12_bitwise_equal"])
    print("median speedup:       %.4fx" % receipt["median_speedup"])

    for name, row in receipt["sites"].items():
        print(
            "%-38s exact=%-5s ref=%8.3fus cand=%8.3fus speedup=%6.3fx"
            % (
                name,
                row["numerical"]["bitwise_equal"],
                row["per_call_us"]["reference"]["median"],
                row["per_call_us"]["candidate"]["median"],
                row["speedup"],
            )
        )

    print("receipt:", out)


if __name__ == "__main__":
    main()
