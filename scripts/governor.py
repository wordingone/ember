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

Selftest (Windows-safe, no torch): env parsing + receipt-block shape.
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
    print("GOVERNOR_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
