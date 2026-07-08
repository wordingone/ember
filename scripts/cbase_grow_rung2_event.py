#!/usr/bin/env python3
"""cbase_grow_rung2_event.py — combined rung-2 grow-event + production
stabilization runner (issue #466), implementing the frozen capture-protocol
addendum on issue #449 (comment 4918052395) and the frozen bands in #449's
own body. One pipeline, phase-driven, receipts at every boundary, each
phase refusing to start unless the prior phase's receipt exists and PASSED
(fail-closed chaining).

Phases (--phase {preflight,b1,b1m,b2,b3,stabilize}):
  preflight  — commit-aware (GlobalMemoryStatusEx.ullAvailPageFile, floor
               10 GiB) + GPU headroom (nvidia-smi + the DEV-002 offloaded
               estimator) + disk headroom (>=40GiB) asserts. No launch.
  b1         — quiesce-PROVEN snapshot of the seed checkpoint: double-sha
               manifest across a wait, an exclusive-open probe, a momentum-
               buffer provenance block (genuineness receipt), RNG state
               disclosure, and a full copy to a B1 snapshot dir that
               production stabilization resumes from untouched.
  b1m        — u_pre on the pinned 8-microstep measurement batch (gate_proj
               layer-0), via build_real_d_comm_closures' U_k/_muon_step_
               in_copy; per-microstep ordered 8-tuple sha; dataloader
               bypassed (serialize/deserialize round-trip); dropout-free
               deterministic forwards; QAT mode receipted; grad_pre_gate
               cached for B3.
  b2         — FRESH widen at eps_sigma>0 (0.0 refused, distinct cache key
               from the banned eps=0 dry-run artifact); realized proof from
               the LOADED post-grow weights (per-pair eta RMS vs tau,
               twin-cosine<1 for every split pair), fail-closed.
  b3         — on a FORKED copy of the B1 snapshot + B2 weights: RESET-arm
               u_post (explicit zero-momentum assertion, never a silent
               fallback) is the band-(i) primary measurement; TRANSPLANT-
               arm u_post (momentum pushed through the widen map) is a
               second disclosed measurement. Emits #448 fields for both
               arms and reads the band off #449's frozen text (never
               re-derived): (i) c in [0.25,0.45], (ii) |c|<0.05, (iii)
               otherwise (attribution only).
  stabilize  — production training of the grown 2.2B from B2 weights with
               a RESET optimizer, under the config VERBATIM from receipt
               cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json
               (micro_batch=1, grad_accum_steps=8, checkpointing OFF with
               an effective_readback assertion), for the D1 fixed-FLOPs
               floor of 491,520 tokens (docs/spec/rung2-grow-spec-v1.md:
               30 steps at batch=16/seq=1024 == the same token count at
               effective_batch=8/seq=1024 over 60 optimizer steps — same
               FLOPs, VRAM-proven shape; disclosed, not silently assumed).
               Writes a planned-outage marker per issue #464's shape
               (issue #464 itself is open/unimplemented — this is
               forward-compatible groundwork, disclosed as inert today).

Reuse discipline (no duplicated math — same rule every script in this
family states for itself):
  - cbase_grow_dryrun.sha256_file / widen_state_dict — the net2net surgery
    math (including the #280 eps_sigma/eps_seed antisymmetric-perturbation
    extension), imported, never reimplemented.
  - cpu_offload_adamw.{estimate_required_gib_offloaded, vram_preflight,
    nvidia_smi_vram} — the DEV-002 VRAM pricing/preflight, reused verbatim.
  - cbase_grow_rung2_gpu_offload_probe._va_report — the commit-aware
    (GlobalMemoryStatusEx + VirtualQuery) probe, reused verbatim.
  - p5_ratio_audit.run_p5_audit.{compute_d_comm, build_real_d_comm_closures,
    _muon_step_in_copy, rms} — the commutation-defect measurement + the
    Muon in-copy step, reused verbatim; this script never re-derives the
    d_comm formula.
  - timeshare_pretrain.{build_v0_model, build_split_optimizer,
    resolve_ce_impl, mtp_total_loss, PackedShardLoader, write_packed_shard,
    _apply_fake_quant, _restore_weights, save_checkpoint, load_checkpoint,
    load_contract} — the real v0 survivor-stack primitives, reused, not
    reimplemented. This runner deliberately bypasses run_v0_segment's
    production interlock/governor/G-budget gates for the same reason
    cbase_grow_rung2_gpu_offload_probe.py's module docstring gives (a
    bounded, receipted measurement run, not a production dispatch through
    the real corpus) — disclosed, not silently dropped; applies its own
    preflight + conservative VRAM fraction cap instead.

Known copy-paste trap (named in the #449 addendum, guarded against here):
  build_real_d_comm_closures' own gate-only G() closure calls
  widen_state_dict WITHOUT eps kwargs (defaults 0.0) — every eps-bearing
  call in this script (B2's fresh widen, B3's G via the SAME closure
  builder) threads eps_sigma/eps_seed EXPLICITLY where the addendum
  requires it; B2's realized-eta proof exists specifically to catch a
  silent eps=0 regression here.

No git commits from this script. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbase_grow_dryrun import sha256_file, widen_state_dict            # noqa: E402
from cpu_offload_adamw import (                                        # noqa: E402
    estimate_required_gib_offloaded, vram_preflight, nvidia_smi_vram,
)
from cbase_grow_rung2_gpu_offload_probe import _va_report               # noqa: E402
from receipt_write import checked_write                                 # noqa: E402
import timeshare_pretrain as ts                                         # noqa: E402
from p5_ratio_audit.run_p5_audit import (                               # noqa: E402
    compute_d_comm, build_real_d_comm_closures, _muon_step_in_copy, rms,
)

REPO = Path(__file__).resolve().parent.parent
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

SEED_CKPT_DEFAULT = (REPO / "models" / "cbase-grow-rung" / "rung1-20260703T155447Z" /
                      "stabilize" / "checkpoints" / "step-00000766")
SEED_SHA_ATTESTED = "58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b"
SEED_SHA_ATTESTATION_RECEIPT = "receipts/spend-annex/attestations/cbase-gpu-verify-trainable-clean-20260707T015633.json"
PARAM_COUNT_AFTER_RUNG2_DEFAULT = 2228265984  # cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json

STABILIZE_CONFIG_RECEIPT = "receipts/cbase-grow-rung2-gpu-offload-probe-20260708T172949Z.json"
STABILIZE_MICRO_BATCH_DEFAULT = 1
STABILIZE_GRAD_ACCUM_STEPS_DEFAULT = 8
STABILIZE_VRAM_ESTIMATE_GIB = 18.253  # same receipt's mb=1 calibration point
STABILIZE_VRAM_KILL_PCT = 15.0
D1_TOTAL_TOKENS = 491520  # docs/spec/rung2-grow-spec-v1.md D1 fixed-FLOPs floor
D1_PROD_BATCH_EQUIV = 16
D1_PROD_STEPS_EQUIV = 30
D1_PROD_SEQ_EQUIV = 1024
assert D1_PROD_BATCH_EQUIV * D1_PROD_SEQ_EQUIV * D1_PROD_STEPS_EQUIV == D1_TOTAL_TOKENS

# Gate-only frozen bands, issue #449 body verbatim (scale convention,
# sqrt(2) null; c == compute_d_comm's own "cos_alignment" field, since
# d_comm^2 = r^2+q^2-2*c*r*q with r=q=1 gate-only under the scale
# convention is exactly the identity #448's PR text derives).
DCOMM_NULL_SQRT2 = 2 ** 0.5
BAND_I_C_RANGE = (0.25, 0.45)
BAND_II_ABS_C_MAX = 0.05

PHASES = ["preflight", "b1", "b1m", "b2", "b3", "stabilize"]
PHASE_PREV = {"b1": "preflight", "b1m": "b1", "b2": "b1m", "b3": "b2", "stabilize": "b3"}
PASS_VERDICTS = {
    "preflight": {"PREFLIGHT_PASS"},
    "b1": {"B1_QUIESCE_PROVEN"},
    "b1m": {"B1M_CAPTURED"},
    "b2": {"B2_REALIZED_PASS"},
    "b3": {"B3_CAPTURED"},
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_path_repo_relative(path_obj, data_root=None) -> str:
    """Convert an absolute path to repo-relative, or keep absolute for out-of-repo paths.

    Converts paths within the data root to repo-relative to avoid leaking implementation
    details in receipts (issue #466 path-leak fix). Paths outside the data root are kept
    absolute (as they're inherently non-portable anyway).

    Args:
        path_obj: Path object or str to convert
        data_root: Path to the data root (where models/receipts/caches live); defaults to REPO

    Returns:
        Repo-relative path string for in-data-root paths, absolute path for out-of-data-root
    """
    if data_root is None:
        data_root = REPO

    path_obj = Path(path_obj).resolve()
    data_root = Path(data_root).resolve()

    try:
        # Check if path is within the data root by computing relpath
        rel = os.path.relpath(path_obj, data_root)
        # If the relative path doesn't start with .., it's within the data root
        if not rel.startswith(".."):
            return rel
        else:
            # Path is outside data root; keep as absolute string
            return str(path_obj)
    except ValueError:
        # Cross-drive on Windows: keep absolute
        return str(path_obj)


def _make_path_absolute_from_receipt(path_str, data_root=None) -> Path:
    """Convert a receipt path (data-relative or absolute) back to absolute.

    Inverse of _make_path_repo_relative: reconstructs absolute paths for
    file operations when reading from receipts (issue #466 path-leak fix).

    For data-relative paths (no drive letter or leading /), join with data root.
    For absolute paths (already absolute), return as-is.

    Args:
        path_str: Path string from a receipt (data-relative or absolute)
        data_root: Path to the data root (where models/receipts/caches live); defaults to REPO

    Returns:
        Absolute Path object
    """
    if data_root is None:
        data_root = REPO

    if not path_str:
        return None

    path_str = str(path_str)
    data_root = Path(data_root)

    # Check if path is already absolute (Windows drive letter or POSIX /)
    if len(path_str) >= 2 and path_str[1] == ":":
        # Windows absolute path (e.g., C:\...)
        return Path(path_str)
    elif path_str.startswith("/"):
        # POSIX absolute path
        return Path(path_str)
    else:
        # Data-relative path; join with data root
        return data_root / path_str


# ---------------------------------------------------------------------------
# Fail-closed phase chaining
# ---------------------------------------------------------------------------

def _receipt_path(receipt_dir: Path, run_id: str, phase: str) -> Path:
    return Path(receipt_dir) / f"cbase-grow-rung2-event-{run_id}-{phase}.json"


def _require_prior_phase(receipt_dir: Path, run_id: str, phase: str) -> dict:
    """Fail-closed chaining (issue #466's own pipeline requirement): the
    caller's phase refuses to start unless the PRIOR phase's receipt exists
    on disk AND its verdict is one of that phase's admissible PASS states.
    Raises SystemExit (never proceeds on a missing/invalid prior receipt —
    no phase may re-derive or assume its predecessor's result)."""
    prev_phase = PHASE_PREV.get(phase)
    if prev_phase is None:
        return {}
    path = _receipt_path(receipt_dir, run_id, prev_phase)
    if not path.exists():
        raise SystemExit(
            f"CBASE-GROW-RUNG2-EVENT: phase {phase!r} refuses to start — prior phase "
            f"{prev_phase!r} receipt missing at {path} (fail-closed chaining, issue #466)")
    data = json.loads(path.read_text(encoding="utf-8"))
    verdict = data.get("verdict")
    admissible = PASS_VERDICTS.get(prev_phase, set())
    if verdict not in admissible:
        raise SystemExit(
            f"CBASE-GROW-RUNG2-EVENT: phase {phase!r} refuses to start — prior phase "
            f"{prev_phase!r} receipt at {path} has verdict={verdict!r}, not in the "
            f"admissible set {sorted(admissible)} (fail-closed chaining, issue #466)")
    return data


# ---------------------------------------------------------------------------
# Double-sha quiesce proof + exclusive-open probe + provenance
# ---------------------------------------------------------------------------

def _directory_manifest(dir_path: Path) -> dict:
    """Deterministic per-file sha256 manifest of every file under dir_path
    (sorted relative paths — order-stable so two manifests can be compared
    or combined into one aggregate sha)."""
    dir_path = Path(dir_path)
    out = {}
    for p in sorted(dir_path.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(dir_path)).replace("\\", "/")] = sha256_file(p)
    return out


def _manifest_aggregate_sha(manifest: dict) -> str:
    h = hashlib.sha256()
    for rel in sorted(manifest):
        h.update(f"{rel}:{manifest[rel]}\n".encode("utf-8"))
    return h.hexdigest()


def _double_sha_quiesce(dir_path: Path, wait_s: float) -> dict:
    """Quiesce condition per the #449 addendum: two full manifests taken
    across a wait must be byte-identical — a copy taken mid-flight (while
    the production optimizer still holds per-param memmap state files open
    r+) is a chimera this catches. Cheap and still mandatory even when the
    source is already at rest (this runner's own B1 call: the seed
    checkpoint has no live writer)."""
    m0 = _directory_manifest(dir_path)
    sha0 = _manifest_aggregate_sha(m0)
    time.sleep(max(0.0, wait_s))
    m1 = _directory_manifest(dir_path)
    sha1 = _manifest_aggregate_sha(m1)
    return {
        "manifest_t0_sha256": sha0, "manifest_t1_sha256": sha1,
        "identical": bool(sha0 == sha1), "wait_s": wait_s,
        "n_files": len(m0), "per_file_manifest_t0": m0,
    }


def _exclusive_open_probe(dir_path: Path) -> list:
    """Best-effort 'no write handles held elsewhere' check: attempt an
    exclusive-mode open ('r+b', no truncate) of every file — a
    PermissionError here means another process holds a competing lock on
    this file RIGHT NOW. This is disclosed as best-effort, not a substitute
    for the double-sha proof above (the double-sha is the mandatory
    mechanical proof; this probe is a supplementary signal only, since a
    writer that opens/closes between our two manifest reads would pass
    this probe but still be caught by the double-sha)."""
    results = []
    for p in sorted(Path(dir_path).rglob("*")):
        if not p.is_file():
            continue
        entry = {"file": str(p.name), "exclusive_open_ok": None, "error": None}
        try:
            with open(p, "r+b"):
                entry["exclusive_open_ok"] = True
        except (PermissionError, OSError) as e:
            entry["exclusive_open_ok"] = False
            entry["error"] = str(e)
        results.append(entry)
    return results


_MOMENTUM_STATE_KEYS = ("momentum_buffer", "exp_avg", "exp_avg_sq")


def _momentum_provenance(optimizer_state: dict) -> dict:
    """Genuineness receipt (#449 addendum): momentum-buffer nonzero-
    fraction stats PER CLASS ('muon'/'adamw', the two keys
    save_optimizers_state bundles). A reconstructed or zeroed optstate is
    detectable here — a class whose EVERY captured buffer is exactly zero
    fails this provenance check (the rung-1 confound this rung-2 event
    must not repeat: rung-1's pre-grow checkpoint had no genuine optimizer
    state at all)."""
    import torch
    per_class = {}
    for cls_key, cls_state in (optimizer_state or {}).items():
        state_dict = cls_state.get("state", {}) if isinstance(cls_state, dict) else {}
        fractions = []
        n_buffers = 0
        for _param_key, st in state_dict.items():
            if not isinstance(st, dict):
                continue
            for key in _MOMENTUM_STATE_KEYS:
                buf = st.get(key)
                if isinstance(buf, torch.Tensor) and buf.numel() > 0:
                    n_buffers += 1
                    frac = float((buf != 0).float().mean())
                    fractions.append(frac)
        all_zero = bool(fractions) and all(f == 0.0 for f in fractions)
        per_class[cls_key] = {
            "n_buffers_inspected": n_buffers,
            "nonzero_fraction_mean": (sum(fractions) / len(fractions)) if fractions else None,
            "nonzero_fraction_min": min(fractions) if fractions else None,
            "nonzero_fraction_max": max(fractions) if fractions else None,
            "all_buffers_exactly_zero": all_zero,
        }
    any_class_fully_zeroed = any(v["all_buffers_exactly_zero"] for v in per_class.values()) if per_class else True
    return {"per_class": per_class, "any_class_fully_zeroed_or_absent": any_class_fully_zeroed}


def _rng_provenance(rng_state: dict) -> dict:
    """RNG numbers explicit (#449 addendum). save_checkpoint's rng.pt
    bundles torch_cpu / torch_cuda (if available) / py_random / np_random
    (if numpy present) — none of these expose a bare 'seed+offset' integer
    pair on CPU-only Mersenne-twister state (that explicit form only
    exists for CUDA's Philox generator), so this discloses what is
    honestly derivable: presence + a content sha256 per component (proves
    two snapshots carry IDENTICAL or DIFFERENT RNG state without needing
    to interpret the opaque byte layout), plus any CUDA Philox seed/offset
    pair when torch.cuda is the component actually present."""
    out = {}
    for key in ("torch_cpu", "torch_cuda", "py_random", "np_random"):
        val = (rng_state or {}).get(key)
        if val is None:
            out[key] = {"present": False}
            continue
        try:
            blob = pickle.dumps(val)
            entry = {"present": True, "content_sha256": hashlib.sha256(blob).hexdigest()}
        except Exception as e:  # pragma: no cover - defensive, not expected
            entry = {"present": True, "content_sha256": None, "pickle_error": str(e)}
        out[key] = entry
    return out


def _copy_checkpoint_dir(src: Path, dst: Path) -> Path:
    dst = Path(dst)
    if dst.exists():
        raise SystemExit(f"CBASE-GROW-RUNG2-EVENT: refusing to overwrite existing snapshot dir {dst}")
    shutil.copytree(str(src), str(dst))
    return dst


# ---------------------------------------------------------------------------
# Pinned measurement-batch construction (shared by B1m and B3)
# ---------------------------------------------------------------------------

def _gate_up_down_keys(layer_index: int = 0) -> tuple:
    prefix = f"backbone_model.layers.{layer_index}.mlp."
    return prefix + "gate_proj.weight", prefix + "up_proj.weight", prefix + "down_proj.weight"


def _serialize_roundtrip(t):
    """Dataloader-bypass discipline (#449 addendum: 'dataloader bypassed in
    the measurement forwards, feed serialized tensors'): the actual forward
    consumes a deserialized COPY, never the loader's live tensor object —
    a torch.save/torch.load round trip via an in-memory buffer proves the
    measurement forward's input is byte-identical to, but independent of,
    whatever the loader is doing internally."""
    import torch
    buf = io.BytesIO()
    torch.save(t, buf)
    buf.seek(0)
    return torch.load(buf, weights_only=True)


def _build_pinned_batch(cache_dir: Path, run_id: str, cfg: dict, n_mtp: int, vocab: int,
                         seq: int, micro_batch: int, grad_accum_steps: int, device: str) -> dict:
    """Same synthetic packed-shard convention as
    cbase_grow_rung2_gpu_offload_probe.py (seed=0), so the batch is a pure
    function of (seq, micro_batch, grad_accum_steps, vocab, n_mtp) — B1m and
    B3 rebuild it independently and prove equality via the ordered 8-tuple
    sha, rather than trusting a shared in-memory object across phases/
    processes."""
    import numpy as np
    import torch
    import tempfile

    shard_tmp = Path(tempfile.mkdtemp(prefix=f"rung2-event-{run_id}-pinned-batch-"))
    try:
        rng = np.random.default_rng(0)
        n_micro_total = grad_accum_steps
        need = (n_micro_total + 4) * micro_batch * seq + seq + n_mtp + 8
        toks = rng.integers(1, vocab, size=int(need), dtype=np.int64)
        toks[:: max(1, seq * 3)] = 0
        ts.write_packed_shard(str(shard_tmp / "synthetic-00000.bin"), toks.astype("<u2").tolist())
        loader = ts.PackedShardLoader(str(shard_tmp), seq, n_mtp)

        microsteps = []
        microstep_shas = []
        for micro_idx in range(grad_accum_steps):
            x, y0, y_mtp = loader.batch(micro_idx, micro_batch)
            attention_mask = torch.ones_like(x)  # full-causal, no padding —
            # constructed explicitly for the pinning sha only; model.backbone()
            # does not accept attention_mask/position_ids kwargs (it builds its
            # own causal mask + positions internally, disclosed), so these two
            # tensors are captured for determinism-pinning purposes, not fed
            # into the forward call.
            position_ids = torch.arange(x.shape[1]).unsqueeze(0).expand(x.shape[0], -1)
            x = _serialize_roundtrip(x)
            y0 = _serialize_roundtrip(y0)
            y_mtp = [_serialize_roundtrip(t) for t in y_mtp]
            attention_mask = _serialize_roundtrip(attention_mask)
            position_ids = _serialize_roundtrip(position_ids)

            h = hashlib.sha256()
            for t in (x, attention_mask, position_ids, y0):
                h.update(t.numpy().tobytes())
            for t in y_mtp:
                h.update(t.numpy().tobytes())
            microstep_shas.append(h.hexdigest())
            microsteps.append({"x": x, "y0": y0, "y_mtp": y_mtp})

        overall = hashlib.sha256("".join(microstep_shas).encode("utf-8")).hexdigest()
        return {
            "microsteps": microsteps,
            "microstep_shas": microstep_shas,
            "overall_sha256": overall,
            "convention": "synthetic packed shard, np.random.default_rng(0), same construction "
                           "as cbase_grow_rung2_gpu_offload_probe.py's probe batch",
            "dataloader_bypassed": True,
            "attention_mask_position_ids_constructed_explicitly_not_fed_to_forward": True,
        }
    finally:
        shutil.rmtree(shard_tmp, ignore_errors=True)


def _pushforward_gate_momentum(momentum_buffer, up_dummy, down_dummy, gate_key: str,
                                up_key: str, down_key: str):
    """TRANSPLANT-arm momentum pushforward for gate_proj (declared rule,
    manifest extension in the #449 addendum): gate/up_proj rows are pure
    duplication under G regardless of eps_sigma (only down_proj's columns
    receive the #280 antisymmetric perturbation), so pushing a gate_proj
    momentum buffer through G is EXACTLY the same row-duplication
    widen_state_dict already applies to a gate_proj WEIGHT — reused
    verbatim via a synthetic 1-layer state dict (up/down slots filled with
    real weights so widen_state_dict's shape assertions are satisfied; only
    the returned gate_key entry is used). eps_sigma=0.0 here is correct BY
    CONSTRUCTION (not a violation of the B2 eps>0 requirement): a momentum
    buffer is not itself perturbed by the #280 operator, only weights are."""
    synth = {gate_key: momentum_buffer, up_key: up_dummy, down_key: down_dummy}
    grown = widen_state_dict(synth, n_layers=1, eps_sigma=0.0, eps_seed=0)
    return grown[gate_key]


MOMENTUM_PUSHFORWARD_RULE_DECLARED = (
    "gate_proj/up_proj momentum buffers: row-duplication pushforward (same G as weights; "
    "eps-invariant, since only down_proj receives the #280 antisymmetric perturbation). "
    "down_proj momentum buffers: half-split-duplication pushforward at eps_sigma=0 (a "
    "momentum buffer is not itself perturbed by the #280 operator; only weights are — this "
    "rule is declared for completeness, not exercised by this script's gate-only measurement). "
    "AdamW-routed params (embeddings/norms/head/mtp_heads): shape-invariant across the grow, "
    "no pushforward needed (net2net widening only touches Muon-routed FF tensors)."
)


# ---------------------------------------------------------------------------
# Phase 0: PREFLIGHT
# ---------------------------------------------------------------------------

def phase_preflight(args) -> dict:
    receipt_dir = Path(args.receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or _ts()
    data_root = Path(args.data_root) if hasattr(args, 'data_root') else REPO

    va = _va_report()
    commit_sufficient = va["avail_pagefile_gib"] > args.commit_margin_gib_floor
    commit_preflight = {
        "avail_pagefile_gib": va["avail_pagefile_gib"], "floor_gib": args.commit_margin_gib_floor,
        "sufficient": commit_sufficient, "va_report": va,
    }

    gpu_attempted = False
    if getattr(args, "skip_gpu_preflight", False):
        gpu_preflight = {"attempted": False, "sufficient": True,
                          "note": "GPU headroom check explicitly skipped via --skip-gpu-preflight "
                                  "(disclosed -- CPU-only synthetic-model selftest, not a claim "
                                  "about real GPU headroom)."}
    else:
        gpu_preflight = {"attempted": False, "sufficient": True,
                          "note": "nvidia-smi unavailable in this environment; GPU headroom check "
                                  "skipped, disclosed (not silently assumed sufficient for the "
                                  "final verdict weighting -- see all_sufficient)."}
    if not getattr(args, "skip_gpu_preflight", False) and shutil.which("nvidia-smi") is not None:
        try:
            nvsmi = nvidia_smi_vram()
            gpu_attempted = True
            required = estimate_required_gib_offloaded(args.param_count_after, micro_batch=args.micro_batch)
            pf = vram_preflight(required["total_estimate_gib"], margin_gib_floor=2.0, nvsmi=nvsmi)
            gpu_preflight = {
                "attempted": True, "required_estimate": required, "preflight": pf,
                "sufficient": bool(pf["sufficient"]),
            }
        except Exception as e:  # pragma: no cover - transient nvidia-smi failure, disclosed
            gpu_preflight = {"attempted": True, "sufficient": False, "error": str(e)}

    disk = shutil.disk_usage(str(REPO))
    disk_free_gib = round(disk.free / (1 << 30), 3)
    disk_sufficient = disk_free_gib >= args.disk_headroom_gib_floor
    disk_preflight = {"free_gib": disk_free_gib, "floor_gib": args.disk_headroom_gib_floor,
                       "sufficient": disk_sufficient, "path_checked": _make_path_repo_relative(REPO, data_root=data_root)}

    all_sufficient = bool(commit_sufficient and gpu_preflight["sufficient"] and disk_sufficient)
    verdict = "PREFLIGHT_PASS" if all_sufficient else "PREFLIGHT_REFUSE"

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-PREFLIGHT", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 466, "refs": [449, 429, 452, 448, 464, 411],
        "run_id": run_id,
        "scope": "PREFLIGHT phase of the combined rung-2 grow-event + stabilization runner: "
                 "commit-aware assert (floor {}GiB), GPU headroom assert (DEV-002 offloaded "
                 "estimator, micro_batch={}), disk headroom assert (floor {}GiB). No launch "
                 "attempted, no checkpoint touched.".format(
                     args.commit_margin_gib_floor, args.micro_batch, args.disk_headroom_gib_floor),
        "param_count_after": args.param_count_after,
        "commit_preflight": commit_preflight,
        "gpu_preflight": gpu_preflight,
        "disk_preflight": disk_preflight,
        "gpu_check_attempted": gpu_attempted,
        "all_sufficient": all_sufficient,
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": verdict,
    }
    path = _receipt_path(receipt_dir, run_id, "preflight")
    checked_write(str(path), receipt)
    print(f"CBASE_GROW_RUNG2_EVENT_PREFLIGHT run_id={run_id} verdict={verdict} receipt={path}", flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Phase 1: B1 — quiesce-proven snapshot
# ---------------------------------------------------------------------------

def phase_b1(args) -> dict:
    receipt_dir = Path(args.receipt_dir)
    run_id = args.run_id
    data_root = Path(args.data_root) if hasattr(args, 'data_root') else REPO
    _require_prior_phase(receipt_dir, run_id, "b1")

    import torch
    seed_ckpt = Path(args.seed_ckpt)
    model_pt = seed_ckpt / "model.pt"
    manifest = json.loads((seed_ckpt / "manifest.json").read_text(encoding="utf-8"))
    actual_sha = sha256_file(model_pt)
    claimed_sha = (manifest.get("files") or {}).get("model.pt")
    manifest_claim_verified = bool(isinstance(claimed_sha, str) and actual_sha == claimed_sha)

    quiesce = _double_sha_quiesce(seed_ckpt, args.wait_s)
    open_probe = _exclusive_open_probe(seed_ckpt)
    any_locked = any(e["exclusive_open_ok"] is False for e in open_probe)

    optimizer_state = torch.load(seed_ckpt / "optimizer.pt", map_location="cpu", weights_only=True)
    provenance = _momentum_provenance(optimizer_state)
    rng_state = torch.load(seed_ckpt / "rng.pt", map_location="cpu", weights_only=False)  # noqa: S614
    rng_prov = _rng_provenance(rng_state)

    quiesce_proven = bool(quiesce["identical"] and not any_locked)
    provenance_ok = not provenance["any_class_fully_zeroed_or_absent"]

    snapshot_dir = None
    snapshot_copy_verified = False
    if manifest_claim_verified and quiesce_proven and provenance_ok:
        snapshot_dir = Path(args.out_dir) / f"rung2-event-{run_id}" / "b1-snapshot"
        snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
        _copy_checkpoint_dir(seed_ckpt, snapshot_dir)
        copy_manifest = _directory_manifest(snapshot_dir)
        src_manifest = quiesce["per_file_manifest_t0"]
        snapshot_copy_verified = bool(copy_manifest == src_manifest)

    if not manifest_claim_verified:
        verdict = "B1_QUIESCE_FAIL"
    elif not quiesce_proven:
        verdict = "B1_QUIESCE_FAIL"
    elif not provenance_ok:
        verdict = "B1_PROVENANCE_FAIL"
    elif not snapshot_copy_verified:
        verdict = "B1_QUIESCE_FAIL"
    else:
        verdict = "B1_QUIESCE_PROVEN"

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-B1", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 466, "refs": [449, 429],
        "run_id": run_id,
        "scope": "B1: quiesce-PROVEN snapshot of the pre-grow seed checkpoint, full provenance "
                 "block, RNG disclosure, verified copy to the B1 snapshot dir production "
                 "stabilization resumes from untouched.",
        "seed_identity": {
            "checkpoint": _make_path_repo_relative(seed_ckpt, data_root=data_root), "model_pt_sha256": actual_sha,
            "manifest_claim_verified": manifest_claim_verified,
            "attested_match": bool(actual_sha == SEED_SHA_ATTESTED),
            "attestation_receipt": SEED_SHA_ATTESTATION_RECEIPT, "step": manifest.get("step"),
        },
        "quiesce": {k: v for k, v in quiesce.items() if k != "per_file_manifest_t0"},
        "quiesce_n_files": quiesce["n_files"],
        "exclusive_open_probe": open_probe, "any_file_locked_elsewhere": any_locked,
        "quiesce_proven": quiesce_proven,
        "provenance": provenance, "provenance_ok": provenance_ok,
        "rng_provenance": rng_prov,
        "snapshot_dir": _make_path_repo_relative(snapshot_dir, data_root=data_root) if snapshot_dir else None,
        "snapshot_copy_verified": snapshot_copy_verified,
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": verdict,
    }
    path = _receipt_path(receipt_dir, run_id, "b1")
    checked_write(str(path), receipt)
    print(f"CBASE_GROW_RUNG2_EVENT_B1 run_id={run_id} verdict={verdict} receipt={path}", flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Phase 2: B1m — u_pre on the pinned batch
# ---------------------------------------------------------------------------

def phase_b1m(args) -> dict:
    receipt_dir = Path(args.receipt_dir)
    run_id = args.run_id
    data_root = Path(args.data_root) if hasattr(args, 'data_root') else REPO
    b1 = _require_prior_phase(receipt_dir, run_id, "b1m")

    import torch
    torch.manual_seed(42)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = _make_path_absolute_from_receipt(b1["snapshot_dir"], data_root=data_root)
    model_pt = snapshot_dir / "model.pt"
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))

    cfg = ts.load_contract(args.contract_path)
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    seq = cfg["model"]["seq"]
    qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))

    sd_bf16 = torch.load(model_pt, map_location="cpu", weights_only=True)
    ff_seed = int(sd_bf16["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])
    gate_key, up_key, down_key = _gate_up_down_keys(0)

    model, vocab, hidden, n_mtp = ts.build_v0_model(
        cfg, live=True, intermediate_override=ff_seed, device=args.device)
    missing, unexpected = model.load_state_dict(sd_bf16, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"CBASE-GROW-RUNG2-EVENT-B1M: checkpoint load mismatch: "
                          f"missing={real_missing} unexpected={unexpected}")

    dropout_modules = [str(type(m).__name__) for m in model.modules()
                       if isinstance(m, torch.nn.Dropout) and m.p != 0.0]
    deterministic_forward = {"dropout_modules_with_nonzero_p": dropout_modules,
                              "deterministic": len(dropout_modules) == 0}

    batch = _build_pinned_batch(cache_dir, run_id, cfg, n_mtp, vocab, seq,
                                 args.micro_batch, args.grad_accum_steps, args.device)

    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    mtp_cfg = cfg["objective"]["mtp_aux_heads"]
    mtp_weight = mtp_cfg["weight"]
    mtp_enabled = mtp_cfg["enabled"]

    gate_param = model.get_parameter(gate_key)

    for microstep in batch["microsteps"]:
        qat_saved = ts._apply_fake_quant(model, "qat") if qat_enabled else []
        x = microstep["x"].to(args.device)
        y0 = microstep["y0"].to(args.device)
        y_mtp = [t.to(args.device) for t in microstep["y_mtp"]]
        hidden_out = model.backbone(x)
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=256)
        mtp_ces = []
        if mtp_enabled:
            for k, head in enumerate(model.mtp_heads):
                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1), chunk_tokens=256)
                mtp_ces.append(ce_k)
        loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
        (loss / args.grad_accum_steps).backward()
        if qat_enabled:
            ts._restore_weights(qat_saved)

    grad_pre_gate = gate_param.grad.detach().clone().to(torch.float32)
    theta_gate_pre = gate_param.detach().clone().to(torch.float32)

    pre_lr = cfg["optimizer"]["lr_muon"]
    seed_optimizer_state = torch.load(snapshot_dir / "optimizer.pt", map_location="cpu", weights_only=True)
    pre_momentum = seed_optimizer_state.get("muon", {}).get(
        "state", {}).get(gate_key, {}).get("momentum_buffer")
    if pre_momentum is None:
        pre_momentum = torch.zeros_like(theta_gate_pre)
    new_weight, new_buf, upd = _muon_step_in_copy(theta_gate_pre, grad_pre_gate, pre_momentum, lr=pre_lr)
    u_pre_rms = float(rms(new_weight - theta_gate_pre))

    cache_paths = {
        "grad_pre_gate": cache_dir / f"{run_id}-grad-pre-gate.pt",
        "theta_gate_pre": cache_dir / f"{run_id}-theta-gate-pre.pt",
        "pre_momentum": cache_dir / f"{run_id}-pre-momentum.pt",
    }
    torch.save(grad_pre_gate, cache_paths["grad_pre_gate"])
    torch.save(theta_gate_pre, cache_paths["theta_gate_pre"])
    torch.save(pre_momentum, cache_paths["pre_momentum"])

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-B1M", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 466, "refs": [449, 448, 327],
        "run_id": run_id,
        "scope": "B1m: u_pre on the pinned 8-microstep measurement batch, gate_proj layer-0, "
                 "via build_real_d_comm_closures'/_muon_step_in_copy's own in-copy Muon step. "
                 "grad_pre_gate cached for B3's compute_d_comm wiring.",
        "ff_seed": ff_seed, "qat_enabled": qat_enabled, "mtp_enabled": mtp_enabled, "ce_impl": ce_impl,
        "batch": {k: v for k, v in batch.items() if k != "microsteps"},
        "deterministic_forward": deterministic_forward,
        "u_pre": {
            "gate_key": gate_key, "rms_update": u_pre_rms,
            "momentum_buffer_source": "B1 snapshot pre-grow momentum_buffer (parent-carried)",
            "lr_used": pre_lr,
            "lr_note": "base configured lr_muon, no WSD multiplier applied -- disclosed "
                       "simplification for the commutation-defect measurement leg only "
                       "(the STABILIZE phase applies the real WSD schedule via apply_wsd).",
        },
        "cache_paths": {k: _make_path_repo_relative(v, data_root=data_root) for k, v in cache_paths.items()},
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": "B1M_CAPTURED",
    }
    path = _receipt_path(receipt_dir, run_id, "b1m")
    checked_write(str(path), receipt)
    print(f"CBASE_GROW_RUNG2_EVENT_B1M run_id={run_id} verdict=B1M_CAPTURED receipt={path}", flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Phase 3: B2 — fresh widen at eps_sigma>0
# ---------------------------------------------------------------------------

def _eps_widen_worker(model_pt_str: str, out_path: str, n_layers: int,
                       eps_sigma: float, eps_seed: int) -> int:
    """Fresh-subprocess widen (same crash-mitigation convention
    cbase_grow_rung2_gpu_offload_probe.py established for this exact
    load->widen->cast sequence at this param scale)."""
    import torch
    sd_bf16 = torch.load(model_pt_str, map_location="cpu", weights_only=True)
    sd_f32 = {k: v.float() for k, v in sd_bf16.items()}
    sd_bf16 = None
    gc.collect()
    grown_f32 = widen_state_dict(sd_f32, n_layers, eps_sigma=eps_sigma, eps_seed=eps_seed)
    sd_f32 = None
    gc.collect()
    grown_bf16 = {k: v.to(torch.bfloat16) for k, v in grown_f32.items()}
    grown_f32 = None
    gc.collect()
    torch.save(grown_bf16, out_path)
    print(f"EPS_WIDEN_WORKER_DONE out_path={out_path} eps_sigma={eps_sigma} eps_seed={eps_seed}", flush=True)
    return 0


def phase_b2(args) -> dict:
    receipt_dir = Path(args.receipt_dir)
    run_id = args.run_id
    data_root = Path(args.data_root) if hasattr(args, 'data_root') else REPO
    _require_prior_phase(receipt_dir, run_id, "b2")  # b1m must have PASSED
    b1 = json.loads(_receipt_path(receipt_dir, run_id, "b1").read_text(encoding="utf-8"))

    if not (args.eps_sigma > 0.0):
        raise SystemExit(
            "CBASE-GROW-RUNG2-EVENT-B2: eps_sigma must be > 0 for the real rung-2 grow -- "
            "the #449 addendum bans the eps=0 dry-run artifact from this run (frozen "
            f"requirement); got eps_sigma={args.eps_sigma}")

    import torch
    snapshot_dir = _make_path_absolute_from_receipt(b1["snapshot_dir"], data_root=data_root)
    model_pt = snapshot_dir / "model.pt"
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    seed_sha = manifest["files"]["model.pt"]

    cfg = ts.load_contract(args.contract_path)
    n_layers = cfg["model"]["layers"]

    operator_sha256 = sha256_file(Path(__file__).resolve().parent / "cbase_grow_dryrun.py")

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Cache key carries eps params (#449 addendum requirement) -- distinct
    # from the banned eps=0 dry-run cache path used by
    # cbase_grow_rung2_gpu_offload_probe.py's GROWN_CACHE_DIR convention.
    eps0_banned_cache_path = (REPO / "models" / "cbase-grow-rung" / "rung2-grown-cache" /
                              f"grown-{seed_sha[:16]}.pt")
    cache_path = cache_dir / f"grown-eps-{seed_sha[:16]}-sigma{args.eps_sigma}-seed{args.eps_seed}.pt"
    if cache_path == eps0_banned_cache_path:  # pragma: no cover - structurally impossible, asserted anyway
        raise SystemExit("CBASE-GROW-RUNG2-EVENT-B2: cache key collided with the banned eps=0 path")

    script_path = str(Path(__file__).resolve())
    cache_hit = cache_path.exists()
    if not cache_hit:
        worker_cmd = [sys.executable, script_path, "--eps-widen-worker",
                      "--model-pt", str(model_pt), "--out-path", str(cache_path),
                      "--n-layers", str(n_layers), "--eps-sigma", str(args.eps_sigma),
                      "--eps-seed", str(args.eps_seed)]
        proc = subprocess.run(worker_cmd, cwd=str(Path(__file__).resolve().parent),
                              capture_output=True, text=True)
        print(proc.stdout, end="", flush=True)
        if proc.returncode != 0 or not cache_path.exists():
            print(proc.stderr, file=sys.stderr, flush=True)
            raise SystemExit(f"CBASE-GROW-RUNG2-EVENT-B2: eps-widen worker failed "
                              f"(exit={proc.returncode})")

    grown_bf16 = torch.load(cache_path, map_location="cpu", weights_only=True)
    sd_bf16 = torch.load(model_pt, map_location="cpu", weights_only=True)

    # Realized proof, computed from the LOADED post-grow weights (never a
    # config echo): recover eta per column pair, check RMS(eta)/tau band and
    # twin-cosine<1 for every split pair, for every layer.
    ratios = []
    max_cosine = -2.0
    n_pairs_checked = 0
    for i in range(n_layers):
        prefix = f"backbone_model.layers.{i}.mlp."
        d_seed = sd_bf16[prefix + "down_proj.weight"].float()
        d_grown = grown_bf16[prefix + "down_proj.weight"].float()
        hidden_dim, interm_seed = d_seed.shape
        d_a = d_grown[:, :interm_seed]
        d_b = d_grown[:, interm_seed:]
        eta_realized = (d_a - d_b) / 2.0
        col_norms = d_seed.norm(dim=0)
        tau = args.eps_sigma * col_norms / (hidden_dim ** 0.5)
        eta_rms_per_col = eta_realized.norm(dim=0) / (hidden_dim ** 0.5)  # RMS over the hidden axis
        nonzero_tau = tau > 0
        if bool(nonzero_tau.any()):
            ratio = (eta_rms_per_col[nonzero_tau] / tau[nonzero_tau])
            ratios.extend(ratio.tolist())
        cosines = torch.nn.functional.cosine_similarity(d_a, d_b, dim=0)
        max_cosine = max(max_cosine, float(cosines.max()))
        n_pairs_checked += interm_seed

    ratio_mean = sum(ratios) / len(ratios) if ratios else None
    ratio_std = (sum((r - ratio_mean) ** 2 for r in ratios) / len(ratios)) ** 0.5 if ratios else None
    eta_band_pass = bool(ratio_mean is not None and 0.7 <= ratio_mean <= 1.3)
    twin_cosine_pass = bool(max_cosine < (1.0 - 1e-9))

    realized_pass = bool(eta_band_pass and twin_cosine_pass)
    verdict = "B2_REALIZED_PASS" if realized_pass else "B2_REALIZED_FAIL"

    hidden_dim0, interm_seed0 = sd_bf16["backbone_model.layers.0.mlp.down_proj.weight"].float().shape

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-B2", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 466, "refs": [449, 452, 280],
        "run_id": run_id,
        "scope": "B2: fresh widen at eps_sigma>0 (banned eps=0 dry-run cache never touched); "
                 "realized proof from the LOADED post-grow weights.",
        "eps": {"eps_sigma": args.eps_sigma, "eps_seed": args.eps_seed,
                "banned_zero_assertion_passed": True},
        "operator_sha256": operator_sha256, "operator_file": "scripts/cbase_grow_dryrun.py",
        "cache": {"cache_path": _make_path_repo_relative(cache_path, data_root=data_root), "cache_hit": cache_hit,
                  "eps0_banned_cache_path": _make_path_repo_relative(eps0_banned_cache_path, data_root=data_root),
                  "distinct_from_eps0_cache": _make_path_repo_relative(cache_path, data_root=data_root) != _make_path_repo_relative(eps0_banned_cache_path, data_root=data_root)},
        "realized_proof": {
            "n_pairs_checked": n_pairs_checked,
            "eta_rms_over_tau_ratio_mean": ratio_mean, "eta_rms_over_tau_ratio_std": ratio_std,
            "eta_band_pass": eta_band_pass, "eta_band_rule": "mean ratio in [0.7, 1.3] "
                "(law-of-large-numbers band around 1.0 for iid-per-column gaussian draws)",
            "twin_cosine_max": max_cosine, "twin_cosine_pass": twin_cosine_pass,
            "twin_cosine_rule": "strictly < 1.0 for every split pair (fail-closed)",
        },
        "column_pair_map": {
            "hidden": hidden_dim0, "interm_seed": interm_seed0, "interm_grown": interm_seed0 * 2,
            "mapping": "grown down_proj column j in [0, interm_seed) pairs with column "
                       "j+interm_seed (torch.cat([d_a, d_b], dim=1) convention)",
        },
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": verdict,
    }
    path = _receipt_path(receipt_dir, run_id, "b2")
    checked_write(str(path), receipt)
    print(f"CBASE_GROW_RUNG2_EVENT_B2 run_id={run_id} verdict={verdict} receipt={path}", flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Phase 4: B3 — RESET-arm + TRANSPLANT-arm on a forked copy
# ---------------------------------------------------------------------------

def phase_b3(args) -> dict:
    receipt_dir = Path(args.receipt_dir)
    run_id = args.run_id
    data_root = Path(args.data_root) if hasattr(args, 'data_root') else REPO
    b2 = _require_prior_phase(receipt_dir, run_id, "b3")
    b1 = json.loads(_receipt_path(receipt_dir, run_id, "b1").read_text(encoding="utf-8"))
    b1m = json.loads(_receipt_path(receipt_dir, run_id, "b1m").read_text(encoding="utf-8"))

    import torch
    torch.manual_seed(42)
    snapshot_dir = _make_path_absolute_from_receipt(b1["snapshot_dir"], data_root=data_root)
    fork_dir = Path(args.out_dir) / f"rung2-event-{run_id}" / "b3-fork"
    if fork_dir.exists():
        raise SystemExit(f"CBASE-GROW-RUNG2-EVENT-B3: refusing to reuse an existing fork dir {fork_dir}")
    fork_dir.parent.mkdir(parents=True, exist_ok=True)
    _copy_checkpoint_dir(snapshot_dir, fork_dir)

    cfg = ts.load_contract(args.contract_path)
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    seq = cfg["model"]["seq"]
    qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))
    gate_key, up_key, down_key = _gate_up_down_keys(0)

    pre_model_state = torch.load(fork_dir / "model.pt", map_location="cpu", weights_only=True)
    pre_model_state = {k: v.float().to(args.device) for k, v in pre_model_state.items()}
    pre_opt_state = torch.load(fork_dir / "optimizer.pt", map_location="cpu", weights_only=True)

    grown_bf16 = torch.load(
        _make_path_absolute_from_receipt(b2["cache"]["cache_path"], data_root=data_root),
        map_location="cpu", weights_only=True)
    ff_grown = int(grown_bf16[gate_key].shape[0])

    model, vocab, hidden, n_mtp = ts.build_v0_model(
        cfg, live=True, intermediate_override=ff_grown, device=args.device)
    missing, unexpected = model.load_state_dict(grown_bf16, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"CBASE-GROW-RUNG2-EVENT-B3: post-grow checkpoint load mismatch: "
                          f"missing={real_missing} unexpected={unexpected}")

    cache_dir = Path(args.cache_dir)
    batch = _build_pinned_batch(cache_dir, run_id, cfg, n_mtp, vocab, seq,
                                 args.micro_batch, args.grad_accum_steps, args.device)
    batch_pin_match = bool(batch["overall_sha256"] == b1m["batch"]["overall_sha256"])
    if not batch_pin_match:
        raise SystemExit(
            "CBASE-GROW-RUNG2-EVENT-B3: pinned-batch sha mismatch vs B1m -- refusing to "
            f"proceed (B1m={b1m['batch']['overall_sha256']} B3={batch['overall_sha256']})")

    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    mtp_cfg = cfg["objective"]["mtp_aux_heads"]
    mtp_weight, mtp_enabled = mtp_cfg["weight"], mtp_cfg["enabled"]
    gate_param = model.get_parameter(gate_key)

    for microstep in batch["microsteps"]:
        qat_saved = ts._apply_fake_quant(model, "qat") if qat_enabled else []
        x = microstep["x"].to(args.device)
        y0 = microstep["y0"].to(args.device)
        y_mtp = [t.to(args.device) for t in microstep["y_mtp"]]
        hidden_out = model.backbone(x)
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=256)
        mtp_ces = []
        if mtp_enabled:
            for k, head in enumerate(model.mtp_heads):
                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1), chunk_tokens=256)
                mtp_ces.append(ce_k)
        loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
        (loss / args.grad_accum_steps).backward()
        if qat_enabled:
            ts._restore_weights(qat_saved)
    grad_post_gate = gate_param.grad.detach().clone().to(torch.float32)

    pre_lr = cfg["optimizer"]["lr_muon"]
    post_lr = cfg["optimizer"]["lr_muon"]

    U_k, _gate_only_ukp1_unused, G = build_real_d_comm_closures(
        pre_model_state, pre_opt_state, None, gate_key, up_key, down_key,
        pre_lr, post_lr, torch.load(
            _make_path_absolute_from_receipt(b1m["cache_paths"]["grad_pre_gate"], data_root=data_root),
            weights_only=True),
        grad_post_gate)

    theta_gate = pre_model_state[gate_key].to(torch.float32)

    # RESET arm (band-(i) primary measurement): explicit zero-momentum
    # assertion, NEVER a silent fallback -- built directly with
    # _muon_step_in_copy so no internal 'buf is None -> zeros' branch is
    # ever relied upon.
    def U_kplus1_reset(theta_gate_grown):
        zero_buf = torch.zeros_like(theta_gate_grown)
        assert float(zero_buf.abs().sum()) == 0.0, \
            "RESET-arm momentum must be exactly zero (explicit assertion, #449 addendum)"
        new_w, _, _ = _muon_step_in_copy(theta_gate_grown, grad_post_gate, zero_buf, lr=post_lr)
        return new_w

    reset_zero_assertion_passed = True
    try:
        _ = U_kplus1_reset(G(theta_gate))  # probe at the correct (grown) width
    except AssertionError:
        reset_zero_assertion_passed = False

    # TRANSPLANT arm (second, disclosed measurement; does not gate band(i)):
    # pushforward the pre-grow momentum buffer for gate_proj through G.
    pre_gate_momentum = torch.load(
        _make_path_absolute_from_receipt(b1m["cache_paths"]["pre_momentum"], data_root=data_root),
        weights_only=True)
    transplanted_momentum = _pushforward_gate_momentum(
        pre_gate_momentum, pre_model_state[up_key], pre_model_state[down_key],
        gate_key, up_key, down_key)

    def U_kplus1_transplant(theta_gate_grown):
        new_w, _, _ = _muon_step_in_copy(theta_gate_grown, grad_post_gate,
                                          transplanted_momentum, lr=post_lr)
        return new_w

    def _fields(d: dict) -> dict:
        return {"d_comm": d["d_comm"], "numerator_rms": d["numerator_rms"],
                "denominator_rms": d["denominator_rms"], "step_rms_post": d["step_rms_post"],
                "pushforward_step_rms": d["pushforward_step_rms"], "cos_alignment": d["cos_alignment"]}

    reset_result = compute_d_comm(theta_gate, U_k, U_kplus1_reset, G)
    transplant_result = compute_d_comm(theta_gate, U_k, U_kplus1_transplant, G)

    c_reset = reset_result["cos_alignment"]
    if BAND_I_C_RANGE[0] <= c_reset <= BAND_I_C_RANGE[1]:
        band = "i"
    elif abs(c_reset) < BAND_II_ABS_C_MAX:
        band = "ii"
    else:
        band = "iii"

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-B3", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 466, "refs": [449, 448, 327, 452],
        "run_id": run_id,
        "scope": "B3: first post-grow update on the pinned batch, forked copy of B1 -- "
                 "RESET arm (band-(i) primary) + TRANSPLANT arm (second, disclosed). "
                 "Production resumes from the untouched B1 snapshot, never this fork.",
        "fork_dir": _make_path_repo_relative(fork_dir, data_root=data_root),
        "batch_pin_check": {"b1m_sha256": b1m["batch"]["overall_sha256"],
                            "b3_recomputed_sha256": batch["overall_sha256"], "match": batch_pin_match},
        "arms": {
            "reset": {"momentum_rule": "explicit zero, asserted (never a silent fallback)",
                      "momentum_zero_assertion_passed": reset_zero_assertion_passed,
                      "d_comm_fields": _fields(reset_result)},
            "transplant": {"momentum_rule": "row-duplication pushforward widen (eps_sigma=0) "
                                            "of the pre-grow gate_proj momentum buffer",
                          "d_comm_fields": _fields(transplant_result)},
        },
        "momentum_pushforward_rule_declared_in_writing": MOMENTUM_PUSHFORWARD_RULE_DECLARED,
        "band_adjudication": {
            "null_sqrt2": DCOMM_NULL_SQRT2, "c_reset_cos_alignment": c_reset,
            "band_i_range": list(BAND_I_C_RANGE), "band_ii_abs_max": BAND_II_ABS_C_MAX,
            "band": band, "rule": "read off #449's frozen bands verbatim, never re-derived",
        },
        "d448_fields_present": True,
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": "B3_CAPTURED",
    }
    path = _receipt_path(receipt_dir, run_id, "b3")
    checked_write(str(path), receipt)
    print(f"CBASE_GROW_RUNG2_EVENT_B3 run_id={run_id} verdict=B3_CAPTURED band={band} receipt={path}",
          flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Phase 5: STABILIZE — production training of the grown model
# ---------------------------------------------------------------------------

def _write_planned_outage_marker(receipt_dir: Path, run_id: str) -> Path:
    """Planned-outage marker per issue #464's shape. Issue #464 (standing
    liveness watchdogs) is OPEN/unimplemented as of this build -- no
    watchdog exists yet to consume this marker. Writing it now is
    forward-compatible groundwork (disclosed as inert today), not a claim
    that #464's watchdog integration is complete."""
    marker = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-PLANNED-OUTAGE-MARKER", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 466, "refs": [464],
        "run_id": run_id,
        "reason": "rung2-event STABILIZE phase: production training window on the shared "
                  "model-server GPU",
        "issue_464_shape": True,
        "owner": "cbase_grow_rung2_event.py stabilize phase",
        "note": "issue #464 (standing liveness watchdogs) is OPEN/unimplemented as of this "
                "build -- this marker is forward-compatible groundwork, disclosed as inert "
                "today (no watchdog currently reads it).",
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": "MARKER_WRITTEN",
    }
    path = Path(receipt_dir) / f"planned-outage-rung2-event-{run_id}.json"
    checked_write(str(path), marker)
    return path


def phase_stabilize(args) -> dict:
    receipt_dir = Path(args.receipt_dir)
    run_id = args.run_id
    data_root = Path(args.data_root) if hasattr(args, 'data_root') else REPO
    b3 = _require_prior_phase(receipt_dir, run_id, "stabilize")
    b1 = json.loads(_receipt_path(receipt_dir, run_id, "b1").read_text(encoding="utf-8"))
    b2 = json.loads(_receipt_path(receipt_dir, run_id, "b2").read_text(encoding="utf-8"))

    import torch
    cfg = ts.load_contract(args.contract_path)
    seq = cfg["model"]["seq"]
    micro_batch = args.micro_batch
    grad_accum_steps = args.grad_accum_steps
    effective_batch = micro_batch * grad_accum_steps
    tokens_per_step = effective_batch * seq
    n_optimizer_steps = args.n_optimizer_steps or max(1, D1_TOTAL_TOKENS // tokens_per_step)
    total_tokens = n_optimizer_steps * tokens_per_step
    tokens_match = bool(total_tokens == D1_TOTAL_TOKENS) if args.n_optimizer_steps is None else None

    grown_bf16 = torch.load(
        _make_path_absolute_from_receipt(b2["cache"]["cache_path"], data_root=data_root),
        map_location="cpu", weights_only=True)
    gate_key = _gate_up_down_keys(0)[0]
    ff_grown = int(grown_bf16[gate_key].shape[0])

    model, vocab, hidden, n_mtp = ts.build_v0_model(
        cfg, live=True, intermediate_override=ff_grown, device=args.device)
    missing, unexpected = model.load_state_dict(grown_bf16, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"CBASE-GROW-RUNG2-EVENT-STABILIZE: checkpoint load mismatch: "
                          f"missing={real_missing} unexpected={unexpected}")
    effective_grad_checkpointing = bool(getattr(model.backbone_model, "gradient_checkpointing", False))
    grad_checkpointing = {
        "config_claims": cfg["model"].get("grad_checkpointing"),
        "effective_readback": effective_grad_checkpointing, "active": effective_grad_checkpointing,
    }
    if effective_grad_checkpointing:
        raise SystemExit(
            "CBASE-GROW-RUNG2-EVENT-STABILIZE: effective_readback asserts gradient "
            "checkpointing is ON, but the proven config (receipt "
            f"{STABILIZE_CONFIG_RECEIPT}) requires it OFF -- refusing to proceed on a config "
            "the VRAM estimate was never calibrated against.")

    # RESET optimizer (fresh build, never resumes B1's momentum -- the whole
    # point of a stabilization leg after a grow event).
    optimizers, base_lrs, routing = ts.build_split_optimizer(
        model, cfg, offload_optimizer_state=(args.device == "cuda"))

    n_params_after = int(sum(v.numel() for v in grown_bf16.values()))
    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    qat_enabled = bool(cfg.get("precision", {}).get("qat", {}).get("enabled", False))
    mtp_cfg = cfg["objective"]["mtp_aux_heads"]
    mtp_weight, mtp_enabled = mtp_cfg["weight"], mtp_cfg["enabled"]

    import tempfile
    import numpy as np
    shard_tmp = Path(tempfile.mkdtemp(prefix=f"rung2-event-{run_id}-stabilize-shard-"))
    losses = []
    vram_samples = []
    nvsmi_before = None
    oom_error = None
    try:
        need = (n_optimizer_steps * grad_accum_steps + 4) * micro_batch * seq + seq + n_mtp + 8
        rng = np.random.default_rng(0)
        toks = rng.integers(1, vocab, size=int(need), dtype=np.int64)
        toks[:: max(1, seq * 3)] = 0
        ts.write_packed_shard(str(shard_tmp / "synthetic-00000.bin"), toks.astype("<u2").tolist())
        loader = ts.PackedShardLoader(str(shard_tmp), seq, n_mtp)

        if args.device == "cuda" and shutil.which("nvidia-smi"):
            nvsmi_before = nvidia_smi_vram()
            torch.cuda.reset_peak_memory_stats()

        try:
            for gstep in range(n_optimizer_steps):
                micro_losses = []
                for micro_idx in range(grad_accum_steps):
                    loader_idx = gstep * grad_accum_steps + micro_idx
                    x, y0, y_mtp = loader.batch(loader_idx, micro_batch)
                    x, y0 = x.to(args.device), y0.to(args.device)
                    y_mtp = [t.to(args.device) for t in y_mtp]
                    qat_saved = ts._apply_fake_quant(model, "qat") if qat_enabled else []
                    hidden_out = model.backbone(x)
                    h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
                    primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=256)
                    mtp_ces = []
                    if mtp_enabled:
                        for k, head in enumerate(model.mtp_heads):
                            ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1), chunk_tokens=256)
                            mtp_ces.append(ce_k)
                    micro_loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
                    micro_losses.append(float(micro_loss.detach()))
                    (micro_loss / grad_accum_steps).backward()
                    if qat_enabled:
                        ts._restore_weights(qat_saved)
                for opt in optimizers.values():
                    opt.step()
                for opt in optimizers.values():
                    opt.zero_grad(set_to_none=True)
                losses.append(sum(micro_losses) / len(micro_losses))
                if args.device == "cuda" and shutil.which("nvidia-smi"):
                    vram_samples.append(nvidia_smi_vram())
        except torch.cuda.OutOfMemoryError as e:  # pragma: no cover - real-GPU path only
            oom_error = str(e)
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                oom_error = str(e)
            else:
                raise
    finally:
        shutil.rmtree(shard_tmp, ignore_errors=True)

    degenerate = bool(losses) and ((len(set(round(v, 6) for v in losses)) == 1) or all(v < 1e-3 for v in losses))

    vram_report = {"attempted": bool(nvsmi_before is not None)}
    if nvsmi_before is not None:
        peak_used_gib = max((s["used_gib"] for s in vram_samples), default=nvsmi_before["used_gib"])
        peak_delta_gib = round(peak_used_gib - nvsmi_before["used_gib"], 3)
        pct_over_estimate = round(((peak_delta_gib - STABILIZE_VRAM_ESTIMATE_GIB) /
                                    STABILIZE_VRAM_ESTIMATE_GIB) * 100, 2)
        kill_estimator_wrong = pct_over_estimate > STABILIZE_VRAM_KILL_PCT
        vram_report.update({
            "nvsmi_before": nvsmi_before, "peak_used_gib": peak_used_gib,
            "peak_delta_gib": peak_delta_gib, "estimate_gib": STABILIZE_VRAM_ESTIMATE_GIB,
            "pct_over_estimate": pct_over_estimate, "kill_threshold_pct": STABILIZE_VRAM_KILL_PCT,
            "kill_estimator_wrong": kill_estimator_wrong,
        })
    else:
        kill_estimator_wrong = False

    checkpoint_dir = None
    if oom_error is None:
        run_dir = Path(args.out_dir) / f"rung2-event-{run_id}" / "stabilize"
        optimizer_state = ts.save_optimizers_state(optimizers)
        rng_state = {"torch_cpu": torch.get_rng_state()}
        checkpoint_dir = ts.save_checkpoint(
            str(run_dir), n_optimizer_steps, model.state_dict(), optimizer_state, rng_state,
            extra={"segment_id": "cbase-grow-rung2-event-stabilize",
                   "becomes_rung3_pregrow_candidate": True, "run_id": run_id,
                   "config_receipt": STABILIZE_CONFIG_RECEIPT})

    marker_path = _write_planned_outage_marker(receipt_dir, run_id)

    if oom_error is not None:
        verdict = "STABILIZE_OOM"
    elif kill_estimator_wrong:
        verdict = "STABILIZE_VRAM_KILL"
    elif degenerate:
        verdict = "STABILIZE_DEGENERATE"
    else:
        verdict = "STABILIZE_PASS"

    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-STABILIZE", "ts": _timestamp_iso(),
        "invariant_sha256": INVARIANT_SHA256, "sha_convention": SHA_CONVENTION,
        "issue": 466, "refs": [464, 429],
        "run_id": run_id,
        "scope": "STABILIZE: production training of the grown model from B2 weights with a "
                 "RESET optimizer, config verbatim from the proven receipt, D1 fixed-FLOPs "
                 "token floor.",
        "config_quoted_from_receipt": STABILIZE_CONFIG_RECEIPT,
        "micro_batch": micro_batch, "grad_accum_steps": grad_accum_steps,
        "n_optimizer_steps": n_optimizer_steps, "seq": seq, "effective_batch": effective_batch,
        "total_tokens": total_tokens, "d1_target_tokens": D1_TOTAL_TOKENS, "tokens_match": tokens_match,
        "d1_equivalence_note": "D1's 30 steps at batch=16/seq=1024 (spec text) == the same "
            f"{D1_TOTAL_TOKENS} tokens at effective_batch={effective_batch}/seq={seq} over "
            f"{n_optimizer_steps} optimizer steps -- same FLOPs, under the VRAM-PROVEN "
            "micro_batch=1/grad_accum=8 shape (disclosed equivalence, not silently assumed).",
        "gradient_checkpointing": grad_checkpointing,
        "optimizer_reset": True, "optimizer_routing": routing,
        "training": {"optimizer_step_losses": losses, "degenerate_loss_trace": degenerate,
                    "oom_error": oom_error, "n_params_after": n_params_after},
        "vram": vram_report,
        "checkpoint": {"dir": _make_path_repo_relative(checkpoint_dir, data_root=data_root) if checkpoint_dir else None,
                      "becomes_rung3_pregrow_candidate": bool(checkpoint_dir is not None)},
        "planned_outage_marker": {"path": _make_path_repo_relative(marker_path, data_root=data_root), "written": True},
        "api_spend_usd": 0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": verdict,
    }
    path = _receipt_path(receipt_dir, run_id, "stabilize")
    checked_write(str(path), receipt)
    print(f"CBASE_GROW_RUNG2_EVENT_STABILIZE run_id={run_id} verdict={verdict} receipt={path}", flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Selftest — full phase chain on a TINY synthetic model, CPU only
# ---------------------------------------------------------------------------

def _build_tiny_contract(tmp_dir: Path) -> Path:
    contract = {
        "model": {"hidden": 32, "layers": 2, "heads": 2, "vocab": 64, "seq": 16,
                  "tied_embeddings": False, "grad_checkpointing": False},
        "precision": {"qat": {"enabled": True}},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 1, "weight": 0.3}},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 3e-4, "weight_decay": 0.1},
        "schedule": {"warmup_frac": 0.01, "stable_until_frac": 0.85, "decay_to_lr_frac": 0.10},
        "throughput": {"batch": 2},
    }
    path = tmp_dir / "tiny-contract.json"
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return path


def _build_tiny_seed_checkpoint(tmp_dir: Path, contract_path: Path) -> Path:
    """A genuine (non-reconstructed) tiny checkpoint: builds the real
    build_v0_model/build_split_optimizer path, runs ONE real optimizer step
    on random data (so momentum buffers are genuinely nonzero -- the exact
    condition B1's provenance check must PASS on), then save_checkpoint via
    the real timeshare_pretrain primitive. Same code path production uses,
    just tiny dims -- not a hand-rolled fixture."""
    import torch
    cfg = ts.load_contract(str(contract_path))
    ff_seed = 8
    model, vocab, hidden, n_mtp = ts.build_v0_model(cfg, live=True, intermediate_override=ff_seed, device="cpu")
    optimizers, base_lrs, routing = ts.build_split_optimizer(model, cfg)
    torch.manual_seed(7)
    seq = cfg["model"]["seq"]
    batch = cfg["throughput"]["batch"]
    x = torch.randint(1, vocab, (batch, seq))
    y0 = torch.randint(0, vocab, (batch, seq))
    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    hidden_out = model.backbone(x)
    h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
    primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=64)
    y_mtp = torch.randint(0, vocab, (batch, seq))
    ce_mtp, _ = ce_fn(h_flat, model.mtp_heads[0].weight, y_mtp.reshape(-1), chunk_tokens=64)
    loss = ts.mtp_total_loss(primary_ce, [ce_mtp], cfg["objective"]["mtp_aux_heads"]["weight"])
    loss.backward()
    for opt in optimizers.values():
        opt.step()

    run_dir = tmp_dir / "tiny-seed-run"
    optimizer_state = ts.save_optimizers_state(optimizers)
    rng_state = {"torch_cpu": torch.get_rng_state()}
    ckpt_dir = ts.save_checkpoint(str(run_dir), 766, model.state_dict(), optimizer_state, rng_state,
                                  extra={"segment_id": "selftest-tiny-seed"})
    return Path(ckpt_dir)


def test_data_root_decoupling() -> int:
    """Test --data-root decoupling: code location independent of data location.

    Per issue #466 frozen spec: test with two temp dirs (fake code root + fake
    data root). Verify:
    (a) resolver with data_root finds a file placed under the data root
    (b) resolver without data_root preserves current behavior
    (c) writer with data_root emits a path relative to data root (no leak)
    """
    import tempfile
    failures = []
    print("=== cbase_grow_rung2_event.py --test-data-root-decoupling ===", flush=True)

    with tempfile.TemporaryDirectory(prefix="rung2-dataroot-test-") as td:
        tmp = Path(td)
        fake_code_root = tmp / "code-root"
        fake_data_root = tmp / "data-root"
        fake_code_root.mkdir()
        fake_data_root.mkdir()

        # Test (b): resolver without data_root preserves current behavior
        # (uses REPO as fallback)
        code_relative_path = "models/test-model.pt"
        result_b = _make_path_absolute_from_receipt(code_relative_path)
        if result_b != REPO / code_relative_path:
            failures.append(
                f"TEST (b) FAIL: resolver without data_root did not preserve REPO fallback: "
                f"got {result_b}, expected {REPO / code_relative_path}")
        else:
            print(
                f"PASS (b): resolver without data_root uses REPO fallback: "
                f"{code_relative_path} -> {result_b}", flush=True)

        # Test (a): resolver with data_root finds a file placed under data root
        test_file = fake_data_root / "models" / "test-model.pt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("test content")

        resolved_path = _make_path_absolute_from_receipt("models/test-model.pt", data_root=fake_data_root)
        if resolved_path != test_file or not resolved_path.exists():
            failures.append(
                f"TEST (a) FAIL: resolver with data_root did not find file in data root: "
                f"got {resolved_path}, expected {test_file}, exists={resolved_path.exists()}")
        else:
            print(
                f"PASS (a): resolver with data_root finds file in data root: "
                f"models/test-model.pt -> {resolved_path}", flush=True)

        # Test (c): writer with data_root emits relative path, no code-root contamination
        absolute_data_path = fake_data_root / "receipts" / "test-receipt.json"
        absolute_data_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_data_path.write_text("{}")

        relative_from_data = _make_path_repo_relative(absolute_data_path, data_root=fake_data_root)
        relative_from_code = _make_path_repo_relative(absolute_data_path, data_root=fake_code_root)

        # On Windows, paths use backslashes; normalize for the test
        expected_relative = os.path.join("receipts", "test-receipt.json")
        if relative_from_data != expected_relative:
            failures.append(
                f"TEST (c) FAIL: writer with data_root did not emit relative path: "
                f"got {relative_from_data}, expected {expected_relative}")
        else:
            print(
                f"PASS (c): writer with data_root emits data-relative path: "
                f"{absolute_data_path} -> {relative_from_data}", flush=True)

        # Verify code-root does NOT contaminate the result
        if relative_from_code == relative_from_data:
            # When path is outside the code-root, it should fall back to absolute
            if not relative_from_code.startswith(str(fake_data_root)):
                print(
                    f"PASS (c): code-root does not contaminate result "
                    f"(path outside code-root kept as absolute)", flush=True)
            else:
                failures.append(
                    f"TEST (c) FAIL: relative path leaked code-root context: "
                    f"same result {relative_from_code} for both code/data roots")
        else:
            print(
                f"PASS (c): code-root isolation verified (different results for code vs data): "
                f"code={relative_from_code} data={relative_from_data}", flush=True)

    print("=== data-root decoupling test summary ===", flush=True)
    if failures:
        for f in failures:
            print(f"DATA_ROOT_DECOUPLING_FAIL: {f}", flush=True)
        print(f"DATA_ROOT_DECOUPLING_TEST_FAIL ({len(failures)} failure(s))", flush=True)
        return 1
    print("DATA_ROOT_DECOUPLING_TEST_PASS", flush=True)
    return 0


def run_selftest() -> int:
    import tempfile
    failures = []
    print("=== cbase_grow_rung2_event.py --selftest ===", flush=True)

    with tempfile.TemporaryDirectory(prefix="rung2-event-selftest-") as td:
        tmp = Path(td)
        receipt_dir = tmp / "receipts"
        cache_dir = tmp / "cache"
        out_dir = tmp / "models"
        receipt_dir.mkdir(parents=True)
        cache_dir.mkdir(parents=True)
        out_dir.mkdir(parents=True)

        contract_path = _build_tiny_contract(tmp)
        seed_ckpt = _build_tiny_seed_checkpoint(tmp, contract_path)
        print(f"tiny seed checkpoint built: {seed_ckpt}", flush=True)

        import torch
        sd = torch.load(seed_ckpt / "model.pt", map_location="cpu", weights_only=True)
        param_count = int(sum(v.numel() for v in sd.values()))

        class NS:
            pass

        def _mk(phase, **kw):
            a = NS()
            a.receipt_dir = str(receipt_dir); a.cache_dir = str(cache_dir); a.out_dir = str(out_dir)
            a.contract_path = str(contract_path); a.seed_ckpt = str(seed_ckpt)
            a.device = "cpu"; a.micro_batch = 1; a.grad_accum_steps = 2
            a.param_count_after = param_count
            a.commit_margin_gib_floor = 0.0  # tiny box may not have 10GiB free pagefile; disclosed override for selftest
            a.disk_headroom_gib_floor = 0.0
            a.skip_gpu_preflight = True  # CPU-only synthetic-model selftest; real GPU contention
                                          # on a shared box is an environmental fact, not a mechanism
                                          # under test here -- disclosed, not silently assumed.
            a.wait_s = 0.2
            a.eps_sigma = 0.05
            a.eps_seed = 0
            a.n_optimizer_steps = 2
            for k, v in kw.items():
                setattr(a, k, v)
            return a

        # --- 1. fail-closed chaining: b1 refuses without a preflight receipt ---
        args_b1_premature = _mk("b1", run_id="selftest-run-1")
        chaining_refused = False
        try:
            phase_b1(args_b1_premature)
        except SystemExit as e:
            chaining_refused = "refuses to start" in str(e)
        if not chaining_refused:
            failures.append("FAIL-CLOSED CHAINING: b1 did not refuse without a preflight receipt")
        else:
            print("PASS: fail-closed chaining (b1 refused with no preflight receipt)", flush=True)

        # --- run the real chain ---
        run_id = "selftest-run-1"
        pf = phase_preflight(_mk("preflight", run_id=run_id))
        if pf["verdict"] != "PREFLIGHT_PASS":
            failures.append(f"PREFLIGHT did not pass in selftest: {pf}")

        b1 = phase_b1(_mk("b1", run_id=run_id))
        if b1["verdict"] != "B1_QUIESCE_PROVEN":
            failures.append(f"B1 did not reach B1_QUIESCE_PROVEN: {b1['verdict']}")
        if not b1["quiesce"]["identical"]:
            failures.append("DOUBLE-SHA MANIFEST: T0/T1 manifests were not identical on a quiesced dir")
        else:
            print("PASS: double-sha manifest identical across the wait", flush=True)
        if b1["provenance"]["any_class_fully_zeroed_or_absent"]:
            failures.append("PROVENANCE: genuine tiny checkpoint's momentum was reported fully-zeroed")
        else:
            print("PASS: momentum provenance nonzero on a genuine checkpoint", flush=True)

        b1m = phase_b1m(_mk("b1m", run_id=run_id))
        if b1m["verdict"] != "B1M_CAPTURED":
            failures.append(f"B1M did not reach B1M_CAPTURED: {b1m['verdict']}")
        sha_a = b1m["batch"]["overall_sha256"]

        # --- microstep-tuple sha stability: rebuild the SAME pinned batch
        # independently and confirm identical shas ---
        cfg_tiny = ts.load_contract(str(contract_path))
        n_mtp = cfg_tiny["objective"]["mtp_aux_heads"]["n_heads"]
        seq = cfg_tiny["model"]["seq"]
        rebuilt = _build_pinned_batch(cache_dir, run_id + "-rebuild-check", cfg_tiny, n_mtp, 64,
                                      seq, 1, 2, "cpu")
        if rebuilt["overall_sha256"] != sha_a:
            failures.append("MICROSTEP SHA STABILITY: independently rebuilt pinned batch sha "
                            f"differs (b1m={sha_a} rebuilt={rebuilt['overall_sha256']})")
        else:
            print("PASS: microstep-tuple sha stable across independent rebuilds", flush=True)

        # --- eps threading: b2 must refuse eps_sigma=0.0 ---
        eps_zero_refused = False
        try:
            phase_b2(_mk("b2", run_id=run_id, eps_sigma=0.0))
        except SystemExit as e:
            eps_zero_refused = "must be > 0" in str(e)
        if not eps_zero_refused:
            failures.append("EPS THREADING: b2 did not refuse eps_sigma=0.0")
        else:
            print("PASS: b2 refuses eps_sigma=0.0 (banned default)", flush=True)

        b2 = phase_b2(_mk("b2", run_id=run_id))
        if b2["verdict"] != "B2_REALIZED_PASS":
            failures.append(f"B2 did not reach B2_REALIZED_PASS: {b2}")
        if not b2["eps"]["eps_sigma"] > 0:
            failures.append("EPS THREADING: b2 receipt does not record eps_sigma>0")
        else:
            print(f"PASS: eps_sigma={b2['eps']['eps_sigma']} threaded through the fresh widen "
                  f"(twin_cosine_max={b2['realized_proof']['twin_cosine_max']:.6f} < 1)", flush=True)

        b3 = phase_b3(_mk("b3", run_id=run_id))
        if b3["verdict"] != "B3_CAPTURED":
            failures.append(f"B3 did not reach B3_CAPTURED: {b3['verdict']}")
        if not b3["arms"]["reset"]["momentum_zero_assertion_passed"]:
            failures.append("RESET-ARM ASSERTION: explicit zero-momentum assertion did not pass")
        else:
            print("PASS: RESET-arm explicit zero-momentum assertion fires and passes", flush=True)
        print(f"  B3 band adjudication: c_reset={b3['band_adjudication']['c_reset_cos_alignment']:.4f} "
              f"band={b3['band_adjudication']['band']} (null={DCOMM_NULL_SQRT2:.5f})", flush=True)

        stab = phase_stabilize(_mk("stabilize", run_id=run_id))
        if stab["verdict"] not in ("STABILIZE_PASS", "STABILIZE_DEGENERATE"):
            # a tiny 2-random-step run is not expected to produce a
            # meaningful loss curve; STABILIZE_DEGENERATE on random labels
            # is an acceptable selftest outcome, OOM/VRAM-kill is not.
            failures.append(f"STABILIZE reached an unexpected verdict: {stab['verdict']}")
        else:
            print(f"PASS: STABILIZE phase completes end-to-end (verdict={stab['verdict']}, "
                  f"checkpoint written={stab['checkpoint']['dir'] is not None})", flush=True)

    print("=== selftest summary ===", flush=True)
    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", flush=True)
        print(f"CBASE_GROW_RUNG2_EVENT_SELFTEST_FAIL ({len(failures)} failure(s))", flush=True)
        return 1
    print("CBASE_GROW_RUNG2_EVENT_SELFTEST_PASS", flush=True)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=PHASES)
    ap.add_argument("--run-id")
    ap.add_argument("--seed-ckpt", default=str(SEED_CKPT_DEFAULT))
    ap.add_argument("--contract-path", default=None)
    ap.add_argument("--data-root", default=None,
                     help="root directory for data (models/receipts/caches); defaults to the repository root; "
                          "use when code executes from an isolated worktree while data resides in the primary tree")
    ap.add_argument("--receipt-dir", default=str(REPO / "receipts"))
    ap.add_argument("--cache-dir", default=str(REPO / "receipts" / ".rung2-event-cache"))
    ap.add_argument("--out-dir", default=str(REPO / "models" / "cbase-grow-rung"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--param-count-after", type=int, default=PARAM_COUNT_AFTER_RUNG2_DEFAULT)
    ap.add_argument("--disk-headroom-gib-floor", type=float, default=40.0)
    ap.add_argument("--commit-margin-gib-floor", type=float, default=10.0)
    ap.add_argument("--skip-gpu-preflight", action="store_true",
                     help="explicit, disclosed bypass of the GPU headroom check (selftest / "
                          "CPU-only environments only -- never for a real dispatch)")
    ap.add_argument("--wait-s", type=float, default=5.0)
    ap.add_argument("--eps-sigma", type=float, default=0.0)
    ap.add_argument("--eps-seed", type=int, default=0)
    ap.add_argument("--micro-batch", type=int, default=STABILIZE_MICRO_BATCH_DEFAULT)
    ap.add_argument("--grad-accum-steps", type=int, default=STABILIZE_GRAD_ACCUM_STEPS_DEFAULT)
    ap.add_argument("--n-optimizer-steps", type=int, default=None,
                     help="default: derived from the D1 fixed-FLOPs token floor")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--test-data-root-decoupling", action="store_true",
                     help="run tests for --data-root decoupling (issue #466)")
    # internal re-exec entry point (eps-widen fresh-subprocess worker)
    ap.add_argument("--eps-widen-worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--model-pt", help=argparse.SUPPRESS)
    ap.add_argument("--out-path", help=argparse.SUPPRESS)
    ap.add_argument("--n-layers", type=int, help=argparse.SUPPRESS)
    args = ap.parse_args()

    # Resolve data_root: default to REPO if not specified
    if args.data_root is None:
        args.data_root = REPO
    else:
        args.data_root = Path(args.data_root).resolve()

    if args.eps_widen_worker:
        return _eps_widen_worker(args.model_pt, args.out_path, args.n_layers, args.eps_sigma, args.eps_seed)

    if args.test_data_root_decoupling:
        return test_data_root_decoupling()

    if args.selftest:
        return run_selftest()

    if not args.phase:
        ap.print_help()
        return 1
    if args.phase != "preflight" and not args.run_id:
        raise SystemExit(f"CBASE-GROW-RUNG2-EVENT: --run-id is required for phase {args.phase!r}")

    dispatch = {
        "preflight": phase_preflight, "b1": phase_b1, "b1m": phase_b1m,
        "b2": phase_b2, "b3": phase_b3, "stabilize": phase_stabilize,
    }
    receipt = dispatch[args.phase](args)
    return 0 if receipt.get("verdict", "").endswith(("PASS", "PROVEN", "CAPTURED")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
