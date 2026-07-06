# Telemetry discrepancy note — flagged, not laundered

`muon-ab-smallfoot-retry-20260705T233603Z.json` → `underlying_receipt.governor.free_gib_at_launch`
reports **10.08 GiB** free at launch (bench_start_utc 2026-07-05T23:35:40Z).

The concurrent `nvidia-smi-samples.csv` (5s cadence, spanning 16:35:27–16:36:12 local /
23:35:27–23:36:12 UTC, bracketing the entire bench window including bench_start) shows
`memory.used` ranging **19624–21954 MiB**, i.e. **free VRAM ranging 2.61–4.94 GiB** —
at no sampled point does free VRAM approach 10 GiB. The two samples nearest bench_start
(16:35:37.406 → 4.94 GiB free, 16:35:42.426 → 4.26 GiB free) bracket it directly.

This is a real discrepancy I cannot fully reconcile: either (a) `torch.cuda.mem_get_info()`
(what the harness reads) and `nvidia-smi`'s reported `memory.used` diverged by ~5-6 GiB at
that instant for a reason I don't have visibility into, or (b) a multi-GB transient shifted
faster than my 5-second sample cadence caught (this system's VRAM has been independently
observed swinging by several GiB within single-digit seconds this session, driven by
processes outside this leg's control — see reproduce-run note below). I am not asserting
either explanation; I'm flagging the field as **unverified against concurrent telemetry**
rather than treating the harness's self-report as ground truth.

What IS corroborated by the concurrent sample, independent of that one field:
- GPU utilization rose from ~0% baseline to 23-41% exactly during the bench window
  (16:35:47–16:36:02) and fell back to ~0-1% immediately after (16:36:07+) — consistent
  with real, in-window GPU compute, the opposite signature of the rejected PR #177 receipt
  (0% utilization throughout its claimed window).
- `memory.used` rose by ~2.3 GiB during the same window and returned to the pre-run baseline
  (19624 MiB) immediately after — consistent with the small-footprint model+optimizer
  allocating and then being freed (`torch.cuda.empty_cache()` at the end of `measure_arm`),
  and roughly matching the per-seed `vram_used_gib` values in the receipt (0.65-2.12 GiB).
- Per-seed step-time arrays show realistic jitter (not suspiciously uniform), and the
  fused arm's `mean_step_s` (0.025-0.032s) is consistently lower than baseline's
  (0.039-0.040s) across all 3 seeds individually, not just in aggregate — internally
  consistent with a genuine measurement rather than a fabricated aggregate.

Verdict on trustworthiness: the bench-window utilization/memory shape is real; the single
`free_gib_at_launch` field is flagged unverified and should not be cited as evidence of
available headroom without independent re-confirmation.

## Also unrelated but observed this session (context for the free-VRAM volatility)

This machine's GPU was independently observed swinging between 140 MiB free and ~5.8 GiB
free within a ~15-minute window this session, driven entirely by processes outside this
leg (three `llama-server.exe` instances churning — one CPU-only `-n-gpu-layers 0` instance
appeared/disappeared unrelated to any action taken here). `llama-server.exe` pid 23892 and
10848 (the two GPU-resident instances) were cmdline-verified alive throughout, untouched.
