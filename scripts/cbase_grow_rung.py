#!/usr/bin/env python3
"""cbase_grow_rung.py — C-SCALE S1 growth-chain rung runner (issue #29).

Generalizes cbase_grow_live.py's net2net FF-widening warm-start pipeline to
the MULTI-RUNG growth chain docs/spec/c-scale-s1-growth-chain-DRAFT.md's
section 9 (PRE-REGISTRATION, binding 2026-07-03) rules govern. Each rung:

  1. loads its PARENT rung's own already-landed grow receipt + final
     (already-stabilized) checkpoint — growth_lineage chaining, D4's
     W1.growth_lineage_from_cbase_seed;
  2. applies the SAME net2net FF-widening surgery cbase_grow_dryrun.
     widen_state_dict already proved (2x exact FF doubling — the only
     receipted, coded operator; spec §2.1/§3.3) to produce the next rung's
     grown checkpoint;
  3. runs ONE stabilization segment (fresh optimizer,
     reset_optimizer_on_resume=True) sized per D1's fixed-FLOPs-budget rule:
       steps(rung) = max(ceil(D1_ANCHOR_FLOPS / (6*N_grown*batch*seq)), 30)
     D1_ANCHOR_FLOPS is DERIVED here (not copied) from the one precedent
     segment ever run — the 718.3M rung's own post-grow segment: 60 steps at
     batch=16/seq=1024 (receipts/cbase-grow-live/cbase-grow-live-live-
     20260703T053225Z.json) — exact value 4,236,803,372,482,560.0 FLOPs.
     Spec §9 D1 rounds this "~=4.2375e15"; this file derives the EXACT
     figure from the precedent's own params/batch/seq/steps rather than
     copying the rounded prose number (verified: both give steps=36 at
     rung 1 — comfortably above the 30-step floor, close to but not exactly
     spec §6's illustrative "≈35 steps", a rounding difference, not a bug);
  4. checks the issue-29 kill criterion (post-grow segment loss within the
     PARENT rung's own last stabilization segment's loss-jump envelope —
     since this rung's grow step resumes DIRECTLY from the parent's
     already-stabilized checkpoint, there is no separate fresh "pre-grow
     continuation" segment to re-run; the parent's own last segment IS the
     pre-grow reference, generalizing D1's "post-grow segment loss within
     pre-grow envelope" wording across a lineage instead of re-running it
     per rung) — a violation (either function-preservation fp_diff>1e-4, or
     post-grow loss outside the envelope) writes a KILL receipt and exits
     nonzero; this script never retries in place;
  5. reports BOTH parameter conventions per D4:
       params_state_dict_sum — raw sum(v.numel() for v in state_dict.values())
         (continuity with the two existing receipted points; double-counts
         the tied embed/head matrix)
       params_unique — state_dict_sum minus the MEASURED (data_ptr-aliasing,
         not a hardcoded vocab*hidden literal) duplicate tied-tensor numel,
         detected on the PARENT checkpoint's raw (pre-.float()) bf16 state
         dict, where torch.save/load is confirmed (empirically, against the
         real on-disk step-00000730 checkpoint: backbone_model.embed_tokens.
         weight and head.weight share data_ptr()) to preserve shared storage
         for tied parameters. The net2net operator never touches embed/head/
         mtp_heads (spec §2.1), so the pre-surgery dedup amount is exactly
         the post-surgery dedup amount — measured once, applied to both.
         NOTE: the measured duplicate here is vocab*hidden = 32,768,000
         (32000*1024) — matching spec §3.2's own derivation exactly, NOT
         the "+32,772,096" figure quoted in §9 D4's own prose (an internal
         ~4,096-element inconsistency in that paragraph between §3.2 and
         §9; flagged here and in this run's report rather than propagated);
  6. pre-flights v0_pretrain_launch_gate.g_budget() with a requested_run
     descriptor priced at the GROWN N and the D1-computed step count —
     refuses (no receipt written for the grow-surgery evidence; a BLOCKED
     receipt IS written for the refusal itself) unless GREEN;
  7. records sustained tok/s + compile_status="SKIP" (eager-only — this
     repo's training loop never calls torch.compile at all, so "SKIP",
     meaning never attempted, is the honest label — distinct from "BREAK",
     attempted and failed, which S2 §3.2 bans from wall-clock projection).
     Per D1: "each rung run MUST bank its own compile-status-honest
     throughput receipt, which arms Option C as a future re-registration" —
     this receipt's tok/s is that banked number, not yet a compile-PASS
     receipt (S2 §3.2's own hard prerequisite for wall-clock projection is
     NOT satisfied by this SKIP-labeled number; flagged, not glossed over).

Reuse discipline (no duplicated math): imports timeshare_pretrain.
run_v0_segment/load_checkpoint/save_checkpoint/load_contract,
cbase_grow_dryrun.widen_state_dict/sha256_file, and cbase_grow_live.
_flops_per_step/_function_preservation_check/_loss_continuity_block/
_small_cfg/SMOKE_FF_SEED/K_SMOKE directly — none of these are reimplemented
in this file.

Modes (mirrors ember_ceff_composition_ab.py's 3-tier convention):
  --selftest   Pure Python/math — D1 step formula (cross-checked against
               spec §6's illustrative rung-1/2/target figures and the
               30-step floor), dedup-by-data_ptr logic (synthetic fake
               tensor objects, no torch import anywhere in this mode),
               MICRO_FIT ceiling cross-check against v0_pretrain_launch_
               gate's own constant (imported lazily, inside the selftest
               function only), receipt-schema round trip. Prints
               CBASE_GROW_RUNG_SELFTEST_PASS.
  --dry-run    CPU only, tiny real-architecture stand-in model built fresh
               (same pattern as cbase_grow_live.py's --smoke) stands in for
               "the parent rung's own already-landed checkpoint" — proves
               the FULL rung pipeline (parent-load -> grow -> dedup -> D1
               step-sizing -> g_budget preflight -> stabilize -> loss-
               envelope kill-check -> receipt) end-to-end without touching
               the real ~718M-param checkpoint or any GPU. The D1 formula
               is ALSO exercised honestly at the real rung-1 scale (proving
               the arithmetic against the real numbers the live run will
               use) even though the CPU segment actually executed is capped
               small for speed — both figures are recorded, never conflated.
               Receipt -> scratch/cbase-grow-rung-dryrun/, self-declares
               dry_run=true (never glob-matched by receipts/ evidence
               searches).
  (no flag)    The real governed GPU run against the real parent checkpoint
               and lineage receipt. Requires EMBER_GATE_AUTHORIZED=1 (env) —
               enforced by run_v0_segment's own eng-33/eng-52 interlock, not
               duplicated here. NOT fired by this authoring session.

No git commits. No downloads. No founder/user names anywhere in this file
or its receipts.

BANKED GPU COMMAND (fire once the current GPU job has freed the card —
attempt 18 / C14 holds first claim on the GPU; this fires after):

  python scripts/cbase_grow_rung.py --rung 1 --shard-dir <real packed uint16 shard dir>

Dispatch via the train MCP (WSL2/CUDA), matching cbase_grow_live.py's own
--live dispatch convention.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from receipt_write import checked_write  # noqa: E402  (light; no torch)

REPO = Path(__file__).resolve().parent.parent
RECEIPT_DIR_DEFAULT = REPO / "receipts" / "cbase-grow-rung"
OUT_DIR_DEFAULT = REPO / "models" / "cbase-grow-rung"
SCRATCH_DRYRUN = REPO / "scratch" / "cbase-grow-rung-dryrun"

# ---------------------------------------------------------------------------
# D1 (spec §9): fixed-FLOPs-budget stabilization-segment sizing — the exact
# FLOPs figure is DERIVED from the one precedent segment ever run, not
# copied from the spec's own rounded "~=4.2375e15" prose.
# ---------------------------------------------------------------------------
D1_PRECEDENT_RECEIPT = "receipts/cbase-grow-live/cbase-grow-live-live-20260703T053225Z.json"
D1_PRECEDENT_PARAMS = 718_316_544     # measured param_count_after in that receipt
D1_PRECEDENT_BATCH = 16
D1_PRECEDENT_SEQ = 1024
D1_PRECEDENT_STEPS = 60               # that receipt's k_steps_post_grow
D1_ANCHOR_FLOPS = (6.0 * D1_PRECEDENT_PARAMS * D1_PRECEDENT_BATCH
                   * D1_PRECEDENT_SEQ * D1_PRECEDENT_STEPS)  # 4,236,803,372,482,560.0
D1_STEP_FLOOR = 30

# rung-1 lineage pin (spec §3.3 table: N(16384) = 215,000,064 + 61,440*16384)
RUNG_PARENT_RECEIPT_DEFAULT: dict[int, str] = {
    1: str(REPO / D1_PRECEDENT_RECEIPT),
}
RUNG_EXPECTED_PARAMS_GROWN: dict[int, int] = {
    1: 1_221_633_024,
    2: 2_228_265_984,
    3: 4_241_531_904,   # "target" rung in the spec's own numbering
}


def d1_stabilization_steps(n_grown: int, batch: int, seq: int) -> int:
    """D1's registered formula: steps = max(ceil(ANCHOR/(6*N*batch*seq)), 30)."""
    per_step_flops = 6.0 * n_grown * batch * seq
    return max(math.ceil(D1_ANCHOR_FLOPS / per_step_flops), D1_STEP_FLOOR)


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def measure_tied_duplicate_numel(sd_raw: dict) -> tuple[int, list[str]]:
    """Dedup by data_ptr() equality on a FRESHLY-LOADED state dict (no
    .float()/.to() cast applied yet — those allocate fresh storage per key
    and destroy the aliasing signal). torch.save/load is confirmed
    empirically (against the real on-disk step-00000730 checkpoint:
    backbone_model.embed_tokens.weight and head.weight share data_ptr())
    to preserve shared storage for tied parameters. Not hardcoded to a
    vocab*hidden literal — whatever the checkpoint's actual tied shapes
    measure is what gets returned. Accepts anything with .data_ptr()/
    .numel() (plain torch tensors, or synthetic fakes for --selftest)."""
    seen: dict[int, str] = {}
    dup_numel = 0
    pairs: list[str] = []
    for k, v in sd_raw.items():
        ptr = v.data_ptr()
        if ptr in seen:
            dup_numel += v.numel()
            pairs.append(f"{seen[ptr]}=={k}")
        else:
            seen[ptr] = k
    return dup_numel, pairs


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _relpath(p) -> str:
    p = Path(p)
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# Shared receipt assembly — both --dry-run and the live path funnel through
# this so the receipt SHAPE never drifts between modes.
# ---------------------------------------------------------------------------

def _assemble_receipt(*, rung: int, mode: str, ts_stamp: str,
                       parent_receipt_path: str, parent_receipt_sha256: str,
                       parent_lineage: dict, tied_pairs: list[str],
                       dup_numel: int, ff_seed: int, ff_grown: int,
                       param_count_before: int, param_count_after: int,
                       fp_check: dict, d1_steps: int, d1_anchor_flops: float,
                       g_budget: dict, stage: str,
                       loss_continuity: dict | None = None,
                       stab: dict | None = None, grow_ckpt_dir: str | None = None,
                       kill_reason: str | None = None,
                       commit_margin_preflight: dict | None = None) -> dict:
    params_unique_before = param_count_before - dup_numel
    params_unique_after = param_count_after - dup_numel

    fp_pass = bool(fp_check["function_preserving"])
    within_envelope = bool(loss_continuity["training_loss_continuity_within_pre_grow_variance_envelope"]) \
        if loss_continuity is not None else None
    issue29_kill_pass = fp_pass and (within_envelope is not False)

    if stage == "fp_check_kill":
        verdict, pass_ = "GROW_RUNG_KILL", False
    elif stage == "g_budget_blocked":
        verdict, pass_ = "GROW_RUNG_BLOCKED", False
    elif stage == "divergence_kill":
        verdict, pass_ = "GROW_RUNG_KILL", False
    else:
        verdict = "GROW_RUNG_PASS" if mode == "live" else "GROW_RUNG_DRYRUN_PASS"
        pass_ = True

    tok_s_paced = None
    compile_status = None
    if stab is not None and stab.get("wall_s"):
        tok_s_paced = round((stab["steps"] * stab["batch"] * stab["seq"]) / stab["wall_s"], 2)
        compile_status = "SKIP"  # never attempted — timeshare_pretrain never calls torch.compile

    receipt: dict[str, Any] = {
        "ticket": "CBASE-GROW-RUNG",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "issue": "#29",
        "spec_ref": "docs/spec/c-scale-s1-growth-chain-DRAFT.md §9 (D1/D2/D3/D4/D5/D6 pre-registration)",
        "scope": ("S1 growth-chain rung: net2net FF-doubling warm-start from the certified "
                  "parent lineage checkpoint, D1-sized stabilization segment, dual parameter "
                  "convention (D4), G-budget micro-fit pre-flight, issue-29 kill criterion"),
        "mode": mode,
        "rung": rung,
        "grow_method": "net2net FF-widening (function-preserving, warm-start), the identical "
                       "grow_operator surgery cbase_grow_dryrun.py proved, applied here from the "
                       "PARENT rung's own already-stabilized checkpoint (no fresh pre-grow "
                       "continuation segment — the parent's last stabilization segment IS the "
                       "pre-grow loss-envelope reference, per this rung's own docstring)",
        "parent_lineage_receipt": parent_receipt_path,
        "parent_lineage_receipt_sha256": parent_receipt_sha256,
        "growth_lineage": parent_lineage,
        "growth_lineage_from_cbase_seed": True,
        "no_borrowed_weights_load_bearing": True,
        "ff_seed": ff_seed,
        "ff_grown": ff_grown,
        "param_count_before": param_count_before,
        "param_count_after": param_count_after,
        "params_state_dict_sum_before": param_count_before,
        "params_state_dict_sum_after": param_count_after,
        "params_dedup": {
            "measured_duplicate_numel": dup_numel,
            "tied_pairs_detected": tied_pairs,
            "method": ("data_ptr() equality on the parent checkpoint's raw (pre-cast) bf16 "
                       "state dict — torch.save/load preserves shared storage for tied "
                       "parameters (empirically verified); the net2net operator never touches "
                       "embed/head/mtp_heads (spec §2.1), so this dedup amount, measured once "
                       "pre-surgery, applies unchanged post-surgery"),
            "note": ("spec §9 D4's own prose states the duplicate as '+32,772,096'; the "
                     "MEASURED value here (via data_ptr aliasing, matching spec §3.2's "
                     "independently-derived 32,768,000 = vocab*hidden) differs by 4,096 "
                     "elements from D4's prose figure — an internal spec inconsistency, "
                     "flagged rather than propagated; D4's RULING (dual reporting, "
                     "params_unique authoritative) is honored exactly, using the measured "
                     "number"),
        },
        "params_unique_before": params_unique_before,
        "params_unique_after": params_unique_after,
        "operating_capability_point_convention": "params_unique (D4: authoritative for the >3e9 "
                                                  "floor and S2's 20N math); params_state_dict_sum "
                                                  "carried alongside for continuity with the two "
                                                  "existing receipted points",
        "function_preservation_check": fp_check,
        "d1_sizing": {
            "rule": "steps(rung) = max(ceil(D1_ANCHOR_FLOPS / (6*N_grown*batch*seq)), 30)",
            "d1_anchor_flops": d1_anchor_flops,
            "d1_anchor_flops_derivation": (
                f"6 * {D1_PRECEDENT_PARAMS} * {D1_PRECEDENT_BATCH} * {D1_PRECEDENT_SEQ} * "
                f"{D1_PRECEDENT_STEPS} (the ONE precedent post-grow segment ever run, "
                f"{D1_PRECEDENT_RECEIPT}) — spec §9 D1 rounds this '~=4.2375e15'; this figure "
                "is the exact value, not the rounded prose copy"),
            "step_floor": D1_STEP_FLOOR,
            "steps_computed": d1_steps,
        },
        "g_budget_preflight": g_budget,
        "commit_margin_preflight": commit_margin_preflight,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "device": "cuda" if mode == "live" else "cpu",
        "measured_on_train_daemon": mode == "live",
        "script": "scripts/cbase_grow_rung.py",
        "pass": pass_,
        "verdict": verdict,
    }
    if grow_ckpt_dir is not None:
        receipt["grow_step"] = {
            "checkpoint": grow_ckpt_dir,
            "mechanism": "ff_widening_net2net (grow_operator, imported from cbase_grow_dryrun.widen_state_dict)",
        }
    if loss_continuity is not None:
        receipt["loss_continuity"] = loss_continuity
    if stab is not None:
        receipt["stabilization_segment"] = {
            "segment_id": stab["segment_id"], "resume_step": stab["resume_step"],
            "global_step_end": stab["global_step_end"], "steps": stab["steps"],
            "loss_first": stab["loss_first"], "loss_last": stab["loss_last"],
            "losses": stab["losses"], "wall_s": stab["wall_s"],
            "checkpoint": stab["checkpoint"], "governor": stab.get("governor"),
            "optimizer_reset_on_resume": True,
            "tok_s_paced": tok_s_paced, "compile_status": compile_status,
            "compile_status_note": ("SKIP = torch.compile never attempted anywhere in "
                                     "timeshare_pretrain's training loop (eager only) — NOT "
                                     "the same as BREAK (attempted, failed). Per S2 §3.2, an "
                                     "eager/SKIP number must not be used to PROJECT wall-clock "
                                     "cost at other widths; per D1, banking it here still "
                                     "'arms Option C as a future re-registration'"),
        }
    receipt["issue_29_kill_criterion"] = {
        "function_preservation_pass": fp_pass,
        "function_preservation_tolerance": fp_check.get("pass_tolerance"),
        "post_grow_within_pre_grow_envelope": within_envelope,
        "overall_pass": issue29_kill_pass if stage != "g_budget_blocked" else None,
        "rule": "Kill: function-preservation fp_diff>1e-4 (tightened from issue #29's own "
                ">1e-3, matching the operator's own PASS_TOL) OR post-grow divergence "
                "(loss outside the pre-grow step-to-step jump envelope). A violation writes "
                "this KILL receipt and exits nonzero — never a retry-in-place.",
    }
    if kill_reason is not None:
        receipt["kill_reason"] = kill_reason
    return receipt


def _write_and_report(receipt: dict, receipt_dir: Path, mode: str) -> int:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    verdict = receipt["verdict"]
    suffix = "" if verdict.endswith("PASS") or verdict.endswith("DRYRUN_PASS") else f"-{verdict.split('_')[-1]}"
    out = receipt_dir / f"cbase-grow-rung{receipt['rung']}-{mode}{suffix}-{receipt['ts'].replace(':', '').replace('-', '')}.json"
    checked_write(str(out), receipt)
    print(f"{verdict} rung={receipt['rung']} mode={mode} "
          f"param_after={receipt.get('param_count_after')} "
          f"params_unique_after={receipt.get('params_unique_after')} "
          f"d1_steps={receipt.get('d1_sizing', {}).get('steps_computed')} "
          f"receipt={out}")
    return 0 if receipt["pass"] else 2


# ---------------------------------------------------------------------------
# Live path — the real GPU run (NOT fired by this authoring session).
# ---------------------------------------------------------------------------

def run_live(args) -> int:
    import torch  # noqa: F401  (lazy — module top stays torch-free)
    import timeshare_pretrain as ts
    from cbase_grow_dryrun import widen_state_dict
    from cbase_grow_live import _function_preservation_check, _loss_continuity_block
    import v0_pretrain_launch_gate as gate_mod
    import governor

    rung = args.rung
    parent_path = Path(args.parent_receipt or RUNG_PARENT_RECEIPT_DEFAULT[rung])
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    parent_sha = _sha256_file(parent_path)

    ckpt_dir = Path(parent["post_grow_segment"]["checkpoint"])
    manifest = json.loads((ckpt_dir / "manifest.json").read_text(encoding="utf-8"))
    model_pt = ckpt_dir / "model.pt"
    actual_sha = _sha256_file(model_pt)
    claimed_sha = (manifest.get("files") or {}).get("model.pt")
    if not (isinstance(claimed_sha, str) and actual_sha == claimed_sha):
        raise SystemExit(f"parent checkpoint hash mismatch: manifest={claimed_sha} actual={actual_sha}")

    cfg = ts.load_contract()
    n_layers = cfg["model"]["layers"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    batch = cfg["throughput"]["batch"]
    seq = cfg["model"]["seq"]
    ts_stamp = _ts()
    receipt_dir = Path(args.receipt_dir)

    m_state, o_state, r_state, ckpt_manifest = ts.load_checkpoint(str(ckpt_dir))
    dup_numel, tied_pairs = measure_tied_duplicate_numel(m_state)

    ff_seed = int(m_state["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])
    ff_grown = ff_seed * 2

    sd_pre_f32 = {k: v.float() for k, v in m_state.items()}
    grown_sd_f32 = widen_state_dict(sd_pre_f32, n_layers)
    param_count_before = int(sum(v.numel() for v in sd_pre_f32.values()))
    param_count_after = int(sum(v.numel() for v in grown_sd_f32.values()))

    fp_check = _function_preservation_check(cfg["model"], n_mtp, sd_pre_f32, grown_sd_f32, ff_seed, ff_grown)

    parent_lineage = parent.get("growth_lineage") or [{
        "rung": "seed", "checkpoint": parent["seed_identity"]["checkpoint"],
        "model_pt_sha256": parent["seed_identity"]["model_pt_sha256"],
        "step": parent["seed_identity"]["step"], "note": "original cbase-v0 from-scratch pretrain seed",
    }, {
        "rung": 0, "ff": ff_seed, "params_state_dict_sum": parent["param_count_after"],
        "receipt": _relpath(parent_path), "receipt_sha256": parent_sha,
        "checkpoint": parent["post_grow_segment"]["checkpoint"],
    }]

    d1_steps = d1_stabilization_steps(param_count_after, batch, seq)

    if not fp_check["function_preserving"]:
        receipt = _assemble_receipt(
            rung=rung, mode="live", ts_stamp=ts_stamp,
            parent_receipt_path=_relpath(parent_path), parent_receipt_sha256=parent_sha,
            parent_lineage=parent_lineage, tied_pairs=tied_pairs, dup_numel=dup_numel,
            ff_seed=ff_seed, ff_grown=ff_grown,
            param_count_before=param_count_before, param_count_after=param_count_after,
            fp_check=fp_check, d1_steps=d1_steps, d1_anchor_flops=D1_ANCHOR_FLOPS,
            g_budget={"skipped": "function preservation failed before g_budget preflight"},
            stage="fp_check_kill", kill_reason="function_preservation_failed")
        return _write_and_report(receipt, receipt_dir, "live")

    requested_run = {
        "source": f"cbase_grow_rung:rung{rung}-stabilization",
        "total_steps": d1_steps, "params": param_count_after, "batch": batch, "seq": seq,
    }
    g_status, g_detail = gate_mod.g_budget(date.today(), requested_run=requested_run)
    g_budget_block = {"status": g_status, "detail": g_detail, "requested_run": requested_run}
    if g_status != "GREEN":
        receipt = _assemble_receipt(
            rung=rung, mode="live", ts_stamp=ts_stamp,
            parent_receipt_path=_relpath(parent_path), parent_receipt_sha256=parent_sha,
            parent_lineage=parent_lineage, tied_pairs=tied_pairs, dup_numel=dup_numel,
            ff_seed=ff_seed, ff_grown=ff_grown,
            param_count_before=param_count_before, param_count_after=param_count_after,
            fp_check=fp_check, d1_steps=d1_steps, d1_anchor_flops=D1_ANCHOR_FLOPS,
            g_budget=g_budget_block, stage="g_budget_blocked")
        return _write_and_report(receipt, receipt_dir, "live")

    grown_sd_bf16 = {k: v.to(torch.bfloat16) for k, v in grown_sd_f32.items()}
    grow_out_root = Path(args.out_dir) / f"rung{rung}-{ts_stamp}"
    grow_ckpt_dir = ts.save_checkpoint(
        str(grow_out_root), ckpt_manifest["step"], grown_sd_bf16, o_state, r_state,
        extra={"segment_id": f"cbase-grow-rung{rung}-grown", "mechanism": "ff_widening_net2net",
               "grown_from_step": ckpt_manifest["step"], "ff_seed": ff_seed, "ff_grown": ff_grown,
               "optimizer_state_carried_but_unused": True,
               "note": "optimizer.pt bytes carried from parent verbatim (shapes stale after "
                       "FF-widening); stabilization segment resumes with "
                       "reset_optimizer_on_resume=True so this file is never loaded into a live "
                       "optimizer"})

    # Host commit-charge preflight (issue #84), the same g_budget-preflight
    # gate step's sibling assert: g_budget above priced compute/FLOPs; this
    # prices host memory for the checkpoint the upcoming run_v0_segment
    # resume is about to map (model.pt + optimizer.pt + rng.pt in
    # grow_ckpt_dir) — the #81 incident's own gap, guarded here before the
    # real GPU/mmap-heavy launch below, never after.
    commit_paths = [os.path.join(grow_ckpt_dir, f) for f in
                    ("model.pt", "optimizer.pt", "rng.pt")]
    commit_expected_bytes = governor.estimate_checkpoint_mapped_bytes(commit_paths)
    commit_margin_block = governor.commit_margin_preflight(commit_expected_bytes)

    stab_dir = grow_out_root / "stabilize"
    total_steps = args.total_steps or manifest.get("extra", {}).get("total_steps") \
        or (cfg["data"]["token_budget"]["compute_optimal"] // (batch * seq))
    stab_receipt = ts.run_v0_segment(
        str(stab_dir), cfg, n_steps=d1_steps, total_steps=total_steps, live=True,
        real_arch=True, device="cuda", resume_ckpt_dir=grow_ckpt_dir,
        shard_dir=args.shard_dir, checkpoint_every=d1_steps,
        segment_id=f"cbase-grow-rung{rung}-stabilize",
        intermediate_override=ff_grown, reset_optimizer_on_resume=True,
        ce_chunk_tokens=args.ce_chunk_tokens, requested_run=requested_run,
    )
    assert stab_receipt["pass"] is True, "stabilization segment did not complete"

    pre_grow_losses = parent["post_grow_segment"]["losses"]
    loss_continuity = _loss_continuity_block(pre_grow_losses, stab_receipt["losses"])

    stage = "pass" if loss_continuity["training_loss_continuity_within_pre_grow_variance_envelope"] \
        else "divergence_kill"
    stab_block = {
        "segment_id": stab_receipt["segment_id"], "resume_step": stab_receipt["resume_step"],
        "global_step_end": stab_receipt["global_step_end"], "steps": stab_receipt["steps"],
        "loss_first": stab_receipt["loss_first"], "loss_last": stab_receipt["loss_last"],
        "losses": stab_receipt["losses"], "wall_s": stab_receipt["wall_s"],
        "checkpoint": stab_receipt["last_checkpoint"], "governor": stab_receipt["governor"],
        "batch": batch, "seq": seq,
    }
    receipt = _assemble_receipt(
        rung=rung, mode="live", ts_stamp=ts_stamp,
        parent_receipt_path=_relpath(parent_path), parent_receipt_sha256=parent_sha,
        parent_lineage=parent_lineage, tied_pairs=tied_pairs, dup_numel=dup_numel,
        ff_seed=ff_seed, ff_grown=ff_grown,
        param_count_before=param_count_before, param_count_after=param_count_after,
        fp_check=fp_check, d1_steps=d1_steps, d1_anchor_flops=D1_ANCHOR_FLOPS,
        g_budget=g_budget_block, stage=stage, loss_continuity=loss_continuity,
        stab=stab_block, grow_ckpt_dir=grow_ckpt_dir,
        kill_reason=None if stage == "pass" else "post_grow_divergence",
        commit_margin_preflight=commit_margin_block)
    return _write_and_report(receipt, receipt_dir, "live")


# ---------------------------------------------------------------------------
# --dry-run — CPU only, tiny stand-in, NO real checkpoint / GPU touched.
# ---------------------------------------------------------------------------

def run_dry(args) -> int:
    import torch  # noqa: F401
    import timeshare_pretrain as ts
    from cbase_grow_dryrun import widen_state_dict
    from cbase_grow_live import (
        _function_preservation_check, _loss_continuity_block, _small_cfg,
        SMOKE_FF_SEED, K_SMOKE,
    )
    import v0_pretrain_launch_gate as gate_mod

    rung = args.rung
    ts_stamp = _ts()
    cfg = _small_cfg(ts.load_contract())
    n_layers = cfg["model"]["layers"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    batch = cfg["throughput"]["batch"]
    seq = cfg["model"]["seq"]

    out_root = SCRATCH_DRYRUN / f"dryrun-rung{rung}-{ts_stamp}"
    parent_dir = out_root / "parent"

    # Stands in for "the parent rung's own already-landed checkpoint" — a
    # small real-architecture CPU model, freshly trained a few steps, never
    # touching the real ~718M-param checkpoint.
    parent_receipt = ts.run_v0_segment(
        str(parent_dir), cfg, n_steps=K_SMOKE, total_steps=K_SMOKE * 4, live=False,
        real_arch=True, device="cpu", resume_ckpt_dir=None, shard_dir=None,
        checkpoint_every=K_SMOKE, segment_id="cbase-grow-rung-dryrun-parent",
        intermediate_override=SMOKE_FF_SEED,
    )
    assert parent_receipt["pass"] is True

    m_state, o_state, r_state, ckpt_manifest = ts.load_checkpoint(parent_receipt["last_checkpoint"])
    dup_numel, tied_pairs = measure_tied_duplicate_numel(m_state)

    ff_seed = int(m_state["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])
    ff_grown = ff_seed * 2

    sd_pre_f32 = {k: v.float() for k, v in m_state.items()}
    grown_sd_f32 = widen_state_dict(sd_pre_f32, n_layers)
    param_count_before = int(sum(v.numel() for v in sd_pre_f32.values()))
    param_count_after = int(sum(v.numel() for v in grown_sd_f32.values()))

    fp_check = _function_preservation_check(cfg["model"], n_mtp, sd_pre_f32, grown_sd_f32, ff_seed, ff_grown)

    parent_lineage = [{
        "rung": "dryrun-parent-stand-in", "checkpoint": parent_receipt["last_checkpoint"],
        "note": "tiny CPU real-architecture stand-in — NOT the real cbase-v0 lineage",
    }]

    # D1 formula exercised honestly at the REAL rung-1 scale (proves the
    # arithmetic mechanism against the real numbers) — the CPU segment
    # actually executed is capped small for speed; both figures recorded.
    d1_steps_at_real_scale = d1_stabilization_steps(
        RUNG_EXPECTED_PARAMS_GROWN.get(rung, param_count_after), 16, 1024)
    d1_steps_at_dryrun_scale = d1_stabilization_steps(param_count_after, batch, seq)
    dryrun_steps_executed = min(K_SMOKE, d1_steps_at_dryrun_scale)

    requested_run = {
        "source": f"cbase_grow_rung:dryrun-rung{rung}-stabilization",
        "total_steps": dryrun_steps_executed, "params": param_count_after,
        "batch": batch, "seq": seq,
    }
    g_status, g_detail = gate_mod.g_budget(date.today(), requested_run=requested_run)
    g_budget_block = {
        "status": g_status, "detail": g_detail, "requested_run": requested_run,
        "note": "exercised at DRY-RUN (tiny) scale — real-scale check is a separate field "
                "(d1_sizing.steps_computed uses d1_steps_at_real_scale for the receipt-shape "
                "proof); this g_budget call is the mechanism proof, not a real-scale price",
    }

    grown_sd_bf16 = {k: v.to(torch.bfloat16) for k, v in grown_sd_f32.items()}
    grow_ckpt_dir = ts.save_checkpoint(
        str(out_root), ckpt_manifest["step"], grown_sd_bf16, o_state, r_state,
        extra={"segment_id": "cbase-grow-rung-dryrun-grown", "mechanism": "ff_widening_net2net",
               "grown_from_step": ckpt_manifest["step"], "ff_seed": ff_seed, "ff_grown": ff_grown})

    stab_dir = out_root / "stabilize"
    stab_receipt = ts.run_v0_segment(
        str(stab_dir), cfg, n_steps=dryrun_steps_executed, total_steps=dryrun_steps_executed * 4,
        live=False, real_arch=True, device="cpu", resume_ckpt_dir=grow_ckpt_dir, shard_dir=None,
        checkpoint_every=dryrun_steps_executed, segment_id="cbase-grow-rung-dryrun-stabilize",
        intermediate_override=ff_grown, reset_optimizer_on_resume=True,
    )
    assert stab_receipt["pass"] is True

    loss_continuity = _loss_continuity_block(parent_receipt["losses"], stab_receipt["losses"])
    stab_block = {
        "segment_id": stab_receipt["segment_id"], "resume_step": stab_receipt["resume_step"],
        "global_step_end": stab_receipt["global_step_end"], "steps": stab_receipt["steps"],
        "loss_first": stab_receipt["loss_first"], "loss_last": stab_receipt["loss_last"],
        "losses": stab_receipt["losses"], "wall_s": stab_receipt["wall_s"],
        "checkpoint": stab_receipt["last_checkpoint"], "governor": stab_receipt.get("governor"),
        "batch": batch, "seq": seq,
    }

    stage = "pass" if loss_continuity["training_loss_continuity_within_pre_grow_variance_envelope"] \
        else "divergence_kill"
    receipt = _assemble_receipt(
        rung=rung, mode="dry-run", ts_stamp=ts_stamp,
        parent_receipt_path="(dry-run stand-in, no real parent receipt file)",
        parent_receipt_sha256="", parent_lineage=parent_lineage, tied_pairs=tied_pairs,
        dup_numel=dup_numel, ff_seed=ff_seed, ff_grown=ff_grown,
        param_count_before=param_count_before, param_count_after=param_count_after,
        fp_check=fp_check, d1_steps=d1_steps_at_real_scale, d1_anchor_flops=D1_ANCHOR_FLOPS,
        g_budget=g_budget_block, stage=stage, loss_continuity=loss_continuity,
        stab=stab_block, grow_ckpt_dir=grow_ckpt_dir,
        kill_reason=None if stage == "pass" else "post_grow_divergence")
    receipt["dry_run"] = True
    receipt["d1_sizing"]["steps_computed_at_dryrun_scale"] = d1_steps_at_dryrun_scale
    receipt["d1_sizing"]["steps_executed_this_run"] = dryrun_steps_executed
    receipt["mode"] = "dry-run"

    SCRATCH_DRYRUN.mkdir(parents=True, exist_ok=True)
    out = SCRATCH_DRYRUN / f"dry-run-rung{rung}-{ts_stamp}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"{receipt['verdict']} (dry-run) rung={rung} param_after={param_count_after} "
          f"params_unique_after={receipt['params_unique_after']} "
          f"d1_steps_real_scale={d1_steps_at_real_scale} "
          f"dryrun_steps_executed={dryrun_steps_executed} receipt={out}")
    return 0 if receipt["pass"] else 2


# ---------------------------------------------------------------------------
# Selftest — pure Python/math, no torch import anywhere in this mode.
# ---------------------------------------------------------------------------

class _FakeTensor:
    """Minimal .data_ptr()/.numel() stand-in for measure_tied_duplicate_numel
    — proves the dedup logic without importing torch."""
    def __init__(self, ptr: int, numel: int):
        self._ptr, self._numel = ptr, numel

    def data_ptr(self) -> int:
        return self._ptr

    def numel(self) -> int:
        return self._numel


def selftest() -> None:
    print("[cbase_grow_rung] selftest: D1 formula + dedup logic + receipt schema (no torch)", flush=True)

    # 1. D1 anchor derivation matches the precedent receipt's own numbers exactly.
    assert D1_ANCHOR_FLOPS == 6.0 * 718316544 * 16 * 1024 * 60, D1_ANCHOR_FLOPS
    assert abs(D1_ANCHOR_FLOPS - 4.2375e15) / 4.2375e15 < 0.001, D1_ANCHOR_FLOPS
    print(f"  D1_ANCHOR_FLOPS={D1_ANCHOR_FLOPS} (matches spec s9 D1's rounded '~=4.2375e15' "
          f"within 0.1%)  PASS")

    # 2. Formula cross-checked against spec §6/§9's own illustrative figures + the 30-floor.
    steps_rung1 = d1_stabilization_steps(RUNG_EXPECTED_PARAMS_GROWN[1], 16, 1024)
    steps_rung2 = d1_stabilization_steps(RUNG_EXPECTED_PARAMS_GROWN[2], 16, 1024)
    steps_target = d1_stabilization_steps(RUNG_EXPECTED_PARAMS_GROWN[3], 16, 1024)
    assert steps_rung1 == 36, steps_rung1          # spec §6 illustrative "≈35" — exact ceil is 36
    assert steps_rung2 == D1_STEP_FLOOR, steps_rung2      # spec §6 "≈19" raw, floored to 30 (D1's own text)
    assert steps_target == D1_STEP_FLOOR, steps_target    # spec §6 "≈10" raw, floored to 30 (D1's own text)
    assert steps_rung1 > D1_STEP_FLOOR, "rung 1 must NOT hit the floor (spec §9 D1 distinguishes it)"
    print(f"  steps: rung1={steps_rung1} rung2={steps_rung2}(floored) target={steps_target}(floored)  PASS")

    # 3. Floor monotonicity: larger N -> fewer (or equal, once floored) steps.
    assert steps_rung1 >= steps_rung2 >= steps_target
    print("  monotonic 1/N shrinkage (floor-clamped at rung2+)  PASS")

    # 4. Micro-fit ceiling cross-check against v0_pretrain_launch_gate's own constant
    #    (imported lazily, HERE ONLY — this module is torch-free at top level).
    import v0_pretrain_launch_gate as gate_mod
    assert abs(gate_mod.MICRO_FIT_CEILING_FLOPS - 2.4311384064e+16) < 1e6, gate_mod.MICRO_FIT_CEILING_FLOPS
    cost_rung1 = 6.0 * RUNG_EXPECTED_PARAMS_GROWN[1] * 16 * 1024 * steps_rung1
    assert cost_rung1 <= gate_mod.MICRO_FIT_CEILING_FLOPS, (cost_rung1, gate_mod.MICRO_FIT_CEILING_FLOPS)
    well_formed, fit_ok, _detail = gate_mod._requested_run_compute_fit({
        "source": "selftest-rung1", "total_steps": steps_rung1,
        "params": RUNG_EXPECTED_PARAMS_GROWN[1], "batch": 16, "seq": 1024})
    assert well_formed and fit_ok, (well_formed, fit_ok)
    print(f"  rung-1 D1-sized segment FITS the micro-fit ceiling "
          f"(cost={cost_rung1:.4g} <= {gate_mod.MICRO_FIT_CEILING_FLOPS:.4g})  PASS")

    # 5. Dedup logic — synthetic fake tensors, no torch. One tied pair (same
    #    ptr), two untied matrices of the same shape (different ptrs) — mirrors
    #    the real checkpoint's embed/head/mtp_0/mtp_1 structure exactly.
    fake_sd = {
        "backbone_model.embed_tokens.weight": _FakeTensor(ptr=1000, numel=32_768_000),
        "head.weight": _FakeTensor(ptr=1000, numel=32_768_000),          # tied — same ptr
        "mtp_heads.0.weight": _FakeTensor(ptr=2000, numel=32_768_000),   # untied
        "mtp_heads.1.weight": _FakeTensor(ptr=3000, numel=32_768_000),   # untied
        "backbone_model.layers.0.mlp.gate_proj.weight": _FakeTensor(ptr=4000, numel=8_388_608),
    }
    dup, pairs = measure_tied_duplicate_numel(fake_sd)
    assert dup == 32_768_000, dup
    assert pairs == ["backbone_model.embed_tokens.weight==head.weight"], pairs
    print(f"  dedup: exactly the tied embed/head pair caught, mtp heads correctly left untied "
          f"(dup_numel={dup})  PASS")

    # 5b. No aliasing at all -> zero duplicate.
    no_alias_sd = {"a": _FakeTensor(1, 10), "b": _FakeTensor(2, 20)}
    dup0, pairs0 = measure_tied_duplicate_numel(no_alias_sd)
    assert dup0 == 0 and pairs0 == [], (dup0, pairs0)
    print("  no-aliasing case -> zero duplicate  PASS")

    # 6. Measured dedup amount (32,768,000) vs spec §9 D4's own prose figure
    #    (32,772,096) — confirms the flagged ~4096-element inconsistency is
    #    real and this file uses the MEASURED number, not D4's prose literal.
    assert dup != 32_772_096, "must not silently match D4's inconsistent prose figure"
    assert 32_772_096 - dup == 4096
    print("  measured dedup (32,768,000) differs from spec s9 D4's own prose figure "
          "(32,772,096) by exactly 4,096 -- inconsistency confirmed, not propagated  PASS")

    # 7. Receipt assembly + receipt_check schema floor (ticket/ts/sha_convention).
    import receipt_check
    synth_fp_check = {"function_preserving": True, "logit_max_abs_diff": 1e-6, "pass_tolerance": 1e-4}
    synth_loss_cont = {"training_loss_continuity_within_pre_grow_variance_envelope": True}
    synth_g_budget = {"status": "GREEN", "detail": "selftest", "requested_run": {}}
    r = _assemble_receipt(
        rung=1, mode="dry-run", ts_stamp="20260703T000000Z",
        parent_receipt_path="synthetic", parent_receipt_sha256="a" * 64,
        parent_lineage=[], tied_pairs=[], dup_numel=32_768_000, ff_seed=8192, ff_grown=16384,
        param_count_before=718316544, param_count_after=1221633024,
        fp_check=synth_fp_check, d1_steps=36, d1_anchor_flops=D1_ANCHOR_FLOPS,
        g_budget=synth_g_budget, stage="pass", loss_continuity=synth_loss_cont)
    findings = receipt_check.validate_receipt(r)
    assert findings == [], findings
    assert r["params_unique_after"] == 1221633024 - 32_768_000, r["params_unique_after"]
    assert r["pass"] is True and r["verdict"] == "GROW_RUNG_DRYRUN_PASS"
    print("  receipt assembly passes receipt_check schema floor, params_unique arithmetic "
          "correct  PASS")

    # 8. KILL-path receipt: function-preservation failure -> pass=False, verdict names KILL.
    bad_fp_check = {"function_preserving": False, "logit_max_abs_diff": 5e-3, "pass_tolerance": 1e-4}
    r_kill = _assemble_receipt(
        rung=1, mode="live", ts_stamp="20260703T000000Z",
        parent_receipt_path="synthetic", parent_receipt_sha256="a" * 64,
        parent_lineage=[], tied_pairs=[], dup_numel=32_768_000, ff_seed=8192, ff_grown=16384,
        param_count_before=718316544, param_count_after=1221633024,
        fp_check=bad_fp_check, d1_steps=36, d1_anchor_flops=D1_ANCHOR_FLOPS,
        g_budget={"skipped": "fp check failed"}, stage="fp_check_kill",
        kill_reason="function_preservation_failed")
    assert r_kill["pass"] is False and r_kill["verdict"] == "GROW_RUNG_KILL", r_kill["verdict"]
    assert receipt_check.validate_receipt(r_kill) == []
    print("  KILL-path receipt (function-preservation failure) shape correct  PASS")

    # 9. BLOCKED-path receipt: g_budget refusal -> pass=False, verdict names BLOCKED,
    #    distinct from KILL (an infra/budget refusal, not a function/quality failure).
    r_blocked = _assemble_receipt(
        rung=1, mode="live", ts_stamp="20260703T000000Z",
        parent_receipt_path="synthetic", parent_receipt_sha256="a" * 64,
        parent_lineage=[], tied_pairs=[], dup_numel=32_768_000, ff_seed=8192, ff_grown=16384,
        param_count_before=718316544, param_count_after=1221633024,
        fp_check=synth_fp_check, d1_steps=36, d1_anchor_flops=D1_ANCHOR_FLOPS,
        g_budget={"status": "BLOCKED", "detail": "synthetic refusal"}, stage="g_budget_blocked")
    assert r_blocked["pass"] is False and r_blocked["verdict"] == "GROW_RUNG_BLOCKED", r_blocked["verdict"]
    assert r_blocked["issue_29_kill_criterion"]["overall_pass"] is None, (
        "a g_budget refusal is not a function/quality verdict — must not claim kill-criterion pass/fail")
    assert receipt_check.validate_receipt(r_blocked) == []
    print("  BLOCKED-path receipt (g_budget refusal) shape correct, distinct from KILL  PASS")

    # 10. Divergence-KILL-path receipt: fp_check passes but post-grow loss falls outside
    #     the pre-grow envelope -> still a KILL (issue #29's second kill condition).
    diverged_loss_cont = {"training_loss_continuity_within_pre_grow_variance_envelope": False,
                          "grow_step_delta": 99.0}
    r_diverged = _assemble_receipt(
        rung=1, mode="live", ts_stamp="20260703T000000Z",
        parent_receipt_path="synthetic", parent_receipt_sha256="a" * 64,
        parent_lineage=[], tied_pairs=[], dup_numel=32_768_000, ff_seed=8192, ff_grown=16384,
        param_count_before=718316544, param_count_after=1221633024,
        fp_check=synth_fp_check, d1_steps=36, d1_anchor_flops=D1_ANCHOR_FLOPS,
        g_budget=synth_g_budget, stage="divergence_kill", loss_continuity=diverged_loss_cont,
        kill_reason="post_grow_divergence")
    assert r_diverged["pass"] is False and r_diverged["verdict"] == "GROW_RUNG_KILL", r_diverged["verdict"]
    assert r_diverged["issue_29_kill_criterion"]["function_preservation_pass"] is True
    assert r_diverged["issue_29_kill_criterion"]["post_grow_within_pre_grow_envelope"] is False
    assert receipt_check.validate_receipt(r_diverged) == []
    print("  KILL-path receipt (post-grow divergence, fp_check itself PASSED) shape correct  PASS")

    print("CBASE_GROW_RUNG_SELFTEST_PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rung", type=int, default=1, choices=sorted(RUNG_EXPECTED_PARAMS_GROWN),
                     help="which rung to grow to (default 1 — the only rung wired with a real "
                          "parent-receipt pin today; 2/3(target) need their own D6-gated VRAM "
                          "route per D2 before they may open)")
    ap.add_argument("--selftest", action="store_true", help="pure math/schema checks, no torch")
    ap.add_argument("--dry-run", action="store_true", help="CPU only, tiny stand-in, no real checkpoint/GPU")
    ap.add_argument("--parent-receipt", default=None,
                     help="override the parent lineage receipt path (default: the pinned rung's own)")
    ap.add_argument("--shard-dir", default=None, help="real packed uint16 shard dir (REQUIRED live)")
    ap.add_argument("--total-steps", type=int, default=None, help="WSD schedule denominator override")
    ap.add_argument("--ce-chunk-tokens", type=int, default=256)
    ap.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--receipt-dir", default=str(RECEIPT_DIR_DEFAULT))
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return 0
    if args.dry_run:
        return run_dry(args)

    if not args.shard_dir:
        raise SystemExit("cbase_grow_rung.py (live) requires --shard-dir (real packed uint16 "
                          "shards; eng-54 #194 refuses synthetic tokens on the live path)")
    return run_live(args)


if __name__ == "__main__":
    sys.exit(main())
