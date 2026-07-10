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
three). fp8_matmul_with_fallback is torch-importing (CPU or GPU tensors) and
is covered separately by scripts/test_governor.py (pytest).
"""

import os
import time


def env_limits():
    """(vram_fraction, margin_gb, throttle_s) from env with frozen defaults."""
    return (float(os.environ.get("EMBER_VRAM_FRACTION", "0.85")),
            float(os.environ.get("EMBER_VRAM_MARGIN_GB", "4.0")),
            float(os.environ.get("EMBER_THROTTLE_S", "0.3")))


def preflight():
    """Apply cap + assert margin. Returns a receipt block. Torch-importing —
    call only inside GPU jobs (POSIX/daemon side)."""
    import torch
    frac, margin_gb, _ = env_limits()
    torch.cuda.set_per_process_memory_fraction(frac)
    free, total = torch.cuda.mem_get_info()
    if free < margin_gb * 1e9:
        raise SystemExit(
            f"VRAM-PREFLIGHT: {free/1e9:.1f}GB free of {total/1e9:.1f}GB — "
            f"need >= {margin_gb}GB free before load; refusing launch")
    return {"vram_fraction": frac, "free_gb": round(free / 1e9, 2),
            "total_gb": round(total / 1e9, 2), "margin_gb": margin_gb}


def throttle_step():
    """Headroom pause for one optimizer step (callback body)."""
    time.sleep(env_limits()[2])


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

    print("GOVERNOR_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
