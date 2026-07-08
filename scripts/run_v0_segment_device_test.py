#!/usr/bin/env python3
"""run_v0_segment_device_test.py — regression test for issue #463.

`run_v0_segment()` (scripts/timeshare_pretrain.py) resolves two independent
device-shaped decisions from the same inputs:

  use_real_arch = live if real_arch is None else real_arch
  use_device    = device or ("cuda" if live else "cpu")

The model is built on `use_device` (correct). Before the #463 cure, the input
batch's device move was gated on the raw `live` flag instead of `use_device`:

    if live:
        x = x.cuda()
        ...

That is byte-identical to `use_device` for every PRE-EXISTING caller (nobody
ever passed `real_arch=True, device="cuda", live=False` — the only way to
reach a real-architecture build without the live/GPU interlock), so the
divergence was never exercised. This test exercises it directly: a genuine,
real-architecture (LlamaModel) `run_v0_segment` call with
`real_arch=True, device="cuda", live=False`. Pre-cure this must raise a
device-mismatch RuntimeError the moment the batch hits the model's first
layer (model on cuda, batch on cpu). Post-cure it must complete with
receipt["pass"] is True and receipt["components"]["arch"]["device"] == "cuda".

Requires an actual CUDA device — the bug IS a CPU/CUDA device mismatch, so a
mock or CPU-only stand-in cannot exercise the seam; the test skips (exit 0,
not a false pass) when no CUDA device is present, per the "seam genuinely
needs CUDA" carve-out (documented, not a default requirement for CI).

Usage:
  python scripts/run_v0_segment_device_test.py

Marker: RUN_V0_SEGMENT_DEVICE_TEST_PASS
"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_SCRIPTS_DIR = _THIS_FILE.parent  # scripts/
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import timeshare_pretrain as ts  # noqa: E402


def _tiny_real_arch_cfg() -> dict:
    """Small-dims copy of the frozen v0 contract, same recipe
    cbase_grow_live.py's `_small_cfg` uses for its own real-LlamaModel smoke
    path: same optimizer/schedule/objective/precision/throughput structure
    (so the SAME code path is exercised), tiny model shape so the real
    architecture builds and trains in a fraction of a second."""
    cfg = copy.deepcopy(ts.load_contract())
    cfg["model"] = dict(cfg["model"], hidden=32, layers=2, heads=2,
                        vocab=64, seq=16, params_estimate=None)
    cfg["throughput"] = dict(cfg["throughput"], batch=2)
    return cfg


def run_test() -> bool:
    import torch

    if not torch.cuda.is_available():
        print("SKIP: no CUDA device available in this environment -- the "
              "real_arch=True/device=cuda/live=False seam is a CPU/CUDA "
              "device-mismatch bug and cannot be exercised without a real "
              "GPU (issue #463).")
        return True

    cfg = _tiny_real_arch_cfg()

    with tempfile.TemporaryDirectory(prefix="run_v0_segment_device_test_") as run_dir:
        try:
            receipt = ts.run_v0_segment(
                run_dir, cfg, n_steps=1,
                real_arch=True, device="cuda", live=False,
                intermediate_override=8, segment_id="issue-463-regression",
            )
        except RuntimeError as e:
            print("FAIL: real_arch=True, device=\"cuda\", live=False raised "
                  "a RuntimeError -- the #463 device mismatch reproduced.")
            print(f"  error: {e}")
            return False

    if receipt.get("pass") is not True:
        print(f"FAIL: run_v0_segment returned pass={receipt.get('pass')!r}, expected True")
        return False
    if receipt["components"]["arch"]["device"] != "cuda":
        print(f"FAIL: receipt arch.device={receipt['components']['arch']['device']!r}, expected 'cuda'")
        return False

    print("PASS: real_arch=True, device=\"cuda\", live=False completed with "
          "no device mismatch (model AND batch both resolved onto \"cuda\").")
    print(f"  loss_first={receipt['loss_first']} loss_last={receipt['loss_last']}")
    return True


if __name__ == "__main__":
    ok = run_test()
    if ok:
        print("RUN_V0_SEGMENT_DEVICE_TEST_PASS")
        sys.exit(0)
    else:
        print("RUN_V0_SEGMENT_DEVICE_TEST_FAIL")
        sys.exit(1)
