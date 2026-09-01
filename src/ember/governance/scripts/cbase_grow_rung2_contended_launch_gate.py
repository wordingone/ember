#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_contended_launch_gate.py — DEV-002 cure-PR follow-up:
MEASURED CONTENDED-FIRST launch-gate receipt for the CPU-offloaded optimizer
config (PR #429, issue #411).

Scope (explicit, narrower than the full cbase_grow_rung2_dryrun.py harness):
answers exactly one question -- under the CURRENT, live GPU contention
(llama-server resident, serving-pause NOT taken), does the DEV-002
candidate-3/4 (CPU-offloaded optimizer + micro-batch/accum) VRAM preflight
(scripts/cpu_offload_adamw.py:vram_preflight) permit or refuse a launch,
using the REAL param_count_after computed from the REAL seed checkpoint
(not the PR body's cited number, hand-typed) and the REAL, live-measured
nvidia-smi numbers.

Deliberately OUT of scope (already covered elsewhere, not duplicated here):
  - net2net function-preservation check (model-building, logits comparison)
    -- covered by PART A of cbase_grow_rung2_dryrun.py, already receipted
    (receipts/grow-op-verify-20260708T060841Z.json, PASS).
  - CPU sanity-scale training segments (PART B2) -- same rationale, already
    receipted (receipts/grow-operator-dryrun-20260708T060841Z.json).
  - An actual GPU training launch under the offloaded config -- per PR
    #429's own text this needs a real shard_dir + the declared serving-pause
    window; explicitly not this run.

Reuse discipline (no duplicated math): sha256_file / widen_state_dict
imported from cbase_grow_dryrun.py (the exact net2net surgery, real
weights, never reimplemented). estimate_required_gib_offloaded /
vram_preflight / nvidia_smi_vram imported from cpu_offload_adamw.py (this
PR's own cure module). checked_write from receipt_write.py (fail-closed
schema floor).

No git commits from this script. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbase_grow_dryrun import sha256_file, widen_state_dict          # noqa: E402
# issue2015 exact-local-import:scripts/cpu_offload_adamw.py
import importlib.util as _ember_af5148f80571f78d_importlib
import sys as _ember_af5148f80571f78d_sys
from pathlib import Path as _ember_af5148f80571f78d_Path
_ember_af5148f80571f78d_path = _ember_af5148f80571f78d_Path(__file__).resolve().parents[4].joinpath('scripts', 'cpu_offload_adamw.py')
if not _ember_af5148f80571f78d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/cpu_offload_adamw.py')
_ember_af5148f80571f78d_aliases = ('_ember_issue2015_af5148f80571f78d', 'cpu_offload_adamw', 'scripts.cpu_offload_adamw')
_ember_af5148f80571f78d_existing = []
for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
    _ember_af5148f80571f78d_candidate = _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias)
    if _ember_af5148f80571f78d_candidate is not None and all(_ember_af5148f80571f78d_candidate is not item for item in _ember_af5148f80571f78d_existing):
        _ember_af5148f80571f78d_existing.append(_ember_af5148f80571f78d_candidate)
if len(_ember_af5148f80571f78d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/cpu_offload_adamw.py')
if _ember_af5148f80571f78d_existing:
    _ember_af5148f80571f78d_module = _ember_af5148f80571f78d_existing[0]
    _ember_af5148f80571f78d_observed = getattr(_ember_af5148f80571f78d_module, '__file__', None)
    if _ember_af5148f80571f78d_observed is None or _ember_af5148f80571f78d_Path(_ember_af5148f80571f78d_observed).resolve() != _ember_af5148f80571f78d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/cpu_offload_adamw.py')
else:
    _ember_af5148f80571f78d_spec = _ember_af5148f80571f78d_importlib.spec_from_file_location('_ember_issue2015_af5148f80571f78d', _ember_af5148f80571f78d_path)
    if _ember_af5148f80571f78d_spec is None or _ember_af5148f80571f78d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/cpu_offload_adamw.py')
    _ember_af5148f80571f78d_module = _ember_af5148f80571f78d_importlib.module_from_spec(_ember_af5148f80571f78d_spec)
    for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
        _ember_af5148f80571f78d_prior = _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias)
        if _ember_af5148f80571f78d_prior is not None and _ember_af5148f80571f78d_prior is not _ember_af5148f80571f78d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/cpu_offload_adamw.py')
        _ember_af5148f80571f78d_sys.modules[_ember_af5148f80571f78d_alias] = _ember_af5148f80571f78d_module
    try:
        _ember_af5148f80571f78d_spec.loader.exec_module(_ember_af5148f80571f78d_module)
    except BaseException:
        for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
            if _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias) is _ember_af5148f80571f78d_module:
                _ember_af5148f80571f78d_sys.modules.pop(_ember_af5148f80571f78d_alias, None)
        raise
for _ember_af5148f80571f78d_alias in _ember_af5148f80571f78d_aliases:
    _ember_af5148f80571f78d_prior = _ember_af5148f80571f78d_sys.modules.get(_ember_af5148f80571f78d_alias)
    if _ember_af5148f80571f78d_prior is not None and _ember_af5148f80571f78d_prior is not _ember_af5148f80571f78d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/cpu_offload_adamw.py')
    _ember_af5148f80571f78d_sys.modules[_ember_af5148f80571f78d_alias] = _ember_af5148f80571f78d_module
estimate_required_gib_offloaded = getattr(_ember_af5148f80571f78d_module, 'estimate_required_gib_offloaded')
vram_preflight = getattr(_ember_af5148f80571f78d_module, 'vram_preflight')
nvidia_smi_vram = getattr(_ember_af5148f80571f78d_module, 'nvidia_smi_vram')
# issue2015 exact-local-import-end:scripts/cpu_offload_adamw.py
from receipt_write import checked_write                              # noqa: E402
from endpoint_identity import assert_board_endpoint_identity          # noqa: E402
# issue2015 exact-local-import:scripts/timeshare_pretrain.py
import importlib.util as _ember_d9c5c82c124e1dc8_importlib
import sys as _ember_d9c5c82c124e1dc8_sys
from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
_ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parents[4].joinpath('scripts', 'timeshare_pretrain.py')
if not _ember_d9c5c82c124e1dc8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/timeshare_pretrain.py')
_ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'scripts.timeshare_pretrain', 'timeshare_pretrain')
_ember_d9c5c82c124e1dc8_existing = []
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
        _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
if len(_ember_d9c5c82c124e1dc8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/timeshare_pretrain.py')
if _ember_d9c5c82c124e1dc8_existing:
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
    _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
    if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/timeshare_pretrain.py')
else:
    _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
    if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
    try:
        _ember_d9c5c82c124e1dc8_spec.loader.exec_module(_ember_d9c5c82c124e1dc8_module)
    except BaseException:
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            if _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias) is _ember_d9c5c82c124e1dc8_module:
                _ember_d9c5c82c124e1dc8_sys.modules.pop(_ember_d9c5c82c124e1dc8_alias, None)
        raise
for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
    _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
    if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
ts = _ember_d9c5c82c124e1dc8_module
# issue2015 exact-local-import-end:scripts/timeshare_pretrain.py                                      # noqa: E402

REPO = Path(__file__).resolve().parent.parent
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

SEED_SHA_ATTESTED = "58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b"
SEED_SHA_ATTESTATION_RECEIPT = "receipts/spend-annex/attestations/cbase-gpu-verify-trainable-clean-20260707T015633.json"

MARGIN_GIB_FLOOR = 2.0


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _probe_server(url: str) -> dict:
    return assert_board_endpoint_identity(url, "27b")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed-ckpt", required=True,
                     help="path to the real rung-1 seed checkpoint dir (model.pt + manifest.json)")
    ap.add_argument("--receipt-dir", default=str(REPO / "receipts"))
    ap.add_argument("--server-health-url", default="http://127.0.0.1:8082/health")
    args = ap.parse_args()

    ts_stamp = _ts()
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    seed_ckpt = Path(args.seed_ckpt)
    model_pt = seed_ckpt / "model.pt"
    manifest = json.loads((seed_ckpt / "manifest.json").read_text(encoding="utf-8"))

    wall_start = time.monotonic()

    # ---- before-baseline: nvidia-smi + server health (server resident and
    # NEVER stopped -- the primary receipt condition per this lane's mandate) ----
    nvsmi_before = nvidia_smi_vram()
    server_before = _probe_server(args.server_health_url)
    print(f"[{ts_stamp}] BEFORE nvidia-smi: {nvsmi_before}", flush=True)
    print(f"[{ts_stamp}] BEFORE server: {server_before}", flush=True)

    # ---- SHA-verify the real seed checkpoint (reuse: sha256_file) ----
    actual_sha = sha256_file(model_pt)
    claimed_sha = (manifest.get("files") or {}).get("model.pt")
    sha_ok = actual_sha == claimed_sha == SEED_SHA_ATTESTED
    print(f"[{ts_stamp}] seed checkpoint SHA verified: {actual_sha} (attested match: {sha_ok})", flush=True)
    if not sha_ok:
        raise SystemExit(f"CBASE-GROW-RUNG2-CONTENDED-LAUNCH-GATE: seed checkpoint hash mismatch: "
                          f"manifest={claimed_sha} attested={SEED_SHA_ATTESTED} actual={actual_sha}")

    # ---- peak-VRAM sampler thread: samples nvidia-smi every 2s DURING the
    # real widen computation below -- proves/disproves the offloaded config's
    # own premise that this attempt touches zero VRAM ----
    samples: list[dict] = []
    stop_flag = threading.Event()

    def _sampler():
        while not stop_flag.is_set():
            try:
                samples.append(nvidia_smi_vram())
            except Exception as e:
                samples.append({"error": str(e)})
            stop_flag.wait(2.0)

    sampler_thread = threading.Thread(target=_sampler, daemon=True)
    sampler_thread.start()

    # ---- real widen computation on the real checkpoint (reuse: widen_state_dict,
    # never reimplemented) -- same load->float->widen sequence as PART A of
    # cbase_grow_rung2_dryrun.py, WITHOUT the model-build/logits function-
    # preservation probe (already covered elsewhere, see module docstring) ----
    import torch
    cfg = ts.load_contract()
    n_layers = cfg["model"]["layers"]

    t_widen_start = time.monotonic()
    sd_seed_bf16 = torch.load(model_pt, map_location="cpu", weights_only=True)
    sd_pre_f32 = {k: v.float() for k, v in sd_seed_bf16.items()}
    sd_seed_bf16 = None
    gc.collect()
    grown_sd_f32 = widen_state_dict(sd_pre_f32, n_layers)
    param_count_before = int(sum(v.numel() for v in sd_pre_f32.values()))
    param_count_after = int(sum(v.numel() for v in grown_sd_f32.values()))
    sd_pre_f32 = None
    grown_sd_f32 = None
    gc.collect()
    t_widen_s = round(time.monotonic() - t_widen_start, 3)

    stop_flag.set()
    sampler_thread.join(timeout=5)

    print(f"[{ts_stamp}] param_count_before={param_count_before} param_count_after={param_count_after} "
          f"widen_wall_s={t_widen_s}", flush=True)

    # ---- after-baseline ----
    nvsmi_after = nvidia_smi_vram()
    server_after = _probe_server(args.server_health_url)
    print(f"[{ts_stamp}] AFTER nvidia-smi: {nvsmi_after}", flush=True)
    print(f"[{ts_stamp}] AFTER server: {server_after}", flush=True)

    # ---- the actual launch-gate: DEV-002 candidate 3/4 offloaded estimate
    # priced against the CONTENDED, live-measured nvidia-smi numbers (reuse:
    # estimate_required_gib_offloaded / vram_preflight, cpu_offload_adamw.py) ----
    prod_batch = cfg["throughput"]["batch"] if cfg["throughput"]["batch"] >= 16 else 16
    micro_batch_offload = 2
    accum_steps_offload = (prod_batch // micro_batch_offload
                            if prod_batch % micro_batch_offload == 0 else 8)
    required_offloaded = estimate_required_gib_offloaded(
        param_count_after, micro_batch=micro_batch_offload, prod_batch=prod_batch)
    # Priced against the CONTENDED "before" snapshot (the primary receipt
    # condition -- server resident, never stopped), not "after": the gate
    # question is "can we launch right now, under current contention."
    offload_preflight = vram_preflight(
        required_offloaded["total_estimate_gib"], margin_gib_floor=MARGIN_GIB_FLOOR,
        nvsmi=nvsmi_before)
    decision_line = (
        f"[DEV-002 cure, CONTENDED] offloaded-config required (estimate): "
        f"{required_offloaded['total_estimate_gib']}GiB VRAM (+ "
        f"{required_offloaded['optimizer_state_host_ram_gib']}GiB host RAM) "
        f"micro_batch={micro_batch_offload} accum_steps={accum_steps_offload} "
        f"effective_batch={micro_batch_offload * accum_steps_offload} | "
        f"OFFLOADED_VRAM_SUFFICIENT={offload_preflight['sufficient']} "
        f"margin_gib={offload_preflight['margin_gib']} verdict={offload_preflight['verdict']}"
    )
    print(decision_line, flush=True)

    wall_s = round(time.monotonic() - wall_start, 3)
    vram_samples_during_attempt = [s for s in samples if "error" not in s]
    peak_used_mib_during_attempt = max(
        (s["used_mib"] for s in vram_samples_during_attempt),
        default=nvsmi_before["used_mib"],
    )
    peak_used_gib_during_attempt = round(peak_used_mib_during_attempt / 1024, 3)

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-CONTENDED-LAUNCH-GATE",
        "ts": timestamp_iso,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "experiment": "C-BASE-clause-d-dryrun",
        "arm": "rung2-cpu-offload-cure-contended-dryrun",
        "pr": 429,
        "issue": 411,
        "scope": ("MEASURED CONTENDED-FIRST launch-gate check for the DEV-002 candidate 3/4 "
                  "(CPU-offloaded optimizer + micro-batch/accum) config, per PR #429's own "
                  "'MEASURED RECEIPTS PENDING' follow-up-push note. Narrower than the full "
                  "cbase_grow_rung2_dryrun.py harness: computes the REAL param_count_after "
                  "(via widen_state_dict on the real seed checkpoint, reused not "
                  "reimplemented) and prices it against the REAL, live nvidia-smi numbers "
                  "under CONTENDED conditions (llama-server resident, never stopped -- the "
                  "primary receipt condition per mandate). Does NOT re-run the net2net "
                  "function-preservation check or the CPU sanity-training segments (both "
                  "already receipted, see related_receipts) or attempt a real GPU training "
                  "launch (needs a real shard_dir + the declared serving-pause window per "
                  "PR #429's own disclosed exclusion; explicitly not this run)."),
        "seed_identity": {
            "checkpoint": str(seed_ckpt),
            "model_pt_sha256": actual_sha,
            "manifest_claim_verified": bool(actual_sha == claimed_sha),
            "attested_match": sha_ok,
            "attestation_receipt": SEED_SHA_ATTESTATION_RECEIPT,
            "step": manifest.get("step"),
        },
        "param_count_before": param_count_before,
        "param_count_after": param_count_after,
        "server_contention": {
            "before": server_before,
            "after": server_after,
            "server_stopped": False,
            "note": "primary receipt condition: server resident throughout, per mandate",
        },
        "vram": {
            "before": nvsmi_before,
            "after": nvsmi_after,
            "samples_during_widen": vram_samples_during_attempt,
            "peak_used_gib_during_attempt": peak_used_gib_during_attempt,
            "peak_vs_baseline_delta_gib": round(peak_used_gib_during_attempt - nvsmi_before["used_gib"], 3),
        },
        "offloaded_config": {
            "micro_batch": micro_batch_offload,
            "accum_steps": accum_steps_offload,
            "effective_batch": micro_batch_offload * accum_steps_offload,
            "required_estimate": required_offloaded,
            "preflight": offload_preflight,
        },
        "launch_gate_decision_line": decision_line,
        "wall_s": {"total": wall_s, "widen_computation": t_widen_s},
        "related_receipts": [
            "receipts/grow-op-verify-20260708T060841Z.json",
            "receipts/grow-operator-dryrun-20260708T060841Z.json",
            "receipts/cbase-grow-rung2-offload-probe-20260708T083445Z.json",
        ],
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": offload_preflight["verdict"],
    }
    receipt_path = Path(args.receipt_dir) / f"cbase-grow-rung2-contended-launch-gate-{ts_stamp}.json"
    checked_write(str(receipt_path), receipt)
    print(f"CBASE_GROW_RUNG2_CONTENDED_LAUNCH_GATE_DONE receipt={receipt_path} "
          f"verdict={offload_preflight['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
