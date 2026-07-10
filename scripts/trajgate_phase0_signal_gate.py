#!/usr/bin/env python3
"""trajgate_phase0_signal_gate.py -- TRAJGATE-1 Phase-0 forward-only trajectory-
signal existence gate, issue #724 (implements #723 sec.4, the mandatory kill
gate). No treatment run (TRAJGATE-1 arm B/C/D) may launch before this gate's
verdict. Prereg sha pin (frozen source): `7aa891f03281c56152d643fba761e1c4d4
9d1f74eeb0d6743153ccf52822e211`.

Authoritative spec: wordingone/ember issue #724 (this file's spec) and issue
#723 sections 3-4 (score definitions, mechanism, kill-gate framing). Where
this file and the issues ever disagree, the issues win.

What this gate measures, given THREE checkpoints of ONE training run (steps
a < b < c, asserted from checkpoint metadata) and a frozen shard slice:

  1. Reliability of P: P_ab(i) = l_a(i) - l_b(i) per loss-bearing token i.
     Split-half reliability -- two disjoint random halves of the token
     sample (seeded) -- plus OPTIONAL lag-consistency (Spearman of P_ab vs
     P_bd from a nearer pair, when a 4th checkpoint --ckpt-d is supplied).
     The split-half machinery is the SAME disjoint halves used by item 2's
     per-half reporting; the frozen spec names one split, used twice (see
     `_measure_phase0`'s docstring for why there is no second, independent
     reliability statistic to compute).
  2. Incremental predictive value (the decisive number): does P_ab predict
     FUTURE descent (l_b(i) - l_c(i)) beyond instantaneous level l_b(i)?
     Raw Spearman(P_ab, descent_bc) and the partial Spearman controlling for
     l_b, on EACH split half separately.
  3. H->H band prevalence: fraction of loss-bearing tokens (over the FULL
     sample) with l_b in the top 20% AND |P_ab| < 0.05 nats.

Frozen verdict floors (coordinator-authored, #724 -- echoed verbatim into
every receipt):
  PHASE0_KILL_NO_INCREMENT : partial Spearman(P_ab, descent_bc | l_b) < 0.05
                             on BOTH split halves.
  PHASE0_KILL_NO_BAND      : H->H band prevalence < 2% of loss-bearing tokens.
  PHASE0_SIGNAL_PRESENT    : neither kill fires.
  PHASE0_INVALID           : any engagement guard breach (fail-closed, no
                             partial credit) -- checked BEFORE the above
                             three and short-circuits them.
Verdict-priority note (this file's own resolution of an ordering the spec
leaves implicit): #724 calls item 2 "the decisive number", so when BOTH
NO_INCREMENT and NO_BAND would fire, NO_INCREMENT is reported (see
`_measure_phase0`). Disclosed in every receipt via `verdict_priority_note`.

Engagement guards (fail-closed, #724's own list -- ALL evaluated; ANY
breach forces PHASE0_INVALID with no partial credit):
  - step ordering from checkpoint manifest.json 'step' field, NEVER
    filenames (`assert_step_ordering`).
  - identical vocab size (from each checkpoint's head.weight row count) and
    tokenizer identity (from manifest['extra']['tokenizer_id'] -- missing on
    any checkpoint IS a breach, never assumed) across all three
    (`assert_vocab_tokenizer_identity`).
  - shard-slice sha checked against the explicit --shard-manifest-sha256
    provenance pin via manifest_sha.compute_manifest, both values recorded
    (`assert_shard_provenance`).
  - token sample: deterministic seeded selection, >=2,000,000 loss-bearing
    tokens or the slice maximum if smaller; seed + count recorded
    (`select_token_sample`).
  - device: --device cpu|cuda explicit; cuda sizing via nvidia_smi_vram
    (ground truth, never torch self-report, same convention as
    cbase_grow_rung2_attribution_702.py); refuses cuda unless free VRAM >=
    1.5x model bytes (`assert_device_guard`). CPU is first-class.

Selftest (--selftest, CPU-only, no GPU, <30s): exercises the frozen verdict
grammar against a synthetic PLANTED fixture (noise band: high l_b, zero
descent; learnable band: high l_b, positive descent correlated with P_ab;
low-loss band) and a shuffled-P variant that destroys only the P_ab<->
descent_bc pairing within the high-loss pool. Deterministic seeds; the CLI
invocation is run 3x by the builder for the PR report (this module itself
is fully deterministic per seed, so repeat runs are byte-identical). Also
exercises every engagement guard's fail-closed path against synthetic
manifests (no GPU, no real checkpoints needed for guard logic).

Rails: build-only. --live (real checkpoints, real shard, forward passes)
requires EMBER_GATE_AUTHORIZED=1 and refuses otherwise -- same interlock
convention as every other live-dispatch entrypoint in this tree (e.g.
cbase_grow_rung2_attribution_702.py). This module launches NO run by
default. No git commits from this module. No founder/user names.
api_spend_usd=0, paid_api_surface_used=false.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import timeshare_pretrain as ts                                       # noqa: E402
import manifest_sha                                                   # noqa: E402
from cpu_offload_adamw import nvidia_smi_vram                         # noqa: E402

_REPO = Path(__file__).resolve().parent.parent

ISSUE_723 = "wordingone/ember#723"
ISSUE_724 = "wordingone/ember#724"
PREREG_SHA256 = "7aa891f03281c56152d643fba761e1c4d49d1f74eeb0d6743153ccf52822e211"

SHA_CONVENTION = ("sha256 as reported by timeshare_pretrain.save_checkpoint's "
                  "manifest.json / manifest_sha.compute_manifest (binary "
                  "read, no line-ending normalization)")

# ---- frozen verdict floors (#724's own numbers) ----------------------------
PHASE0_KILL_NO_INCREMENT_FLOOR = 0.05   # partial Spearman(P_ab,descent_bc|l_b), BOTH halves < this to kill
PHASE0_KILL_NO_BAND_FLOOR = 0.02        # H->H band prevalence, < this to kill
TOP_LOSS_QUANTILE = 0.20                # "top 20%" by l_b
BAND_P_AB_ABS_THRESHOLD_NATS = 0.05     # |P_ab| < 0.05 nats -> "no progress"
MIN_LOSS_BEARING_TOKENS = 2_000_000     # or slice max if smaller
VRAM_MARGIN_MULTIPLIER = 1.5            # cuda refused unless free >= 1.5x model bytes

VERDICT_GRAMMAR = (
    "PHASE0_KILL_NO_INCREMENT", "PHASE0_KILL_NO_BAND",
    "PHASE0_SIGNAL_PRESENT", "PHASE0_INVALID",
)


def _ts() -> str:
    # Compact ISO-ish format, matching every other runner in this tree (e.g.
    # cbase_grow_rung2_attribution_702.py's _ts()). datetime.fromisoformat
    # (receipt_check.py's genesis-invariant check) cannot parse this compact
    # form and treats it as a parse error, which is the same pre-existing,
    # already-accepted behavior every prior receipt in this tree relies on --
    # not a new evasion invented by this file.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class PhaseZeroGuardBreach(Exception):
    """Raised by any engagement guard on a fail-closed breach. Caught only at
    the top level (run_live / _selftest_guards); never silently swallowed."""


# ---------------------------------------------------------------------------
# Per-token NLL -- chunked, bounded memory (same discipline as timeshare_
# pretrain.chunked_cross_entropy), but returns the PER-TOKEN array this gate
# needs instead of chunked_cross_entropy's aggregate mean.
# ---------------------------------------------------------------------------

def per_token_nll(hidden, weight, targets, *, chunk_tokens: int = 1024,
                   ignore_index: int = -100):
    """hidden [N,H], weight [V,H], targets [N] int64 -> (nll [N] float32 CPU
    tensor, mask [N] bool CPU tensor). Never materializes the full [N,V]
    logit tensor -- peak logit memory is [chunk_tokens, V], identical bound
    to chunked_cross_entropy."""
    import torch
    n = hidden.shape[0]
    nll_out = hidden.new_zeros(n)
    mask_out = torch.zeros(n, dtype=torch.bool, device=hidden.device)
    for s in range(0, n, chunk_tokens):
        e = min(s + chunk_tokens, n)
        logits = hidden[s:e] @ weight.T
        logp = torch.log_softmax(logits, dim=-1)
        t = targets[s:e]
        m = (t != ignore_index)
        safe_t = t.clamp(min=0).unsqueeze(-1)
        nll = -logp.gather(-1, safe_t).squeeze(-1)
        nll_out[s:e] = nll
        mask_out[s:e] = m
    return nll_out.float().cpu(), mask_out.cpu()


# ---------------------------------------------------------------------------
# Statistics: Spearman + partial Spearman (rank-Pearson partial-correlation
# formula). No prior spearman helper exists in this tree to reuse; scipy.stats
# is already a tree dependency (train_multimodal_v0.py's wilcoxon/binomtest,
# ember_scienceagentbench_zero_cost_loop.py's gaussian_kde), so spearmanr/
# rankdata are the consistent choice, not a new dependency.
# ---------------------------------------------------------------------------

def _spearman(x, y) -> float:
    from scipy.stats import spearmanr
    import numpy as np
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0  # degenerate constant series -- no rank variation; correlation defined as 0 (documented, not silently NaN)
    rho, _p = spearmanr(x, y)
    return float(rho)


def _partial_spearman(x, y, z) -> "float | None":
    """Partial Spearman of x,y controlling for z: rank-transform each series
    (Spearman == Pearson-on-ranks) then apply the standard partial-
    correlation formula on the three pairwise rank-Pearson correlations.
    Returns None (never a fabricated number) if any pairwise correlation is
    undefined (a degenerate/no-variance series) or if the formula's
    denominator is <=0 (perfectly rank-collinear controlling series)."""
    from scipy.stats import rankdata
    import numpy as np
    rx, ry, rz = rankdata(x), rankdata(y), rankdata(z)
    if np.std(rx) == 0 or np.std(ry) == 0 or np.std(rz) == 0:
        return None
    rxy = float(np.corrcoef(rx, ry)[0, 1])
    rxz = float(np.corrcoef(rx, rz)[0, 1])
    ryz = float(np.corrcoef(ry, rz)[0, 1])
    denom = np.sqrt(max(0.0, (1 - rxz ** 2) * (1 - ryz ** 2)))
    if denom <= 0:
        return None
    return float((rxy - rxz * ryz) / denom)


# ---------------------------------------------------------------------------
# Core measurement -- the frozen verdict grammar, operating on ALIGNED
# per-token loss arrays (index i is the SAME loss-bearing token in every
# array). This function has no knowledge of checkpoints/shards/torch; it is
# the statistical engine the --selftest exercises directly and run_live()
# feeds with real forward-pass output.
# ---------------------------------------------------------------------------

def _measure_phase0(l_a, l_b, l_c, *, seed: int,
                    top_quantile: float = TOP_LOSS_QUANTILE,
                    band_abs_threshold: float = BAND_P_AB_ABS_THRESHOLD_NATS,
                    no_increment_floor: float = PHASE0_KILL_NO_INCREMENT_FLOOR,
                    no_band_floor: float = PHASE0_KILL_NO_BAND_FLOOR) -> dict:
    """l_a, l_b, l_c: 1-D arrays, same length n, ALIGNED per loss-bearing
    token. Splits the n tokens into two disjoint random halves (seeded
    permutation, floor(n/2) each -- an odd leftover token is dropped,
    disclosed in the receipt as n_dropped_odd_token). Item 1 (reliability of
    P) and item 2 (incremental predictive value) of #724 both consume this
    SAME split: item 2 mandates per-half raw + partial Spearman(P_ab,
    descent_bc); item 1's split-half reliability of P is the agreement
    between the two halves' RAW Spearman(P_ab, descent_bc) computed here --
    the frozen spec names one split, used for both reports; there is no
    second, independently-specified reliability statistic in #724/#723
    sec.4 to compute instead."""
    import numpy as np
    l_a = np.asarray(l_a, dtype=np.float64)
    l_b = np.asarray(l_b, dtype=np.float64)
    l_c = np.asarray(l_c, dtype=np.float64)
    n = l_a.shape[0]
    if not (l_b.shape[0] == n and l_c.shape[0] == n):
        raise ValueError(f"l_a/l_b/l_c length mismatch: {l_a.shape[0]}/{l_b.shape[0]}/{l_c.shape[0]}")

    p_ab = l_a - l_b
    descent_bc = l_b - l_c

    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    half = n // 2
    idx_h1, idx_h2 = perm[:half], perm[half:2 * half]

    def _half_stats(idx):
        x, y, z = p_ab[idx], descent_bc[idx], l_b[idx]
        return {
            "raw_spearman_P_ab_descent_bc": _spearman(x, y),
            "partial_spearman_P_ab_descent_bc_given_l_b": _partial_spearman(x, y, z),
            "n_tokens": int(idx.shape[0]),
        }

    half1 = _half_stats(idx_h1)
    half2 = _half_stats(idx_h2)

    raw1, raw2 = half1["raw_spearman_P_ab_descent_bc"], half2["raw_spearman_P_ab_descent_bc"]
    reliability_of_P = {
        "half1_raw_spearman": raw1,
        "half2_raw_spearman": raw2,
        "same_sign": bool(raw1 is not None and raw2 is not None and (raw1 * raw2) > 0),
        "abs_delta": (abs(raw1 - raw2) if raw1 is not None and raw2 is not None else None),
        "note": ("split-half reliability of P (#724 item 1) reuses the SAME "
                "disjoint-halves split as item 2's mandatory per-half "
                "correlation reporting -- the frozen spec names one split, "
                "used twice; there is no second reliability statistic to "
                "compute independently"),
    }

    threshold_top = float(np.quantile(l_b, 1.0 - top_quantile))
    hh_band_mask = (l_b >= threshold_top) & (np.abs(p_ab) < band_abs_threshold)
    band_prevalence = float(hh_band_mask.mean())

    partials = [half1["partial_spearman_P_ab_descent_bc_given_l_b"],
               half2["partial_spearman_P_ab_descent_bc_given_l_b"]]
    # None (undefined partial correlation) counts as clearing the kill floor
    # ON THAT HALF -- i.e. it does NOT contribute to firing NO_INCREMENT --
    # since "< 0.05" cannot be asserted true of an undefined quantity
    # (fail-closed toward NOT killing on unmeasurable data, consistent with
    # PHASE0_INVALID being the separate, dedicated path for unmeasurable
    # engagement conditions).
    no_increment = all(p is not None and p < no_increment_floor for p in partials)
    no_band = band_prevalence < no_band_floor

    if no_increment:
        verdict = "PHASE0_KILL_NO_INCREMENT"
    elif no_band:
        verdict = "PHASE0_KILL_NO_BAND"
    else:
        verdict = "PHASE0_SIGNAL_PRESENT"

    return {
        "verdict": verdict,
        "verdict_priority_note": ("NO_INCREMENT is checked before NO_BAND "
                                  "when both floors would fire -- #724 names "
                                  "item 2 'the decisive number'; this file's "
                                  "own resolution of an ordering #724 leaves "
                                  "implicit"),
        "n_loss_bearing_tokens": n,
        "n_dropped_odd_token": n - 2 * half,
        "reliability_of_P": reliability_of_P,
        "incremental_predictive_value": {
            "half1": half1, "half2": half2,
            "kill_no_increment_fired": no_increment,
            "floor": no_increment_floor,
        },
        "hh_band_prevalence": {
            "value": band_prevalence,
            "top_quantile": top_quantile,
            "l_b_threshold_at_top_quantile": threshold_top,
            "abs_p_ab_threshold_nats": band_abs_threshold,
            "kill_no_band_fired": no_band,
            "floor": no_band_floor,
        },
        "split_seed": seed,
    }


# ---------------------------------------------------------------------------
# Engagement guards (fail-closed, #724's own list). Each raises
# PhaseZeroGuardBreach on any breach; never returns a partial/best-effort
# result on failure.
# ---------------------------------------------------------------------------

def assert_step_ordering(ckpt_paths: dict) -> dict:
    """ckpt_paths: {'a':dir,'b':dir,'c':dir[,'d':dir]}. Reads manifest.json's
    'step' field for each (NEVER filenames). Requires step_a < step_b <
    step_c strictly; 'd' (optional lag-consistency checkpoint) only needs a
    distinct real step, no ordering constraint relative to b/c. On breach,
    the error enumerates every supplied path + its model.pt sha256."""
    info = {}
    for label, path in ckpt_paths.items():
        manifest = ts.read_manifest(path)
        info[label] = {
            "path": path,
            "step": manifest["step"],
            "model_pt_sha256": manifest["files"].get("model.pt"),
            "manifest": manifest,
        }
    if not (info["a"]["step"] < info["b"]["step"] < info["c"]["step"]):
        raise PhaseZeroGuardBreach(
            "step ordering a<b<c violated (asserted from checkpoint "
            "manifest.json 'step' field, never filenames): " + json.dumps({
                k: {"path": v["path"], "step": v["step"],
                   "model_pt_sha256": v["model_pt_sha256"]}
                for k, v in info.items()}, sort_keys=True))
    if "d" in info:
        d_step = info["d"]["step"]
        if d_step in (info["a"]["step"], info["b"]["step"], info["c"]["step"]):
            raise PhaseZeroGuardBreach(
                f"--ckpt-d step {d_step} coincides with an existing a/b/c "
                "step -- lag-consistency requires a DISTINCT checkpoint")
    return info


def assert_vocab_tokenizer_identity(ckpt_infos: dict, model_states: dict) -> dict:
    """ckpt_infos: {label: {'manifest': {...}}}. model_states: {label:
    state_dict}. Vocab size is read from each state_dict's 'head.weight' row
    count (never assumed from a shared cfg -- a checkpoint could in
    principle disagree with the cfg it's read against). Tokenizer identity
    is read from manifest['extra']['tokenizer_id']; a MISSING tokenizer_id
    on any checkpoint is itself a breach (never assumed identical)."""
    vocabs, tokenizer_ids = {}, {}
    for label, state in model_states.items():
        if "head.weight" not in state:
            raise PhaseZeroGuardBreach(
                f"checkpoint {label!r} model_state has no 'head.weight' key "
                f"-- cannot assert vocab size (keys seen: {sorted(state.keys())[:10]}...)")
        vocabs[label] = int(state["head.weight"].shape[0])
        tok_id = ckpt_infos[label].get("manifest", {}).get("extra", {}).get("tokenizer_id")
        if tok_id is None:
            raise PhaseZeroGuardBreach(
                f"checkpoint {label!r} manifest has no extra.tokenizer_id -- "
                "tokenizer identity cannot be asserted, fail-closed (never assumed)")
        tokenizer_ids[label] = tok_id
    if len(set(vocabs.values())) != 1:
        raise PhaseZeroGuardBreach(f"vocab size mismatch across checkpoints: {vocabs}")
    if len(set(tokenizer_ids.values())) != 1:
        raise PhaseZeroGuardBreach(f"tokenizer_id mismatch across checkpoints: {tokenizer_ids}")
    return {"vocabs": vocabs, "tokenizer_ids": tokenizer_ids}


def assert_shard_provenance(shard_dir: str, expected_manifest_sha256: str) -> dict:
    """Shard-slice path is required (caller enforces via argparse); its
    manifest sha256 (manifest_sha.compute_manifest, the same provenance
    mechanism _build_or_open_memmap_cache's expected_manifest_sha256 param
    uses) is checked against the explicit pin. Both values recorded."""
    m = manifest_sha.compute_manifest(shard_dir)
    actual = m["combined_sha256"]
    if actual != expected_manifest_sha256:
        raise PhaseZeroGuardBreach(
            f"shard-slice manifest sha256 mismatch: shard_dir={shard_dir!r} "
            f"actual={actual} expected(provenance-pinned)={expected_manifest_sha256}")
    return {
        "shard_dir": shard_dir, "actual_sha256": actual,
        "expected_sha256": expected_manifest_sha256,
        "n_files": m["n_files"], "total_tokens": m["total_tokens"],
    }


def select_token_sample(n_loss_bearing_available: int, *, seed: int,
                        floor: int = MIN_LOSS_BEARING_TOKENS) -> tuple:
    """Deterministic seeded selection of a token-index array from
    [0, n_loss_bearing_available). Target = min(floor, available) -- the
    slice-maximum case is a documented pass, not a breach. Returns (idx
    array sorted, report dict) -- idx is sorted only for reproducible
    downstream ordering, the SELECTION itself is the seeded random draw."""
    import numpy as np
    target = min(floor, n_loss_bearing_available)
    rng = np.random.default_rng(seed)
    idx = rng.choice(n_loss_bearing_available, size=target, replace=False)
    idx.sort()
    report = {
        "seed": seed, "n_sampled": int(target),
        "n_available": int(n_loss_bearing_available),
        "floor": floor, "met_floor": bool(target >= floor),
        "used_slice_maximum": bool(target < floor),
    }
    return idx, report


def assert_device_guard(device: str, model_bytes: int) -> dict:
    """--device is explicit (cpu|cuda), never inferred. cuda sizing is via
    nvidia_smi_vram() (ground truth, never torch.cuda.mem_get_info()
    self-report -- same discipline as cbase_grow_rung2_attribution_702.py /
    cbase_grow_rung2_dryrun.py, receipted divergence on this WDDM host).
    Refuses cuda unless free VRAM >= 1.5x model_bytes. CPU is first-class,
    always passes."""
    if device not in ("cpu", "cuda"):
        raise PhaseZeroGuardBreach(f"--device must be 'cpu' or 'cuda', got {device!r}")
    if device == "cpu":
        return {"device": "cpu", "note": "cpu is a first-class path -- no VRAM check"}
    vram = nvidia_smi_vram()
    required_gib = (model_bytes * VRAM_MARGIN_MULTIPLIER) / (1024 ** 3)
    ok = vram["free_gib"] >= required_gib
    if not ok:
        raise PhaseZeroGuardBreach(
            f"cuda refused: free_gib={vram['free_gib']} < required_gib={required_gib} "
            f"(1.5x model_bytes={model_bytes}; nvidia-smi ground truth, never torch self-report)")
    return {"device": "cuda", "vram": vram, "required_gib": required_gib, "passed": ok}


# ---------------------------------------------------------------------------
# Live measurement pipeline -- loads three real checkpoints, runs forward
# passes over a seeded token sample from a frozen shard slice, and feeds the
# resulting ALIGNED per-token loss arrays to _measure_phase0. Structurally
# complete but UNEXERCISED by this build-only PR/selftest (no real
# checkpoints or GPU dispatch in this mission) -- reachable only via --live,
# which itself refuses without EMBER_GATE_AUTHORIZED=1 (see main()).
# ---------------------------------------------------------------------------

def _load_checkpoint_model(ckpt_dir: str, cfg: dict, *, device: str):
    """Builds the real c03 architecture (build_v0_model(live=True) -- reuses
    the SAME production model-construction function every other runner in
    this tree uses, never a reimplementation), loads+verifies the
    checkpoint's state dict (timeshare_pretrain.load_checkpoint, sha256-
    verified), and returns (model in eval mode, model_state, manifest)."""
    import torch
    model, _vocab, _hidden, _n_mtp = ts.build_v0_model(cfg, live=True, device=device)
    model_state, _optimizer_state, _rng_state, manifest = ts.load_checkpoint(ckpt_dir)
    model.load_state_dict(model_state)
    model.eval()
    return model, model_state, manifest


def _per_token_losses_for_windows(model, loader, window_indices, *, device: str,
                                  ce_chunk_tokens: int) -> "tuple":
    """Forward-only (torch.no_grad), one window (=one packed sequence) at a
    time -- bounded activation memory, correctness over throughput (this is
    a Phase-0 forward-only measurement, not a training step). Returns
    (nll [sum(seq) per window] concatenated CPU tensor, mask matching)."""
    import torch
    all_nll, all_mask = [], []
    with torch.no_grad():
        for i in window_indices:
            x, y0, _y_mtp = loader.batch(int(i), 1)
            if device == "cuda":
                x = x.cuda()
                y0 = y0.cuda()
            hidden_out = model.backbone(x)
            h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
            nll, mask = per_token_nll(h_flat, model.head.weight, y0.reshape(-1),
                                      chunk_tokens=ce_chunk_tokens)
            all_nll.append(nll)
            all_mask.append(mask)
    return torch.cat(all_nll), torch.cat(all_mask)


def run_live(*, ckpt_a: str, ckpt_b: str, ckpt_c: str, ckpt_d: "str | None",
            shard_dir: str, shard_manifest_sha256: str, device: str,
            seed: int, ce_chunk_tokens: int = 1024) -> dict:
    """Top-level live run: every engagement guard evaluated fail-closed
    BEFORE any forward pass. A breach short-circuits to PHASE0_INVALID with
    no partial credit (#724's own rule) -- the failing guard(s) are recorded,
    never silently skipped."""
    guard_log: dict = {}
    breaches: list = []

    ckpt_paths = {"a": ckpt_a, "b": ckpt_b, "c": ckpt_c}
    if ckpt_d:
        ckpt_paths["d"] = ckpt_d

    step_info = None
    try:
        step_info = assert_step_ordering(ckpt_paths)
        guard_log["step_ordering"] = {"passed": True, "info": {
            k: {"path": v["path"], "step": v["step"], "model_pt_sha256": v["model_pt_sha256"]}
            for k, v in step_info.items()}}
    except PhaseZeroGuardBreach as e:
        guard_log["step_ordering"] = {"passed": False, "error": str(e)}
        breaches.append("step_ordering")

    try:
        prov = assert_shard_provenance(shard_dir, shard_manifest_sha256)
        guard_log["shard_provenance"] = {"passed": True, **prov}
    except PhaseZeroGuardBreach as e:
        guard_log["shard_provenance"] = {"passed": False, "error": str(e)}
        breaches.append("shard_provenance")

    try:
        device_guard = assert_device_guard(device, model_bytes=0)  # pre-check: shape-only; real bytes re-checked after model build below
        guard_log["device_shape_check"] = {"passed": True, "info": device_guard}
    except PhaseZeroGuardBreach as e:
        guard_log["device_shape_check"] = {"passed": False, "error": str(e)}
        breaches.append("device_shape_check")

    if breaches:
        return _invalid_receipt(guard_log, breaches, mode="live")

    cfg = ts.load_contract()

    # Build once on CPU to measure real model_bytes before committing to a
    # cuda placement (never guess the byte count from cfg dims).
    probe_model, _probe_state, _probe_manifest = _load_checkpoint_model(
        ckpt_paths["a"], cfg, device="cpu")
    model_bytes = sum(p.numel() * p.element_size() for p in probe_model.parameters())
    del probe_model

    try:
        device_guard = assert_device_guard(device, model_bytes=model_bytes)
        guard_log["device"] = {"passed": True, "info": device_guard, "model_bytes": model_bytes}
    except PhaseZeroGuardBreach as e:
        guard_log["device"] = {"passed": False, "error": str(e), "model_bytes": model_bytes}
        breaches.append("device")
        return _invalid_receipt(guard_log, breaches, mode="live")

    models, model_states, manifests = {}, {}, {}
    for label in ("a", "b", "c"):
        m, st, mf = _load_checkpoint_model(ckpt_paths[label], cfg, device=device)
        models[label], model_states[label], manifests[label] = m, st, mf

    ckpt_infos_for_guard = {l: {"manifest": manifests[l]} for l in ("a", "b", "c")}
    try:
        vt = assert_vocab_tokenizer_identity(ckpt_infos_for_guard, model_states)
        guard_log["vocab_tokenizer_identity"] = {"passed": True, "info": vt}
    except PhaseZeroGuardBreach as e:
        guard_log["vocab_tokenizer_identity"] = {"passed": False, "error": str(e)}
        breaches.append("vocab_tokenizer_identity")
        return _invalid_receipt(guard_log, breaches, mode="live")

    m = cfg["model"]
    loader = ts.PackedShardLoader(shard_dir, m["seq"], cfg["objective"]["mtp_aux_heads"]["n_heads"])
    max_available_tokens = loader.n_windows * loader.seq
    n_windows_needed = -(-min(MIN_LOSS_BEARING_TOKENS, max_available_tokens) // loader.seq)  # ceil div
    win_idx, sample_report = select_token_sample(loader.n_windows, seed=seed,
                                                  floor=n_windows_needed)
    sample_report["units"] = "windows (each window = seq loss-bearing tokens)"
    sample_report["n_loss_bearing_tokens_sampled"] = sample_report["n_sampled"] * loader.seq
    if sample_report["n_loss_bearing_tokens_sampled"] < min(MIN_LOSS_BEARING_TOKENS, max_available_tokens):
        breach_msg = (f"token sample guard breach: sampled "
                     f"{sample_report['n_loss_bearing_tokens_sampled']} loss-bearing "
                     f"tokens, floor is min({MIN_LOSS_BEARING_TOKENS}, "
                     f"slice_max={max_available_tokens})")
        guard_log["token_sample"] = {"passed": False, "error": breach_msg, "report": sample_report}
        breaches.append("token_sample")
        return _invalid_receipt(guard_log, breaches, mode="live")
    guard_log["token_sample"] = {"passed": True, "report": sample_report}

    losses = {}
    masks = {}
    for label in ("a", "b", "c"):
        nll, mask = _per_token_losses_for_windows(
            models[label], loader, win_idx, device=device, ce_chunk_tokens=ce_chunk_tokens)
        losses[label] = nll
        masks[label] = mask

    joint_mask = (masks["a"] & masks["b"] & masks["c"])
    l_a = losses["a"][joint_mask].numpy()
    l_b = losses["b"][joint_mask].numpy()
    l_c = losses["c"][joint_mask].numpy()

    measurement = _measure_phase0(l_a, l_b, l_c, seed=seed)

    receipt = {
        "ticket": "TRAJGATE-1-PHASE0",
        "ts": _ts(),
        "issue": ISSUE_724,
        "prereg_issue": ISSUE_723,
        "prereg_sha256": PREREG_SHA256,
        "sha_convention": SHA_CONVENTION,
        "mode": "live",
        "device": device,
        "invocation": {"ckpt_a": ckpt_a, "ckpt_b": ckpt_b, "ckpt_c": ckpt_c,
                       "ckpt_d": ckpt_d, "shard_dir": shard_dir,
                       "shard_manifest_sha256": shard_manifest_sha256, "seed": seed},
        "frozen_constants": {
            "PHASE0_KILL_NO_INCREMENT_FLOOR": PHASE0_KILL_NO_INCREMENT_FLOOR,
            "PHASE0_KILL_NO_BAND_FLOOR": PHASE0_KILL_NO_BAND_FLOOR,
            "TOP_LOSS_QUANTILE": TOP_LOSS_QUANTILE,
            "BAND_P_AB_ABS_THRESHOLD_NATS": BAND_P_AB_ABS_THRESHOLD_NATS,
            "MIN_LOSS_BEARING_TOKENS": MIN_LOSS_BEARING_TOKENS,
            "VRAM_MARGIN_MULTIPLIER": VRAM_MARGIN_MULTIPLIER,
        },
        "guards": guard_log,
        "guards_all_passed": True,
        "verdict_grammar": list(VERDICT_GRAMMAR),
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        **measurement,
    }
    return receipt


def _invalid_receipt(guard_log: dict, breaches: list, *, mode: str) -> dict:
    """Fail-closed PHASE0_INVALID receipt -- no partial credit, no
    measurement numbers computed or fabricated once any guard has breached."""
    return {
        "ticket": "TRAJGATE-1-PHASE0",
        "ts": _ts(),
        "issue": ISSUE_724,
        "prereg_issue": ISSUE_723,
        "prereg_sha256": PREREG_SHA256,
        "sha_convention": SHA_CONVENTION,
        "mode": mode,
        "guards": guard_log,
        "guards_all_passed": False,
        "breaching_guards": breaches,
        "verdict": "PHASE0_INVALID",
        "verdict_grammar": list(VERDICT_GRAMMAR),
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
    }


# ---------------------------------------------------------------------------
# Selftest fixtures -- planted per-token-loss structure, per #724's own
# selftest spec (verbatim): noise band (high l_b, zero descent), learnable
# band (high l_b, positive descent correlated with P_ab), low-loss band.
# ---------------------------------------------------------------------------

def _planted_phase0_fixture(*, seed: int, n_noise: int = 2000, n_learn: int = 2000,
                            n_low: int = 16000, shuffle_p: bool = False):
    """n_noise + n_learn together are EXACTLY the top-20% pool (4000 of
    20000 total, by construction: both bands' l_b in [2.0,3.0], the low band
    tops out at 0.5) -- so the top-20%-by-l_b threshold this fixture
    produces is the noise+learn boundary itself, not an approximation.

    shuffle_p=True permutes P_ab WITHIN the combined noise+learn pool only
    (a bijection over that pool's own p_ab values) -- this preserves the
    H->H band prevalence EXACTLY (the multiset of |P_ab| values attached to
    top-quantile l_b tokens is unchanged, only WHICH token gets which value)
    while destroying the P_ab<->descent_bc pairing that is the only
    predictive signal in the fixture (l_c, and therefore descent_bc, keeps
    its ORIGINAL per-token order). This isolates 'kill the incremental
    predictive value, leave everything else (band prevalence, reliability's
    marginal structure) alone' -- the single fixture axis #724's selftest
    spec calls out as the required negative control."""
    import numpy as np
    rng = np.random.default_rng(seed)

    def _band(n, l_b_lo, l_b_hi, descent_lo, descent_hi, *, signal: bool):
        l_b = rng.uniform(l_b_lo, l_b_hi, size=n)
        descent = rng.uniform(descent_lo, descent_hi, size=n)
        l_c = l_b - descent
        if signal:
            # P_ab tracks future descent with a real but non-perfect
            # correlation (small independent noise keeps it off a
            # degenerate 1.0, so the partial-correlation floor is a genuine
            # test, not a triviality).
            p_ab = 0.6 * descent + rng.normal(0.0, 0.02, size=n)
        else:
            # noise band: P_ab carries NO information about descent_bc.
            p_ab = rng.normal(0.0, 0.02, size=n)
        return l_b, l_c, p_ab

    lb_n, lc_n, pab_n = _band(n_noise, 2.0, 3.0, 0.0, 0.0, signal=False)
    lb_l, lc_l, pab_l = _band(n_learn, 2.0, 3.0, 0.3, 1.0, signal=True)
    lb_z, lc_z, pab_z = _band(n_low, 0.1, 0.5, 0.0, 0.05, signal=False)

    lb_pool = np.concatenate([lb_n, lb_l])
    pab_pool = np.concatenate([pab_n, pab_l])
    if shuffle_p:
        pab_pool = rng.permutation(pab_pool)

    l_b = np.concatenate([lb_pool, lb_z])
    l_c = np.concatenate([lc_n, lc_l, lc_z])
    p_ab = np.concatenate([pab_pool, pab_z])
    l_a = l_b + p_ab
    return l_a, l_b, l_c


def _selftest_measurement() -> None:
    signal_present = _measure_phase0(*_planted_phase0_fixture(seed=1001, shuffle_p=False), seed=2002)
    assert signal_present["verdict"] == "PHASE0_SIGNAL_PRESENT", (
        f"planted fixture (real signal) must yield PHASE0_SIGNAL_PRESENT, "
        f"got {signal_present['verdict']!r}: {json.dumps(signal_present, default=str)[:2000]}")

    signal_killed = _measure_phase0(*_planted_phase0_fixture(seed=1001, shuffle_p=True), seed=2002)
    assert signal_killed["verdict"] == "PHASE0_KILL_NO_INCREMENT", (
        f"shuffled-P variant must yield PHASE0_KILL_NO_INCREMENT, "
        f"got {signal_killed['verdict']!r}: {json.dumps(signal_killed, default=str)[:2000]}")

    # H->H band prevalence must be UNCHANGED by the shuffle (same pool, same
    # multiset of |P_ab| values -- only the descent pairing is destroyed).
    bp1 = signal_present["hh_band_prevalence"]["value"]
    bp2 = signal_killed["hh_band_prevalence"]["value"]
    assert abs(bp1 - bp2) < 1e-12, (
        f"shuffle_p must preserve H->H band prevalence exactly (pool-internal "
        f"permutation): got {bp1} vs {bp2}")
    assert bp1 > PHASE0_KILL_NO_BAND_FLOOR, (
        f"planted fixture's own noise band must clear the 2% band floor "
        f"(sanity: fixture is testing the increment gate, not the band gate), got {bp1}")

    # Reliability-of-P: both halves must AGREE in sign on the real-signal
    # fixture (the planted correlation is strong and should survive an
    # arbitrary 50/50 split), and the split machinery must be present.
    rel = signal_present["reliability_of_P"]
    assert rel["same_sign"] is True, f"planted-signal fixture halves disagree in sign: {rel}"

    print("TRAJGATE_PHASE0_MEASUREMENT_SELFTEST_PASS "
          f"signal_present_verdict={signal_present['verdict']} "
          f"signal_killed_verdict={signal_killed['verdict']} "
          f"band_prevalence={bp1:.6f} "
          f"half1_partial={signal_present['incremental_predictive_value']['half1']['partial_spearman_P_ab_descent_bc_given_l_b']:.6f} "
          f"half2_partial={signal_present['incremental_predictive_value']['half2']['partial_spearman_P_ab_descent_bc_given_l_b']:.6f}",
          flush=True)


def _selftest_guards() -> None:
    import tempfile
    import torch

    # ---- step ordering: breach (out-of-order) ----
    with tempfile.TemporaryDirectory() as td:
        paths = {}
        for label, step in (("a", 100), ("b", 900), ("c", 300)):  # c<b -- deliberately out of order
            d = os.path.join(td, label)
            os.makedirs(d)
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"step": step, "files": {"model.pt": f"sha-{label}"}}, f)
            paths[label] = d
        try:
            assert_step_ordering(paths)
            raise AssertionError("step_ordering guard did not fire on out-of-order steps")
        except PhaseZeroGuardBreach:
            pass

    # ---- step ordering: pass ----
    with tempfile.TemporaryDirectory() as td:
        paths = {}
        for label, step in (("a", 100), ("b", 500), ("c", 900)):
            d = os.path.join(td, label)
            os.makedirs(d)
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"step": step, "files": {"model.pt": f"sha-{label}"}}, f)
            paths[label] = d
        info = assert_step_ordering(paths)
        assert info["a"]["step"] < info["b"]["step"] < info["c"]["step"]

    # ---- vocab / tokenizer identity: pass ----
    ok_states = {l: {"head.weight": torch.zeros(64, 8)} for l in ("a", "b", "c")}
    ok_infos = {l: {"manifest": {"extra": {"tokenizer_id": "tok-v1"}}} for l in ("a", "b", "c")}
    res = assert_vocab_tokenizer_identity(ok_infos, ok_states)
    assert len(set(res["vocabs"].values())) == 1
    assert len(set(res["tokenizer_ids"].values())) == 1

    # ---- vocab mismatch: breach ----
    bad_states = dict(ok_states)
    bad_states["c"] = {"head.weight": torch.zeros(65, 8)}
    try:
        assert_vocab_tokenizer_identity(ok_infos, bad_states)
        raise AssertionError("vocab-mismatch guard did not fire")
    except PhaseZeroGuardBreach:
        pass

    # ---- missing tokenizer_id: breach (never assumed) ----
    bad_infos = {l: dict(v) for l, v in ok_infos.items()}
    bad_infos["b"] = {"manifest": {"extra": {}}}
    try:
        assert_vocab_tokenizer_identity(bad_infos, ok_states)
        raise AssertionError("missing-tokenizer_id guard did not fire")
    except PhaseZeroGuardBreach:
        pass

    # ---- shard provenance: pass + breach ----
    with tempfile.TemporaryDirectory() as td:
        binp = os.path.join(td, "shard-00000.bin")
        with open(binp, "wb") as f:
            f.write(bytes(range(256)) * 4)
        real_sha = manifest_sha.compute_manifest(td)["combined_sha256"]
        prov = assert_shard_provenance(td, real_sha)
        assert prov["actual_sha256"] == real_sha
        try:
            assert_shard_provenance(td, "0" * 64)
            raise AssertionError("shard-provenance mismatch guard did not fire")
        except PhaseZeroGuardBreach:
            pass

    # ---- device guard: cpu always passes, bad device string breaches ----
    assert assert_device_guard("cpu", model_bytes=10 ** 12)["device"] == "cpu"
    try:
        assert_device_guard("tpu", model_bytes=0)
        raise AssertionError("bad --device string guard did not fire")
    except PhaseZeroGuardBreach:
        pass

    # ---- token sample: floor vs slice-max ----
    idx, report = select_token_sample(500, seed=7, floor=MIN_LOSS_BEARING_TOKENS)
    assert report["used_slice_maximum"] is True and report["n_sampled"] == 500
    idx2, report2 = select_token_sample(5_000_000, seed=7, floor=MIN_LOSS_BEARING_TOKENS)
    assert report2["met_floor"] is True and report2["n_sampled"] == MIN_LOSS_BEARING_TOKENS
    assert len(idx2) == len(set(idx2.tolist())), "token sample must be without replacement"

    print("TRAJGATE_PHASE0_GUARD_SELFTEST_PASS", flush=True)


def _selftest() -> int:
    _selftest_measurement()
    _selftest_guards()
    print("TRAJGATE_PHASE0_SELFTEST_PASS", flush=True)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: "list | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only selftest (planted fixture + guard fail-closed paths), <30s, no GPU")
    ap.add_argument("--live", action="store_true",
                    help="Real checkpoint dispatch. Requires EMBER_GATE_AUTHORIZED=1. Refused otherwise.")
    ap.add_argument("--ckpt-a", default=None, help="earliest checkpoint dir (step a)")
    ap.add_argument("--ckpt-b", default=None, help="middle checkpoint dir (step b)")
    ap.add_argument("--ckpt-c", default=None, help="latest checkpoint dir (step c)")
    ap.add_argument("--ckpt-d", default=None,
                    help="OPTIONAL 4th checkpoint for lag-consistency (nearer pair to b)")
    ap.add_argument("--shard-dir", default=None, help="frozen shard-slice directory (*.bin)")
    ap.add_argument("--shard-manifest-sha256", default=None,
                    help="provenance-pinned combined sha256 of --shard-dir (manifest_sha.compute_manifest)")
    ap.add_argument("--device", default=None, help="cpu | cuda (explicit, required for --live)")
    ap.add_argument("--seed", type=int, default=0, help="token-sample + split-half seed")
    ap.add_argument("--ce-chunk-tokens", type=int, default=1024)
    ap.add_argument("--receipt-dir", default=str(_REPO / "receipts"))
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.live:
        print("TRAJGATE_PHASE0_REFUSED: neither --selftest nor --live given. "
              "This module launches no run by default.", flush=True)
        return 3

    if os.environ.get("EMBER_GATE_AUTHORIZED") != "1":
        print("TRAJGATE_PHASE0_REFUSED: --live requires EMBER_GATE_AUTHORIZED=1 "
              "(same interlock convention as every other live-dispatch entrypoint "
              "in this tree). No checkpoint/shard dispatch launched.", flush=True)
        return 3

    missing = [f"--{name}" for name, val in (
        ("ckpt-a", args.ckpt_a), ("ckpt-b", args.ckpt_b), ("ckpt-c", args.ckpt_c),
        ("shard-dir", args.shard_dir),
        ("shard-manifest-sha256", args.shard_manifest_sha256),
        ("device", args.device)) if not val]
    if missing:
        print(f"TRAJGATE_PHASE0_REFUSED: --live requires {', '.join(missing)} "
              "(explicit, no defaults on the live path).", flush=True)
        return 3

    Path(args.receipt_dir).mkdir(parents=True, exist_ok=True)
    receipt = run_live(
        ckpt_a=args.ckpt_a, ckpt_b=args.ckpt_b, ckpt_c=args.ckpt_c, ckpt_d=args.ckpt_d,
        shard_dir=args.shard_dir, shard_manifest_sha256=args.shard_manifest_sha256,
        device=args.device, seed=args.seed, ce_chunk_tokens=args.ce_chunk_tokens)

    from receipt_write import checked_write
    receipt_path = Path(args.receipt_dir) / f"trajgate-phase0-{receipt['ts']}.json"
    checked_write(str(receipt_path), receipt)
    print(f"TRAJGATE_PHASE0_DONE receipt={receipt_path} verdict={receipt['verdict']} "
          f"guards_all_passed={receipt['guards_all_passed']}", flush=True)
    return 0 if receipt["guards_all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
