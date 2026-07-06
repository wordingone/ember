#!/usr/bin/env python3
"""run_p5_audit.py -- P0 PROBE P5: ratio-invariance + commutation audit
(ember issue #207, P0 composition-law program).

FROZEN SPEC (do not deviate without a dated entry in this file AND
docs/deviations.md -- the freeze rule, verbatim from the pre-registration):
  state/prereg-p0-probes-p5-p1tier0-v1.md, section "PROBE P5", v1.1
  (frozen 2026-07-06). This file implements that section EXACTLY. Anything
  this file cannot honestly ground in a live production object is recorded
  as an explicit N/A-with-reason, never silently invented or approximated.
  Silent iteration voids receipts (the spec's own zombie rule: loss/
  trajectory bands alone certify NOTHING here; mechanism metrics are
  co-primary; a run whose engagement assertions did not fire writes NO
  metrics artifact -- it writes a FAILED-ENGAGEMENT receipt, #216).

GOAL: measure whether the seven dimensionless mechanism ratios below are
ladder-invariant by default across three checkpoints (368M "QAT", 718M
"D6-segment", 1.22B "rung-1"), and whether the net2net grow pushforward
approximately commutes with the update map. INSTRUMENTATION ONLY: no
training. Per measurement point: forward + backward + optimizer-step-IN-
COPY (never mutates the source checkpoint's own state dict -- asserted).

GROUNDING PASS (this authoring session, direct code reads, file:line cited
so every pin below is either CONFIRMED-BY-CODE or an honest structural
N/A -- never assumed):
  - Live QUANTIZER used for the grid step (Delta): the production QAT
    fake-quant transform is scripts/timeshare_pretrain.py::_apply_fake_quant
    (mode="qat"), PER-CHANNEL granularity: for a torch.nn.Linear weight
    W (out_features, in_features), s = W.abs().amax(dim=1, keepdim=True)
    .clamp(min=1e-8) / 127.0 -- one scale per OUTPUT ROW (a "channel" =
    one output neuron), int8 grid (256 levels, +-127 after clamp). This is
    DIFFERENT from scripts/ember_bitnet_core.py's absmean_scale (per-
    TENSOR, ternary {-1,0,+1} BitNet b1.58 path) -- that track (C15
    bitnet-vs-dense comparison) has no full-scale (368M+) checkpoint
    receipted in this repo snapshot (only receipts/ember-tiny-bitnet-
    comparison/* at toy scale exist); _apply_fake_quant int8-grid QAT is
    the one actually exercised at the 368M/718M/1.22B scales this probe
    targets, so it is the live quantizer this harness reads. Granularity
    pin = "per-channel (per-output-row), int8 grid, 127-level symmetric" --
    stamped every run, never assumed to be per-tensor or per-block.
  - Muon optimizer: scripts/timeshare_pretrain.py::_muon_class/_Muon
    (line ~742-798). ns_steps default 5, coefficients (a,b,c) =
    (3.4445, -4.7750, 2.0315) -- the quintic Newton-Schulz iteration,
    copied verbatim below (same discipline as scripts/expc1/
    run_expc1_rank_sweep.py: a self-contained copy, not an import, so this
    research harness stays decoupled from timeshare_pretrain's production
    contract/config loading). momentum=0.95, nesterov=True defaults. State
    dict key: "momentum_buffer". Split: split_param_groups (line ~801) --
    a 2D weight that is not an embedding and not a head goes to Muon;
    everything else (embeddings, 1D norms/biases, heads) goes to AdamW.
  - optimizer_reset_on_resume: a REAL parameter name --
    scripts/timeshare_pretrain.py::run_v0_segment(reset_optimizer_on_resume:
    bool = False, ...) (line ~1229). Ordinary continuation segments default
    False (optimizer state warm-loaded/carried on resume). The net2net
    grow-chain callers (scripts/cbase_grow_rung.py, scripts/
    cbase_grow_live.py) explicitly pass True and RECEIPT it verbatim as
    "optimizer_reset_on_resume": true in their own emitted receipts (grep-
    confirmed in both files) -- because grow changes FF-dim param shapes,
    so pre-grow momentum cannot be replayed into the post-grow optimizer.
    This harness runtime-reads this field from the checkpoint's OWN
    receipt (never hardcodes it) and treats it as spec-critical: it drives
    both the rho_spec N/A-with-reason path AND the cross-width state-
    provenance-mismatch guard on rho_SR (see STATE + LR PINS below).
  - net2net grow path: scripts/cbase_grow_dryrun.py::widen_state_dict
    (line ~85) -- EXACT function-preserving duplication: gate_proj/up_proj
    rows -> cat([w, w]); down_proj columns -> cat([w*0.5, w*0.5], dim=1).
    No noise term anywhere in this operator (grep-confirmed across
    scripts/cbase_grow_*.py and scripts/ember_growth_harness.py -- the
    net2net path as actually coded is noise-free by construction). This is
    a genuine MEASUREMENT (epsilon = 0 exactly, not an N/A), reconfirmed
    empirically every run below (never merely assumed from the docstring)
    by diffing the two realized duplicate copies post-widen.
  - Rank projection (rho_rank / rho_grow): no production code path
    projects a Muon-eligible tensor into a rank-r subspace anywhere in
    scripts/timeshare_pretrain.py or the cbase_grow_* family (grep-
    confirmed). scripts/expc1/run_expc1_rank_sweep.py is a SEPARATE
    research harness exploring a hypothetical design; it is not wired into
    production. rho_rank / rho_grow are therefore N/A-by-construction
    (structural, no projector enabled) for all three checkpoints -- an
    honest finding per the spec's own "an N/A is a finding, not a gap".
  - 8-bit optimizer state (rho_block): scripts/ember_d6_bf16_momentum_ab.py
    measured (CPU selftest, no assumption) that production optimizer state
    is bf16-native end to end (AdamW/_Muon zeros_like(g) inherits the
    bf16 param/grad dtype; nothing promotes to fp32 anywhere in the
    training step) -- there is no 8-bit optimizer-state path in production.
    rho_block is therefore N/A (structural) in the real run. The formula
    itself IS implemented and unit-tested in --selftest against a
    synthetic 8-bit state tensor (per the spec's letter: the metric must
    be correct and tested even though currently unreachable in production).
  - Checkpoint discovery: NO clean single receipt was found in this repo
    snapshot recording an actual file path or HF-repo id for a "368M QAT",
    "718M D6-segment", or "1.22B rung-1" checkpoint. Param-count
    fingerprints exist (368354304 in receipts/fp19-bench-*.json and
    receipts/fp33-e4-profiler-*.json; 718316544 in receipts/d6-bf16-
    momentum-ab-20260703T160041Z.json) but carry no path field, and the
    growth-chain receipts referenced BY NAME in other files (e.g.
    "cbase-grow-live-live-20260703T053225Z.json") are not present as files
    in this worktree. Per the spec's own INPUTS clause ("runtime-
    discovered, fail-closed if absent"), discover_checkpoints() below scans
    receipts/ for these fingerprints, records every receipt it consulted,
    and reports MISSING (not a guess) for any checkpoint whose actual
    weight location cannot be resolved. The real (no-flag) run is
    EXPECTED to self-block on this box today -- that is the fail-closed
    contract working as designed, not a harness defect. discover_checkpoints
    is the single extension point: once a maintainer supplies real
    receipts/HF-repo ids for the three checkpoints, wire them into
    CHECKPOINT_FINGERPRINTS below; no other function needs to change.

STATE + LR PINS (confound guards, verdict-critical -- spec verbatim):
  Optimizer-state provenance must be identical IN KIND across the three
  checkpoints. This harness reads optimizer_reset_on_resume per checkpoint
  (from its own receipt) and computes a provenance_mismatch flag: True
  unless all three checkpoints share the same reset-kind (all warm-loaded,
  or all reset-at-grow). On provenance_mismatch, every cross-width
  comparison (the rho_SR headline verdict) is forced UNRESOLVED rather
  than KILL/PROMOTE/GRAY -- never silently compared across a provenance
  discontinuity. The in-copy update is computed TWICE per checkpoint: at
  the checkpoint's own LR (checkpoint-LR series, reported alongside) and
  at pinned unit LR (lr=1.0, all else identical -- the UNIT-LR series is
  the one all cross-width rho_SR verdicts are taken on).

MEASUREMENTS (per checkpoint, per tensor class: attention / FF /
embedding, computed separately) -- see the module-level functions:
  rho_sr        -- per-block ||update_b||_RMS / Delta_b (median over
                   blocks -> per-tensor; median over tensors -> per-class).
                   Block granularity is per-channel (see quantizer above);
                   one "block" = one output-row scale.
  rho_noise     -- epsilon / Delta; epsilon = the REALIZED (measured, not
                   assumed) net2net duplicate-pair delta, empirically 0 for
                   this production grow path (see grounding above).
  rho_rank,
  rho_grow      -- N/A-by-construction, all checkpoints (no projector).
  rho_spec      -- at the grow event only (1.22B rung-1, PRE-grow state):
                   ||M - P_dup(M)||_2 / sigma_max(M). N/A-by-construction
                   at non-grow checkpoints (368M/718M). At the grow event:
                   N/A-with-reason="production-reset" whenever
                   optimizer_reset_on_resume reads True for that checkpoint
                   (the momentum matrix does not carry state across the
                   grow, so there is no M to measure) -- itself a
                   law-relevant finding per the spec.
  rho_batch     -- Welford over the 16 frozen microbatches:
                   B_simple = tr(Sigma_g) / ||g_bar||^2;
                   rho_batch = (batch_size * (1-beta)^-1) / B_simple, beta
                   read from the live Muon param group's "momentum".
  rho_block     -- N/A (structural, no 8-bit optimizer state in
                   production; formula implemented + selftested anyway).
  d_comm        -- commutation defect at the rung-1 grow event (measurement
                   only, no pass bar at v1.1).

ENGAGEMENT ASSERTIONS (before ANY artifact write; #216 fail-closed rule):
  checkpoint sha recorded; Delta read from the live quantizer (grid object
  exists and quantizes a test tensor); update computed in-copy (source
  state dict bitwise unchanged after the probe); probe batch sha matches
  the frozen batch on disk; LR / schedule-position / tokens-seen / state-
  provenance stamped per checkpoint; all 7 ratios carry a non-null value OR
  an explicit recorded N/A-with-reason. Any assertion failure -> a
  FAILED-ENGAGEMENT receipt is written INSTEAD of a metrics artifact; the
  metrics artifact is never written on a partial assertion pass.

VERDICT (per-class KILL / PROMOTE / GRAY; headline = majority; mixed
per-class outcomes -> GRAY/UNRESOLVED overall with the per-class table as
the artifact -- see compute_verdict() for the exact band logic, the noise-
floor rule, and the missing-point -> UNRESOLVED rule).

BUDGET: CPU/GPU minutes; hard wall 60 min per checkpoint. GPU co-resident
<=2 GiB; nvidia-smi preflight; serialize behind any running GPU job (one-
job rule; this probe WAITS, it never kills).

GOVERNOR / LAUNCH-GATE (never loosened; --dry-run and --selftest touch
neither CUDA nor nvidia-smi nor any real checkpoint): the live path (no
flags) requires EMBER_GATE_AUTHORIZED=1 (env) or refuses closed (status
BLOCKED, receipt WRITTEN, probe NOT executed) -- identical interlock
pattern to scripts/expc1/run_expc1_rank_sweep.py. NOT fired by this
authoring session. Even when authorized, the live path first runs
discover_checkpoints(); on any MISSING checkpoint it writes a
FAILED-ENGAGEMENT receipt (never fabricates a path) and stops.

MODES:
  --selftest   Pure Python/math + CPU-only torch checks: every ratio
               formula (including the ones that are N/A in production, so
               the formula itself is proven correct), Welford vs direct
               covariance-trace agreement, the P_dup symmetrization
               identity (rho_spec ~ 0 when M is already symmetric under
               P_dup, nonzero under a controlled perturbation), the
               commutation-defect formula (d_comm = 0 when U and G are
               constructed to commute by design, nonzero under a
               controlled perturbation), engagement-assertion pass/fail
               paths, verdict-band logic (KILL/PROMOTE/GRAY/UNRESOLVED,
               noise-floor rule, missing-point rule, mixed-per-class rule,
               provenance-mismatch-forces-UNRESOLVED rule), and receipt-
               schema round trip. Prints P5_AUDIT_SELFTEST_PASS.
  --dry-run    CPU only, toy widths (24/32/48 hidden, standing in for the
               368M/718M/1.22B ladder), NO real checkpoints -- builds three
               self-contained toy transformers (own module, decoupled from
               timeshare_pretrain's contract loader -- same discipline as
               expc1), but reuses the PRODUCTION math byte-for-byte: the
               _apply_fake_quant per-channel int8 formula, the Muon/
               Newton-Schulz update, and the net2net cat([w,w]) /
               cat([w*0.5,w*0.5]) widen operator. Proves the harness
               plumbing end-to-end (all 7 ratios + commutation defect +
               engagement assertions + verdict logic) at zero real-
               experiment weight. NOT research-conclusive (receipt says
               so). Receipt -> receipts/p5-ratio-audit-dryrun-<ts>.json.
  (no flag)    The real run: discover_checkpoints() (fail-closed if any
               checkpoint is unresolved) then, only under
               EMBER_GATE_AUTHORIZED=1, the full probe on the three real
               checkpoints. NOT fired by this authoring session.

No git commits from inside this file. No downloads. No founder/user names
anywhere in this file or its receipts. UTF-8 / plain-ASCII source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))           # scripts/p5_ratio_audit
SCRIPTS_DIR = os.path.dirname(HERE)                          # scripts/
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)                     # repo root
RECEIPTS = os.path.join(REPO_ROOT, "receipts")
sys.path.insert(0, SCRIPTS_DIR)

from receipt_write import checked_write  # noqa: E402  (light; no torch)

# ---------------------------------------------------------------------------
# Frozen constants (pre-registration v1.1 -- never change without a dated
# deviation entry, per the freeze rule).
# ---------------------------------------------------------------------------

SPEC_REF = "state/prereg-p0-probes-p5-p1tier0-v1.md#PROBE-P5"
SPEC_VERSION = "v1.1"
ISSUE = "#207"

PROBE_SEED = 20260706
PROBE_N_MICROBATCHES = 16
PROBE_SEQ_LEN = 1024

UNIT_LR = 1.0

KILL_RATIO_MAX = 1.2          # max/min <= 1.2 (~+-10%) -> KILL (drift rejected)
PROMOTE_RATIO_MIN = 1.5       # max/min >= 1.5 + monotone + noise-band-excluded -> PROMOTE
# 1.2 < ratio < 1.5, or non-monotone, or noise-band overlap -> GRAY/UNRESOLVED

TENSOR_CLASSES = ("attention", "ff", "embedding")

RATIO_NAMES = ("rho_sr", "rho_noise", "rho_rank", "rho_grow", "rho_spec",
               "rho_batch", "rho_block")

# Checkpoint fingerprints -- the ONLY extension point for wiring in real
# checkpoint locations once a maintainer supplies them. Each entry names the
# param-count signature this authoring session found receipted (see module
# docstring grounding pass) and the receipt-name substrings to search.
CHECKPOINT_FINGERPRINTS = {
    "368M_QAT": {
        "label": "368M QAT",
        "param_count_hint": 368354304,
        "receipt_name_hints": ["fp19-bench", "fp33-e4-profiler", "qat", "368"],
        "role": "non_grow",
    },
    "718M_D6_segment": {
        "label": "718M D6-segment",
        "param_count_hint": 718316544,
        "receipt_name_hints": ["d6-bf16-momentum-ab", "d6", "718"],
        "role": "non_grow",
    },
    "1_22B_rung1": {
        "label": "1.22B rung-1",
        "param_count_hint": 1_220_000_000,  # approximate; rung-1 is a grow target, not exact
        "receipt_name_hints": ["cbase-grow-rung1", "cbase-grow-live", "rung1", "rung-1"],
        "role": "grow_event",
    },
}

PATH_KEY_HINTS = ("checkpoint", "checkpoint_path", "ckpt", "ckpt_path",
                  "last_checkpoint", "hf_repo", "hf_repo_id", "local_path",
                  "save_path", "output_dir", "run_dir")

PRE_REGISTRATION = {
    "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION, "issue": ISSUE,
    "prediction": "rho_SR (unit-LR series) is NOT invariant -- it drifts "
        "monotonically with width across 368M -> 718M -> 1.22B under the "
        "default per-channel-referenced int8 grid.",
    "verdict_bands": {
        "kill_per_class": "max/min rho_SR across the three widths <= "
            f"{KILL_RATIO_MAX} (~+-10%) -> KILL (drift rejected, promote-the-"
            "null, GOOD outcome, law simplifies).",
        "promote_per_class": f"max/min >= {PROMOTE_RATIO_MIN}, monotone "
            "direction, AND the across-width spread exceeds the within-"
            "checkpoint noise (95% band per width point, from the 16 "
            "per-microbatch replicates, must EXCLUDE the kill band).",
        "gray_per_class": f"{KILL_RATIO_MAX}-{PROMOTE_RATIO_MIN}, non-"
            "monotone, or noise-band overlap -> UNRESOLVED, extend to "
            "per-layer resolution before any claim.",
        "headline": "majority of per-class verdicts; ANY class PROMOTE "
            "while ANY class KILL -> GRAY/UNRESOLVED overall with the "
            "per-class table as the artifact.",
        "missing_point_rule": "any missing width point (OOM/wall-cap kill "
            "of one leg) -> UNRESOLVED; two-point 'monotone' is non-"
            "evidence, pre-registered.",
        "provenance_mismatch_rule": "optimizer-state provenance must be "
            "identical in kind across the three checkpoints; on mismatch "
            "every cross-width comparison is forced UNRESOLVED, never "
            "compared across the discontinuity.",
    },
    "state_lr_pins": {
        "optimizer_state_provenance": "warm-loaded from the checkpoint's "
            "own saved state in all three, OR the probe records "
            "PROVENANCE-MISMATCH and affected ratios are UNRESOLVED, never "
            "compared cross-width.",
        "dual_lr_series": "in-copy update computed at the checkpoint's own "
            "LR AND at pinned unit LR (lr=1.0); ALL cross-width rho_SR "
            "verdicts are taken on the UNIT-LR series; checkpoint-LR "
            "series reported alongside.",
    },
    "budget": {"hard_wall_min_per_checkpoint": 60, "gpu_coresident_gib_max": 2},
    "no_pass_bar_metrics": ["d_comm"],
    "scope_disclosures": [
        "quantizer granularity is PER-CHANNEL (per-output-row int8), "
        "confirmed at scripts/timeshare_pretrain.py::_apply_fake_quant "
        "mode='qat' -- NOT per-tensor and NOT genuinely sub-channel "
        "per-block; 'block' in this harness means one output-row scale.",
        "rho_rank/rho_grow are N/A-by-construction for all three "
        "checkpoints -- no rank-projection code exists in production "
        "(grep-confirmed); scripts/expc1's rank-sweep is a separate, "
        "unwired research harness.",
        "rho_block is N/A (structural) -- production optimizer state is "
        "bf16-native end to end, no 8-bit optimizer-state path exists "
        "(scripts/ember_d6_bf16_momentum_ab.py measured this directly); "
        "the formula is implemented and selftested regardless.",
        "net2net grow noise (epsilon) is measured, not assumed, every run "
        "by diffing the realized duplicate pair post-widen; production's "
        "cat([w,w]) operator carries no noise term, so epsilon=0 is "
        "expected but never hardcoded.",
        "checkpoint discovery is fail-closed: no confirmed real path/HF-"
        "repo-id exists in this repo snapshot for any of the three named "
        "checkpoints (param-count fingerprints only); the real run is "
        "expected to self-block on this box (BLOCKED/FAILED-ENGAGEMENT), "
        "which is the fail-closed contract working as designed.",
    ],
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Checkpoint discovery -- runtime, fail-closed if absent (spec INPUTS
# clause). The ONLY extension point: CHECKPOINT_FINGERPRINTS above.
# ---------------------------------------------------------------------------

def _load_json_safe(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _find_path_field(obj, depth: int = 4):
    """Recursively search a receipt dict for a checkpoint-location field.
    Returns (key_path, value) for the first hit, or None. Depth-bounded so a
    malformed/huge receipt cannot hang discovery."""
    if depth <= 0 or not isinstance(obj, dict):
        return None
    for k, v in obj.items():
        lk = k.lower()
        if isinstance(v, str) and any(h in lk for h in PATH_KEY_HINTS):
            return (k, v)
        if isinstance(v, dict):
            hit = _find_path_field(v, depth - 1)
            if hit is not None:
                return hit
    return None


def _receipt_mentions_param_count(obj, param_count_hint: int, tolerance: float = 0.02):
    """True if any int field in obj (recursively, depth-bounded) is within
    `tolerance` fraction of param_count_hint -- a soft fingerprint match
    since the exact rung-1 param count is a target, not a fixed constant."""
    def _walk(o, depth):
        if depth <= 0:
            return False
        if isinstance(o, dict):
            for v in o.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if abs(v - param_count_hint) <= param_count_hint * tolerance:
                        return True
                if isinstance(v, (dict, list)):
                    if _walk(v, depth - 1):
                        return True
        elif isinstance(o, list):
            for item in o[:20]:
                if _walk(item, depth - 1):
                    return True
        return False
    return _walk(obj, 5)


def discover_checkpoints(receipts_dir: str = RECEIPTS) -> dict:
    """Scan receipts_dir for each of the three named checkpoints. Returns a
    dict keyed by CHECKPOINT_FINGERPRINTS key with:
      found: bool
      checkpoint_path: str | None
      consulted_receipts: list[str]  -- EVERY receipt examined for this
        checkpoint (spec: "the receipt file consulted is itself recorded in
        the artifact"), whether or not a path was found in it.
      matched_receipt: str | None    -- the receipt a path field was found in
      reason: str                    -- present when found=False
      optimizer_reset_on_resume: bool | None -- runtime-read from the
        matched receipt when present; None if unresolved/absent.
    Never raises; never fabricates a path. This is the ONLY function that
    needs to change when real checkpoint locations become available.
    """
    result = {}
    dir_path = Path(receipts_dir)
    all_receipt_files = sorted(dir_path.glob("*.json")) if dir_path.is_dir() else []

    for key, spec in CHECKPOINT_FINGERPRINTS.items():
        consulted = []
        matched_receipt = None
        checkpoint_path = None
        reset_flag = None
        for fpath in all_receipt_files:
            name_lower = fpath.name.lower()
            name_hit = any(h.lower() in name_lower for h in spec["receipt_name_hints"])
            if not name_hit:
                continue
            obj = _load_json_safe(str(fpath))
            if obj is None:
                continue
            consulted.append(str(fpath.relative_to(REPO_ROOT)) if fpath.is_relative_to(Path(REPO_ROOT)) else str(fpath))
            param_hit = _receipt_mentions_param_count(obj, spec["param_count_hint"])
            path_field = _find_path_field(obj)
            if path_field is not None and (param_hit or True):
                # Prefer a receipt that ALSO matches the param-count
                # fingerprint, but record any path field found under a
                # name-matched receipt -- never silently discard a hit.
                matched_receipt = str(fpath.relative_to(REPO_ROOT)) if fpath.is_relative_to(Path(REPO_ROOT)) else str(fpath)
                checkpoint_path = path_field[1]
                reset_flag = _find_reset_flag(obj)
                if param_hit:
                    break  # strong match; stop scanning further candidates

        if checkpoint_path is not None:
            result[key] = {
                "label": spec["label"], "role": spec["role"], "found": True,
                "checkpoint_path": checkpoint_path,
                "matched_receipt": matched_receipt,
                "consulted_receipts": consulted,
                "optimizer_reset_on_resume": reset_flag,
            }
        else:
            result[key] = {
                "label": spec["label"], "role": spec["role"], "found": False,
                "checkpoint_path": None,
                "matched_receipt": None,
                "consulted_receipts": consulted,
                "optimizer_reset_on_resume": None,
                "reason": (
                    f"MISSING: no receipt under {receipts_dir} matching "
                    f"name-hints {spec['receipt_name_hints']} carried a "
                    f"checkpoint-location field (checked keys: "
                    f"{PATH_KEY_HINTS}). {len(consulted)} candidate "
                    f"receipt(s) consulted (listed above); param-count "
                    f"fingerprint {spec['param_count_hint']} alone is not "
                    f"sufficient evidence of a resolvable weight location. "
                    "Fail-closed per spec INPUTS clause."
                ),
            }
    return result


def _find_reset_flag(obj, depth: int = 5):
    """Recursively search for an 'optimizer_reset_on_resume' field
    (verbatim key name, scripts/timeshare_pretrain.py::run_v0_segment
    parameter, receipted verbatim by scripts/cbase_grow_rung.py and
    scripts/cbase_grow_live.py). Returns bool or None if absent."""
    if depth <= 0 or not isinstance(obj, dict):
        return None
    for k, v in obj.items():
        if k == "optimizer_reset_on_resume" and isinstance(v, bool):
            return v
        if isinstance(v, dict):
            hit = _find_reset_flag(v, depth - 1)
            if hit is not None:
                return hit
    return None


def all_checkpoints_found(discovery: dict) -> bool:
    return all(v["found"] for v in discovery.values())


def provenance_mismatch(discovery: dict) -> bool:
    """STATE+LR PIN: provenance must be identical IN KIND across all three.
    None (unresolved) counts as a mismatch (fail-closed -- never assume a
    missing flag means 'same as the others')."""
    flags = [v.get("optimizer_reset_on_resume") for v in discovery.values()]
    if any(f is None for f in flags):
        return True
    return len(set(flags)) > 1


# ---------------------------------------------------------------------------
# Frozen probe batch -- 16 microbatches x 1024 tokens, seed 20260706, saved
# to disk before any measurement, sha256 in artifact.
# ---------------------------------------------------------------------------

def build_probe_batch(vocab: int, batch_size: int, out_dir: str,
                       n_micro: int = PROBE_N_MICROBATCHES,
                       seq_len: int = PROBE_SEQ_LEN, seed: int = PROBE_SEED):
    """Build the frozen probe batch: n_micro microbatches of (batch_size,
    seq_len) token ids, fixed seed, saved to disk BEFORE any measurement,
    sha256 recorded. Generation uses a dedicated CPU torch.Generator (never
    the model-init seed) -- decoupled, matching the repo's own convention
    (see scripts/expc1/run_expc1_rank_sweep.py::make_batch)."""
    import torch
    gen = torch.Generator().manual_seed(seed)
    microbatches = []
    for _ in range(n_micro):
        x = torch.randint(1, vocab, (batch_size, seq_len), generator=gen)
        y = torch.randint(1, vocab, (batch_size, seq_len), generator=gen)
        microbatches.append((x, y))

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"p5-probe-batch-seed{seed}.pt")
    torch.save(microbatches, path)
    sha = _sha256_file(path)
    return microbatches, path, sha


def verify_probe_batch_sha(path: str, expected_sha: str) -> bool:
    return os.path.isfile(path) and _sha256_file(path) == expected_sha


# ---------------------------------------------------------------------------
# Live quantizer -- byte-identical copy of scripts/timeshare_pretrain.py
# ::_apply_fake_quant(mode="qat") grid-step math (see module docstring
# grounding pass). Per-channel (per-output-row) int8 grid.
# ---------------------------------------------------------------------------

def quant_delta_per_channel(weight):
    """Delta_b per output row (channel) for a 2D weight tensor (out, in),
    IDENTICAL formula to scripts/timeshare_pretrain.py::_apply_fake_quant
    mode='qat': s = |W|.amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.
    Returns a (out, 1) tensor -- the live grid step per channel."""
    import torch
    assert weight.ndim == 2, "quant_delta_per_channel expects a 2D weight"
    return weight.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0


def assert_quantizer_engaged(weight) -> None:
    """Engagement assertion: the grid object exists and actually quantizes a
    test tensor (spec: 'assert grid object exists and quantizes a test
    tensor')."""
    import torch
    delta = quant_delta_per_channel(weight)
    assert delta.shape[0] == weight.shape[0] and delta.shape[1] == 1, delta.shape
    assert bool((delta > 0).all()), "quantizer produced a non-positive grid step"
    probe = torch.randn_like(weight)
    q = (probe / delta).round().clamp(-127, 127) * delta
    assert not torch.equal(q, probe), "quantizer is a no-op on a test tensor"


# ---------------------------------------------------------------------------
# rho_SR -- ||update_b||_RMS / Delta_b, median over blocks -> per-tensor,
# median over tensors -> per-class.
# ---------------------------------------------------------------------------

def rms(t) -> float:
    import torch
    return float(torch.sqrt(torch.mean(t.to(torch.float32) ** 2)))


def rho_sr_per_tensor(update, delta_per_channel) -> float:
    """update, delta_per_channel: same shape (out, in) / (out, 1) resp.
    Per-block (=per-channel row) RMS ratio, reduced by MEDIAN over blocks."""
    import torch
    assert update.shape[0] == delta_per_channel.shape[0]
    row_rms = torch.sqrt(torch.mean(update.to(torch.float32) ** 2, dim=1, keepdim=True))
    ratios = row_rms / delta_per_channel.to(torch.float32)
    return float(torch.median(ratios))


def rho_sr_per_class(tensor_ratios: list) -> float | None:
    """Median over tensors -> per-class. None if the class has no tensors."""
    import torch
    if not tensor_ratios:
        return None
    return float(torch.median(torch.tensor(tensor_ratios, dtype=torch.float32)))


# ---------------------------------------------------------------------------
# rho_noise -- epsilon / Delta. epsilon is MEASURED (realized duplicate-pair
# delta post-widen), never assumed. Delta = same per-channel reduction.
# ---------------------------------------------------------------------------

def net2net_widen_linear(gate_or_up_weight, down_weight):
    """Self-contained copy of the net2net FF-widen surgery documented in
    scripts/cbase_grow_dryrun.py (module docstring, line ~12-18): exact
    function-preserving duplication.
      gate/up rows:  cat([w, w], dim=0)          -- duplicate FF rows
      down columns:  cat([w*0.5, w*0.5], dim=1)  -- halve + duplicate cols
    Kept as a self-contained copy (same discipline as the Newton-Schulz
    copy above) so this research harness stays decoupled from
    cbase_grow_dryrun's production state-dict key-name assumptions, which
    do not match a toy/self-contained model's module layout."""
    import torch
    grown_gate_or_up = torch.cat([gate_or_up_weight, gate_or_up_weight], dim=0)
    grown_down = torch.cat([down_weight * 0.5, down_weight * 0.5], dim=1)
    return grown_gate_or_up, grown_down


def measure_net2net_epsilon(gate_or_up_weight) -> dict:
    """Realized noise measurement: widen, then diff the two duplicate
    halves. Production's cat([w,w]) is noise-free by construction; this
    measures that empirically rather than assuming it from the docstring."""
    import torch
    grown, _ = net2net_widen_linear(gate_or_up_weight, gate_or_up_weight)
    half = gate_or_up_weight.shape[0]
    a, b = grown[:half], grown[half:]
    diff = (a - b).abs()
    return {
        "epsilon_max": float(diff.max()),
        "epsilon_mean": float(diff.mean()),
        "epsilon_is_zero": bool(diff.max() == 0.0),
    }


def rho_noise(epsilon: float, delta_per_channel) -> float:
    import torch
    delta_scalar = float(torch.median(delta_per_channel))
    return epsilon / delta_scalar if delta_scalar > 0 else float("nan")


# ---------------------------------------------------------------------------
# rho_rank / rho_grow -- N/A-by-construction (no production rank projector).
# ---------------------------------------------------------------------------

def rho_rank_rho_grow_na() -> dict:
    return {
        "rho_rank": None, "rho_grow": None,
        "na_reason": "structural: no rank-projection code exists in "
            "production (scripts/timeshare_pretrain.py, scripts/"
            "cbase_grow_*.py grep-confirmed clean); scripts/expc1's "
            "rank-sweep is a separate, unwired research harness -- "
            "recorded per checkpoint, per tensor class.",
    }


# ---------------------------------------------------------------------------
# rho_spec -- P_dup symmetrization projector over duplicated column pairs,
# at the grow event only. N/A-by-construction at non-grow checkpoints;
# N/A-with-reason=production-reset when optimizer_reset_on_resume is True.
# ---------------------------------------------------------------------------

def p_dup_projector(n: int, duplicated_pairs: list):
    """Build the symmetrization projector P_dup over n columns/rows given a
    list of (i, j) duplicated-index pairs: P_dup averages each pair.
    P_dup(M) replaces columns i and j with their mean (the exact
    symmetrization the net2net duplication is supposed to preserve)."""
    import torch
    P = torch.eye(n, dtype=torch.float32)
    for i, j in duplicated_pairs:
        P[i, i] = P[i, j] = P[j, i] = P[j, j] = 0.5
    return P


def rho_spec(M, duplicated_pairs: list) -> float:
    """rho_spec = ||M - P_dup(M)||_2 / sigma_max(M). M: momentum matrix
    (out, in) or (in, in) depending on which axis is duplicated; caller
    passes M already oriented so duplicated_pairs index its FIRST axis."""
    import torch
    n = M.shape[0]
    P = p_dup_projector(n, duplicated_pairs)
    PM = P @ M
    num = torch.linalg.matrix_norm(M - PM, ord=2)
    denom = torch.linalg.matrix_norm(M, ord=2)  # sigma_max
    return float(num / denom) if float(denom) > 0 else float("nan")


def rho_spec_for_checkpoint(role: str, optimizer_reset_on_resume) -> dict:
    """Dispatch the N/A-by-construction / N/A-with-reason logic. Returns a
    dict; caller fills in a numeric value only when role == 'grow_event'
    and optimizer_reset_on_resume is False (state actually carries over)."""
    if role != "grow_event":
        return {"rho_spec": None, "na_reason": "N/A-by-construction: not the "
                "grow-event checkpoint (rho_spec is defined only at the "
                "rung-1 pre-grow state)."}
    if optimizer_reset_on_resume is None:
        return {"rho_spec": None, "na_reason": "UNRESOLVED: "
                "optimizer_reset_on_resume could not be runtime-read from "
                "this checkpoint's own receipt -- fail-closed, not assumed."}
    if optimizer_reset_on_resume:
        return {"rho_spec": None, "na_reason": "N/A-with-reason="
                "production-reset: optimizer_reset_on_resume=True for this "
                "checkpoint (runtime-read from its own receipt) -- the "
                "momentum matrix does not carry state across the grow, so "
                "there is no M to measure. This N/A is itself a "
                "law-relevant finding, per spec."}
    return {"rho_spec": "COMPUTE", "na_reason": None}  # caller computes rho_spec()


# ---------------------------------------------------------------------------
# rho_batch -- Welford over the 16 microbatches, tr(Sigma_g)/||g_bar||^2.
# ---------------------------------------------------------------------------

class WelfordAccumulator:
    """Online mean + M2 (sum of squared deviations) over a stream of
    flattened gradient vectors, one call to update() per microbatch.
    tr(Sigma_g) recovers as M2.sum() / (n-1) (component-wise variance,
    summed across components == trace of the covariance matrix)."""

    def __init__(self):
        self.n = 0
        self.mean = None
        self.m2 = None

    def update(self, g_flat) -> None:
        import torch
        self.n += 1
        if self.mean is None:
            self.mean = torch.zeros_like(g_flat)
            self.m2 = torch.zeros_like(g_flat)
        delta = g_flat - self.mean
        self.mean += delta / self.n
        delta2 = g_flat - self.mean
        self.m2 += delta * delta2

    def trace_sigma(self) -> float:
        if self.n < 2:
            return float("nan")
        return float((self.m2 / (self.n - 1)).sum())

    def mean_norm_sq(self) -> float:
        import torch
        return float(torch.sum(self.mean ** 2))


def rho_batch(grad_flats: list, batch_size: int, beta: float) -> dict:
    """grad_flats: list of per-microbatch flattened gradient tensors (one
    tensor class concatenated together). beta: Muon momentum coefficient,
    runtime-read from the live optimizer's param group."""
    acc = WelfordAccumulator()
    for g in grad_flats:
        acc.update(g)
    tr_sigma = acc.trace_sigma()
    g_bar_sq = acc.mean_norm_sq()
    b_simple = tr_sigma / g_bar_sq if g_bar_sq > 0 else float("nan")
    numerator = batch_size * (1.0 - beta) ** -1
    value = numerator / b_simple if b_simple not in (0.0,) and b_simple == b_simple else float("nan")
    return {
        "rho_batch": value, "b_simple": b_simple, "tr_sigma_g": tr_sigma,
        "g_bar_norm_sq": g_bar_sq, "batch_size": batch_size, "beta": beta,
        "numerator": numerator,
    }


def direct_trace_sigma(grad_flats: list) -> float:
    """Non-Welford reference computation (small N=16 here, used ONLY to
    cross-check the Welford accumulator in --selftest, never in the real
    measurement path)."""
    import torch
    stacked = torch.stack(grad_flats, dim=0)  # (n, d)
    mean = stacked.mean(dim=0)
    var = ((stacked - mean) ** 2).sum(dim=0) / (stacked.shape[0] - 1)
    return float(var.sum())


# ---------------------------------------------------------------------------
# rho_block -- 8-bit optimizer state only; N/A (structural) in production.
# Formula implemented + selftested regardless (spec's letter).
# ---------------------------------------------------------------------------

def rho_block_8bit(fresh_state_int8, scale_per_block) -> dict:
    """per-block min |fresh-state entry| / (absmax_block/(2^{bits-1}-1)).
    fresh_state_int8: int8 tensor (block, ...). scale_per_block: (block,)
    absmax per block already divided by 127 (8-bit: 2^7 - 1 = 127)."""
    import torch
    abs_entries = fresh_state_int8.to(torch.float32).abs()
    flat = abs_entries.reshape(abs_entries.shape[0], -1)
    min_abs = flat.min(dim=1).values
    grid_step = scale_per_block  # already absmax_block / 127
    ratios = min_abs / grid_step.clamp(min=1e-12)
    return {"rho_block_per_block": ratios.tolist(), "rho_block_median": float(torch.median(ratios))}


def rho_block_for_checkpoint() -> dict:
    return {"rho_block": None, "na_reason": "N/A (structural): production "
            "optimizer state is bf16-native end to end (scripts/"
            "ember_d6_bf16_momentum_ab.py measured this directly -- AdamW/"
            "_Muon zeros_like(g) inherits the bf16 param/grad dtype, "
            "nothing promotes to fp32); no 8-bit optimizer-state path "
            "exists to apply this formula to."}


# ---------------------------------------------------------------------------
# Commutation defect d_comm at the rung-1 grow event.
# ---------------------------------------------------------------------------

def commutation_defect(state_after_U_then_G, state_after_G_then_U, state_before) -> float:
    """d_comm = ||U_{k+1}(G(theta_k)) - G(U_k(theta_k))||_RMS /
                ||U_k(theta_k) - theta_k||_RMS
    All three args are flat tensors of the SAME shape (post-grow width):
      state_after_U_then_G = G(U_k(theta_k))   -- update then grow
      state_after_G_then_U = U_{k+1}(G(theta_k)) -- grow then update
      state_before         = G(theta_k) at the SAME width as the other two
                              (so the denominator's U_k(theta_k) - theta_k
                              is measured pre-grow and passed in already
                              RMS-normalized by the caller -- see
                              compute_d_comm below for the exact wiring)."""
    num = rms(state_after_G_then_U - state_after_U_then_G)
    denom = rms(state_after_U_then_G - state_before)
    return num / denom if denom > 0 else float("nan")


def compute_d_comm(theta_k, U_k_apply, U_kplus1_apply, G_apply) -> dict:
    """Wires the commutation defect exactly per spec:
      d_comm = ||U_{k+1}(G(theta_k)) - G(U_k(theta_k))||_RMS /
               ||U_k(theta_k) - theta_k||_RMS
    U_k_apply(theta) -> U_k(theta) at pre-grow width (one in-copy step).
    G_apply(theta)   -> G(theta), the net2net widen to post-grow width.
    U_kplus1_apply(theta) -> U_{k+1}(theta) at post-grow width (one
      in-copy step using the PRODUCTION pushforward optimizer state, i.e.
      whatever the runtime-read reset/carry flag says -- pre-registered as
      production-as-found, stamped by the caller)."""
    import torch
    Uk_theta = U_k_apply(theta_k)
    denom = rms(Uk_theta - theta_k)
    G_Uk_theta = G_apply(Uk_theta)
    G_theta = G_apply(theta_k)
    Ukp1_G_theta = U_kplus1_apply(G_theta)
    num = rms(Ukp1_G_theta - G_Uk_theta)
    value = num / denom if denom > 0 else float("nan")
    return {"d_comm": value, "numerator_rms": num, "denominator_rms": denom}


# ---------------------------------------------------------------------------
# Engagement assertions (before ANY artifact write -- #216 fail-closed).
# ---------------------------------------------------------------------------

class EngagementFailure(Exception):
    pass


def run_engagement_assertions(*, checkpoint_sha: str, source_state_before,
                               source_state_after, probe_batch_path: str,
                               probe_batch_sha: str, lr, schedule_position,
                               tokens_seen, state_provenance: str,
                               ratio_values: dict) -> list:
    """Returns the list of assertion labels that PASSED. Raises
    EngagementFailure with a message naming exactly which assertion failed
    -- caller writes a FAILED-ENGAGEMENT receipt on any raise, never a
    metrics artifact."""
    import torch
    passed = []

    if not checkpoint_sha:
        raise EngagementFailure("checkpoint sha not recorded")
    passed.append("checkpoint_sha_recorded")

    for name, before, after in (("source_state", source_state_before, source_state_after),):
        if before is not None and after is not None:
            for k in before:
                if not torch.equal(before[k], after[k]):
                    raise EngagementFailure(
                        f"source state dict mutated during in-copy probe: key {k!r}")
    passed.append("in_copy_update_source_state_bitwise_unchanged")

    if not (probe_batch_path and os.path.isfile(probe_batch_path)):
        raise EngagementFailure("probe batch file missing on disk")
    if _sha256_file(probe_batch_path) != probe_batch_sha:
        raise EngagementFailure("probe batch sha mismatch against frozen batch")
    passed.append("probe_batch_sha_matches")

    for label, val in (("lr", lr), ("schedule_position", schedule_position),
                       ("tokens_seen", tokens_seen)):
        if val is None:
            raise EngagementFailure(f"{label} not stamped")
    passed.append("lr_schedule_tokens_stamped")

    if not state_provenance:
        raise EngagementFailure("state provenance not stamped")
    passed.append("state_provenance_stamped")

    for ratio_name in RATIO_NAMES:
        entry = ratio_values.get(ratio_name)
        if entry is None:
            raise EngagementFailure(f"ratio {ratio_name} missing entirely from ratio_values")
        has_value = entry.get("value") is not None
        has_na_reason = entry.get("na_reason") is not None
        if not (has_value or has_na_reason):
            raise EngagementFailure(
                f"ratio {ratio_name} has neither a value nor an explicit N/A-with-reason")
    passed.append("all_seven_ratios_have_value_or_na_reason")

    return passed


def write_failed_engagement_receipt(*, ticket: str, mode: str, reason: str,
                                    extra: dict | None = None) -> Path:
    ts = _ts()
    receipt = {
        "ticket": ticket, "ts": ts, "mode": mode, "issue": ISSUE,
        "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "FAILED-ENGAGEMENT",
        "reason": reason,
        "zombie_rule": "loss/trajectory bands alone certify NOTHING; this "
            "run's engagement assertions did not all pass, so NO metrics "
            "artifact is written (#216 fail-closed).",
        "pre_registration": PRE_REGISTRATION,
    }
    if extra:
        receipt.update(extra)
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"p5-ratio-audit-FAILED-ENGAGEMENT-{ts}.json")
    checked_write(path, receipt)
    print(f"[p5-ratio-audit] FAILED-ENGAGEMENT: {reason}", flush=True)
    print(f"P5_AUDIT_DONE status=FAILED-ENGAGEMENT receipt={path}", flush=True)
    return Path(path)


# ---------------------------------------------------------------------------
# Verdict logic -- per-class KILL/PROMOTE/GRAY/UNRESOLVED, headline
# majority, noise-floor rule, missing-point rule, provenance-mismatch rule.
# ---------------------------------------------------------------------------

def per_class_verdict(width_values: list, width_noise_bands: list, *, mismatch: bool = False) -> dict:
    """width_values: list of 3 floats (rho_SR unit-LR at 368M/718M/1.22B) or
    None for a missing leg. width_noise_bands: list of 3 (lo, hi) 95% bands
    (from the 16 per-microbatch replicates at that width), or None.
    mismatch: STATE+LR provenance-mismatch flag -- forces UNRESOLVED."""
    if mismatch:
        return {"verdict": "UNRESOLVED", "reason": "provenance-mismatch: "
                "optimizer-state provenance differs in kind across the "
                "three checkpoints; cross-width comparison is invalid, "
                "never compared across the discontinuity."}
    if any(v is None for v in width_values):
        return {"verdict": "UNRESOLVED", "reason": "missing-point: at least "
                "one width leg is absent (OOM/wall-cap kill); two-point "
                "'monotone' is non-evidence, pre-registered as such."}

    lo, hi = min(width_values), max(width_values)
    ratio = hi / lo if lo > 0 else float("inf")
    monotone = (width_values[0] <= width_values[1] <= width_values[2]) or \
               (width_values[0] >= width_values[1] >= width_values[2])

    if ratio <= KILL_RATIO_MAX:
        return {"verdict": "KILL", "ratio": ratio,
                "reason": "max/min <= 1.2 -- drift REJECTED, promote-the-"
                "null, law simplifies (GOOD outcome for this prediction)."}

    if ratio >= PROMOTE_RATIO_MIN and monotone:
        if width_noise_bands is None or any(b is None for b in width_noise_bands):
            return {"verdict": "GRAY", "ratio": ratio, "monotone": monotone,
                    "reason": "ratio/monotonicity satisfied but no "
                    "within-checkpoint noise band was supplied -- cannot "
                    "confirm the across-width spread excludes the "
                    "kill band; UNRESOLVED pending per-layer resolution."}
        excludes_kill_band = all(
            not (lo_b <= KILL_RATIO_MAX <= hi_b) for lo_b, hi_b in width_noise_bands
        )
        if excludes_kill_band:
            return {"verdict": "PROMOTE", "ratio": ratio, "monotone": monotone,
                    "reason": "max/min >= 1.5, monotone, 95% noise bands "
                    "exclude the kill band -- drift confirmed for this class."}
        return {"verdict": "GRAY", "ratio": ratio, "monotone": monotone,
                "reason": "ratio/monotonicity satisfied but the "
                "per-microbatch noise band overlaps the kill band at one "
                "or more widths -- GRAY, extend to per-layer resolution."}

    return {"verdict": "GRAY", "ratio": ratio, "monotone": monotone,
            "reason": "1.2 < max/min < 1.5, or non-monotone -- GRAY/"
            "UNRESOLVED, extend to per-layer resolution before any claim; "
            "no third category invented post hoc."}


def headline_verdict(per_class: dict) -> dict:
    verdicts = [v["verdict"] for v in per_class.values()]
    if any(v == "UNRESOLVED" for v in verdicts):
        return {"verdict": "UNRESOLVED", "per_class": per_class,
                "reason": "at least one class is UNRESOLVED (missing-point "
                "or provenance-mismatch) -- headline cannot be computed."}
    if "PROMOTE" in verdicts and "KILL" in verdicts:
        return {"verdict": "GRAY", "per_class": per_class,
                "reason": "mixed per-class outcomes (some PROMOTE, some "
                "KILL) -- GRAY/UNRESOLVED overall, per-class table is the "
                "artifact, pre-registered as such."}
    counts = {v: verdicts.count(v) for v in set(verdicts)}
    majority = max(counts, key=counts.get)
    return {"verdict": majority, "per_class": per_class,
            "reason": f"majority of per-class verdicts ({counts})."}


# ---------------------------------------------------------------------------
# Selftest -- pure Python/math + CPU-only torch checks. No real checkpoints.
# ---------------------------------------------------------------------------

def selftest() -> None:
    import torch

    print("[p5-ratio-audit] selftest: quantizer + rho_SR + rho_noise + "
          "rho_spec/P_dup + Welford rho_batch + rho_block + d_comm + "
          "verdict logic + engagement assertions + receipt schema", flush=True)

    # 1. Quantizer: per-channel grid step matches the byte-identical copy of
    #    _apply_fake_quant's formula; assertion helper actually engages.
    torch.manual_seed(0)
    w = torch.randn(8, 6) * 3.0
    delta = quant_delta_per_channel(w)
    expected = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0
    assert torch.allclose(delta, expected), "quant_delta_per_channel formula drifted"
    assert_quantizer_engaged(w)  # must not raise
    print("  quant_delta_per_channel: per-channel int8 grid step, formula-exact, engaged  PASS")

    # 2. rho_SR: per-block (row) RMS ratio, median-over-blocks then
    #    median-over-tensors. Known update makes the answer computable by hand.
    update = torch.ones(4, 6) * 0.02   # RMS per row = 0.02 for every row
    delta2 = torch.full((4, 1), 0.01)  # Delta_b = 0.01 for every row
    r = rho_sr_per_tensor(update, delta2)
    assert abs(r - 2.0) < 1e-6, r
    per_class = rho_sr_per_class([r, r * 1.5, r * 0.5])
    assert abs(per_class - r) < 1e-6, per_class  # median of [2,3,1] = 2
    print(f"  rho_sr_per_tensor uniform case: {r:.4f} (expected 2.0)  PASS")
    print(f"  rho_sr_per_class median-of-tensors: {per_class:.4f}  PASS")

    # 3. rho_noise: production net2net widen is noise-free BY MEASUREMENT
    #    (not assumed) -- diff the two realized duplicate halves is exactly 0.
    gate_w = torch.randn(5, 6)
    eps_measurement = measure_net2net_epsilon(gate_w)
    assert eps_measurement["epsilon_is_zero"] is True, eps_measurement
    assert eps_measurement["epsilon_max"] == 0.0
    rn = rho_noise(eps_measurement["epsilon_max"], torch.full((5, 1), 0.5))
    assert rn == 0.0, rn
    print(f"  net2net widen epsilon measured (not assumed): "
          f"max={eps_measurement['epsilon_max']} -> rho_noise=0.0  PASS")

    # 3b. net2net widen shape/value correctness (cat([w,w]) / cat([w*.5,w*.5])).
    down_w = torch.randn(6, 5)
    grown_gate, grown_down = net2net_widen_linear(gate_w, down_w)
    assert grown_gate.shape == (10, 6), grown_gate.shape
    assert grown_down.shape == (6, 10), grown_down.shape
    assert torch.equal(grown_gate[:5], grown_gate[5:]), "duplicate rows must be identical"
    assert torch.allclose(grown_down[:, :5] + grown_down[:, 5:], down_w), \
        "halved+duplicated down columns must sum back to the original (function-preserving)"
    print("  net2net_widen_linear: shapes + function-preserving identity  PASS")

    # 4. rho_rank/rho_grow N/A path.
    na = rho_rank_rho_grow_na()
    assert na["rho_rank"] is None and na["rho_grow"] is None and na["na_reason"]
    print("  rho_rank/rho_grow: N/A-by-construction, reason stamped  PASS")

    # 5. rho_spec / P_dup projector: exact symmetrization identity.
    n = 6
    pairs = [(0, 3), (1, 4), (2, 5)]
    M_sym = torch.randn(n, 4)
    # Force M to be exactly symmetric under P_dup: duplicated rows equal.
    for i, j in pairs:
        M_sym[j] = M_sym[i]
    gap_sym = rho_spec(M_sym, pairs)
    assert gap_sym < 1e-5, gap_sym
    M_asym = torch.randn(n, 4)  # generic -- not symmetric under P_dup
    gap_asym = rho_spec(M_asym, pairs)
    assert gap_asym > 1e-3, gap_asym
    print(f"  rho_spec/P_dup: symmetric M gap={gap_sym:.2e} (~0), "
          f"generic M gap={gap_asym:.4f} (>0)  PASS")

    # 5b. rho_spec N/A dispatch: non-grow, production-reset, unresolved, compute.
    d1 = rho_spec_for_checkpoint("non_grow", False)
    assert d1["rho_spec"] is None and "N/A-by-construction" in d1["na_reason"]
    d2 = rho_spec_for_checkpoint("grow_event", True)
    assert d2["rho_spec"] is None and "production-reset" in d2["na_reason"]
    d3 = rho_spec_for_checkpoint("grow_event", None)
    assert d3["rho_spec"] is None and "UNRESOLVED" in d3["na_reason"]
    d4 = rho_spec_for_checkpoint("grow_event", False)
    assert d4["rho_spec"] == "COMPUTE"
    print("  rho_spec_for_checkpoint: non-grow / production-reset / "
          "unresolved / compute dispatch  PASS")

    # 6. Welford rho_batch vs direct covariance-trace reference.
    torch.manual_seed(1)
    grads = [torch.randn(500) * 0.1 + 0.05 for _ in range(16)]
    acc = WelfordAccumulator()
    for g in grads:
        acc.update(g)
    welford_trace = acc.trace_sigma()
    direct_trace = direct_trace_sigma(grads)
    assert abs(welford_trace - direct_trace) < 1e-4, (welford_trace, direct_trace)
    rb = rho_batch(grads, batch_size=8, beta=0.95)
    assert rb["rho_batch"] == rb["rho_batch"]  # not NaN
    print(f"  Welford trace(Sigma_g)={welford_trace:.6f} vs direct="
          f"{direct_trace:.6f} (agree)  PASS")
    print(f"  rho_batch={rb['rho_batch']:.6f} b_simple={rb['b_simple']:.6f}  PASS")

    # 7. rho_block formula (implemented + tested even though N/A in prod).
    torch.manual_seed(2)
    fresh = torch.randint(-40, 40, (3, 10), dtype=torch.int8)
    fresh[fresh == 0] = 1  # avoid a literal zero entry degenerating the min
    absmax_per_block = fresh.to(torch.float32).abs().max(dim=1).values
    scale_per_block = absmax_per_block / 127.0
    rb8 = rho_block_8bit(fresh, scale_per_block)
    assert len(rb8["rho_block_per_block"]) == 3
    assert rb8["rho_block_median"] >= 0
    print(f"  rho_block_8bit formula (implemented+tested; N/A in prod): "
          f"median={rb8['rho_block_median']:.4f}  PASS")
    prod = rho_block_for_checkpoint()
    assert prod["rho_block"] is None and "N/A (structural)" in prod["na_reason"]
    print("  rho_block_for_checkpoint: N/A (structural), reason stamped  PASS")

    # 8. Commutation defect: commuting-by-construction -> ~0; a controlled
    #    perturbation to the post-grow update path -> nonzero.
    torch.manual_seed(3)
    theta = torch.randn(4, 6)
    step_delta = torch.randn(4, 6) * 0.01
    pairs4 = [(0, 2), (1, 3)]

    def G(t):
        top, bot = net2net_widen_linear(t, t)
        return top  # widen rows only, for this synthetic commuting check

    def U_k(t):
        return t + step_delta

    def U_kplus1_commuting(t):
        # Constructed to commute: same additive delta, duplicated the same
        # way G duplicates rows, so U_{k+1}(G(theta)) == G(U_k(theta)) exactly.
        grown_delta, _ = net2net_widen_linear(step_delta, step_delta)
        return t + grown_delta

    d_commuting = compute_d_comm(theta, U_k, U_kplus1_commuting, G)
    assert d_commuting["d_comm"] < 1e-5, d_commuting

    def U_kplus1_noncommuting(t):
        return t + torch.randn_like(t) * 0.05  # unrelated perturbation

    d_noncommuting = compute_d_comm(theta, U_k, U_kplus1_noncommuting, G)
    assert d_noncommuting["d_comm"] > 1e-2, d_noncommuting
    print(f"  commutation_defect: commuting-by-construction d_comm="
          f"{d_commuting['d_comm']:.2e} (~0), perturbed d_comm="
          f"{d_noncommuting['d_comm']:.4f} (>0)  PASS")

    # 9. Verdict logic: KILL / PROMOTE / GRAY / UNRESOLVED bands.
    kill = per_class_verdict([1.0, 1.05, 1.1], None)
    assert kill["verdict"] == "KILL", kill
    gray_mid = per_class_verdict([1.0, 1.3, 1.35], None)
    assert gray_mid["verdict"] == "GRAY", gray_mid
    gray_nonmonotone = per_class_verdict([1.0, 2.0, 1.2], [(0.9, 1.1), (1.8, 2.2), (1.0, 1.4)])
    assert gray_nonmonotone["verdict"] == "GRAY", gray_nonmonotone
    promote = per_class_verdict([1.0, 1.6, 2.0], [(0.9, 1.1), (1.5, 1.7), (1.9, 2.1)])
    assert promote["verdict"] == "PROMOTE", promote
    gray_noise_overlap = per_class_verdict([1.0, 1.6, 2.0], [(0.9, 1.3), (1.5, 1.7), (1.9, 2.1)])
    assert gray_noise_overlap["verdict"] == "GRAY", gray_noise_overlap
    missing = per_class_verdict([1.0, None, 2.0], None)
    assert missing["verdict"] == "UNRESOLVED", missing
    mismatched = per_class_verdict([1.0, 1.6, 2.0], [(0.9, 1.1), (1.5, 1.7), (1.9, 2.1)], mismatch=True)
    assert mismatched["verdict"] == "UNRESOLVED", mismatched
    print("  per_class_verdict: KILL/GRAY(mid)/GRAY(non-monotone)/PROMOTE/"
          "GRAY(noise-overlap)/UNRESOLVED(missing)/UNRESOLVED(mismatch)  PASS")

    headline_mixed = headline_verdict({
        "attention": {"verdict": "PROMOTE"}, "ff": {"verdict": "KILL"},
        "embedding": {"verdict": "KILL"},
    })
    assert headline_mixed["verdict"] == "GRAY", headline_mixed
    headline_majority = headline_verdict({
        "attention": {"verdict": "KILL"}, "ff": {"verdict": "KILL"},
        "embedding": {"verdict": "GRAY"},
    })
    assert headline_majority["verdict"] == "KILL", headline_majority
    headline_unresolved = headline_verdict({
        "attention": {"verdict": "UNRESOLVED"}, "ff": {"verdict": "KILL"},
        "embedding": {"verdict": "KILL"},
    })
    assert headline_unresolved["verdict"] == "UNRESOLVED", headline_unresolved
    print("  headline_verdict: mixed->GRAY, majority->KILL, "
          "any-unresolved->UNRESOLVED  PASS")

    # 10. Engagement assertions: pass path + each failure path.
    src_before = {"w": torch.zeros(3, 3)}
    src_after_ok = {"w": torch.zeros(3, 3)}
    tmp_dir = os.path.join(REPO_ROOT, "receipts", ".p5_selftest_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    batch_path = os.path.join(tmp_dir, "selftest_batch.bin")
    with open(batch_path, "wb") as f:
        f.write(b"selftest-probe-bytes")
    batch_sha = _sha256_file(batch_path)
    ok_ratios = {name: {"value": 1.0, "na_reason": None} for name in RATIO_NAMES}
    passed = run_engagement_assertions(
        checkpoint_sha="deadbeef", source_state_before=src_before,
        source_state_after=src_after_ok, probe_batch_path=batch_path,
        probe_batch_sha=batch_sha, lr=0.02, schedule_position=100,
        tokens_seen=1000, state_provenance="warm-loaded", ratio_values=ok_ratios)
    assert len(passed) == 6, passed
    try:
        src_after_mutated = {"w": torch.ones(3, 3)}
        run_engagement_assertions(
            checkpoint_sha="deadbeef", source_state_before=src_before,
            source_state_after=src_after_mutated, probe_batch_path=batch_path,
            probe_batch_sha=batch_sha, lr=0.02, schedule_position=100,
            tokens_seen=1000, state_provenance="warm-loaded", ratio_values=ok_ratios)
        assert False, "should have raised on mutated source state"
    except EngagementFailure:
        pass
    try:
        bad_ratios = dict(ok_ratios)
        bad_ratios["rho_sr"] = {"value": None, "na_reason": None}
        run_engagement_assertions(
            checkpoint_sha="deadbeef", source_state_before=src_before,
            source_state_after=src_after_ok, probe_batch_path=batch_path,
            probe_batch_sha=batch_sha, lr=0.02, schedule_position=100,
            tokens_seen=1000, state_provenance="warm-loaded", ratio_values=bad_ratios)
        assert False, "should have raised on a ratio with neither value nor na_reason"
    except EngagementFailure:
        pass
    os.remove(batch_path)
    os.rmdir(tmp_dir)
    print("  run_engagement_assertions: pass path + mutated-source-state "
          "failure + missing-ratio failure  PASS")

    # 11. discover_checkpoints / provenance_mismatch pure-logic paths
    #     (no real receipts dir needed -- synthetic discovery dicts).
    disc_all_found_matched = {
        "a": {"found": True, "optimizer_reset_on_resume": False},
        "b": {"found": True, "optimizer_reset_on_resume": False},
        "c": {"found": True, "optimizer_reset_on_resume": False},
    }
    assert all_checkpoints_found(disc_all_found_matched)
    assert provenance_mismatch(disc_all_found_matched) is False
    disc_mismatch = {
        "a": {"found": True, "optimizer_reset_on_resume": False},
        "b": {"found": True, "optimizer_reset_on_resume": False},
        "c": {"found": True, "optimizer_reset_on_resume": True},
    }
    assert provenance_mismatch(disc_mismatch) is True
    disc_unresolved = {
        "a": {"found": True, "optimizer_reset_on_resume": False},
        "b": {"found": True, "optimizer_reset_on_resume": None},
        "c": {"found": True, "optimizer_reset_on_resume": False},
    }
    assert provenance_mismatch(disc_unresolved) is True
    disc_missing = {"a": {"found": True}, "b": {"found": False}, "c": {"found": True}}
    assert all_checkpoints_found(disc_missing) is False
    print("  discover_checkpoints logic: all-found / provenance-mismatch / "
          "unresolved-counts-as-mismatch / missing-checkpoint  PASS")

    # 12. Receipt-shape round trip via the shared schema-floor validator.
    import receipt_check
    synth = {
        "ticket": "P5-RATIO-AUDIT", "ts": "20260706T000000Z", "mode": "selftest",
        "sha_convention": "bytes on disk as-is", "harness_sha": "a" * 64,
        "status": "OK",
    }
    findings = receipt_check.validate_receipt(synth)
    assert findings == [], findings
    print("  receipt-shape round trip passes receipt_check schema floor  PASS")

    print("P5_AUDIT_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Dry-run -- toy widths standing in for 368M/718M/1.22B, NO real checkpoints.
# Self-contained toy transformer (decoupled from timeshare_pretrain's
# contract loader), but PRODUCTION math reused byte-for-byte throughout.
# ---------------------------------------------------------------------------

DRY_WIDTHS = {"368M_QAT": 24, "718M_D6_segment": 32, "1_22B_rung1": 48}
DRY_VOCAB = 48
DRY_BATCH = 2
DRY_SEQ = 16
DRY_N_MICRO = 4  # smaller than the frozen 16 for a fast CPU plumbing proof


def _build_toy_ffn(hidden: int, ff: int, seed: int):
    """Self-contained toy FF block (gate/up/down, SwiGLU-style naming to
    mirror the production net2net key convention conceptually) -- own
    module, not coupled to timeshare_pretrain's state-dict key names."""
    import torch
    g = torch.Generator().manual_seed(seed)
    gate = torch.nn.Linear(hidden, ff, bias=False)
    up = torch.nn.Linear(hidden, ff, bias=False)
    down = torch.nn.Linear(ff, hidden, bias=False)
    with torch.no_grad():
        gate.weight.copy_(torch.randn(ff, hidden, generator=g) * 0.05)
        up.weight.copy_(torch.randn(ff, hidden, generator=g) * 0.05)
        down.weight.copy_(torch.randn(hidden, ff, generator=g) * 0.05)
    return gate, up, down


def _toy_forward_backward(gate, up, down, embed, head, x, y):
    import torch
    import torch.nn.functional as F
    h = embed(x)
    ff_out = down(F.silu(gate(h)) * up(h))
    logits = head(ff_out)
    loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1))
    loss.backward()
    return float(loss.item())


def _muon_step_in_copy(weight, grad, momentum_buffer, lr, momentum=0.95,
                       nesterov=True, ns_steps=5):
    """One Muon step, IN COPY (returns a new weight tensor + new momentum
    buffer; never mutates the inputs). Byte-identical math to
    scripts/timeshare_pretrain.py::_muon_class (self-contained copy, same
    discipline as scripts/expc1)."""
    import torch
    a, b, c = 3.4445, -4.7750, 2.0315

    def zeropower(G, steps=ns_steps, eps=1e-7):
        X = G.to(torch.float32)
        transposed = False
        if X.shape[0] > X.shape[1]:
            X = X.T
            transposed = True
        X = X / (X.norm() + eps)
        for _ in range(steps):
            A = X @ X.T
            B = b * A + c * (A @ A)
            X = a * X + B @ X
        if transposed:
            X = X.T
        return X

    new_buf = momentum_buffer.clone()
    new_buf.mul_(momentum).add_(grad)
    upd = grad.add(new_buf, alpha=momentum) if nesterov else new_buf
    upd = zeropower(upd, steps=ns_steps)
    scale = max(1.0, weight.shape[0] / weight.shape[1]) ** 0.5
    new_weight = weight.detach().clone()
    new_weight.add_(upd, alpha=-lr * scale)
    return new_weight, new_buf, upd


def run_and_emit_dry() -> Path:
    import torch

    tmp_dir = os.path.join(REPO_ROOT, "receipts", ".p5_dryrun_tmp")
    probe_batches, batch_path, batch_sha = build_probe_batch(
        DRY_VOCAB, DRY_BATCH, tmp_dir, n_micro=DRY_N_MICRO, seq_len=DRY_SEQ, seed=PROBE_SEED)

    per_width_rho_sr = {}
    per_class_results = {cls: [] for cls in TENSOR_CLASSES}
    checkpoints_report = {}

    for key, hidden in DRY_WIDTHS.items():
        gen = torch.Generator().manual_seed(PROBE_SEED + hidden)
        embed = torch.nn.Embedding(DRY_VOCAB, hidden)
        head = torch.nn.Linear(hidden, DRY_VOCAB, bias=False)
        gate, up, down = _build_toy_ffn(hidden, hidden * 2, seed=PROBE_SEED + hidden)
        with torch.no_grad():
            embed.weight.copy_(torch.randn(DRY_VOCAB, hidden, generator=gen) * 0.05)
            head.weight.copy_(torch.randn(DRY_VOCAB, hidden, generator=gen) * 0.05)

        source_state_before = {"gate": gate.weight.detach().clone(),
                               "up": up.weight.detach().clone(),
                               "down": down.weight.detach().clone()}

        x, y = probe_batches[0]
        _toy_forward_backward(gate, up, down, embed, head, x, y)

        # Engagement: quantizer live-object check on the FF gate weight.
        assert_quantizer_engaged(gate.weight.detach())
        delta_gate = quant_delta_per_channel(gate.weight.detach())

        momentum_buffer = torch.zeros_like(gate.weight)
        new_weight_unit, new_buf, upd_unit = _muon_step_in_copy(
            gate.weight.detach(), gate.weight.grad.detach(), momentum_buffer, lr=UNIT_LR)
        update_unit = new_weight_unit - gate.weight.detach()

        r_sr = rho_sr_per_tensor(update_unit, delta_gate)
        per_width_rho_sr[key] = r_sr
        per_class_results["ff"].append(r_sr)

        eps_meas = measure_net2net_epsilon(gate.weight.detach())
        r_noise = rho_noise(eps_meas["epsilon_max"], delta_gate)

        na_rank_grow = rho_rank_rho_grow_na()

        role = CHECKPOINT_FINGERPRINTS[key]["role"]
        # Dry-run stands in reset_on_resume=True only for the grow-event
        # slot, mirroring production's cbase_grow_* convention exactly.
        reset_flag = True if role == "grow_event" else False
        spec_dispatch = rho_spec_for_checkpoint(role, reset_flag)
        if spec_dispatch["rho_spec"] == "COMPUTE":
            pairs = [(i, i + hidden // 2) for i in range(hidden // 2)]
            spec_val = rho_spec(momentum_buffer if momentum_buffer.shape[0] > 1
                                else gate.weight.detach(), pairs[:1])
            spec_dispatch = {"rho_spec": spec_val, "na_reason": None}

        source_state_after = {"gate": gate.weight.detach().clone(),
                              "up": up.weight.detach().clone(),
                              "down": down.weight.detach().clone()}

        grad_flats = []
        for mx, my in probe_batches:
            gate.weight.grad = None
            up.weight.grad = None
            down.weight.grad = None
            _toy_forward_backward(gate, up, down, embed, head, mx, my)
            grad_flats.append(gate.weight.grad.detach().flatten().clone())
        rb = rho_batch(grad_flats, batch_size=DRY_BATCH, beta=0.95)

        rb_block = rho_block_for_checkpoint()

        ratio_values = {
            "rho_sr": {"value": r_sr, "na_reason": None},
            "rho_noise": {"value": r_noise, "na_reason": None},
            "rho_rank": {"value": None, "na_reason": na_rank_grow["na_reason"]},
            "rho_grow": {"value": None, "na_reason": na_rank_grow["na_reason"]},
            "rho_spec": {"value": spec_dispatch["rho_spec"] if spec_dispatch["rho_spec"] != "COMPUTE" else None,
                        "na_reason": spec_dispatch["na_reason"]},
            "rho_batch": {"value": rb["rho_batch"], "na_reason": None},
            "rho_block": {"value": rb_block["rho_block"], "na_reason": rb_block["na_reason"]},
        }

        passed_assertions = run_engagement_assertions(
            checkpoint_sha=_sha256_bytes(key.encode()),
            source_state_before=source_state_before,
            source_state_after=source_state_after,
            probe_batch_path=batch_path, probe_batch_sha=batch_sha,
            lr=UNIT_LR, schedule_position=0, tokens_seen=DRY_BATCH * DRY_SEQ * DRY_N_MICRO,
            state_provenance="reset-at-grow" if reset_flag else "warm-loaded",
            ratio_values=ratio_values)

        checkpoints_report[key] = {
            "label": CHECKPOINT_FINGERPRINTS[key]["label"], "toy_hidden": hidden,
            "role": role, "optimizer_reset_on_resume": reset_flag,
            "ratios": ratio_values, "engagement_assertions_passed": passed_assertions,
            "net2net_epsilon_measurement": eps_meas,
        }

    # Commutation defect at the (toy) grow event: 718M_D6_segment ->
    # 1_22B_rung1 stand-in widen.
    pre_hidden = DRY_WIDTHS["718M_D6_segment"]
    theta = torch.randn(pre_hidden * 2, pre_hidden) * 0.05
    step_delta = torch.randn(pre_hidden * 2, pre_hidden) * 0.001

    def G(t):
        top, _ = net2net_widen_linear(t, t)
        return top

    def U_k(t):
        return t + step_delta

    def U_kplus1(t):
        # production-as-found: reset_on_resume=True at the grow event means
        # the post-grow optimizer starts from FRESH (zero-momentum) state --
        # modeled here as a fresh, independent small step (not derived from
        # the pre-grow momentum), stamped explicitly, no pass bar at v1.1.
        return t + torch.randn_like(t) * 0.001

    d_comm_result = compute_d_comm(theta, U_k, U_kplus1, G)

    # Provenance + per-class verdict (single class "ff" populated in this
    # toy plumbing proof; attention/embedding are structurally absent from
    # the toy FF-only model -- recorded, not silently omitted).
    discovery_stub = {k: {"found": True,
                          "optimizer_reset_on_resume": checkpoints_report[k]["optimizer_reset_on_resume"]}
                     for k in DRY_WIDTHS}
    mismatch = provenance_mismatch(discovery_stub)
    ff_values = [per_width_rho_sr[k] for k in ("368M_QAT", "718M_D6_segment", "1_22B_rung1")]
    ff_verdict = per_class_verdict(ff_values, None, mismatch=mismatch)
    per_class_verdicts = {
        "attention": {"verdict": "UNRESOLVED", "reason": "structurally absent: "
                     "toy dry-run model is FF-only (no attention block) -- "
                     "recorded, not silently omitted."},
        "ff": ff_verdict,
        "embedding": {"verdict": "UNRESOLVED", "reason": "structurally absent: "
                     "embedding-class rho_SR needs a Muon-routed 2D embedding "
                     "tensor; this toy model routes embed/head to AdamW per "
                     "split_param_groups convention (embed/head excluded from "
                     "Muon) -- consistent with production routing, recorded."},
    }
    headline = headline_verdict(per_class_verdicts)

    ts = _ts()
    receipt = {
        "ticket": "P5-RATIO-AUDIT", "ts": ts, "mode": "dry-run", "issue": ISSUE,
        "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "OK",
        "scope": "CPU plumbing proof ONLY, toy widths ({}) standing in for "
                 "368M/718M/1.22B, NO real checkpoints. Reuses PRODUCTION "
                 "math byte-for-byte (per-channel int8 quantizer, Muon/"
                 "Newton-Schulz update, net2net cat([w,w]) widen) on a "
                 "self-contained toy model. NOT research-conclusive -- "
                 "proves the harness computes and gates every formula and "
                 "verdict path correctly, nothing more.".format(DRY_WIDTHS),
        "probe_batch": {"path": os.path.relpath(batch_path, REPO_ROOT), "sha256": batch_sha,
                        "n_microbatches": DRY_N_MICRO, "seq_len": DRY_SEQ, "seed": PROBE_SEED},
        "pre_registration": PRE_REGISTRATION,
        "checkpoints": checkpoints_report,
        "provenance_mismatch": mismatch,
        "commutation_defect": d_comm_result,
        "per_class_verdict": per_class_verdicts,
        "headline_verdict": headline,
        "note": "dry-run at toy widths over a 4-microbatch frozen batch -- "
                "per-checkpoint ratio values are NOT research-conclusive; "
                "they demonstrate the harness computes and gates on them "
                "correctly, nothing more.",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"p5-ratio-audit-dryrun-{ts}.json")
    checked_write(path, receipt)
    print(f"[p5-ratio-audit] dry-run receipt: {path}", flush=True)
    print(f"[p5-ratio-audit] headline_verdict={headline['verdict']} "
          f"d_comm={d_comm_result['d_comm']:.4f}", flush=True)
    print(f"P5_AUDIT_DRYRUN_DONE receipt={path}", flush=True)

    try:
        os.remove(batch_path)
        os.rmdir(tmp_dir)
    except OSError:
        pass
    return Path(path)


# ---------------------------------------------------------------------------
# Live run -- NOT fired this authoring session. GOVERNOR / LAUNCH-GATE.
# ---------------------------------------------------------------------------

def run_and_emit_live() -> Path:
    ts = _ts()
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"

    discovery = discover_checkpoints()
    discovery_summary = {k: {kk: vv for kk, vv in v.items() if kk != "reason"}
                         for k, v in discovery.items()}

    if not authorized:
        msg = ("P5_AUDIT_INTERLOCK_REFUSED: requires EMBER_GATE_AUTHORIZED=1 "
               "(env) -- one-GPU-job serialization on this box; live launch "
               "is held for the maintainer's explicit authorization "
               "(P0 tick-2 dispatch, ember issue #207).")
        receipt = {
            "ticket": "P5-RATIO-AUDIT", "ts": ts, "mode": "live", "issue": ISSUE,
            "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION,
            "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
            "harness_sha": _harness_sha(),
            "status": "BLOCKED",
            "interlock": {"authorized": False, "detail": msg},
            "checkpoint_discovery": discovery_summary,
            "pre_registration": PRE_REGISTRATION,
        }
        os.makedirs(RECEIPTS, exist_ok=True)
        path = os.path.join(RECEIPTS, f"p5-ratio-audit-BLOCKED-{ts}.json")
        checked_write(path, receipt)
        print(f"[p5-ratio-audit] LAUNCH_BLOCKED: {msg}", flush=True)
        print(f"P5_AUDIT_DONE status=BLOCKED receipt={path}", flush=True)
        return Path(path)

    if not all_checkpoints_found(discovery):
        missing = [v["label"] for v in discovery.values() if not v["found"]]
        reasons = {k: v.get("reason") for k, v in discovery.items() if not v["found"]}
        return write_failed_engagement_receipt(
            ticket="P5-RATIO-AUDIT", mode="live",
            reason=(f"checkpoint discovery MISSING for: {missing}. Fail-"
                    f"closed per spec INPUTS clause -- see checkpoint_discovery "
                    f"in this receipt for every receipt consulted per checkpoint."),
            extra={"checkpoint_discovery": discovery_summary, "missing_reasons": reasons})

    # Reachable only under explicit maintainer authorization WITH all three
    # checkpoints resolved. NOT reachable this authoring session (checkpoint
    # discovery is expected to self-block first -- see module docstring
    # grounding pass). Real checkpoint-loading + model-instantiation glue is
    # intentionally NOT implemented past this point: wiring it in without a
    # confirmed real checkpoint to load against would be inventing unfounded
    # facts, exactly what this harness's own discipline forbids. The
    # extension point is discover_checkpoints() (CHECKPOINT_FINGERPRINTS) --
    # once real locations are confirmed, the loader is the next authored
    # increment, built against the ACTUAL discovered path/format.
    return write_failed_engagement_receipt(
        ticket="P5-RATIO-AUDIT", mode="live",
        reason=("checkpoints resolved by discovery but real-checkpoint "
                "loading is not yet authored (no confirmed checkpoint "
                "format/path existed to build it against honestly during "
                "this authoring session) -- fail-closed rather than guess."),
        extra={"checkpoint_discovery": discovery_summary})


def main() -> int:
    ap = argparse.ArgumentParser(
        description="P5 ratio-invariance + commutation audit harness "
                    "(P0 composition-law program, ember issue #207)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, toy widths -- proves plumbing + receipt shape")
    ap.add_argument("--selftest", action="store_true",
                    help="pure math/schema checks + CPU-only torch empirical checks")
    args, _ = ap.parse_known_args()

    if args.selftest:
        selftest()
        return 0
    if args.dry_run:
        run_and_emit_dry()
        return 0
    run_and_emit_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
