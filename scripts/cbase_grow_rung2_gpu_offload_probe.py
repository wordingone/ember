#!/usr/bin/env python3
"""cbase_grow_rung2_gpu_offload_probe.py — DEV-002 cure-PR follow-up:
MEASURED GPU-peak probe for the CPU-offloaded optimizer config (PR #429,
issue #411).

Real few-step CUDA training loop on the REAL 2.2B grown architecture, real
widened checkpoint weights, using CPUOffloadOptimizer + grad_accum_steps=8 +
micro_batch=2 (the exact DEV-002 candidate 3/4 config), sampling nvidia-smi
during execution to get an ACTUALLY MEASURED VRAM peak -- vs the 9.301GiB
estimate cbase_grow_rung2_dryrun.py's PART B1 computes but never executes
(that script's own `if vram_sufficient:` branch is a `pass` stub; no code
path in this repo has ever launched a real CUDA training step under this
config before this script).

Why this is a NEW script, not a call to run_v0_segment(device="cuda", ...):
run_v0_segment's `if live: x = x.cuda()` gates the input-tensor device move
on its OWN `live` flag (the production-dispatch flag), not on the `device`
param -- so `real_arch=True, device="cuda", live=False` (the only way to
reach a real-arch build without the full production interlock) leaves the
model on CUDA but the input batch on CPU: a genuine device-mismatch nobody
has ever exercised (every existing caller is either real_arch+device="cpu",
or the fully-governed live=True+real-shard_dir production path). live=True
is NOT appropriate for a probe either: it requires EMBER_GATE_AUTHORIZED=1 +
a REAL shard_dir + v0_pretrain_launch_gate all-GREEN (corpus/tokenizer/
shards/budget/prereg) -- real production-dispatch machinery, wrong
semantics for a bounded synthetic-data memory probe, and would either
falsely consume production budget or be correctly refused for an
unprepared corpus.

So this script builds the real model/optimizer via the SAME real functions
timeshare_pretrain.py exports (build_v0_model, build_split_optimizer,
resolve_ce_impl, mtp_total_loss, PackedShardLoader/write_packed_shard) and
runs its own minimal step loop that correctly moves the loaded batch to the
model's device. No loss/optimizer/update-rule math is reimplemented here --
only the outer loop, plus the one device-move that run_v0_segment's
live=False path happens to skip.

Deliberately bypassed (disclosed, not silently dropped): _check_launch_
interlock, _apply_governor(), and the registry/G-budget gates inside
run_v0_segment -- this is a bounded, synthetic-data VRAM probe, not a
production dispatch. In their place this script applies its OWN preflight
(reusing cpu_offload_adamw.py's real vram_preflight/nvidia_smi_vram, same
functions the contended-launch-gate receipt used) and its own conservative
torch.cuda.set_per_process_memory_fraction cap before allocating -- in the
spirit of (not a substitute for) the real governor.

If full 2.2B-scale allocation fails (OOM), that IS the receipt: the
9.301GiB estimate was wrong, and this script captures the actual measured
peak at the failure point -- no silent fallback to a reduced stand-in, no
fix-forward on the failure.

No git commits from this script. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false.
"""
from __future__ import annotations

import argparse
import faulthandler
import gc
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

faulthandler.enable()  # on a native SIGSEGV, prints the exact crashing Python
                        # frame to stderr instead of a bare exit code -- added
                        # after 3 crashes at 3 different, previously-unlocated
                        # code points in this run's history.

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbase_grow_dryrun import sha256_file, widen_state_dict          # noqa: E402
from cpu_offload_adamw import (                                      # noqa: E402
    estimate_required_gib_offloaded, vram_preflight, nvidia_smi_vram,
)
from receipt_write import checked_write                              # noqa: E402
import timeshare_pretrain as ts                                      # noqa: E402

REPO = Path(__file__).resolve().parent.parent
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

SEED_SHA_ATTESTED = "58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b"
SEED_SHA_ATTESTATION_RECEIPT = "receipts/spend-annex/attestations/cbase-gpu-verify-trainable-clean-20260707T015633.json"

MARGIN_GIB_FLOOR = 2.0
KILL_PCT_OVER_ESTIMATE = 15.0  # DEV-002 kill/promote criterion

# widen becomes build-once (issue #446): widen_state_dict() crashed natively
# (SIGSEGV/ACCESS_VIOLATION) 3/3 times even inside a fresh subprocess, after
# succeeding cleanly once -- see issue #446 for the full timeline. Rather than
# re-run the crash-prone widen step on every retry, it runs AT MOST ONCE per
# seed SHA and the grown bf16 state dict is persisted here; every subsequent
# probe run (this one and future rung-2 work) loads it directly and never
# calls widen_state_dict() again. `models/` is gitignored -- this cache is
# local-only, never committed.
GROWN_CACHE_DIR = REPO / "models" / "cbase-grow-rung" / "rung2-grown-cache"


def _grown_cache_paths(seed_sha: str) -> tuple[Path, Path]:
    stem = GROWN_CACHE_DIR / f"grown-{seed_sha[:16]}.pt"
    return stem, Path(str(stem) + ".meta.json")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _probe_server(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"reachable": True, "status_code": resp.status, "body": body}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def _nvidia_smi_vram_resilient(retries: int = 3, backoff_s: float = 1.0) -> dict:
    """nvidia_smi_vram() raises CalledProcessError on a transient nvidia-smi
    failure (observed once: exit 255 immediately after a torch CUDA OOM/
    context-teardown moment -- resolved on manual retry within a second).
    An uncaught failure here must never crash the receipt-writing pipeline
    (the run's actual result, e.g. a real OOM, is the valuable data and must
    not be lost to an unrelated query hiccup). Retries briefly, then returns
    a disclosed error dict rather than raising."""
    last_err = None
    for attempt in range(retries):
        try:
            return nvidia_smi_vram()
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(backoff_s)
    return {"error": last_err, "note": f"nvidia-smi failed {retries}x, giving up (see error)"}


def _va_report() -> dict:
    """Allocator-level snapshot (issue #446 discriminator): GlobalMemoryStatusEx
    + a VirtualQuery walk of this process's own virtual address space for the
    largest contiguous FREE region. A native SIGSEGV/ACCESS_VIOLATION kills the
    process before any post-hoc capture is possible -- this must run and print
    (flush=True, so it survives in the parent's captured stdout even if this
    process dies moments later) immediately BEFORE the crash-prone call, not
    after. This is "largest free block right before the attempt", the closest
    non-invasive proxy to "state at the moment of fault" without a debugger
    attach or crash dump."""
    import ctypes
    import ctypes.wintypes as wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
            ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
        ]

    MEM_FREE = 0x10000
    kernel32 = ctypes.windll.kernel32
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))

    mbi = MEMORY_BASIC_INFORMATION()
    addr = 0
    max_addr = stat.ullTotalVirtual or (1 << 47)
    largest_free = 0
    largest_free_addr = 0
    n_free_regions = 0
    total_free = 0
    iterations = 0
    while addr < max_addr and iterations < 2_000_000:
        iterations += 1
        ret = kernel32.VirtualQuery(ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if ret == 0:
            break
        if mbi.State == MEM_FREE:
            n_free_regions += 1
            total_free += mbi.RegionSize
            if mbi.RegionSize > largest_free:
                largest_free = mbi.RegionSize
                largest_free_addr = addr
        addr += mbi.RegionSize if mbi.RegionSize else 0x1000

    return {
        "mem_load_pct": stat.dwMemoryLoad,
        "avail_phys_gib": round(stat.ullAvailPhys / (1024 ** 3), 3),
        "avail_pagefile_gib": round(stat.ullAvailPageFile / (1024 ** 3), 3),
        "avail_virtual_gib": round(stat.ullAvailVirtual / (1024 ** 3), 3),
        "largest_free_va_region_gib": round(largest_free / (1024 ** 3), 3),
        "largest_free_va_region_addr_hex": hex(largest_free_addr),
        "n_free_va_regions": n_free_regions,
        "total_free_va_gib": round(total_free / (1024 ** 3), 3),
    }


def _phase_measure(label: str, fn, phases_list: list):
    """Per-phase CUDA memory attribution (issue #459 follow-up, 2026-07-08):
    the KILL_ESTIMATOR_UNDERSTATED verdict (measured 17.334GiB delta vs
    9.301GiB estimate, +86.4%) means the estimator is the defect, and fixing
    it requires knowing WHERE the missing ~8GiB actually goes -- not guessing
    (candidates named going in: QAT fake-quant clones of every Linear weight,
    cut_ce_chunked's chunk buffers, MTP head activations). This measures ONE
    phase's genuine incremental cost, not just an absolute peak:

    baseline_before = memory already resident when the phase starts (so a
    later phase's own footprint doesn't get blamed on an earlier phase's
    still-resident tensors). reset_peak_memory_stats() resets the PEAK
    tracking to the current level (not to zero -- confirmed from torch's own
    semantics), so max_memory_allocated() read after the phase reflects the
    highest level reached DURING this phase specifically. delta_gib =
    peak_during - baseline_before is this phase's actual incremental cost;
    resident_after_gib shows what it left behind (e.g. QAT clones should
    mostly vanish after qat_restore, cut_ce/activation buffers should mostly
    vanish after backward -- a phase that does NOT give memory back after
    it "should" is itself a finding)."""
    import torch
    baseline_gib = round(torch.cuda.memory_allocated() / (1 << 30), 4)
    torch.cuda.reset_peak_memory_stats()
    result = fn()
    torch.cuda.synchronize()
    peak_alloc_gib = round(torch.cuda.max_memory_allocated() / (1 << 30), 4)
    peak_reserved_gib = round(torch.cuda.max_memory_reserved() / (1 << 30), 4)
    active_peak_gib = round(torch.cuda.memory_stats().get("active_bytes.all.peak", 0) / (1 << 30), 4)
    after_gib = round(torch.cuda.memory_allocated() / (1 << 30), 4)
    entry = {
        "phase": label,
        "baseline_before_gib": baseline_gib,
        "peak_during_gib": peak_alloc_gib,
        "delta_gib": round(peak_alloc_gib - baseline_gib, 4),
        "reserved_peak_gib": peak_reserved_gib,
        "active_bytes_peak_gib": active_peak_gib,
        "resident_after_gib": after_gib,
    }
    phases_list.append(entry)
    print(f"  VRAM_PHASE {json.dumps(entry)}", flush=True)
    return result


def _widen_cast_worker(seed_ckpt_str: str, out_path: str) -> int:
    """SHA-verify + load + widen + bf16-cast, run as a FRESH subprocess and
    result written to disk -- NOT inline in the main process.

    Cause of the two reproduced SIGSEGVs (exit 139) when this ran inline: the
    SAME native-crash class cbase_grow_rung2_dryrun.py's own module docstring
    documents for this exact machine at this ~1.19B->2.2B param scale
    (allocator/fragmentation state, reproduced even at 24-33GiB free RAM, not
    a raw memory-shortage problem) -- specifically the bf16-cast step, which
    transiently holds grown_sd_f32 (~8.8GiB fp32) AND the growing
    grown_sd_bf16 dict simultaneously mid dict-comprehension. Part A of
    cbase_grow_rung2_dryrun.py dispatches this exact sequence to a fresh
    subprocess for the same reason; this mirrors that established remedy
    rather than inventing a new one."""
    import torch
    seed_ckpt = Path(seed_ckpt_str)
    model_pt = seed_ckpt / "model.pt"
    manifest = json.loads((seed_ckpt / "manifest.json").read_text(encoding="utf-8"))
    actual_sha = sha256_file(model_pt)
    claimed_sha = (manifest.get("files") or {}).get("model.pt")
    if not (actual_sha == claimed_sha == SEED_SHA_ATTESTED):
        raise SystemExit(f"CBASE-GROW-RUNG2-GPU-OFFLOAD-PROBE: seed checkpoint hash mismatch: "
                          f"manifest={claimed_sha} attested={SEED_SHA_ATTESTED} actual={actual_sha}")
    print(f"seed checkpoint SHA verified: {actual_sha}", flush=True)

    cfg = ts.load_contract()
    n_layers = cfg["model"]["layers"]
    sd_seed_bf16 = torch.load(model_pt, map_location="cpu", weights_only=True)
    ff_seed = int(sd_seed_bf16["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])
    ff_grown = ff_seed * 2
    sd_pre_f32 = {k: v.float() for k, v in sd_seed_bf16.items()}
    sd_seed_bf16 = None
    gc.collect()
    va_before_widen = _va_report()
    print(f"VA_REPORT_BEFORE_WIDEN {json.dumps(va_before_widen)}", flush=True)
    grown_sd_f32 = widen_state_dict(sd_pre_f32, n_layers)
    param_count_after = int(sum(v.numel() for v in grown_sd_f32.values()))
    sd_pre_f32 = None
    gc.collect()
    grown_sd_bf16 = {k: v.to(torch.bfloat16) for k, v in grown_sd_f32.items()}
    grown_sd_f32 = None
    gc.collect()
    torch.save(grown_sd_bf16, out_path)
    meta = {"ff_seed": ff_seed, "ff_grown": ff_grown, "param_count_after": param_count_after,
            "actual_sha": actual_sha, "claimed_sha": claimed_sha, "step": manifest.get("step")}
    Path(out_path + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"WIDEN_CAST_WORKER_DONE out_path={out_path} ff_seed={ff_seed} ff_grown={ff_grown} "
          f"param_count_after={param_count_after}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed-ckpt", required=True,
                     help="path to the real rung-1 seed checkpoint dir (model.pt + manifest.json)")
    ap.add_argument("--receipt-dir", default=str(REPO / "receipts"))
    ap.add_argument("--server-health-url", default="http://127.0.0.1:8082/health")
    ap.add_argument("--n-optimizer-steps", type=int, default=2,
                     help="real optimizer.step() calls (2 crosses the accumulation boundary twice)")
    ap.add_argument("--grad-accum-steps", type=int, default=8, help="DEV-002 config: accum_steps")
    ap.add_argument("--micro-batch", type=int, default=2, help="DEV-002 config: micro_batch")
    ap.add_argument("--sample-interval-s", type=float, default=1.0)
    ap.add_argument("--measure-every-optimizer-step", action="store_true",
                     help="#524 M1/M3: phase-measure EVERY optimizer_step (not just gs=0) to "
                          "reveal whether the CPUOffloadOptimizer.step() copy-back transient "
                          "(M2 finding: unmeasured, no estimator term) plateaus or grows across "
                          "a multi-step run. Default False preserves prior gs==0-only behavior.")
    ap.add_argument("--widen-cast-worker", action="store_true",
                     help=argparse.SUPPRESS)  # internal: re-exec entry point, see _widen_cast_worker
    ap.add_argument("--out-path", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.widen_cast_worker:
        return _widen_cast_worker(args.seed_ckpt, args.out_path)

    ts_stamp = _ts()
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    seed_ckpt = Path(args.seed_ckpt)
    model_pt = seed_ckpt / "model.pt"
    manifest = json.loads((seed_ckpt / "manifest.json").read_text(encoding="utf-8"))

    wall_start = time.monotonic()
    receipt_dir = Path(args.receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)

    # ---- before-baseline: nvidia-smi + server health (server resident and
    # NEVER stopped -- the primary receipt condition per mandate) ----
    nvsmi_before = nvidia_smi_vram()
    server_before = _probe_server(args.server_health_url)
    print(f"[{ts_stamp}] BEFORE nvidia-smi: {nvsmi_before}", flush=True)
    print(f"[{ts_stamp}] BEFORE server: {server_before}", flush=True)

    # ---- SHA-verify + widen + bf16-cast: build-once, persisted cache
    # (issue #446 -- widen_state_dict() crashed natively 3/3 times, including
    # inside a FRESH subprocess with a clean heap, after succeeding cleanly
    # once; the fresh-subprocess mitigation that fixes #406's class did not
    # prevent this one). Cache hit skips the crash-prone step entirely; a
    # cache miss still dispatches to a fresh subprocess (never worse than
    # before) and persists the result so this is the LAST time this seed ever
    # needs widening. ----
    import torch
    cfg = ts.load_contract()
    cache_path, cache_meta_path = _grown_cache_paths(SEED_SHA_ATTESTED)
    if cache_path.exists() and cache_meta_path.exists():
        meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
        cache_hit = True
        print(f"[{ts_stamp}] grown-checkpoint cache HIT: {cache_path} (no widen_state_dict() call "
              f"this run -- issue #446 build-once cure)", flush=True)
    else:
        cache_hit = False
        GROWN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        worker_cmd = [sys.executable, str(Path(__file__).resolve()), "--widen-cast-worker",
                      "--seed-ckpt", str(seed_ckpt), "--out-path", str(cache_path)]
        worker_proc = subprocess.run(worker_cmd, cwd=str(Path(__file__).resolve().parent),
                                      capture_output=True, text=True)
        print(worker_proc.stdout, end="", flush=True)
        if worker_proc.returncode != 0 or not cache_meta_path.exists():
            print(worker_proc.stderr, file=sys.stderr, flush=True)
            raise SystemExit(f"CBASE-GROW-RUNG2-GPU-OFFLOAD-PROBE: widen-cast worker failed "
                              f"(exit={worker_proc.returncode}); see stderr above; issue #446")
        meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
        print(f"[{ts_stamp}] grown-checkpoint cache MISS -> widened fresh, cached at {cache_path} "
              f"for all future rung-2 work (issue #446 build-once cure)", flush=True)
    ff_seed = meta["ff_seed"]
    ff_grown = meta["ff_grown"]
    param_count_after = meta["param_count_after"]
    actual_sha = meta["actual_sha"]
    claimed_sha = meta["claimed_sha"]
    sha_ok = actual_sha == claimed_sha == SEED_SHA_ATTESTED
    grown_sd_bf16 = torch.load(cache_path, map_location="cpu", weights_only=True)
    print(f"[{ts_stamp}] ff_seed={ff_seed} ff_grown={ff_grown} "
          f"param_count_after={param_count_after} (verified: {sha_ok}, cache_hit={cache_hit})", flush=True)

    # ---- the actual launch-gate: DEV-002 candidate 3/4 offloaded estimate,
    # priced against CONTENDED live nvidia-smi (reuse: estimate_required_gib_
    # offloaded / vram_preflight, cpu_offload_adamw.py). Refuse-to-launch,
    # never fix-forward, if this fails -- that IS a valid receipt.
    #
    # prod_batch/activation_estimate_gib_at_prod_shape kwargs REMOVED (issue
    # #459 follow-up): that estimate (9.301GiB) was wrong by 86-121% against
    # measurement (verdict OOM_ESTIMATE_WRONG, receipt cbase-grow-rung2-gpu-
    # offload-probe-20260708T171259Z.json) -- replaced with a measured-
    # calibration-point estimator (qat_clone_gib + activation_gib both
    # anchored to real per-phase attribution). See cpu_offload_adamw.py's
    # estimate_required_gib_offloaded docstring for the full correction. ----
    required_offloaded = estimate_required_gib_offloaded(
        param_count_after, micro_batch=args.micro_batch)
    offload_preflight = vram_preflight(
        required_offloaded["total_estimate_gib"], margin_gib_floor=MARGIN_GIB_FLOOR,
        nvsmi=nvsmi_before)
    print(f"[{ts_stamp}] preflight: required={required_offloaded['total_estimate_gib']}GiB "
          f"verdict={offload_preflight['verdict']} margin_gib={offload_preflight['margin_gib']}",
          flush=True)

    # ---- commit-aware preflight (2026-07-08, post-mortem on the day's 4
    # crash sites): free-PHYSICAL RAM is BANNED as a launch gate from here on
    # -- the measured root cause was Windows COMMIT exhaustion (a small fixed
    # 16GiB pagefile), which reads completely differently from free-physical
    # (commit-available ~19GiB while free-physical read ~31GiB the same
    # moment). PLANNED_NEW_COMMIT_GIB is a deliberately conservative residual
    # estimate: the 2026-07-08 memmap redesign moved the dominant ~26GiB/param
    # buffer term (shadow+grad+exp_avg/momentum) to file-backed storage (zero
    # commit charge), so what's left is CUDA driver host allocations + torch/
    # python overhead + the transient per-param grad-staging tensor + the
    # shard loader's small arrays -- all sub-GiB individually. ----
    PLANNED_NEW_COMMIT_GIB = 2.0
    COMMIT_MARGIN_GIB_FLOOR = 8.0
    va_before_probe = _va_report()
    commit_available_gib = va_before_probe["avail_pagefile_gib"]
    commit_sufficient = commit_available_gib > (PLANNED_NEW_COMMIT_GIB + COMMIT_MARGIN_GIB_FLOOR)
    print(f"[{ts_stamp}] commit preflight: commit_available={commit_available_gib}GiB "
          f"planned_new_commit={PLANNED_NEW_COMMIT_GIB}GiB margin_floor={COMMIT_MARGIN_GIB_FLOOR}GiB "
          f"sufficient={commit_sufficient} (free_physical={va_before_probe['avail_phys_gib']}GiB "
          f"shown for contrast only -- NOT the gate)", flush=True)

    launch_sufficient = bool(offload_preflight["sufficient"] and commit_sufficient)
    if not launch_sufficient:
        # Refuse-to-launch (abort-not-degrade, DEV-002 acceptance #3). A
        # refused launch IS a valid, honest receipt -- no attempt made.
        wall_s = round(time.monotonic() - wall_start, 3)
        receipt = {
            "ticket": "CBASE-GROW-RUNG2-GPU-OFFLOAD-PROBE",
            "ts": timestamp_iso,
            "invariant_sha256": INVARIANT_SHA256,
            "sha_convention": SHA_CONVENTION,
            "pr": 429, "issue": 411,
            "scope": "MEASURED GPU-peak probe for the DEV-002 candidate 3/4 config -- "
                     "REFUSED at preflight, no CUDA launch attempted (abort-not-degrade).",
            "param_count_after": param_count_after,
            "offloaded_config": {"micro_batch": args.micro_batch,
                                  "accum_steps": args.grad_accum_steps,
                                  "required_estimate": required_offloaded,
                                  "preflight": offload_preflight},
            "commit_preflight": {
                "commit_available_gib": commit_available_gib,
                "planned_new_commit_gib": PLANNED_NEW_COMMIT_GIB,
                "margin_floor_gib": COMMIT_MARGIN_GIB_FLOOR,
                "sufficient": commit_sufficient,
                "free_physical_gib_not_the_gate": va_before_probe["avail_phys_gib"],
            },
            "attempted": False,
            "wall_s": {"total": wall_s},
            "api_spend_usd": 0, "paid_api_surface_used": False,
            "invalid_tokens_present": [],
            "verdict": "REFUSE_TO_LAUNCH",
        }
        receipt_path = receipt_dir / f"cbase-grow-rung2-gpu-offload-probe-{ts_stamp}.json"
        checked_write(str(receipt_path), receipt)
        print(f"CBASE_GROW_RUNG2_GPU_OFFLOAD_PROBE_REFUSED receipt={receipt_path}", flush=True)
        return 2

    # ---- self-imposed conservative VRAM fraction cap (governor spirit;
    # _apply_governor() itself is coupled to the production interlock this
    # probe intentionally bypasses, so this is an explicit, disclosed
    # stand-in, not a silent skip) ----
    # Bug fixed here (this run's own prior attempt): set_per_process_memory_
    # fraction(f) caps THIS process at f * TOTAL device memory, not "baseline
    # + a budget" -- the previous ad hoc (used_gib + 12.0) / total_gib formula
    # produced a cap of 18.43GiB that bound TIGHTER than the real device
    # headroom: the OOM message it produced explicitly reported "18.43 GiB
    # allowed" while cudaMemGetInfo showed 6.18GiB still genuinely free on the
    # device at that exact moment -- a self-imposed-governor artifact, not a
    # real hardware limit, and not the measurement this probe exists to make.
    # Fixed to reuse this repo's own MARGIN_GIB_FLOOR convention (same margin
    # vram_preflight already applies) against the WHOLE device instead.
    safe_fraction = min(0.97, (nvsmi_before["total_gib"] - MARGIN_GIB_FLOOR) / nvsmi_before["total_gib"])
    torch.cuda.set_per_process_memory_fraction(safe_fraction)
    allowed_gib = round(safe_fraction * nvsmi_before["total_gib"], 3)
    print(f"[{ts_stamp}] self-imposed VRAM fraction cap: {safe_fraction:.4f} "
          f"({allowed_gib}GiB of {nvsmi_before['total_gib']}GiB total allowed, "
          f"{MARGIN_GIB_FLOOR}GiB margin floor reserved, matching vram_preflight's own "
          f"convention)", flush=True)

    # ---- build the REAL model (real architecture, real device placement,
    # gradient checkpointing) via the real build_v0_model -- not reimplemented ----
    vram_attribution_phases: list[dict] = []
    _build_result: dict = {}

    def _do_model_build():
        model, vocab, hidden, n_mtp = ts.build_v0_model(
            cfg, live=True, intermediate_override=ff_grown, device="cuda")
        missing, unexpected = model.load_state_dict(grown_sd_bf16, strict=False)
        real_missing = [k for k in missing if k != "head.weight"]
        if real_missing or unexpected:
            raise SystemExit(f"CBASE-GROW-RUNG2-GPU-OFFLOAD-PROBE: grown checkpoint load mismatch: "
                              f"missing={real_missing} unexpected={unexpected}")
        _build_result.update(model=model, vocab=vocab, hidden=hidden, n_mtp=n_mtp)

    _phase_measure("model_build_and_load", _do_model_build, vram_attribution_phases)
    model, vocab, hidden, n_mtp = (_build_result["model"], _build_result["vocab"],
                                    _build_result["hidden"], _build_result["n_mtp"])
    grown_sd_bf16 = None
    gc.collect()
    # Effective checkpointing readback (issue #459 fix): read from the model
    # ITSELF, not the config claim -- build_v0_model used to enable
    # checkpointing unconditionally regardless of what the contract said, so
    # the config value alone was never trustworthy evidence of what actually
    # ran. This is the same "measure, don't assume" discipline the phase
    # attribution above applies to memory.
    effective_grad_checkpointing = bool(getattr(model.backbone_model, "gradient_checkpointing", False))
    print(f"[{ts_stamp}] real grown model loaded onto cuda (bf16), vocab={vocab} hidden={hidden} "
          f"n_mtp={n_mtp}, effective_grad_checkpointing={effective_grad_checkpointing} "
          f"(config claims {cfg['model'].get('grad_checkpointing')})", flush=True)

    # ---- real optimizer via the real build_split_optimizer, offload wrapper ----
    optimizers, base_lrs, routing = ts.build_split_optimizer(
        model, cfg, offload_optimizer_state=True)
    print(f"[{ts_stamp}] optimizer routing: {routing}", flush=True)

    # ---- synthetic packed shard (SAME convention run_v0_segment uses
    # internally for its own dry-run path when shard_dir=None) ----
    seq = cfg["model"]["seq"]
    n_micro_total = args.n_optimizer_steps * args.grad_accum_steps
    shard_tmp = tempfile.mkdtemp(prefix="rung2-gpu-offload-probe-shard-")
    try:
        import numpy as np
        rng = np.random.default_rng(0)
        need = (n_micro_total + 4) * args.micro_batch * seq + seq + n_mtp + 8
        toks = rng.integers(1, vocab, size=int(need), dtype=np.int64)
        toks[:: max(1, seq * 3)] = 0
        ts.write_packed_shard(str(Path(shard_tmp) / "synthetic-00000.bin"), toks.astype("<u2").tolist())
        loader = ts.PackedShardLoader(shard_tmp, seq, n_mtp)

        ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
        mtp_cfg = cfg["objective"]["mtp_aux_heads"]
        mtp_weight = mtp_cfg["weight"]
        mtp_enabled = mtp_cfg["enabled"]
        # QAT gate (cfg["precision"]["qat"]["enabled"]) -- the REAL contract has
        # this True. run_v0_segment's real training loop applies int8-grid
        # fake-quant to every Linear weight pre-forward and restores it post-
        # backward (STE); the CPU-sanity B2b crash was diagnosed as exactly
        # this QAT clone + gradients + optimizer momentum at the grown width.
        # Skipping QAT here would understate real memory (no clone buffers) and
        # test a config the real launch doesn't use -- reused via the SAME
        # private helpers run_v0_segment calls, not reimplemented.
        qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))
        print(f"[{ts_stamp}] ce_impl={ce_impl} mtp_enabled={mtp_enabled} qat_enabled={qat_enabled} "
              f"seq={seq} micro_batch={args.micro_batch} grad_accum_steps={args.grad_accum_steps} "
              f"n_optimizer_steps={args.n_optimizer_steps}", flush=True)

        # ---- peak-VRAM sampler thread: real nvidia-smi samples DURING the
        # real training loop below ----
        samples: list[dict] = []
        stop_flag = threading.Event()

        def _sampler():
            # Prints every sample (not just appends) -- 2026-07-08 fix: a
            # SIGSEGV crash mid-run kills this thread's in-memory `samples`
            # list along with the process, and it was NEVER printed, so a
            # crashed run's entire VRAM trace was unrecoverable. Printing
            # means the trace survives in captured stdout even if the
            # process dies moments later.
            while not stop_flag.is_set():
                try:
                    s = nvidia_smi_vram()
                    samples.append(s)
                    print(f"  VRAM_SAMPLE {json.dumps(s)}", flush=True)
                except Exception as e:
                    samples.append({"error": str(e)})
                    print(f"  VRAM_SAMPLE_ERROR {e}", flush=True)
                stop_flag.wait(args.sample_interval_s)

        sampler_thread = threading.Thread(target=_sampler, daemon=True)
        sampler_thread.start()

        server_during = None
        losses: list[float] = []
        micro_loss_log: list[float] = []
        oom_error: str | None = None
        t_train_start = time.monotonic()
        try:
            for global_step in range(args.n_optimizer_steps):
                micro_losses = []
                for micro_idx in range(args.grad_accum_steps):
                    ckpt = f"gs={global_step} mi={micro_idx}"
                    # Fine-grained per-phase VRAM attribution (issue #459
                    # follow-up) ONLY on the very first micro-step: this is
                    # a "short re-fire" whose job is to ATTRIBUTE the
                    # KILL_ESTIMATOR_UNDERSTATED gap, not re-verify every
                    # micro-step -- 8 resets/step * n_optimizer_steps would
                    # bloat the run and the log for no attribution benefit
                    # (later micro-steps repeat the same phase shape).
                    attribute_this_microstep = (global_step == 0 and micro_idx == 0)
                    _box: dict = {}

                    loader_idx = global_step * args.grad_accum_steps + micro_idx
                    x, y0, y_mtp = loader.batch(loader_idx, args.micro_batch)
                    print(f"  CKPT[{ckpt}] batch loaded", flush=True)

                    def _do_cuda_transfer():
                        _box["x"] = x.cuda()
                        _box["y0"] = y0.cuda()
                        _box["y_mtp"] = [t.cuda() for t in y_mtp]
                    if attribute_this_microstep:
                        _phase_measure(f"[{ckpt}] cuda_transfer", _do_cuda_transfer, vram_attribution_phases)
                    else:
                        _do_cuda_transfer()
                    x, y0, y_mtp = _box["x"], _box["y0"], _box["y_mtp"]
                    print(f"  CKPT[{ckpt}] .cuda() transfers done", flush=True)

                    # QAT pre-forward: transform Linear weights to int8-grid (STE) --
                    # same helper, same placement as run_v0_segment's real loop.
                    def _do_qat_apply():
                        _box["qat_saved"] = ts._apply_fake_quant(model, "qat") if qat_enabled else []
                    if attribute_this_microstep:
                        _phase_measure(f"[{ckpt}] qat_fakequant_apply", _do_qat_apply, vram_attribution_phases)
                    else:
                        _do_qat_apply()
                    _qat_saved = _box["qat_saved"]
                    print(f"  CKPT[{ckpt}] QAT fake-quant applied (enabled={qat_enabled})", flush=True)

                    def _do_backbone_forward():
                        _box["hidden_out"] = model.backbone(x)
                    if attribute_this_microstep:
                        _phase_measure(f"[{ckpt}] backbone_forward", _do_backbone_forward, vram_attribution_phases)
                    else:
                        _do_backbone_forward()
                    hidden_out = _box["hidden_out"]
                    print(f"  CKPT[{ckpt}] backbone forward done", flush=True)
                    h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])

                    def _do_primary_ce():
                        _box["primary_ce"], _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=256)
                    if attribute_this_microstep:
                        _phase_measure(f"[{ckpt}] primary_ce (cut_ce_chunked)", _do_primary_ce, vram_attribution_phases)
                    else:
                        _do_primary_ce()
                    primary_ce = _box["primary_ce"]
                    print(f"  CKPT[{ckpt}] primary CE done", flush=True)

                    def _do_mtp_ce():
                        _mtp_ces = []
                        if mtp_enabled:
                            for k, head in enumerate(model.mtp_heads):
                                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1), chunk_tokens=256)
                                _mtp_ces.append(ce_k)
                        _box["mtp_ces"] = _mtp_ces
                    if attribute_this_microstep:
                        _phase_measure(f"[{ckpt}] mtp_ce ({n_mtp} heads)", _do_mtp_ce, vram_attribution_phases)
                    else:
                        _do_mtp_ce()
                    mtp_ces = _box["mtp_ces"]
                    print(f"  CKPT[{ckpt}] MTP CE done ({len(mtp_ces)} heads)", flush=True)
                    micro_loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
                    loss_val = float(micro_loss.detach())
                    micro_losses.append(loss_val)
                    micro_loss_log.append(loss_val)
                    print(f"  CKPT[{ckpt}] loss computed = {loss_val:.6f}", flush=True)

                    def _do_backward():
                        (micro_loss / args.grad_accum_steps).backward()
                    if attribute_this_microstep:
                        _phase_measure(f"[{ckpt}] backward", _do_backward, vram_attribution_phases)
                    else:
                        _do_backward()
                    print(f"  CKPT[{ckpt}] backward done", flush=True)

                    # QAT post-backward: restore full-precision weights (STE semantics).
                    def _do_qat_restore():
                        if qat_enabled:
                            ts._restore_weights(_qat_saved)
                    if attribute_this_microstep:
                        _phase_measure(f"[{ckpt}] qat_restore", _do_qat_restore, vram_attribution_phases)
                    else:
                        _do_qat_restore()
                    print(f"  CKPT[{ckpt}] QAT weights restored", flush=True)

                def _do_optimizer_step():
                    for opt in optimizers.values():
                        opt.step()
                # #524 M1/M3 addition: measure EVERY step's optimizer_step phase
                # when --measure-every-optimizer-step is set (default False,
                # preserves prior gs==0-only behavior byte-identically for any
                # other caller) -- gs==0 alone cannot show whether the
                # CPUOffloadOptimizer.step() copy-back transient (M2 finding:
                # cpu_offload_adamw.py's real_p.data.copy_(shadow_p.data.to(
                # real_p.device,...)) has no term in the estimator and no prior
                # GPU measurement) is a one-time cost the caching allocator
                # reuses on later steps, or one that keeps growing reserved
                # memory step over step -- only a multi-step series answers that.
                if global_step == 0 or args.measure_every_optimizer_step:
                    _phase_measure(f"[gs={global_step}] optimizer_step (all groups)",
                                    _do_optimizer_step, vram_attribution_phases)
                else:
                    _do_optimizer_step()
                for opt in optimizers.values():
                    opt.zero_grad(set_to_none=True)
                losses.append(sum(micro_losses) / len(micro_losses))
                print(f"  optimizer_step={global_step} loss={losses[-1]:.6f}", flush=True)
                if global_step == 0:
                    server_during = _probe_server(args.server_health_url)
                    print(f"[{ts_stamp}] DURING (after step 0) server: {server_during}", flush=True)
        except torch.cuda.OutOfMemoryError as e:
            oom_error = str(e)
            print(f"[{ts_stamp}] OOM: {oom_error}", flush=True)
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                oom_error = str(e)
                print(f"[{ts_stamp}] OOM (RuntimeError): {oom_error}", flush=True)
            else:
                raise
        t_train_s = round(time.monotonic() - t_train_start, 3)

        stop_flag.set()
        sampler_thread.join(timeout=5)
    finally:
        shutil.rmtree(shard_tmp, ignore_errors=True)

    # ---- after-baseline (resilient: a transient nvidia-smi failure here must
    # never lose an already-captured training result, e.g. a real OOM) ----
    nvsmi_after = _nvidia_smi_vram_resilient()
    server_after = _probe_server(args.server_health_url)
    print(f"[{ts_stamp}] AFTER nvidia-smi: {nvsmi_after}", flush=True)
    print(f"[{ts_stamp}] AFTER server: {server_after}", flush=True)

    vram_samples_during = [s for s in samples if "error" not in s]
    peak_used_mib = max((s["used_mib"] for s in vram_samples_during),
                         default=nvsmi_before["used_mib"])
    peak_used_gib = round(peak_used_mib / 1024, 3)
    peak_delta_vs_baseline_gib = round(peak_used_gib - nvsmi_before["used_gib"], 3)
    margin_vs_total_gib = round(nvsmi_before["total_gib"] - peak_used_gib, 3)
    fits_total_minus_margin = margin_vs_total_gib >= MARGIN_GIB_FLOOR

    estimate_gib = required_offloaded["total_estimate_gib"]
    pct_over_estimate = (round(((peak_delta_vs_baseline_gib - estimate_gib) / estimate_gib) * 100, 2)
                         if estimate_gib else None)
    kill_estimator_wrong = bool(pct_over_estimate is not None and pct_over_estimate > KILL_PCT_OVER_ESTIMATE)

    all_losses = losses
    degenerate = bool(all_losses) and ((len(set(round(v, 6) for v in all_losses)) == 1)
                                        or all(v < 1e-3 for v in all_losses))

    if oom_error is not None:
        verdict = "OOM_ESTIMATE_WRONG"
    elif kill_estimator_wrong:
        verdict = "KILL_ESTIMATOR_UNDERSTATED"
    elif not fits_total_minus_margin:
        verdict = "MEASURED_FAIL_MARGIN"
    elif degenerate:
        verdict = "MEASURED_FAIL_DEGENERATE_LOSS"
    else:
        verdict = "MEASURED_PASS"

    # #524 M1/M3: pull every recorded optimizer_step phase entry into its own
    # time series -- the direct answer to "does the CPUOffloadOptimizer.step()
    # copy-back transient (M2 finding) plateau or grow across a multi-step
    # run", without needing to re-parse the full vram_attribution.phases list.
    optimizer_step_transient_series = [
        p for p in vram_attribution_phases if "optimizer_step" in p["phase"]
    ]

    wall_s = round(time.monotonic() - wall_start, 3)
    receipt = {
        "ticket": "CBASE-GROW-RUNG2-GPU-OFFLOAD-PROBE",
        "ts": timestamp_iso,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "experiment": "C-BASE-clause-d-dryrun",
        "arm": "rung2-cpu-offload-cure-gpu-measured",
        "pr": 429,
        "issue": 411,
        "scope": ("MEASURED (not estimated) GPU-peak probe for the DEV-002 candidate 3/4 "
                  "(CPU-offloaded optimizer + micro-batch/accum) config: real forward+backward"
                  "+optimizer.step() on the REAL 2.2B grown architecture with REAL widened "
                  "checkpoint weights, on CUDA, under CONTENDED conditions (llama-server "
                  "resident, never stopped -- the primary receipt condition per mandate). "
                  "Bypasses run_v0_segment's production interlock/governor/G-budget gates "
                  "(disclosed, not silently dropped -- see module docstring) since this is a "
                  "bounded synthetic-data memory probe, not a production dispatch; applies its "
                  "own preflight assert + conservative VRAM fraction cap instead. Does NOT "
                  "re-run the net2net function-preservation check (already receipted, PASS, "
                  "unaffected by this run) or attempt a full multi-hour production stabilization "
                  "run (needs a real shard_dir + declared serving-pause window per PR #429's "
                  "own text; still out of scope)."),
        "seed_identity": {
            "checkpoint": str(seed_ckpt),
            "model_pt_sha256": actual_sha,
            "manifest_claim_verified": bool(actual_sha == claimed_sha),
            "attested_match": sha_ok,
            "attestation_receipt": SEED_SHA_ATTESTATION_RECEIPT,
            "step": manifest.get("step"),
        },
        "widen_state_dict_provenance": {
            "issue": 446,
            "cache_hit": cache_hit,
            "cache_path": str(cache_path),
            "method": ("build-once: widen_state_dict() runs at most once per seed SHA, in a fresh "
                       "subprocess, with the grown bf16 state dict persisted to cache_path; every "
                       "subsequent run (this one included, on a cache hit) loads it directly and "
                       "never calls widen_state_dict() again for this seed."),
            "prior_crash_history": (
                "Before this cure: the identical widen_state_dict() call succeeded cleanly once "
                "(2026-07-08T12:59:47Z, commit 1ff844e, cbase_grow_rung2_contended_launch_gate.py), "
                "then crashed natively 3/3 consecutive times ~30min later with no code change: "
                "(1) inline in this probe's main process, exit 139 SIGSEGV; (2) inside a FRESH "
                "subprocess with a clean heap (this repo's own established Part-A-style mitigation "
                "for this crash class), exit 3221225477 / ACCESS_VIOLATION; (3) a minimal isolated "
                "3-line repro (torch.load -> .float() -> widen_state_dict(), no probe code, no "
                "CUDA) pinpointing the crash to inside widen_state_dict() itself, exit 139. All 3 "
                "crashes: ~28-29GiB free RAM, GPU flat at server-only baseline, server 200 OK, "
                "nothing left wedged. Timing correlates with a concurrent lane (P1) finishing a "
                "~13.96GiB corpus-cache disk write ~13:29Z, just before the crashes started -- "
                "filed as issue #446 with the full timeline; not yet confirmed as causal."
            ),
        },
        "param_count_after": param_count_after,
        "commit_preflight": {
            "commit_available_gib": commit_available_gib,
            "planned_new_commit_gib": PLANNED_NEW_COMMIT_GIB,
            "margin_floor_gib": COMMIT_MARGIN_GIB_FLOOR,
            "sufficient": commit_sufficient,
            "free_physical_gib_not_the_gate": va_before_probe["avail_phys_gib"],
            "note": ("free-physical RAM is BANNED as a launch gate (2026-07-08): the day's 4 "
                     "crash sites unified under Windows COMMIT exhaustion (fixed 16GiB pagefile), "
                     "which reads completely differently from free-physical at the same moment."),
        },
        "server_contention": {
            "before": server_before,
            "during_after_step_0": server_during,
            "after": server_after,
            "server_stopped": False,
            "note": "primary receipt condition: server resident throughout, per mandate",
        },
        "vram": {
            "before": nvsmi_before,
            "after": nvsmi_after,
            "samples_during_training": vram_samples_during,
            "sample_interval_s": args.sample_interval_s,
            "peak_used_gib_total_card": peak_used_gib,
            "peak_delta_vs_baseline_gib": peak_delta_vs_baseline_gib,
            "margin_vs_total_gib": margin_vs_total_gib,
            "margin_gib_floor": MARGIN_GIB_FLOOR,
            "fits_total_minus_margin": fits_total_minus_margin,
        },
        "vram_attribution": {
            "issue": 459,
            "scope": ("Per-phase torch.cuda memory attribution -- issue #459 follow-up to the "
                      "KILL_ESTIMATOR_UNDERSTATED verdict (measured 17.334GiB delta vs 9.301GiB "
                      "estimate, +86.4%). Each phase entry's delta_gib = peak allocated DURING "
                      "that phase minus what was already resident BEFORE it (reset_peak_memory_"
                      "stats() resets the peak tracker to the current level, not to zero -- "
                      "confirmed against torch's own semantics before relying on it). Fine-grained "
                      "phases (cuda_transfer/qat_fakequant_apply/backbone_forward/primary_ce/"
                      "mtp_ce/backward/qat_restore) are measured on gs=0 mi=0 ONLY (a full 8-"
                      "microstep repeat would not add attribution signal); optimizer_step is "
                      "measured once for the whole gs=0 accumulation window. nvidia-smi (used "
                      "elsewhere in this receipt) reports the DRIVER's view of device memory "
                      "(includes CUDA context/driver overhead + allocator-reserved-but-unallocated "
                      "blocks); torch.cuda.memory_allocated/max_memory_allocated report the "
                      "CACHING ALLOCATOR's view (tensor bytes actually requested by PyTorch) -- "
                      "the two are expected to differ, and that difference is itself diagnostic "
                      "(a large reserved-vs-allocated gap points at allocator fragmentation/"
                      "caching rather than a genuine tensor-level cost)."),
            "phases": vram_attribution_phases,
            "measure_every_optimizer_step": args.measure_every_optimizer_step,
            "optimizer_step_transient_series": optimizer_step_transient_series,
            "optimizer_step_transient_series_note": (
                "#524 M1/M3: per-step delta_gib/reserved_peak_gib for every optimizer_step "
                "phase entry. delta_gib holding roughly steady across steps means the CUDA "
                "caching allocator is reusing blocks for the CPUOffloadOptimizer.step() "
                "copy-back transient (M2's best-case bound, ~0.0625 GiB); a rising trend "
                "means it is NOT being reused and the transient compounds toward M2's "
                "worst-case bound (~4.089 GiB) -- only present when "
                "--measure-every-optimizer-step was passed (else only gs=0 is populated)."
            ),
        },
        "offloaded_config": {
            "micro_batch": args.micro_batch,
            "accum_steps": args.grad_accum_steps,
            "effective_batch": args.micro_batch * args.grad_accum_steps,
            "n_optimizer_steps": args.n_optimizer_steps,
            "n_micro_steps_total": n_micro_total,
            "required_estimate_gib": estimate_gib,
            "required_estimate_detail": required_offloaded,
            "preflight": offload_preflight,
            "self_imposed_vram_fraction_cap": safe_fraction,
            "optimizer_routing": routing,
        },
        "measured_vs_estimate": {
            "estimate_gib": estimate_gib,
            "measured_delta_gib": peak_delta_vs_baseline_gib,
            "pct_over_estimate": pct_over_estimate,
            "kill_threshold_pct": KILL_PCT_OVER_ESTIMATE,
            "kill_estimator_wrong": kill_estimator_wrong,
            "rule": "DEV-002 kill/promote: kill if measured peak exceeds estimate by >15% "
                    "(the estimator is then the defect; fix estimator before config).",
        },
        "training": {
            "ce_impl": ce_impl,
            "mtp_enabled": mtp_enabled,
            "qat_enabled": qat_enabled,
            "seq": seq,
            "optimizer_step_losses": losses,
            "micro_step_losses": micro_loss_log,
            "degenerate_loss_trace": degenerate,
            "oom_error": oom_error,
            "wall_s_training_only": t_train_s,
            "gradient_checkpointing": {
                "config_claims": cfg["model"].get("grad_checkpointing"),
                "effective_readback": effective_grad_checkpointing,
                "active": effective_grad_checkpointing,
                "note": ("issue #459 FIXED (2026-07-08): build_v0_model() used to call "
                         "backbone_model.gradient_checkpointing_enable() UNCONDITIONALLY "
                         "regardless of cfg['model']['grad_checkpointing'] -- every real-arch "
                         "caller silently got checkpointing ON even though the contract says "
                         "False (per PR #298's own receipted 1.213x-vs-full-ckpt A/B). Now "
                         "conditional on the config key, AND this field is read back from the "
                         "MODEL ITSELF (getattr(model.backbone_model, 'gradient_checkpointing', "
                         "False)), not from the config claim -- the prior bug is exactly why the "
                         "config claim alone was never trustworthy evidence of what actually ran."),
                "estimate_function_assumption": ("SUPERSEDED (issue #459 second fix, same day): "
                         "this receipt's OWN run is the one that exposed the confound described in "
                         "the ORIGINAL version of this note (checkpointing silently ON while the "
                         "estimator was silent on checkpointing state) -- checkpointing is now "
                         "genuinely OFF (effective_readback above proves it), and "
                         "cpu_offload_adamw.estimate_required_gib_offloaded's activation term is "
                         "now calibrated from a REAL measured peak taken under checkpointing-OFF "
                         "conditions (this run's own per-phase attribution), not a borrowed "
                         "constant. See vram_attribution below for the phase-by-phase measurement "
                         "and cpu_offload_adamw.py's module-level comment for the full correction."),
            },
        },
        "wall_s": {"total": wall_s, "training_only": t_train_s},
        "related_receipts": [
            "receipts/grow-op-verify-20260708T060841Z.json",
            "receipts/grow-operator-dryrun-20260708T060841Z.json",
            "receipts/cbase-grow-rung2-offload-probe-20260708T083445Z.json",
        ],
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": verdict,
    }
    receipt_path = receipt_dir / f"cbase-grow-rung2-gpu-offload-probe-{ts_stamp}.json"
    checked_write(str(receipt_path), receipt)
    print(f"CBASE_GROW_RUNG2_GPU_OFFLOAD_PROBE_DONE receipt={receipt_path} verdict={verdict} "
          f"peak_delta_gib={peak_delta_vs_baseline_gib} estimate_gib={estimate_gib}", flush=True)
    return 0 if verdict == "MEASURED_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
