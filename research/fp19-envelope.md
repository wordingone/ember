# fp-19 — owned-core feasibility envelope (VERDICT: non-empty; v0 named)

**Evidence class / certification status (artifact-local, per the
adopted design-zone boundary):** the measured throughput legs and the
envelope arithmetic are **RECEIPTED** (executed local bench,
`fp19-bench-20260611T024648Z.json`). The v0 architecture and optimizer
RATIONALE (why this config, Muon-as-upside, QAT-native) is
**HYPOTHESIS / FABLE-DERIVED — NEEDS INDEPENDENT RECEIPT** except where
a row cites an external paper; the discharge path is the 1B/2B/4B floor
checkpoints + the fp-22 world probes (named experiments, not prose).
The multiplier table is Haiku/Fable-family MINED EVIDENCE with
citations — an attack surface, not a certification. Certification
comes only from executed receipts.

Frozen 2026-06-11 (#111). Inputs: MEASURED bench receipt
`fp19-bench-20260611T024648Z.json` (daemon eval b839e851, governed:
VRAM fraction 0.80, margin assert ≥1.5 GiB held, paced duty cycle;
budget math uses PACED tok/s) + the refuter-adjusted multiplier table
`research/gpu-math-multiplier-table-2026-06-11.json` (gpu-math-attack
workflow, 24 agents).

## Envelope table (full training steps: fwd+loss+bwd+AdamW, seq 1024, grad-ckpt ON)

| config | params | variant | paced tok/s | 8-day tokens | compute-optimal need (20 t/p) | ratio |
|---|---|---|---|---|---|---|
| c01 | 99M | bf16 | 55,064 | 38.1B | 2.0B | **19.2×** |
| c01 | 99M | qat | 52,027 | 36.0B | 2.0B | 18.1× |
| c01 | 99M | ternary | 53,302 | 36.8B | 2.0B | 18.6× |
| c03 | 368M | bf16 | 20,201 | 14.0B | 7.4B | **1.9×** |
| c03 | 368M | qat | 18,738 | 13.0B | 7.4B | 1.76× |
| c03 | 368M | ternary | 19,509 | 13.5B | 7.4B | 1.83× |

Receipt flags carried: STE proxies not fused kernels (overhead shape
honest, ~5% — kernel speedups NOT claimed); synthetic batches = tok/s
upper bound on corpus-fed; raw (unpaced) rates ~1.3-1.5× higher but the
governor rate is the budget rate.

## Verdict

**The envelope is NON-EMPTY — the rung-kill does not fire; no hardware
escalation.** A 0.37B-class core trains COMPUTE-OPTIMAL inside the
remaining window at 1.76–1.9× margin; a 0.1B-class core has 18–19×
(room for heavy over-training or repeated restarts). Quantization-native
training costs ~5% at this scale — the QAT contract component is
effectively free.

**v0 config (named):**
- **Architecture:** c03 shape — 0.37B decoder (hidden 1024, 20 layers,
  16 heads, vocab 32k, seq 1024, tied embeddings), grad checkpointing.
- **Bit-discipline:** QAT int8-grid fake-quant (receipt-proven STE
  path). Ternary/b1.58 = staged v1 lever (also in-envelope at ~1.8×) if
  the v0 floor clears — not stacked into v0 (one variable at a time).
- **Optimizer:** Muon on hidden 2D weights (table's strongest lever,
  1.77× data-efficiency, CONTESTED — treated as upside, NOT load-bearing:
  the envelope clears WITHOUT it). Pre-registered switch rule: any
  fake-quant-phase instability → AdamW for that phase (the cited
  Muon×fake-quant interaction).
- **Token plan:** 7.4B target, checkpoints at 1B/2B/4B for
  K1-equivalent floor probes (fp-22's world). With Muon upside the
  target lands in ~2.4 effective GPU-days; without it, ~4.2 days —
  both inside the timeshare budget (map §3).
- **Timeshare:** pretrain holds GPU, checkpoint-resume handoff for
  round windows (eng-33 harness).

## What fp-19 does NOT decide (→ fp-22)

The corpus and the verify-floor world: license-clean data mix
(arc-dsl-MIT / apache-2.0 / permissive-only per §8.15d) and the world
where a 0.3B core clears a K1-equivalent verify floor (candidates:
synthetic program-curriculum, MBPP-easy stratum, ARC micro-tasks).
Launch gate = fp-22's mix + eng-33's harness + this config.
