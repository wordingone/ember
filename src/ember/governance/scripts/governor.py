# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# issue: #898 packet-2 A VRAM wall

"""governor — the resource governor as a module (eng #9).

The launch preconditions that keep this PC alive (post-crash 0670e3ec,
user headroom rule 2026-06-10) currently live as duplicated inline blocks
in t1_probe.load_model, t2_round.train_lora, t2_grpo, t2_mtp. This module
is the single canonical copy. Semantics are byte-equivalent to the inline
blocks — extraction changes WHERE the floor lives, never what it asserts:

  1. Hard per-process VRAM fraction cap (EMBER_VRAM_FRACTION, default 0.85)
  2. Free-VRAM margin assert BEFORE any load (EMBER_VRAM_MARGIN_GB, 4.0)
     — refuse the launch, never fix-forward
  3. Step throttle (EMBER_THROTTLE_S, 0.3) — never pegged wall-to-wall
  4. (decode pacing lives in t1_probe.decode_pacer — generation-side twin)

preflight() additionally RETURNS a receipt block {frac, free_gb, total_gb,
margin_gb} so governor evidence rides on every receipt instead of being
asserted in prose.

Wiring discipline (issue #9: "file now, wiring post-chain"): t2_grpo wires
now (never launched); t1_probe / t2_round / t2_mtp keep their inline
blocks until the live W-code chain completes — editing modules under a
staged/running job chain is the registered hazard. Wait-window item:
swap the three inline blocks for governor.preflight() post-chain, diff
asserting byte-equivalent semantics.

Selftest (Windows-safe, no torch): env parsing + receipt-block shape, plus
the device-adaptive precision ladder (device_capability / select_precision /
device_relative_threshold -- pure Python, no torch import needed for these
three), plus the in-run commit governor (commit_env_limit /
estimate_checkpoint_mapped_bytes / _commit_status / commit_margin_preflight
-- also pure Python, ctypes only on win32). fp8_matmul_with_fallback is
torch-importing (CPU or GPU tensors) and is covered separately by
src/ember/governance/scripts/test_governor.py (pytest).
"""

import os
import sys
import time
import uuid


_DAEMON_VRAM_ENV = (
    "EMBER_LAB_DISPATCH_VRAM_PROVIDER",
    "EMBER_LAB_DISPATCH_VRAM_DEVICE_UUID",
    "EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS",
    "EMBER_LAB_DISPATCH_MAXIMUM_PROCESS_VRAM_BYTES",
    "EMBER_LAB_DISPATCH_MINIMUM_FREE_VRAM_BYTES",
)


def daemon_vram_contract():
    """Return the complete daemon-stamped VRAM contract, or None.

    Partial/caller-shaped contracts fail closed. The fraction is explicitly
    the torch caching-allocator ceiling; the daemon's external PID/UUID
    sentinel remains load-bearing for non-torch CUDA allocations.
    """
    present = [name for name in _DAEMON_VRAM_ENV if os.environ.get(name, "").strip()]
    if not present:
        return None
    if len(present) != len(_DAEMON_VRAM_ENV):
        missing = next(name for name in _DAEMON_VRAM_ENV if name not in present)
        raise RuntimeError(f"VRAM-WALL: incomplete daemon contract; missing {missing}")
    provider = os.environ[_DAEMON_VRAM_ENV[0]]
    device_uuid = os.environ[_DAEMON_VRAM_ENV[1]]
    if provider != "nvidia_smi_nvml" or not device_uuid.startswith("GPU-"):
        raise RuntimeError("VRAM-WALL: invalid daemon provider/device identity")
    parsed = {}
    for name, maximum in (
        (_DAEMON_VRAM_ENV[2], 1_000_000),
        (_DAEMON_VRAM_ENV[3], 2**64 - 1),
        (_DAEMON_VRAM_ENV[4], 2**64 - 1),
    ):
        raw = os.environ[name]
        try:
            value = int(raw)
        except ValueError as error:
            raise RuntimeError(f"VRAM-WALL: {name} is not an integer") from error
        if value <= 0 or value > maximum or str(value) != raw:
            raise RuntimeError(f"VRAM-WALL: {name} is not canonical positive")
        parsed[name] = value
    fraction_millionths = parsed[_DAEMON_VRAM_ENV[2]]
    return {
        "provider": provider,
        "device_uuid": device_uuid,
        "fraction_millionths": fraction_millionths,
        "fraction": fraction_millionths / 1_000_000,
        "maximum_process_vram_bytes": parsed[_DAEMON_VRAM_ENV[3]],
        "minimum_free_vram_bytes": parsed[_DAEMON_VRAM_ENV[4]],
        "claim_boundary": (
            "torch_allocator_fraction_plus_load_bearing_external_sentinel_"
            "not_total_vram_guarantee"
        ),
    }


def env_limits():
    """(vram_fraction, margin_gb, throttle_s) from env with frozen defaults."""
    daemon_contract = daemon_vram_contract()
    fraction = (
        daemon_contract["fraction"]
        if daemon_contract is not None
        else float(os.environ.get("EMBER_VRAM_FRACTION", "0.85"))
    )
    margin_gb = (
        daemon_contract["minimum_free_vram_bytes"] / 1e9
        if daemon_contract is not None
        else float(os.environ.get("EMBER_VRAM_MARGIN_GB", "4.0"))
    )
    return (fraction,
            margin_gb,
            float(os.environ.get("EMBER_THROTTLE_S", "0.3")))


def _canonical_gpu_uuid(value):
    """Normalize nvidia-smi and torch UUID representations to 32 hex digits."""
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="strict")
    raw = str(value).strip()
    if raw.upper().startswith("GPU-"):
        raw = raw[4:]
    try:
        return uuid.UUID(raw).hex
    except (AttributeError, ValueError) as error:
        raise RuntimeError("VRAM-WALL: malformed CUDA device UUID") from error


def _contracted_torch_device(torch, device_uuid):
    """Resolve the visible torch ordinal carrying the contracted GPU UUID.

    The daemon contract is physical-device authority. Never fall back to the
    process default CUDA ordinal: CUDA_VISIBLE_DEVICES and driver ordering can
    otherwise make the allocator cap and margin check govern a different GPU.
    """
    contracted_uuid = _canonical_gpu_uuid(device_uuid)
    matches = []
    for index in range(torch.cuda.device_count()):
        try:
            observed_uuid = getattr(torch.cuda.get_device_properties(index), "uuid")
        except (AttributeError, RuntimeError) as error:
            raise RuntimeError(
                "VRAM-WALL: torch cannot attest visible CUDA device UUIDs"
            ) from error
        if _canonical_gpu_uuid(observed_uuid) == contracted_uuid:
            matches.append(index)
    if len(matches) != 1:
        raise RuntimeError(
            "VRAM-WALL: contracted device UUID does not identify exactly one "
            "visible torch CUDA device"
        )
    return matches[0]


def preflight():
    """Apply cap + assert margin. Returns a receipt block. Torch-importing —
    call only inside GPU jobs (POSIX/daemon side)."""
    import torch
    frac, margin_gb, _ = env_limits()
    daemon_contract = daemon_vram_contract()
    device = None
    if daemon_contract is not None:
        device = _contracted_torch_device(torch, daemon_contract["device_uuid"])
    torch.cuda.set_per_process_memory_fraction(frac, device=device)
    free, total = torch.cuda.mem_get_info(device=device)
    if free < margin_gb * 1e9:
        raise SystemExit(
            f"VRAM-PREFLIGHT: {free/1e9:.1f}GB free of {total/1e9:.1f}GB — "
            f"need >= {margin_gb}GB free before load; refusing launch")
    receipt = {"vram_fraction": frac, "free_gb": round(free / 1e9, 2),
               "total_gb": round(total / 1e9, 2), "margin_gb": margin_gb}
    if daemon_contract is not None:
        receipt["daemon_vram_wall"] = daemon_contract
        receipt["daemon_vram_wall"]["torch_device_ordinal"] = device
    return receipt


def throttle_step():
    """Headroom pause for one optimizer step (callback body)."""
    time.sleep(env_limits()[2])


# ---------------------------------------------------------------------------
# Commit-margin preflight (issue #763, refs #756, #702) -- host commit
# charge, the sibling resource to VRAM above. #81 incident: a 27B checkpoint
# load charged ~54GB of copy-on-write mmap commit against a 79.6GB ceiling
# carrying ~51GB baseline, and died as a SIGSEGV in the mmap read (torch) /
# OSError 1455 (numpy) -- a hard crash, never a clean refusal, because host
# commit charge had no guard at all next to the VRAM fraction/margin assert
# above. This is directly the mechanism #702 addendum-2 clause C (pre-load
# commit gate before the eager checkpoint torch.load) needs, and converges
# with the cockpit-commit-leak governor concern (#756). Kept as functions
# separate from env_limits()/preflight() (never folded into their
# signatures) so every existing `frac, margin_gb, throttle_s =
# governor.env_limits()` 3-tuple unpacking call site is left byte-untouched.
# ADDITIVE ONLY: no existing function's signature or default changes.
# ---------------------------------------------------------------------------

def commit_env_limit():
    """Commit-margin floor from env, GiB. Sibling of env_limits()'s VRAM
    margin, kept as its own function for the reason given above."""
    return float(os.environ.get("EMBER_COMMIT_MARGIN_GB", "4.0"))


def estimate_checkpoint_mapped_bytes(paths):
    """expected_mapped_bytes estimation rule for commit_margin_preflight():
    the sum of on-disk st_size for every file ONE load maps/reads
    simultaneously -- every safetensors shard a from_pretrained() call opens
    for one checkpoint, or every torch.load() file (model.pt + optimizer.pt +
    rng.pt) a checkpoint resume reads. Callers own the file-list/glob; this
    never re-derives a file list from a bare directory path itself. Sized
    from REAL on-disk bytes (os.path.getsize), never a config-derived guess
    -- the #702 rerun's own pinned sizes (model.pt 4,391,063,423B +
    optimizer.pt 9,175,455,079B = 12.6347 GiB) are exactly this sum."""
    return sum(os.path.getsize(p) for p in paths)


def _commit_status():
    """(commit_avail_bytes, commit_total_bytes) via GlobalMemoryStatusEx
    (ctypes, ullAvailPageFile/ullTotalPageFile) -- the #81 incident's own
    working repro (scratch/nf4-segv/mmap_repro5.py).

    Two distinct "no number" outcomes, never conflated (gate-discipline:
    an unavailable decisive statistic is a refusal, not a disclosed skip):
      - INAPPLICABLE (returns None): non-Windows platform. Commit-charge/
        page-file accounting is a Windows concept with no direct POSIX
        equivalent (see commit_margin_preflight's docstring for the
        documented psutil.virtual_memory() fallback stance) -- the leg does
        not exist here, so there is nothing to refuse.
      - UNAVAILABLE (raises OSError): on win32, but the syscall itself
        failed. commit_margin_preflight below REFUSES this case rather than
        treating a failed read as "not applicable" -- those two outcomes
        must never collapse into the same NOT_APPLICABLE receipt.

    Factored out so the selftest can monkeypatch the syscall
    (governor._commit_status = lambda: (avail, total), or a raising callable
    for the UNAVAILABLE path) without touching ctypes.windll on a
    non-Windows box."""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD)] + [
            (n, ctypes.c_ulonglong) for n in (
                "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile",
                "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual",
                "ullAvailExtendedVirtual")]

    m = _MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    if not ok:
        raise OSError(
            f"GlobalMemoryStatusEx failed: "
            f"{ctypes.WinError(ctypes.get_last_error())}")
    return m.ullAvailPageFile, m.ullTotalPageFile


def commit_margin_preflight(expected_mapped_bytes, margin_gb=None):
    """Host commit-charge preflight (issue #763, refs #756, #702 addendum-2
    clause C) -- the mmap/commit-charge sibling of preflight()'s VRAM margin
    assert (see module-section comment above for the #81 incident this
    extracts from).

    expected_mapped_bytes: caller-supplied sum of on-disk file sizes for
    every file ONE load maps/reads simultaneously -- see
    estimate_checkpoint_mapped_bytes's docstring for the exact estimation
    rule. Never re-derived from a path here; callers own the file-list/glob.

    This is the "before" leg of the #702 clause C before/peak/after commit
    lifecycle (PRE-LOAD check -> load -> in-place copy -> del+gc.collect()
    -> prove recovery): this function owns only the pre-load refusal
    decision; callers measure "peak" (mid-load) and "after" (post-cleanup)
    with their own _commit_status() reads around the load/cleanup they
    perform, and assemble the before/peak/after receipt from all three.

    Refuses (SystemExit, COMMIT_MARGIN_REFUSED, arithmetic in the message and
    in the returned receipt's "detail") when
    expected_mapped_bytes + margin_gb*GiB > commit_avail. The refusal fires
    BEFORE the caller's load, never after -- a named wall, not a crash.

    UNAVAILABLE (win32 syscall failure) also refuses (SystemExit,
    COMMIT_MARGIN_UNAVAILABLE) rather than silently treating a failed
    measurement as a disclosed skip -- see _commit_status's docstring for
    the INAPPLICABLE-vs-UNAVAILABLE distinction this preserves.

    Cross-platform: commit-charge/page-file accounting is a Windows concept.
    On non-Windows platforms (INAPPLICABLE, _commit_status() returns None)
    this returns a NOT_APPLICABLE receipt rather than asserting anything. A
    psutil.virtual_memory()-based available-memory number is the natural
    POSIX analog for a future host-memory margin, but virtual-memory
    accounting there does not carry Windows' page-file commit/overcommit
    semantics -- documented here as the fallback stance, not wired as an
    enforced gate.
    """
    if margin_gb is None:
        margin_gb = commit_env_limit()
    try:
        status = _commit_status()
    except Exception as exc:
        msg = (
            f"COMMIT_MARGIN_UNAVAILABLE: commit-charge measurement failed on "
            f"{sys.platform} ({exc!r}); a decisive gate statistic that could "
            f"not be measured is a refusal, never a disclosed skip"
        )
        raise SystemExit(msg) from exc
    if status is None:
        return {
            "status": "NOT_APPLICABLE",
            "platform": sys.platform,
            "note": ("commit-charge accounting is a Windows page-file concept; "
                     "no enforced assert on this platform -- see "
                     "commit_margin_preflight's docstring for the documented "
                     "psutil.virtual_memory() fallback stance"),
        }
    commit_avail, commit_total = status
    gib = 1 << 30
    expected_gib = round(expected_mapped_bytes / gib, 2)
    avail_gib = round(commit_avail / gib, 2)
    total_gib = round(commit_total / gib, 2)
    required_gib = round(expected_gib + margin_gb, 2)
    receipt = {
        "status": "PASS",
        "platform": sys.platform,
        "expected_mapped_gib": expected_gib,
        "margin_gib": margin_gb,
        "required_gib": required_gib,
        "commit_avail_gib": avail_gib,
        "commit_total_gib": total_gib,
    }
    if expected_mapped_bytes + margin_gb * gib > commit_avail:
        receipt["status"] = "REFUSED"
        msg = (
            f"COMMIT_MARGIN_REFUSED: expected_mapped={expected_gib}GiB + "
            f"margin={margin_gb}GiB = {required_gib}GiB required > "
            f"{avail_gib}GiB commit available (of {total_gib}GiB commit "
            f"ceiling); refusing launch"
        )
        receipt["detail"] = msg
        raise SystemExit(msg)
    return receipt


# ---------------------------------------------------------------------------
# Device-adaptive precision ladder + device-relative threshold (C-PORT gap
# closure, issue #21). preflight()/env_limits() above already query VRAM at
# runtime and read EMBER_VRAM_FRACTION from env (no hardcoded 24 GiB
# literal) -- the three remaining named C-PORT gaps this section closes are:
#   (a) fp8 gate        -- fp8 only attempted at sm>=FP8_MIN_SM
#   (b) bf16 ladder      -- every other device (lower sm, or no GPU at all)
#                           falls back to bf16, never a bare fp8 RuntimeError
#   (c) device-relative  -- throughput basis derived from a per-device
#       thresholds          roofline fraction, never an absolute tok/s gate
# TIGHTEN-ONLY: this section only ADDS a fallback ladder around the existing
# 4090 path; it never raises the VRAM fraction cap, lowers the margin floor,
# or removes a check -- the governor change is tighten only, never loosen
# the 4090 floor.
# ---------------------------------------------------------------------------

# fp8 GEMM requires Ada/Hopper-class compute capability (sm_89, e.g. RTX
# 4090) or newer. Earlier architectures (Ampere sm_86, Turing sm_75, ...)
# and CPU-only targets have no fp8 tensor-core path and fall back to bf16.
FP8_MIN_SM = 89

# Informal relative peak-FLOPS tiers (dense bf16/fp16, order-of-magnitude),
# used ONLY to derive a device-relative throughput FRACTION against a named
# reference device -- never an absolute tok/s pass/fail literal. Extend this
# table when a new target device is added to the portability probe roster.
DEVICE_ROOFLINE_RELATIVE_TFLOPS = {
    "5090": 104.8,
    "4090": 82.6,
    "rtx-spark": 62.0,
    "rtx spark": 62.0,
    "amd": 47.0,
    "mi": 47.0,
    "3090": 35.6,
    "t4": 8.1,
    "cpu": 1.0,
}


def device_capability(simulate=None):
    """Return {"name", "sm", "kind"} describing a compute device.

    `simulate` (or EMBER_SIMULATE_DEVICE env, e.g. "3090:86" or "cpu") injects
    a NAMED, DISCLOSED simulated profile for portability probing on hardware
    that doesn't physically have the target device -- kind is "simulated" /
    "simulated-cpu" so a receipt built from this never claims a real query it
    didn't make. With no simulate input, this queries torch.cuda AT RUNTIME
    (kind "real") or reports the real CPU-only fallback (kind "real-cpu") --
    never a hardcoded device literal.
    """
    sim = simulate if simulate is not None else os.environ.get("EMBER_SIMULATE_DEVICE")
    if sim:
        sim = sim.strip()
        if sim.lower() in ("cpu", "cpu-only"):
            return {"name": "cpu", "sm": None, "kind": "simulated-cpu"}
        name, _, sm_txt = sim.partition(":")
        sm = None
        if sm_txt:
            try:
                sm = int(sm_txt)
            except ValueError:
                sm = None
        return {"name": name or sim, "sm": sm, "kind": "simulated"}
    try:
        import torch
        if torch.cuda.is_available():
            major, minor = torch.cuda.get_device_capability()
            return {"name": torch.cuda.get_device_name(0),
                    "sm": major * 10 + minor, "kind": "real"}
    except Exception:
        pass
    return {"name": "cpu", "sm": None, "kind": "real-cpu"}


def select_precision(capability):
    """fp8 -> bf16 numerics fallback ladder.

    fp8 is selected ONLY when capability['sm'] clears FP8_MIN_SM (sm>=89).
    Every other device -- lower sm, or no sm at all (CPU / unrecognised) --
    resolves to bf16. The ladder always resolves to a usable precision; there
    is no "needs fp8, hardware doesn't have it, raise" dead end.
    """
    sm = capability.get("sm")
    if sm is not None and sm >= FP8_MIN_SM:
        return "fp8"
    return "bf16"


def fp8_matmul_with_fallback(a, b, capability=None):
    """Matmul through the fp8/bf16 numerics ladder (select_precision above).

    fp8 GEMM is attempted only when select_precision says "fp8" (sm>=89). If
    the concrete fp8 kernel itself is unavailable despite the sm gate (e.g.
    no fp8 tensor-core support in this torch build), the attempt is caught
    and the bf16 floor absorbs it -- this closes the C-PORT invalid-token
    `fp8_runtimeerror_no_fallback` (an fp8 RuntimeError with no bf16 path).
    Every other device computes directly in bf16, no fp8 attempt at all.

    Returns (result_tensor, precision_used).
    """
    import torch
    cap = capability if capability is not None else device_capability()
    precision = select_precision(cap)
    if precision == "fp8":
        try:
            fp8_dtype = torch.float8_e4m3fn
            out = torch.matmul(a.to(fp8_dtype), b.to(fp8_dtype)).to(torch.bfloat16)
            return out, "fp8"
        except (RuntimeError, AttributeError, NotImplementedError, TypeError):
            # sm gate said fp8, but the concrete kernel isn't reachable here
            # (build/driver/backend gap) -- fall through to the bf16 floor
            # rather than propagate a bare fp8 RuntimeError.
            pass
    return torch.matmul(a.to(torch.bfloat16), b.to(torch.bfloat16)), "bf16"


def device_relative_threshold(capability, reference_device="4090"):
    """Device-relative, roofline-derived throughput basis.

    Matches capability['name'] against DEVICE_ROOFLINE_RELATIVE_TFLOPS tiers
    and returns the tier's FLOPS fraction relative to `reference_device` --
    a device-relative basis, never an absolute tok/s pass/fail literal (the
    19000/25463/27702-class gates C-PORT names as invalid on another device).
    """
    name = (capability.get("name") or "").lower()
    tier = next((k for k in DEVICE_ROOFLINE_RELATIVE_TFLOPS if k in name), "cpu")
    ref_tflops = DEVICE_ROOFLINE_RELATIVE_TFLOPS[reference_device]
    tier_tflops = DEVICE_ROOFLINE_RELATIVE_TFLOPS[tier]
    return {
        "basis": "device-relative roofline-derived threshold",
        "device_tier": tier,
        "reference_device": reference_device,
        "relative_flops_fraction": round(tier_tflops / ref_tflops, 4),
    }


def make_headroom_callback():
    """TrainerCallback applying throttle_step on every optimizer step."""
    from transformers import TrainerCallback

    class _Headroom(TrainerCallback):
        def on_step_end(self, args, state, control, **kw):
            throttle_step()

    return _Headroom()


def _selftest():
    old = {k: os.environ.get(k) for k in
           ("EMBER_VRAM_FRACTION", "EMBER_VRAM_MARGIN_GB", "EMBER_THROTTLE_S")}
    try:
        for k in old:
            os.environ.pop(k, None)
        assert env_limits() == (0.85, 4.0, 0.3)  # frozen defaults
        os.environ["EMBER_VRAM_FRACTION"] = "0.5"
        os.environ["EMBER_VRAM_MARGIN_GB"] = "6"
        os.environ["EMBER_THROTTLE_S"] = "0.1"
        assert env_limits() == (0.5, 6.0, 0.1)
        t0 = time.time()
        throttle_step()
        assert time.time() - t0 >= 0.1
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # --- device-adaptive precision ladder (C-PORT gap closure) -----------
    cap_3090 = device_capability(simulate="3090:86")
    assert cap_3090 == {"name": "3090", "sm": 86, "kind": "simulated"}
    assert select_precision(cap_3090) == "bf16"  # sm 86 < FP8_MIN_SM (89)

    cap_4090 = device_capability(simulate="4090:89")
    assert select_precision(cap_4090) == "fp8"  # sm 89 >= FP8_MIN_SM

    cap_cpu = device_capability(simulate="cpu")
    assert cap_cpu == {"name": "cpu", "sm": None, "kind": "simulated-cpu"}
    assert select_precision(cap_cpu) == "bf16"  # no sm at all -> bf16 floor

    thr_4090 = device_relative_threshold(cap_4090)
    assert thr_4090["relative_flops_fraction"] == 1.0  # reference == itself
    assert "device-relative" in thr_4090["basis"] and "roofline" in thr_4090["basis"]
    thr_3090 = device_relative_threshold(cap_3090)
    assert 0 < thr_3090["relative_flops_fraction"] < 1.0  # 3090 < 4090 tier
    # never an absolute tok/s literal anywhere in the derived basis.
    for literal in ("19000", "25463", "27702"):
        assert literal not in str(thr_4090) and literal not in str(thr_3090)

    # --- Commit-margin preflight (issue #763, refs #756, #702) ------------
    assert os.environ.get("EMBER_COMMIT_MARGIN_GB") is None
    assert commit_env_limit() == 4.0  # frozen default

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p1, p2 = os.path.join(td, "a.bin"), os.path.join(td, "b.bin")
        with open(p1, "wb") as f:
            f.write(b"x" * 100)
        with open(p2, "wb") as f:
            f.write(b"y" * 250)
        # real on-disk st_size, never a config-derived guess.
        assert estimate_checkpoint_mapped_bytes([p1, p2]) == 350

    real_commit_status = _commit_status
    try:
        # (a) Refusal path: 2GiB avail, 10GiB mapped + 4GiB margin required.
        # Flip test: delete the `if expected_mapped_bytes + margin_gb*gib >
        # commit_avail` branch and this assertion fails -- commit_margin_
        # preflight would return a PASS receipt instead of raising.
        globals()["_commit_status"] = lambda: (2 * (1 << 30), 64 * (1 << 30))
        try:
            commit_margin_preflight(10 * (1 << 30), margin_gb=4.0)
            raise AssertionError("expected COMMIT_MARGIN_REFUSED SystemExit")
        except SystemExit as exc:
            assert "COMMIT_MARGIN_REFUSED" in str(exc)
            assert "14.0GiB required > 2.0GiB" in str(exc)

        # Pass path: 100GiB avail -- same requested load is a healthy no-op.
        globals()["_commit_status"] = lambda: (100 * (1 << 30), 128 * (1 << 30))
        receipt = commit_margin_preflight(10 * (1 << 30), margin_gb=4.0)
        assert receipt == {
            "status": "PASS", "platform": sys.platform,
            "expected_mapped_gib": 10.0, "margin_gib": 4.0,
            "required_gib": 14.0, "commit_avail_gib": 100.0,
            "commit_total_gib": 128.0,
        }

        # Cross-platform stance: simulate off-Windows -- INAPPLICABLE, no
        # assert (the leg does not exist on this simulated platform).
        globals()["_commit_status"] = lambda: None
        na_receipt = commit_margin_preflight(10 * (1 << 30), margin_gb=4.0)
        assert na_receipt["status"] == "NOT_APPLICABLE"

        # (b) UNAVAILABLE path: the win32 syscall itself fails (GlobalMemory
        # StatusEx read error) -- must REFUSE, never silently collapse into
        # the NOT_APPLICABLE receipt reserved for the non-Windows INAPPLICABLE
        # leg above (gate-discipline: an unavailable decisive statistic is a
        # refusal, not a disclosed skip). Flip test: delete the try/except
        # around `_commit_status()` in commit_margin_preflight and this
        # assertion fails -- the RuntimeError below propagates raw instead of
        # the named COMMIT_MARGIN_UNAVAILABLE SystemExit.
        def _raising_commit_status():
            raise RuntimeError("simulated GlobalMemoryStatusEx failure")
        globals()["_commit_status"] = _raising_commit_status
        try:
            commit_margin_preflight(1 * (1 << 30), margin_gb=4.0)
            raise AssertionError("expected COMMIT_MARGIN_UNAVAILABLE SystemExit")
        except SystemExit as exc:
            assert "COMMIT_MARGIN_UNAVAILABLE" in str(exc)
            assert "never a disclosed skip" in str(exc)
        except RuntimeError:
            raise AssertionError(
                "UNAVAILABLE must surface as SystemExit, not a raw RuntimeError")

        # (c) before/peak/after live-measurement lifecycle (#702 addendum-2
        # clause C: "receipt carries before/peak/after commit").
        # commit_margin_preflight owns only the pre-load ("before") refusal
        # decision; peak/after are the caller's own _commit_status() reads
        # around the load + del/gc.collect() it performs. Demonstrated here
        # with a simulated load/cleanup trace, proving the primitive is
        # sufficient to build that lifecycle without a new public function.
        commit_trace = [
            (80 * (1 << 30), 128 * (1 << 30)),   # before: plenty free
            (65 * (1 << 30), 128 * (1 << 30)),   # peak: mid-load, ~15GiB charged
            (79 * (1 << 30), 128 * (1 << 30)),   # after: recovered post del+gc
        ]
        trace_iter = iter(commit_trace)
        globals()["_commit_status"] = lambda: next(trace_iter)
        before_receipt = commit_margin_preflight(10 * (1 << 30), margin_gb=4.0)
        assert before_receipt["status"] == "PASS"
        peak_avail, _ = _commit_status()   # caller's own mid-load read
        after_avail, _ = _commit_status()  # caller's own post-cleanup read
        lifecycle_report = {
            "before_commit_avail_gib": before_receipt["commit_avail_gib"],
            "peak_commit_avail_gib": round(peak_avail / (1 << 30), 2),
            "after_commit_avail_gib": round(after_avail / (1 << 30), 2),
        }
        assert set(lifecycle_report) == {
            "before_commit_avail_gib", "peak_commit_avail_gib",
            "after_commit_avail_gib"}
        # load consumed commit, cleanup recovered it -- the shape #702
        # clause C needs to "prove commit recovery".
        assert (lifecycle_report["peak_commit_avail_gib"]
                < lifecycle_report["before_commit_avail_gib"])
        assert (lifecycle_report["after_commit_avail_gib"]
                > lifecycle_report["peak_commit_avail_gib"])
    finally:
        globals()["_commit_status"] = real_commit_status

    print("GOVERNOR_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
