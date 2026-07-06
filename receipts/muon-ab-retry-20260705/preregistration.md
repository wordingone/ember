# Pre-registration — fused-Muon NS chain governed small-footprint retry (#175)

Written BEFORE the retry run, per #175 frozen spec item 4.

## Reproduce finding (step 1, precedes this file)

Ran `scripts/fp35_fused_muon_kernel_ab.py` as-is on the native Windows Python env
(torch 2.10.0+cu126, triton 3.5.0, CUDA available, cl.exe NOT on PATH) at
2026-07-05T23:28:15Z. Verbatim capture: `reproduce-20260705T232815Z.log`.

Result: the originally-reported Triton/MSVC compile failure (kill receipt
`fp35-fused-muon-ab-20260612T213247Z.json`, "MinGW cannot link against CUDA MSVC
.lib files, FileNotFoundError [WinError 2]") **did not reproduce**. `_check_ns5_equiv`
compiled and ran `_ns5_fused` (torch.compile(ns5, mode="reduce-overhead")) on CUDA
successfully: `NS5 equiv PASS: max_abs_delta=1.90e-07 (tol=1.00e-03)`. `muon-baseline`
arm then began producing real bench numbers (seed 16: 11594 tok/s; seed 17: 11607 tok/s)
before the run was killed by my own 2-minute Bash tool timeout mid-seed-18 — not by any
env/compile failure. No env-fix rung (vcvars/triton-pin/TRITON_* override) was needed;
whatever changed between 2026-06-12 and today (env package drift outside this session)
already cleared rung (a)+(b). VS 2022 Community + VC Tools 14.44.35207 confirmed present
at `C:\Program Files\Microsoft Visual Studio\2022\Community` (vcvars64.bat located) as a
banked fallback if compile ever regresses, but it was not invoked this leg.

## VRAM state at pre-registration time (2026-07-05T23:32Z)

`nvidia-smi`: 24564 MiB total, 18362 MiB used, 5777 MiB free, 1% util. Three
`llama-server.exe` PIDs resident (23892, 33140, 10848) — cmdline-verified, all alive,
none touched. `ember-cockpit-172.exe` (22744) alive, untouched.

c03 shapes (HIDDEN=1024, LAYERS=20, FFN=4096, SEQ=1024, BATCH=4) empirically need
~8.4 GiB per arm (both June receipts and my own partial run this leg agree: seed 17
this run reported `vram_used_gib=8.44`). 5.78 GiB free < 8.4 GiB required + 1 GiB
margin floor → **the full c03-scale retry does not fit today**. Per #175 item 3
("Small/medium shapes only; full-scale sweep deferred to a model-idle residency
window"), this leg runs a **small-footprint** shape variant instead, sized to fit
comfortably under current free VRAM with margin.

## Small-footprint shape override (this retry only — frozen script untouched)

Applied via external monkeypatch of module globals before calling `main()` — the
tracked file `scripts/fp35_fused_muon_kernel_ab.py` is NOT edited, its `harness_sha`
is unchanged, byte-identical to the frozen spec's harness:

| const | c03 (frozen default) | this retry |
|---|---|---|
| HIDDEN | 1024 | 512 |
| LAYERS | 20 | 4 |
| HEADS | 16 | 16 |
| FFN | 4096 | 2048 |
| SEQ | 1024 | 512 |
| BATCH | 4 | 4 |
| VOCAB | 32000 | 32000 (unchanged) |
| SEEDS | [16,17,18] | [16,17,18] (unchanged) |
| warmup/bench reps | 5/20 | 5/20 (unchanged) |
| VRAM_FRACTION/MARGIN_GIB/PACE_S | 0.80/1.5/0.05 | unchanged — governor rails HOLD |

Expected footprint: roughly (512/1024) × (4/20) of c03's ~8.4 GiB ≈ well under 1 GiB
per arm — a wide safety margin under the 5.78 GiB currently free, chosen deliberately
oversized-safe rather than shaving the margin thin.

## Pre-registered outcome bands (fixed before the run; not adjusted after seeing data)

- **Compile check**: `_check_ns5_equiv` on CUDA must PASS (max_abs_delta <= 1e-3) before
  any bench arm runs — this is the harness's own gate, unchanged.
- **muon-fused mean tokens/s ÷ muon-baseline mean tokens/s (measured_multiplier)**:
  - `>= 1.02` → harness verdict `MUON_FUSED_VIABLE` = **WORKING** at small-footprint scale.
  - `< 1.02` (including `< 1.0`, i.e. fused SLOWER than baseline) → **this is a REPORT,
    NOT a kill.** Terminal state is `PARKED-pending-named-wall-break` naming the next
    move (e.g. re-test at c03 scale during a residency window, since fusion gains from
    memory-bound kernels are shape-dependent and a small-footprint negative does not
    settle the c03-scale question).
  - Any `OOM_AT_BUILD` / `OOM_AT_WARMUP` / `OOM_AT_BENCH` on either arm at this reduced
    footprint → PARKED-pending-residency-window, VRAM state named exactly.
- **No self-kill of the #175 leg regardless of the multiplier value** — the only
  terminal states are WORKING or PARKED-pending-named-wall-break, per #155's standing
  verdict and #175 item 4.
- **This retry does NOT settle the c03-scale (full-footprint) question either way** —
  a small-footprint PASS or REPORT both leave the full-scale sweep deferred to the named
  residency window, per #175 item 3. A small-footprint WORKING is evidence the fusion
  mechanism is sound on this GPU/driver/torch/triton stack; it upgrades confidence but is
  not a substitute receipt for the c03 criterion.

## Telemetry schema for the retry receipt (binding, per dispatch)

1. Concurrent `nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used --format=csv -l 5`
   sample file spanning the full bench window, path referenced in the final receipt.
2. Bench start/end UTC timestamps in the receipt, span consistent with
   warmup+reps×seeds×arms.
3. This reproduce-log path (`reproduce-20260705T232815Z.log`) referenced in the receipt.
