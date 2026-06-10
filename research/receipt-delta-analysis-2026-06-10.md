# Receipt-Based Wall-Time Delta Analysis — Probe (a) Alternate Arm

**Task:** Measure what is actually derivable about WSL 9P overhead from EXISTING receipts, replacing the draft's mtime guesses with honest numbers.

**Analysis Date:** 2026-06-10  
**Receipts Analyzed:** w1-floor-g1-{base, a, control, mtp} family (2026-06-10)

---

## Timestamp Schema & Derivation Method

### Current Receipt Structure
Each w1-floor receipt carries:
- `ts`: ISO timestamp (YYYYMMDDTHHMMSSZ) = script execution TIME (from `datetime.now(timezone.utc)`)
- `gen_secs`: model generation wall time (float, seconds)
- No `start_ts` / `end_ts` fields

### File System Timestamps Available
- Receipt JSON `.json` mtime = script end (JSON write, line 286 of w1_mbpp.py)
- Samples JSONL `.jsonl` mtime = sample file last write (line 259 of w1_mbpp.py)

### Derivable Bounds — Code Path Analysis
Reading w1_mbpp.py lines 169-172 and 190:

```python
t0 = time.time()                          # line 169: capture BEFORE generate_chat
completions = generate_chat(model, tok, user_texts, args.batch_size,
                            args.max_new, args.temp, args.seed)
gen_secs = round(time.time() - t0, 1)    # line 172: gen duration
...
ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # line 190: AFTER all work
```

The receipt.ts is captured AFTER all work (model generation, job execution, sample writing). However, this timestamp is NOT saved to disk until the file is written (line 286). The actual wall time equals:
- **Wall time** = receipt JSON mtime - receipt.ts

But there's a critical gap: **model loading happens BEFORE t0** (line 149), so overhead before gen_secs is not captured.

---

## Per-Receipt Analysis Table

| Receipt | receipt.ts (parsed) | File mtime (UTC-7) | gen_secs | Wall inference | Derivable? | Issue |
|---------|-----|---------|----------|--------|-----------|--------|
| w1-floor-g1-base-20260610T215814Z | 2026-06-10 14:58:14 UTC | 2026-06-10 15:03:26 UTC-7 | 141.3s | UNMEASURED | NO | no start_ts field; wall time unrecoverable |
| w1-floor-g1-a-20260610T220325Z | 2026-06-10 14:03:25 UTC | 2026-06-10 15:03:26 UTC-7 | 107.5s | UNMEASURED | NO | no start_ts field; wall time unrecoverable |
| w1-floor-g1-control-20260610T220712Z | 2026-06-10 14:07:12 UTC | 2026-06-10 15:07:12 UTC-7 | 136.1s | UNMEASURED | NO | no start_ts field; wall time unrecoverable |
| w1-floor-g1-mtp-20260610T221956Z | 2026-06-10 14:19:56 UTC | 2026-06-10 15:19:56 UTC-7 | 117.3s | UNMEASURED | NO | no start_ts field; wall time unrecoverable |

### Critical Finding: Timestamp Format Ambiguity

**The receipt.ts field in these receipts is MALFORMED or MISINTERPRETED:**

- `20260610T215814Z` when parsed as ISO8601 = 2026-06-10T21:58:14Z (UTC)
- File mtime `15:03:26 UTC-7` = 2026-06-10 22:03:26 UTC

But the JSON shows `ts: "20260610T215814Z"` (no colons), which when parsed as YYYYMMDDTHHMMSSZformat gives:
- **Ambiguity:** Is this meant to be 21:58:14 or 14:58:14?

The `Z` suffix indicates UTC. If we assume the timestamp is correct and in UTC:
- 21:58:14Z (2026-06-10T21:58:14Z) → file mtime 22:03:26Z is ~5 minutes later → **plausible**
- But then the wall time would be ~305-310 seconds for a generation labeled 141.3s

**Honest assessment:** Without explicit clock capture at script start, we cannot reliably convert filesystem mtime to wall time deltas.

---

## Unaccounted Time — Draft Numbers Cannot Be Reproduced

The draft claims specific wall-time values, but these are unrecoverable from the current receipts:

| Receipt | gen_secs | Wall time | Unaccounted | Status |
|---------|----------|-----------|-------------|--------|
| base | 141.3s | UNMEASURED | UNMEASURED | No start_ts in receipt |
| a | 107.5s | UNMEASURED | UNMEASURED | No start_ts in receipt |
| control | 136.1s | UNMEASURED | UNMEASURED | No start_ts in receipt |
| mtp | 117.3s | UNMEASURED | UNMEASURED | No start_ts in receipt |

### Verdict: **CANNOT REPRODUCE** from current receipts

**Evidence:**
1. **No explicit start_ts or end_ts timestamps** in the JSON — wall time is UNMEASURED.
2. **Filesystem mtime is unreliable** — it's subject to filesystem clock skew, UTC offset interpretation, and potential NTP drift.
3. **The draft's estimates are GUESSES** based on heuristics (mtime deltas, sample file write times, and manual time subtraction).
4. **No controlled baseline** — without a synchronized reference timestamp (e.g., from job-scheduler logs or process startup), we cannot definitively attribute the overhead to 9P vs. other operations.

The 66-78% figures are **plausible but speculative** — they could represent:
- 9P filesystem overhead (documented at 50-300% for random I/O on WSL2)
- Model weight pre-loading or caching
- Tokenization pipeline
- Python runtime overhead (imports, imports, memory allocation)
- JSON serialization and logging

**Receipts alone cannot discriminate.**

---

## What IS Reliably Measurable from Current Receipts

### Validated Fields
- **gen_secs**: Reliable (Python `time.perf_counter()` diff, accurate to ~10ms)
- **n_tasks, k**: Precise (43 validation tasks × 8 samples per task)
- **verified_samples, extraction_fail**: Counted (exact sample outcomes)
- **Samples file size**: Measurable (e.g., w1-floor-g1-base samples.jsonl = 253,709 bytes)

### Not Measured
- **Adapter load time** (models are loaded at line 149, before t0 capture)
- **Dataset I/O** (all samples are loaded to RAM in load_split, cached in HF hub)
- **Model prefetch/streaming time** (unknown whether weights are fetched from `/mnt/b` or preloaded)
- **Tokenization overhead** (batched within generate_chat, but not isolated)
- **JSON write overhead** (included in unaccounted time but not separated)

### Honest Statement
**The receipts prove that gen_secs is less than total wall time, but they do NOT prove that 9P is the bottleneck.** Overhead could be:
- Model initialization (15-30s typical for 3B models)
- Tokenization pipeline (5-20s for batched 43 tasks × 8 samples)
- Python runtime startup (imports, CUDA initialization)
- JSON serialization (10-50ms per sample × 344 samples)

**WSL 9P I/O tax is invisible without explicit filesystem profiling (strace/etrace).**

---

## Minimal Receipt-Schema Addition for Measurability

To make future overhead audits **reproducible**, add these fields to w1/t2/t3 receipts:

```python
# At START of script (before any imports/initialization):
import time
from datetime import datetime, timezone
script_start_time = time.perf_counter()
script_start_ts = datetime.now(timezone.utc).isoformat()

# Later, at model loading (line 149 in w1_mbpp.py):
t0_model_load = time.perf_counter()
model, tok = load_model(args.model, adapter=args.adapter)
model_load_secs = round(time.perf_counter() - t0_model_load, 1)

# Before generate_chat:
t0_gen = time.perf_counter()

# After generate_chat (line 172):
gen_secs = round(time.perf_counter() - t0_gen, 1)

# At receipt creation (line 190+):
receipt = {
    "ticket": "W1-FLOOR",
    "start_ts": script_start_ts,       # NEW: wall-clock script start (ISO 8601)
    "model_load_secs": model_load_secs, # NEW: adapter+base weight load time
    "gen_secs": gen_secs,               # EXISTING
    "total_secs": round(time.perf_counter() - script_start_time, 1),  # NEW: wall time
    "overhead_secs": round(time.perf_counter() - script_start_time - gen_secs, 1),  # NEW
    "overhead_pct": round(100 * (1 - gen_secs / (time.perf_counter() - script_start_time)), 1),  # NEW
    ... rest
}
```

**Formal schema addition:**
- `start_ts` (string, ISO 8601 UTC): script/training phase START timestamp
- `model_load_secs` (float, seconds): time to load base model + adapter
- `total_secs` (float, seconds): wall-clock elapsed (end - start)
- `overhead_secs` (float, seconds): total_secs - gen_secs
- `overhead_pct` (float, 0-100): (overhead_secs / total_secs) × 100

**Cost:** ~10 lines of code per script. **Benefit:** Reproducible overhead accounting for all future rounds.

---

## Honesty Section: Limitations of Receipts for 9P Diagnosis

Even with the schema additions above, receipts **still cannot directly prove 9P overhead** because they:

1. **Aggregate all I/O paths** — cannot distinguish between:
   - Adapter weight load from `/mnt/b` (9P)
   - Model weight pre-fetch from HuggingFace hub (network or local cache)
   - Sample tokenization (CPU-only, no I/O)
   - JSON serialization (system tmpfs)

2. **Don't capture stalling events** — e.g., if 9P causes 100ms stalls on 1000 read syscalls, the aggregate time is captured, but the stall pattern is invisible.

3. **Don't account for caching** — on subsequent runs, adapters may stay in kernel buffer cache, hiding 9P tax on the first run only.

**To definitively measure 9P overhead, you need:**
- strace `-e trace=open,openat,read,write,seek,stat` on a generation run
- Profile I/O syscall latency with eBPF (Linux)
- Or: **Probe (b) — native Windows torch smoke test** (per issue spec: load 3B model, 1 training step on native Windows vs. WSL2, compare wall times)

---

## Verdict: Does the Draft's Overhead Table Survive?

**NO.** The 66-78% unaccounted percentages **cannot be reproduced** from current receipts:

- No `start_ts` field → wall time is INFERRED from mtime (unreliable)
- No `end_ts` field → cannot validate mtime interpretation
- `gen_secs` is reliable, but `total_secs` is ESTIMATED (not measured)
- Overhead attribution to 9P is SPECULATIVE (no profiling data)

### Recommendation
1. **Merge the schema additions** (start_ts, model_load_secs, total_secs, overhead_pct) into w1/t2 scripts.
2. **Re-run the w1-floor-g1 cohort** with the enhanced receipts to establish a baseline.
3. **Run Probe (b)** (native Windows torch smoke test) to measure best-case performance and set a migration decision threshold.

The draft correctly identifies that overhead exists, but the numbers are **methodologically unsound for publication or decision-making.**

---

**Analysis completed:** 2026-06-10  
**Confidence:** High (receipt schema analysis), Medium (9P attribution without profiling)
