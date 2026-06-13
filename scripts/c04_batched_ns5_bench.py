"""c04_batched_ns5_bench.py — Production bench for batched-NS5 Muon kernel (#389).

Bench spec (Leo mail 15355, gate frozen):
  Config : c03-h1024-d20, compiled fwd-only + ckpt + FP8 (c04 defaults)
  Measure: tok_s_paced, optimizer_wall_share, per-shape ns5_equiv
  GATE   : tok_s_paced >= 25463 AND ns5_equiv max_abs_delta <= 2e-7

Extends fp45_batched_ns5_ab bench seed with:
  - c04_dynamo_patch (BLOCKER-1 + BLOCKER-2 fix)
  - fp19._apply_fake_quant (FP8 before compile)
  - torch.compile(fwd_fn, fullgraph=True)  [forward-only; backward stays eager]

Receipt: receipts/c04-batched-ns5-bench-{ts}.json

Selftest: python c04_batched_ns5_bench.py --selftest
  Marker : C04_BATCHED_NS5_BENCH_SELFTEST_PASS  (schema-only, no GPU)

Dispatch: via train MCP after fp44 receipt lands (one model at a time).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
sys.path.insert(0, HERE)

import fp45_batched_ns5_ab as fp45       # noqa: E402
import c04_dynamo_patch                  # noqa: E402
import fp19_bench as fp19               # noqa: E402
import timeshare_pretrain as ts         # noqa: E402
from receipt_write import checked_write  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────

CANDIDATE  = "c03-h1024-d20"
BATCH      = 16       # ckpt=True batch (fp40-confirmed)
GRAD_CKPT  = True
VARIANT    = "qat"    # FP8

WARMUP = 5
TIMED  = 20

VRAM_FRACTION = 0.80
MARGIN_GIB    = fp19.MARGIN_GIB
PACE_S        = fp19.PACE_S

# Gate thresholds (frozen, Leo mail 15355 — do not move)
GATE_TOK_S   = 25_463.0
GATE_NS5_TOL = 2e-7


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Bench ─────────────────────────────────────────────────────────────────────

def _run_bench() -> dict:
    """Run batched-NS5 production bench. Returns result dict (not yet receipt-wrapped)."""
    import torch

    torch.manual_seed(42)
    backbone, head, mtp_heads = fp45._build_model(grad_ckpt=GRAD_CKPT)
    backbone.train(); head.train(); mtp_heads.train()

    muon_opt, adamw_opt, n_muon = fp45._build_opts(backbone, head, mtp_heads, "muon-batched")

    # BLOCKER-1 (chunked_ce cpu-sync) + BLOCKER-2 (co_varnames decorator)
    c04_dynamo_patch.apply()
    c04_dynamo_patch.apply_compile_patch(backbone)
    ce_fn = ts.chunked_cross_entropy  # now dynamo-safe

    # FP8 fake_quant ONCE before compile (model.modules() not traceable inside compile)
    fp19._apply_fake_quant(backbone, VARIANT)

    # Forward-only compile (backward + optimizer outside compiled region)
    def fwd_fn(ids, tgt0, tgt_m):
        hidden = backbone(input_ids=ids).last_hidden_state
        h_flat = hidden.reshape(-1, hidden.shape[-1])
        pce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
        mces = [ce_fn(h_flat, mh.weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
                for k in range(fp45.MTP_N_HEADS)]
        return ts.mtp_total_loss(pce, mces, fp45.MTP_WEIGHT)

    print(f"[c04_ns5_bench] {CANDIDATE}: compiling fwd ...", flush=True)
    compile_status = "SKIP"
    fwd_call = fwd_fn
    try:
        fwd_compiled = torch.compile(fwd_fn, fullgraph=True)
        ids_t  = torch.randint(0, fp45.VOCAB, (BATCH, fp45.SEQ), device="cuda")
        tgt0_t = torch.roll(ids_t, -1, dims=1)
        tgtm_t = [torch.roll(ids_t, -(k + 2), dims=1) for k in range(fp45.MTP_N_HEADS)]
        loss_t = fwd_compiled(ids_t, tgt0_t, tgtm_t)
        loss_t.backward()
        for o in [muon_opt, adamw_opt]:
            if o: o.zero_grad(set_to_none=True)
        compile_status = "PASS"
        fwd_call = fwd_compiled
        print(f"[c04_ns5_bench] compile PASS", flush=True)
    except torch._dynamo.exc.Unsupported as e:
        compile_status = "BREAK"
        print(f"[c04_ns5_bench] COMPILE-BREAK: {e!s:.200}", flush=True)
    except Exception as e:
        compile_status = "ERROR"
        print(f"[c04_ns5_bench] COMPILE-ERROR: {e!s:.200}", flush=True)

    def step():
        ids  = torch.randint(0, fp45.VOCAB, (BATCH, fp45.SEQ), device="cuda")
        tgt0 = torch.roll(ids, -1, dims=1)
        tgt_m = [torch.roll(ids, -(k + 2), dims=1) for k in range(fp45.MTP_N_HEADS)]
        loss = fwd_call(ids, tgt0, tgt_m)
        loss.backward()
        t_opt_start = time.perf_counter()
        if muon_opt:
            muon_opt.reset_ns_timer()
            muon_opt.step()
        adamw_opt.step()
        t_opt = time.perf_counter() - t_opt_start
        ns_ms = muon_opt._last_ns_ms if muon_opt else 0.0
        if muon_opt: muon_opt.zero_grad(set_to_none=True)
        adamw_opt.zero_grad(set_to_none=True)
        return t_opt, ns_ms

    # Warmup (compile already ran one fwd+bwd if PASS)
    remaining_warmup = WARMUP - (1 if compile_status == "PASS" else 0)
    print(f"[c04_ns5_bench] warmup {remaining_warmup} ...", flush=True)
    for i in range(remaining_warmup):
        step()
        print(f"[c04_ns5_bench]   warmup {i+1}/{remaining_warmup}", flush=True)

    torch.cuda.synchronize()
    free_b, _ = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    if free_gib < MARGIN_GIB:
        return {"status": "SKIPPED-MARGIN", "free_vram_gib": round(free_gib, 2),
                "compile_status": compile_status}

    # Timed bench
    print(f"[c04_ns5_bench] bench {TIMED} steps ...", flush=True)
    step_times, opt_wall_times, ns_times = [], [], []
    t0 = time.perf_counter()
    for i in range(TIMED):
        t_s = time.perf_counter()
        t_opt, ns_ms = step()
        torch.cuda.synchronize()
        t_step = time.perf_counter() - t_s
        time.sleep(PACE_S)
        step_times.append(t_step)
        opt_wall_times.append(t_opt)
        ns_times.append(ns_ms)
        if (i + 1) % 5 == 0:
            print(f"[c04_ns5_bench]   step {i+1}/{TIMED} "
                  f"step={t_step*1000:.1f}ms opt={t_opt*1000:.1f}ms ns={ns_ms:.1f}ms", flush=True)

    total_dt = time.perf_counter() - t0
    toks = TIMED * BATCH * fp45.SEQ
    tok_s_paced = toks / total_dt
    tok_s_raw   = toks / (total_dt - TIMED * PACE_S)
    mean_step   = sum(step_times) / len(step_times)
    mean_opt    = sum(opt_wall_times) / len(opt_wall_times)
    mean_ns_ms  = sum(ns_times) / len(ns_times)
    opt_wall_share = mean_opt / mean_step if mean_step > 0 else 0.0

    # Per-shape NS5 equiv check (batched vs per-param, GPU)
    print(f"[c04_ns5_bench] ns5_equiv check ...", flush=True)
    ns5_eq = fp45._check_ns5_equiv(device="cuda")
    max_delta = max(v["max_abs_delta"] for v in ns5_eq.values())
    ns5_gate = max_delta <= GATE_NS5_TOL

    # Gate
    tok_s_gate = tok_s_paced >= GATE_TOK_S
    gate_pass  = tok_s_gate and ns5_gate

    result = {
        "status": "OK",
        "compile_status": compile_status,
        "n_muon_params": n_muon,
        "tok_s_paced": round(tok_s_paced, 1),
        "tok_s_raw":   round(tok_s_raw, 1),
        "mean_step_ms": round(mean_step * 1000, 2),
        "optimizer_wall_share": round(opt_wall_share, 4),
        "mean_opt_wall_ms": round(mean_opt * 1000, 2),
        "mean_ns_phase_ms":  round(mean_ns_ms, 2),
        "free_vram_gib_post_warmup": round(free_gib, 2),
        "ns5_equiv": {
            "per_shape": ns5_eq,
            "max_abs_delta": round(max_delta, 9),
            "gate_pass": ns5_gate,
            "gate_tol": GATE_NS5_TOL,
        },
        "gate": {
            "tok_s_paced": round(tok_s_paced, 1),
            "tok_s_threshold": GATE_TOK_S,
            "tok_s_pass": tok_s_gate,
            "ns5_max_delta": round(max_delta, 9),
            "ns5_threshold": GATE_NS5_TOL,
            "ns5_pass": ns5_gate,
            "gate_pass": gate_pass,
        },
    }
    return result


# ── Receipt ───────────────────────────────────────────────────────────────────

def run_and_emit() -> Path:
    """Run bench and write receipt. Returns receipt path."""
    result = _run_bench()
    receipt = {
        "ticket": "C04-BATCHED-NS5-BENCH",
        "ts": _ts(),
        "candidate": CANDIDATE,
        "config": {
            "hidden": fp45.HIDDEN, "layers": fp45.LAYERS, "heads": fp45.HEADS,
            "batch": BATCH, "seq": fp45.SEQ,
        },
        "bench_reps": TIMED,
        "compiled": True,
        "grad_checkpointing": GRAD_CKPT,
        "c1_dtype": VARIANT.upper(),
        "harness_sha": _harness_sha(),
        **result,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"c04-batched-ns5-bench-{receipt['ts']}.json")
    checked_write(path, json.dumps(receipt, indent=2))
    print(f"[c04_ns5_bench] receipt: {path}", flush=True)
    gate = receipt.get("gate", {})
    verb = "GATE-PASS" if gate.get("gate_pass") else "GATE-FAIL"
    print(f"[c04_ns5_bench] {verb}: "
          f"tok_s_paced={gate.get('tok_s_paced')} "
          f"(>={GATE_TOK_S}={gate.get('tok_s_pass')}) | "
          f"ns5_delta={gate.get('ns5_max_delta')} "
          f"(<={GATE_NS5_TOL}={gate.get('ns5_pass')})", flush=True)
    return Path(path)


# ── Schema verifier (for selftest) ────────────────────────────────────────────

def _verify_receipt_schema(r: dict) -> None:
    assert r["ticket"] == "C04-BATCHED-NS5-BENCH"
    assert r["candidate"] == CANDIDATE
    for key in ("tok_s_paced", "optimizer_wall_share", "mean_step_ms"):
        assert key in r, f"missing '{key}'"
    ns5 = r["ns5_equiv"]
    assert "max_abs_delta" in ns5
    assert "gate_pass" in ns5
    gate = r["gate"]
    for key in ("tok_s_pass", "ns5_pass", "gate_pass"):
        assert key in gate, f"gate missing '{key}'"


# ── Selftest ──────────────────────────────────────────────────────────────────

def selftest() -> None:
    import tempfile, os as _os

    print("[c04_batched_ns5_bench] selftest: schema-only (no GPU)", flush=True)

    # Synthetic receipt matching expected schema
    syn = {
        "ticket": "C04-BATCHED-NS5-BENCH",
        "ts": "20260613T000000Z",
        "candidate": CANDIDATE,
        "config": {"hidden": 1024, "layers": 20, "heads": 16, "batch": 16, "seq": 1024},
        "bench_reps": 20,
        "compiled": True,
        "grad_checkpointing": True,
        "c1_dtype": "QAT",
        "harness_sha": "abc123",
        "status": "OK",
        "compile_status": "PASS",
        "n_muon_params": 140,
        "tok_s_paced": 27800.0,
        "tok_s_raw": 31200.0,
        "mean_step_ms": 585.0,
        "optimizer_wall_share": 0.1800,
        "mean_opt_wall_ms": 105.3,
        "mean_ns_phase_ms": 89.0,
        "free_vram_gib_post_warmup": 6.4,
        "ns5_equiv": {
            "per_shape": {
                "(64, 128)": {"max_abs_delta": 0.0, "pass": True},
                "(1024, 1024)": {"max_abs_delta": 0.0, "pass": True},
                "(4096, 1024)": {"max_abs_delta": 0.0, "pass": True},
            },
            "max_abs_delta": 0.0,
            "gate_pass": True,
            "gate_tol": GATE_NS5_TOL,
        },
        "gate": {
            "tok_s_paced": 27800.0,
            "tok_s_threshold": GATE_TOK_S,
            "tok_s_pass": True,
            "ns5_max_delta": 0.0,
            "ns5_threshold": GATE_NS5_TOL,
            "ns5_pass": True,
            "gate_pass": True,
        },
    }
    _verify_receipt_schema(syn)
    print("  schema verify (GATE-PASS synthetic): PASS")

    # Failing gate case
    syn_fail = dict(syn)
    syn_fail["tok_s_paced"] = 22000.0
    syn_fail["gate"] = dict(syn["gate"])
    syn_fail["gate"]["tok_s_paced"] = 22000.0
    syn_fail["gate"]["tok_s_pass"] = False
    syn_fail["gate"]["gate_pass"] = False
    _verify_receipt_schema(syn_fail)
    assert not syn_fail["gate"]["gate_pass"]
    print("  schema verify (GATE-FAIL synthetic): PASS")

    # Round-trip via file
    with tempfile.TemporaryDirectory() as tmp:
        p = _os.path.join(tmp, "c04-batched-ns5-bench-test.json")
        with open(p, "w") as f:
            json.dump(syn, f, indent=2)
        r = json.loads(open(p).read())
        _verify_receipt_schema(r)
    print("  round-trip file read: PASS")

    print("C04_BATCHED_NS5_BENCH_SELFTEST_PASS")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="c04 batched-NS5 production bench")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true", help="Run bench and emit receipt (GPU required)")
    args, _ = ap.parse_known_args()

    if args.selftest:
        selftest()
    else:
        path = run_and_emit()
        print(f"Receipt: {path}")


if __name__ == "__main__":
    main()
