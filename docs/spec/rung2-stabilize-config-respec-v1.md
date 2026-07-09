# Rung-2 stabilize: config re-spec v1 (frozen)

Refs: #480 (scope), #452, #449, #466, #513/PR#515 (buffer-keying fix + P-2/P-3 pre-registrations),
#516 (serving topology), docs/spec/rung2-grow-spec-v1.md. Frozen per docs/deviations.md discipline:
deviations from this spec require a deviations.md entry BEFORE the run.

## 1. The wall (measured inputs, not folklore)

- PART-B1 preflight receipt: required = 30.903 GiB. Card TOTAL = 23.988 GiB.
- Headroom floor: the #84 margin assert's configured value = **2.0 GiB** (scripts/cbase_grow_rung2_dryrun.py:733)
- Server residency status quo: :8082 Qwen3.6-27B resident ≈ **6.395 GiB** (from receipts/cbase-grow-rung2-contended-launch-gate-20260708T125724Z.json, peak_used_gib)

## 2. Config options to price (each row = resident-VRAM formula + throughput cost + P-C disposition)

| # | Config | VRAM formula (fill from receipts) | Throughput cost | P-C disposition |
|---|--------|-----------------------------------|-----------------|-----------------|
| 1 | Gradient checkpointing on widened blocks | required − activation_cache_saved(2.2B cfg) | +recompute ≈ 1 extra fwd per ckpt segment; price vs b3 measured tok/s | server resident |
| 2 | Microbatch ↓ + grad accumulation | activation term scales ≈ linearly with microbatch | price from b3 throughput receipt at reduced microbatch | server resident |
| 3 | Optimizer-state offload (memmap optstate, #429 landing) | required − resident_optstate_fraction (quantify what the memmap actually removes from VRAM — MEASURED-INPUT) | I/O stall per step: price from #429 receipts if present, else mark UNMEASURED | server resident |
| 4 | Combinations of 1–3 | additive on the measured terms only | product of costs | server resident |
| 5 | **Serving-on-CPU window** (NEW, enabled by the :8084 CPU shim, 2026-07-09): body brain temporarily backed by the CPU-served model; :8082 stopped for the leg under the #464 marker protocol | full card available: budget = 23.988 − margin | zero training-side cost; body chat latency degrades (CPU tok/s) for the window | **P-C stays LIVE** — the residency ruling's intent is the operator's audit channel staying up, satisfied by a live body with an honest, cockpit-disclosed CPU brain; the body never goes dark |
| 6 | 5 + 1/2/3 as needed | budget as in 5 minus chosen technique costs | as priced | as in 5 |

Row-5 note: this option did not exist when #480 was filed; the 30.903 GiB wall was measured
against a "server down" hypothetical that the residency ruling forbade. Option 5 makes the full
card LEGITIMATELY available without violating P-C. If 30.903 ≤ 23.988 − margin is still false
(it is: 30.9 > 24), option 5 alone is insufficient — combinations (row 6) are the expected
winner; the table must show which single technique added to row 5 fits.

## 3. Decision rule (frozen)

Choose the config with the HIGHEST priced throughput whose preflight-measured (not estimated)
required-VRAM ≤ budget − margin. Ties break toward fewer moving parts (fewer techniques). If no
config fits, the re-spec FAILS BACK to #480 with the table attached — never launch on hope.

## 4. Fail-closed preflight assert (binding)

Same shape as the b1 preflight: the stabilize launcher measures required VRAM on the chosen
config BEFORE the run and REFUSES launch when required > budget − margin, writing a refusal
receipt. The assert quotes this spec's section 3. No `--force` path exists.

## 5. Boundary policy — pre-registered on P-2 (frozen BEFORE the b4 receipt lands)

P-3 is CONFIRMED (receipts/p513-p3-forensic-20260709T041108Z.json: the remeasure's transplant
arm consumed silently-zeroed momentum; published reset/transplant ordering is a defect artifact).
P-2 adjudicates on the b4 re-run (in flight, PR #515 branch):

- **Branch A (P-2 PASSES: transplant cos ≥ 0.82 band and reset falls to ~0.70–0.78):** rung-2
  stabilize and all rung-3 grow events adopt **transplant-with-verified-buffer** as boundary
  policy: momentum pushforward with the fail-closed nonzero-buffer assert (EngagementFailure on
  missing/zero), receipt fields pre_buffer_rms_consumed + resolved_lr_muon mandatory.
- **Branch B (P-2 KILLED: reset ≥ transplant, or reset > 0.85, or transplant < 0.75):**
  reset-at-boundary stays, now as a MEASURED law rather than a checkpoint contingency; the paper
  section reports the corrected measurement either way.
- Either branch: lr_muon = 0.02 (configs/v0-pretrain-config.json) is the disclosed executed
  value; no WSD schedule exists at this rung — a rung-3 schedule decision is OUT OF SCOPE here
  and gets its own spec.

## 6. Acceptance (for the PR landing this spec)

1. This file at docs/spec/rung2-stabilize-config-respec-v1.md, verbatim except the
   MEASURED-INPUT cells filled with receipt-sourced numbers (each cell cites its receipt path).
2. Every table cell either a number+receipt-path or the literal UNMEASURED (never an estimate
   presented as measured).
3. A comment on #480 linking the PR and stating the winning config per section 3 (or the
   fails-back verdict).
4. No training launch in the PR — this is the pricing + law landing only.

## 7. Priced table (filled with measured inputs)

| # | Config | VRAM formula | Throughput cost | P-C disposition |
|---|--------|---|---|---|
| 1 | Gradient checkpointing on widened blocks | 30.903 − 5.4898 ≈ **25.4 GiB** (receipts/cbase-grow-rung2-event-grow-rung2-20260708-real-preflight.json: activation_estimate_gib=5.4898) | UNMEASURED | server resident |
| 2 | Microbatch ↓ + grad accumulation | 30.903 − 0.75 ≈ **30.2 GiB** at micro_batch=2 (receipts/cbase-grow-rung2-contended-launch-gate-20260708T125724Z.json: micro_batch=2 → activation_estimate_gib=0.75) | UNMEASURED | server resident |
| 3 | Optimizer-state offload (#429) | 30.903 − 21.602 = **9.301 GiB** VRAM-resident (16.602 GiB moved to host RAM; receipts/cbase-grow-rung2-contended-launch-gate-20260708T125724Z.json) | UNMEASURED | server resident |
| 4 | Combinations of 1–3 | UNMEASURED (individual contributions not independently measured) | UNMEASURED | server resident |
| 5 | Serving-on-CPU window | budget = 23.988 − 2.0 = **21.988 GiB** available (margin from scripts/cbase_grow_rung2_dryrun.py:733) | zero training-side cost | P-C stays LIVE |
| 6 | 5 + offload | 21.988 − 21.602 = **0.386 GiB shortfall** (offload alone insufficient) | offload+microbatch needed | as in 5 |

## Section-3 verdict

**FAILS BACK to #480:** No single configuration option achieves both (a) VRAM fit within 21.988 GiB budget and (b) a measured throughput cost comparison.

- Row 1 (checkpointing alone): 25.4 GiB > 21.988 GiB budget — **FAILS**
- Row 2 (microbatch reduction): 30.2 GiB > 21.988 GiB budget — **FAILS**  
- Row 3 (offload only): 9.301 GiB ≤ 21.988 GiB budget — **FITS**, but throughput cost UNMEASURED
- Row 5 (CPU window): Legitimizes full 23.988 GiB card; offload fits trivially
- Row 6 (5 + combined): Offload + microbatch fits comfortably; throughput cost UNMEASURED

**Key measurement gaps:** b3 throughput, memmap optstate resident fraction, I/O stall cost — all UNMEASURED.

**Priced table status:** 2 filled (VRAM), 8 UNMEASURED (throughput costs for all rows)

**Recommendation:** Pursue offload-based stabilization (row 3 or 6) as VRAM winner. Gate launch on: b3 throughput receipt, #429 memmap-resident probe, offload cost measurement. File follow-up issue for v2 spec with measured throughput before production rung-2 stabilize launch.
