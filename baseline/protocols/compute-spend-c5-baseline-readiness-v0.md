# Compute-Spend Packet: C5-0 Baseline Readiness

Status: SMOKE AUTHORIZED, FULL BASELINE NOT AUTHORIZED.
Created: 2026-06-29.
Claim family: C5-LOOP.

## Claim IDs

- C5-0A-MLAgentBench-CLRS
- C5-0B-AI-Scientist-nanoGPT-lite

## Purpose

Advance the selected zero-spend self-improvement subset from static task selection toward baseline-run receipts without launching an unbounded training job.

## Current Readiness

- C5-0A MLAgentBench CLRS: INVALID-RUN for baseline execution in the current Python environment because `chex`, `haiku`, `optax`, and `clrs` are missing. Repair is an isolated environment with CLRS requirements, not global package mutation.
- C5-0B AI Scientist nanoGPT_lite: baseline-readiness PASS for Python modules and CUDA visibility. PyTorch sees one NVIDIA GeForce RTX 4090 and bf16 support.

## Allowed Short Jobs

1. Run `data/shakespeare_char/prepare.py` for C5-0B.
   - Expected output: `input.txt`, `train.bin`, `val.bin`, `meta.pkl` under the AI Scientist checkout.
   - Network: allowed only to fetch Tiny Shakespeare from Karpathy char-rnn if absent.
   - Stop rule: fail if download/import/write errors occur.

2. Static/import checks for C5-0A isolated environment planning.
   - No training.
   - No global Python mutation.

3. Run `scripts/run_c5_nanogpt_smoke.py` for C5-0B only.
   - It must copy `templates/nanoGPT_lite` to `C:\tmp\ember-baseline-ai-scientist\templates\nanoGPT_lite_smoke`, patch only the copy, use one seed, max_iters=3, eval_iters=2, n_layer=2, n_head=2, n_embd=128, block_size=64, batch_size=4, compile=False, num_samples=1, and max_new_tokens=16.
   - Timeout: <=240 seconds.
   - Stop rule: INVALID-RUN if final_info JSON is absent, CUDA errors occur, or timeout occurs.
   - This is a smoke/admission receipt only; it is not a baseline performance result and cannot satisfy C5 T0/T1/T2.

## Forbidden Without New Packet

- Full unpatched `python experiment.py --out_dir run_0` for nanoGPT_lite.
- Full MLAgentBench CLRS `train.py` baseline.
- Any package install into the active global Python environment.
- Any hosted LLM/API review or agent generation.

## Receipts

- `receipts/c5-baseline-readiness-2026-06-29.json`
- `receipts/c5-nanogpt-lite-data-prep-2026-06-29.json`
- `receipts/c5-nanogpt-lite-smoke-2026-06-29.json` after bounded smoke

## Current Verdict

SMOKE AUTHORIZED, FULL BASELINE NOT AUTHORIZED. Data prep is complete; a bounded C5-0B smoke is authorized. Full baseline training remains forbidden without a new packet.