# 07 — Governor and Resource Management

## scripts/governor.py

The canonical resource governor (`scripts/governor.py` docstring: "the
launch preconditions that keep this PC alive"), extracted from duplicated
inline blocks in `t1_probe.load_model`, `t2_round.train_lora`, `t2_grpo`,
`t2_mtp`, semantics kept byte-equivalent to the original inline logic.

Core preconditions:
1. Hard per-process VRAM fraction cap (`EMBER_VRAM_FRACTION`, default `0.85`)
2. Free-VRAM margin assert BEFORE any load (`EMBER_VRAM_MARGIN_GB`, `4.0`) — refuse the launch, never fix-forward
3. Step throttle (`EMBER_THROTTLE_S`, `0.3`) — never pegged wall-to-wall
4. Decode pacing lives separately in `t1_probe.decode_pacer`

`preflight()` returns a receipt block `{frac, free_gb, total_gb, margin_gb}`
so governor evidence rides on every receipt rather than being asserted in
prose.

## Function surface

- `env_limits()`, `preflight()`, `throttle_step()` — the core VRAM/pace floor above
- `commit_env_limit()`, `estimate_checkpoint_mapped_bytes()`, `_commit_status()`, `commit_margin_preflight()` — the **in-run commit governor**: tracks committed (not just reserved) memory against a limit as checkpoints grow, so a long training run cannot silently exceed host commit and crash the box
- `device_capability()`, `select_precision()`, `device_relative_threshold()` — the **device-adaptive precision ladder** (feeds condition `C-PORT`): queries actual device capability (with a `simulate` override for non-GPU test hosts) and selects a precision scheme relative to a reference device ("4090") rather than hardcoding an absolute floor
- `fp8_matmul_with_fallback()` — torch-importing fp8 matmul with a fallback path (covered separately by `scripts/test_governor.py`, since it needs torch)
- `make_headroom_callback()` — a reusable headroom-check callback for long-running loops

## Selftest

`python scripts/governor.py` runs a Windows-safe, no-torch selftest covering
env parsing, the receipt-block shape, the device-adaptive precision ladder,
and the in-run commit governor (all pure Python plus `ctypes` on win32); the
fp8 matmul path is exercised separately.

## Current gaps — honestly stated

Condition `C-PORT` (device portability) was GREEN on the last board render,
backed by `receipts/c-port-device-portability-sim-20260710T001548Z.json`
("governor + forward pass ran without crash on a non-4090 device
(simulated 3090-class...)"). This doc describes the governor module as it
exists; it does not claim every training script has been migrated onto
`governor.preflight()` — the module's own docstring records that migration
as a "wiring discipline... wait-window item" for scripts still carrying
inline copies.
