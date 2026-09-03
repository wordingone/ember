#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c_port_simulated_device_receipt.py -- executes a genuine CPU forward pass
under a SIMULATED non-4090 device profile and emits the C-PORT
device-portability receipt that src/ember/governance/scripts/ember_totality/test_c_port.py (issue
#21) requires: governor + forward pass, no crash, device-relative threshold,
fp8-gated-with-bf16-fallback numerics ladder.

Simulation boundary (disclosed, never silently claimed as real): this
process runs on CPU-only torch -- no CUDA device is queried or started --
and injects a NAMED non-4090 capability profile via
governor.device_capability(simulate=...) to drive the numerics-ladder and
threshold-basis decisions as if that GPU were present. The forward pass
itself is REAL (an actual nn.Linear + matmul on real tensors, real
finite-output assertion) -- only the DEVICE IDENTITY used for gating is
simulated, and the receipt says so explicitly.

Run:  wsl python3 src/ember/governance/scripts/c_port_simulated_device_receipt.py [--device 3090:86]

Writes receipts/c-port-device-portability-sim-<ts>.json via
receipt_write.checked_write (fail-closed schema floor -- deletes the file if
malformed) -- never a hand-assembled receipt string.
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/governor.py
import importlib.util as _ember_86cfcf0844b5c48e_importlib
import sys as _ember_86cfcf0844b5c48e_sys
from pathlib import Path as _ember_86cfcf0844b5c48e_Path
_ember_86cfcf0844b5c48e_path = _ember_86cfcf0844b5c48e_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'governor.py')
if not _ember_86cfcf0844b5c48e_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/governor.py')
_ember_86cfcf0844b5c48e_aliases = ('_ember_issue2015_86cfcf0844b5c48e', 'governor', 'scripts.governor')
_ember_86cfcf0844b5c48e_existing = []
for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
    _ember_86cfcf0844b5c48e_candidate = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
    if _ember_86cfcf0844b5c48e_candidate is not None and all(_ember_86cfcf0844b5c48e_candidate is not item for item in _ember_86cfcf0844b5c48e_existing):
        _ember_86cfcf0844b5c48e_existing.append(_ember_86cfcf0844b5c48e_candidate)
if len(_ember_86cfcf0844b5c48e_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/governor.py')
if _ember_86cfcf0844b5c48e_existing:
    _ember_86cfcf0844b5c48e_module = _ember_86cfcf0844b5c48e_existing[0]
    _ember_86cfcf0844b5c48e_observed = getattr(_ember_86cfcf0844b5c48e_module, '__file__', None)
    if _ember_86cfcf0844b5c48e_observed is None or _ember_86cfcf0844b5c48e_Path(_ember_86cfcf0844b5c48e_observed).resolve() != _ember_86cfcf0844b5c48e_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/governor.py')
else:
    _ember_86cfcf0844b5c48e_spec = _ember_86cfcf0844b5c48e_importlib.spec_from_file_location('_ember_issue2015_86cfcf0844b5c48e', _ember_86cfcf0844b5c48e_path)
    if _ember_86cfcf0844b5c48e_spec is None or _ember_86cfcf0844b5c48e_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/governor.py')
    _ember_86cfcf0844b5c48e_module = _ember_86cfcf0844b5c48e_importlib.module_from_spec(_ember_86cfcf0844b5c48e_spec)
    for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
        _ember_86cfcf0844b5c48e_prior = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
        if _ember_86cfcf0844b5c48e_prior is not None and _ember_86cfcf0844b5c48e_prior is not _ember_86cfcf0844b5c48e_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/governor.py')
        _ember_86cfcf0844b5c48e_sys.modules[_ember_86cfcf0844b5c48e_alias] = _ember_86cfcf0844b5c48e_module
    try:
        _ember_86cfcf0844b5c48e_spec.loader.exec_module(_ember_86cfcf0844b5c48e_module)
    except BaseException:
        for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
            if _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias) is _ember_86cfcf0844b5c48e_module:
                _ember_86cfcf0844b5c48e_sys.modules.pop(_ember_86cfcf0844b5c48e_alias, None)
        raise
for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
    _ember_86cfcf0844b5c48e_prior = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
    if _ember_86cfcf0844b5c48e_prior is not None and _ember_86cfcf0844b5c48e_prior is not _ember_86cfcf0844b5c48e_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/governor.py')
    _ember_86cfcf0844b5c48e_sys.modules[_ember_86cfcf0844b5c48e_alias] = _ember_86cfcf0844b5c48e_module
governor = _ember_86cfcf0844b5c48e_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/governor.py  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
receipt_write = _ember_66ee9e91637922dc_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))

# Post-genesis constitutional invariant stamp (issue #281 / receipt_check.py
# GENESIS_TS + INVARIANT_SHA256) -- required on any receipt timestamped after
# 2026-07-06T14:13:23-07:00, copied verbatim, never retyped from memory.
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"

# Simulated VRAM totals per device tier (disclosed simulation, not a runtime
# GPU query) -- used only to populate the governor block's total_gib for a
# device that is not physically present on this host.
SIM_TOTAL_GIB = {
    "3090": 24.0, "4090": 24.0, "5090": 32.0, "t4": 16.0,
    "rtx-spark": 128.0, "rtx spark": 128.0, "amd": 24.0, "mi": 24.0, "cpu": 0.0,
}


def _git_sha(override: str | None) -> str:
    if override:
        return override
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception as e:
        return f"unavailable ({e})"


def _git_branch(override: str | None) -> str:
    if override:
        return override
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unavailable"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="3090:86",
                     help="simulated <name>:<sm> profile (default: 3090:86 -- "
                          "Ampere sm_86, the C-PORT probe's own fixture target)")
    ap.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "receipts"),
                     help="receipts/ directory to write into (default: repo receipts/)")
    ap.add_argument("--git-sha", default=None,
                     help="override git HEAD sha (this worktree's .git pointer uses a "
                          "Windows-style gitdir path WSL git cannot resolve across the "
                          "WSL/Windows boundary; pass the value read via native git "
                          "instead of a subprocess re-detect that would fail closed to "
                          "'unavailable'). Falls back to internal `git rev-parse HEAD` "
                          "when omitted.")
    ap.add_argument("--git-branch", default=None, help="override git branch name (see --git-sha)")
    ap.add_argument("--verify-only", action="store_true",
                     help="run the identical governor + forward-pass path, write NO receipt, "
                          "print one verdict line (VERIFY PASS or VERIFY FAIL), exit 0 on PASS, 1 on FAIL")
    args = ap.parse_args()

    import torch  # imported here, not at module load, matching governor.py's own convention

    real_cuda_available = torch.cuda.is_available()

    # --- inject the simulated non-4090 capability profile ------------------
    capability = governor.device_capability(simulate=args.device)

    # --- the numerics-ladder + threshold decisions this receipt proves -----
    precision_selected = governor.select_precision(capability)
    frac, margin_gb, throttle_s = governor.env_limits()
    threshold_basis = governor.device_relative_threshold(capability)

    # --- REAL forward pass: real tensors, real nn.Linear, real matmul ------
    torch.manual_seed(20260709)
    layer = torch.nn.Linear(64, 64)
    x = torch.randn(8, 64)
    crashed = False
    error_note = None
    precision_used = None
    forward_ok = False
    output_shape = None
    output_abs_mean = None
    try:
        w = layer.weight.detach()
        bias = layer.bias.detach()
        out, precision_used = governor.fp8_matmul_with_fallback(x, w.t(), capability=capability)
        out = (out.float() + bias)
        forward_ok = bool(torch.isfinite(out).all().item())
        output_shape = list(out.shape)
        output_abs_mean = round(float(out.abs().mean().item()), 6)
    except Exception as e:  # forward pass is expected to succeed; disclose honestly if not
        crashed = True
        error_note = f"{type(e).__name__}: {e}"

    tier_name = (capability.get("name") or "cpu").lower()
    total_gib = next((v for k, v in SIM_TOTAL_GIB.items() if k in tier_name), 0.0)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sm = capability.get("sm")
    device_label = (
        f"simulated {capability['name']}-class (sm_{sm}, non-4090 profile)"
        if sm is not None else
        f"simulated {capability['name']}-class (CPU-only profile, non-4090)"
    )

    no_crash = (not crashed) and forward_ok

    # --- Verify-only mode: run identical logic, print verdict line, NO receipt ---
    if args.verify_only:
        if not no_crash:
            print(f"VERIFY FAIL forward_pass_crashed_or_failed")
            return 1
        # Success: print the verdict line with precision and device tier
        device_tier = capability.get("name", "cpu").lower()
        print(f"VERIFY PASS precision={precision_selected} device_tier={device_tier}")
        return 0

    receipt = {
        "ticket": "C-PORT-DEVICE-PORTABILITY-SIM",
        "ts": ts,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "invariant_sha256": INVARIANT_SHA256,
        "kind": "device_portability_probe",
        "device": device_label,
        "simulated_device": True,
        "simulation_boundary": (
            "REAL forward pass executed on this process's own CPU "
            f"(torch.cuda.is_available()={real_cuda_available} on the host that "
            "ran this script -- no CUDA device was queried or started, no "
            "llama-server / model process was launched); the DEVICE IDENTITY "
            f"used to drive the governor's precision/threshold gating "
            f"({capability['name']}, sm={sm}) is a NAMED, injected simulation "
            "(governor.device_capability(simulate=...)), disclosed here, never "
            "claimed as a real GPU query."
        ),
        "forward_pass": {
            "no_crash": no_crash,
            "crashed": crashed,
            "error": error_note,
            "layer": "torch.nn.Linear(64, 64) via governor.fp8_matmul_with_fallback",
            "input_shape": [8, 64],
            "output_shape": output_shape,
            "output_abs_mean": output_abs_mean,
            "precision_selected": precision_selected,
            "precision_used": precision_used,
        },
        "governor": {
            "total_gib": total_gib,
            "ember_vram_fraction": frac,
            "margin_gb": margin_gb,
            "throttle_s": throttle_s,
        },
        "throughput_basis": threshold_basis["basis"],
        "throughput_threshold": threshold_basis,
        "fp8_note": (
            f"fp8 path gated on sm>={governor.FP8_MIN_SM} (governor.FP8_MIN_SM); "
            f"bf16 fallback used for sm<{governor.FP8_MIN_SM} or no GPU at all -- "
            f"this device (sm={sm}) selected precision={precision_selected!r}, "
            "no bare fp8 RuntimeError (governor.fp8_matmul_with_fallback catches "
            "and falls back rather than propagate)."
        ),
        "note": "governor change is tighten only, never loosen the 4090 floor",
        "provenance": {
            "script": "src/ember/governance/scripts/c_port_simulated_device_receipt.py",
            "args": {"device": args.device,
                     "out_dir": os.path.relpath(str(args.out_dir), REPO_ROOT).replace(os.sep, "/")},
            "git_sha": _git_sha(args.git_sha),
            "git_branch": _git_branch(args.git_branch),
            "host_python": sys.version.split()[0],
            "host_torch": torch.__version__,
            "host_platform": platform.platform(),
            "host_cuda_available": real_cuda_available,
            "rerun_command": (
                f"wsl python3 src/ember/governance/scripts/c_port_simulated_device_receipt.py --device {args.device}"
            ),
        },
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"c-port-device-portability-sim-{ts}.json"
    receipt_write.checked_write(str(out_path), receipt)
    print(f"WROTE {out_path}")
    print(f"forward_pass.no_crash={no_crash} precision_used={precision_used} "
          f"device={device_label}")
    return 0 if no_crash else 1


if __name__ == "__main__":
    sys.exit(main())
