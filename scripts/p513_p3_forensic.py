#!/usr/bin/env python3
"""P-3 FORENSIC (issue #513, CPU-only, no GPU).

Runs the pre-registered P-3 forensic against the 2026-07-08 rung2-event
remeasure run's persisted optimizer checkpoint (b1-snapshot, the seed for
the b3-fork RESET/TRANSPLANT arms) + the resolved config contract. Records,
verbatim per #513's pre-registration:

  (1) what the OLD resolver path (opt_state['state'][gate_key], a STRING
      key at the top level) returns for the gate key -- pre-registered
      expectation: zero/missing.
  (2) the true buffer rms via the NEW resolver
      (resolve_gate_momentum_buffer -- int-param-id keyed, tolerant of both
      the nested {'muon': {'state': {int_id: ...}}} and flat
      {'state': {int_id: ...}} forms) -- pre-registered expectation:
      nonzero, cached value ~3.6057e-4.
  (3) the resolved lr_muon from the frozen config contract -- pre-
      registered expectation: 0.02 (not the never-executed script
      constant 0.015).

Pre-registered kill conditions (#513, quoted verbatim):
  "KILL: U_k-consumed buffer rms >= 1e-6 under the old resolver, or
   lr_muon = 0.015 in the resolved cfg."

Writes a receipt to receipts/ (repo convention, checked_write-validated).
No git commits from this script. No founder/user names.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, SCRIPTS_DIR)

from receipt_write import checked_write  # noqa: E402
from p5_ratio_audit.run_p5_audit import resolve_gate_momentum_buffer, rms  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

GATE_KEY = "backbone_model.layers.0.mlp.gate_proj.weight"
CKPT_RELATIVE = os.path.join(
    "models", "cbase-grow-rung", "rung2-event-grow-rung2-20260708-real", "b1-snapshot")

CACHED_REFERENCE_RMS = 3.6057e-4  # #513 pre-registration's "cached 3.6057e-4"
KILL_RMS_THRESHOLD_OLD_RESOLVER = 1e-6
KILL_LR_MUON = 0.015
EXPECTED_LR_MUON = 0.02


def old_resolver(opt_state: dict, gate_key: str):
    """The DEFECTIVE resolver #513 fixes: a STRING key at the TOP level of
    'state' -- never matches the real on-disk {'muon': {'state': {int_id:
    ...}}} nesting, so it silently returned None (which the removed
    zeros_like fallback then substituted with zeros)."""
    return opt_state.get("state", {}).get(gate_key, {}).get("momentum_buffer")


def main() -> int:
    import torch

    models_root = os.environ.get("EMBER_MODELS_ROOT", REPO_ROOT)
    ckpt_dir = os.path.join(models_root, CKPT_RELATIVE)
    model_pt = os.path.join(ckpt_dir, "model.pt")
    optimizer_pt = os.path.join(ckpt_dir, "optimizer.pt")

    if not (os.path.isfile(model_pt) and os.path.isfile(optimizer_pt)):
        print(f"P513_P3_FORENSIC_REFUSED: checkpoint not found under {ckpt_dir!r} "
              f"(EMBER_MODELS_ROOT={os.environ.get('EMBER_MODELS_ROOT')!r}); "
              "models/ is gitignored -- set EMBER_MODELS_ROOT to the box holding "
              "the real checkpoint tree.", flush=True)
        return 1

    model_state = torch.load(model_pt, map_location="cpu", weights_only=True)
    opt_state = torch.load(optimizer_pt, map_location="cpu", weights_only=True)

    # (1) OLD resolver.
    old_buf = old_resolver(opt_state, GATE_KEY)
    old_buf_rms = float(rms(old_buf)) if old_buf is not None else 0.0
    old_resolver_missing_or_zero = (old_buf is None) or (old_buf_rms < 1e-10)

    # (2) NEW resolver.
    new_buf = resolve_gate_momentum_buffer(model_state, opt_state, GATE_KEY)
    new_buf_present = new_buf is not None
    new_buf_rms = float(rms(new_buf)) if new_buf is not None else None

    # (3) resolved lr_muon from the frozen config contract.
    cfg_path = os.path.join(REPO_ROOT, "configs", "v0-pretrain-config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    resolved_lr_muon = cfg["optimizer"]["lr_muon"]

    # Pre-registered kill conditions, quoted verbatim from #513:
    # "KILL: U_k-consumed buffer rms >= 1e-6 under the old resolver, or
    #  lr_muon = 0.015 in the resolved cfg."
    kill_old_resolver_nonzero = old_buf_rms >= KILL_RMS_THRESHOLD_OLD_RESOLVER
    kill_lr_muon_wrong = (resolved_lr_muon == KILL_LR_MUON)
    killed = kill_old_resolver_nonzero or kill_lr_muon_wrong
    verdict = "KILL" if killed else "PASS_NOT_KILLED"

    reference_match = (
        new_buf_rms is not None
        and abs(new_buf_rms - CACHED_REFERENCE_RMS) < 3e-7
    )

    receipt = {
        "ticket": "P513-P3-FORENSIC", "ts": datetime.now(timezone.utc).isoformat(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 513, "refs": [482, 498, 449, 466],
        "scope": ("P-3 FORENSIC: CPU-only, no GPU. Records what the OLD (mis-keyed, "
                  "string-top-level 'state') resolver returns for the gate momentum vs. "
                  "the NEW (int-param-id, 'muon'.'state') resolver, against the real "
                  "2026-07-08 rung2-event remeasure run's b1-snapshot optimizer.pt, plus "
                  "the resolved cfg lr_muon."),
        "checkpoint": {
            "relative_path": CKPT_RELATIVE,
            "models_root_env": "EMBER_MODELS_ROOT" if "EMBER_MODELS_ROOT" in os.environ else "REPO_ROOT-fallback",
        },
        "gate_key": GATE_KEY,
        "old_resolver": {
            "path": "opt_state['state'][gate_key]['momentum_buffer'] (STRING key, top-level)",
            "result_present": old_buf is not None,
            "rms": old_buf_rms,
            "missing_or_zero": old_resolver_missing_or_zero,
            "pre_registered_expectation": "zero/missing",
            "expectation_matched": old_resolver_missing_or_zero,
        },
        "new_resolver": {
            "path": "resolve_gate_momentum_buffer: opt_state['muon']['state'][param_id]"
                    "['momentum_buffer'], param_id = list(model_state.keys()).index(gate_key)",
            "result_present": new_buf_present,
            "rms": new_buf_rms,
            "pre_registered_cached_reference_rms": CACHED_REFERENCE_RMS,
            "reference_match_within_3e-7": reference_match,
        },
        "resolved_lr_muon": {
            "config_source": "configs/v0-pretrain-config.json:optimizer.lr_muon",
            "value": resolved_lr_muon,
            "pre_registered_expectation": EXPECTED_LR_MUON,
            "never_executed_script_constant": KILL_LR_MUON,
            "expectation_matched": (resolved_lr_muon == EXPECTED_LR_MUON),
        },
        "pre_registered_kill_conditions_verbatim": (
            "KILL: U_k-consumed buffer rms >= 1e-6 under the old resolver, or "
            "lr_muon = 0.015 in the resolved cfg."
        ),
        "kill_condition_evaluation": {
            "kill_old_resolver_nonzero (rms>=1e-6)": kill_old_resolver_nonzero,
            "kill_lr_muon_wrong (==0.015)": kill_lr_muon_wrong,
            "killed": killed,
        },
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": verdict,
    }

    receipts_dir = os.path.join(REPO_ROOT, "receipts")
    os.makedirs(receipts_dir, exist_ok=True)
    ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(receipts_dir, f"p513-p3-forensic-{ts_compact}.json")
    checked_write(out_path, receipt)

    print(f"P513_P3_FORENSIC verdict={verdict} old_resolver_rms={old_buf_rms:.6e} "
          f"new_resolver_rms={new_buf_rms} resolved_lr_muon={resolved_lr_muon} "
          f"receipt={out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
