#!/usr/bin/env python3
"""cbase_grow_clause_d_dryrun.py — C-BASE clause (d) genuine rebuild, hardened
receipt schema (issue #785).

Diagnosis (why receipts/grow-operator-dryrun-20260708T060841Z.json recorded
replays=false): that receipt is from cbase_grow_rung2_dryrun.py's rung-2 run
(net2net FF-widening 16384->32768 on the real ~1.19B-param rung-1 checkpoint).
Its own PART A (deterministic function-preservation check, the actual "grow +
replay on a fixed probe batch" clause (d) asks for) PASSED cleanly:
logit_max_abs_diff=5.7220458984375e-06 vs pass_tolerance=1e-4
(receipts/grow-op-verify-20260708T060841Z.json, verdict PASS). The overall
receipt still recorded verdict FAIL / replays=false because that script's
verdict formula additionally requires an EXTRA, heavier CPU sanity POST-GROW
TRAINING segment (timeshare_pretrain.run_v0_segment at the grown ~2.2B-param
width, with QAT fake-quant + gradient checkpointing + optimizer momentum all
active) to complete — and that segment crashed with a reproducible native
ACCESS_VIOLATION (exit=3221225477), reproduced identically 3x at different
measured free-RAM levels (24GiB, 33GiB), ruling out contention. That crash is
NOT attributable to the grow operator itself (PART A already proves the
operator independently) and is disclosed, not hidden, in that receipt's
cpu_sanity_stabilization.post_grow_segment_failure block.

Is that crash class cured in current master? NO. git log on
scripts/cbase_grow_rung2_dryrun.py shows exactly one commit after the
060841Z run: e97c9216 "rung-2 CPU-offload optimizer + micro-batch cure"
(2026-07-08 10:40 -0700, DEV-002 / issue #411 track). That commit adds a
CPU-offloaded-optimizer VRAM estimate for the PRODUCTION stabilization shape
(batch16/seq1024) only — it does not touch _cpu_pretrain_worker /
_cpu_grow_worker / _cpu_post_grow_worker (the CPU-sanity workers) or
timeshare_pretrain.run_v0_segment's QAT/gradient-checkpointing machinery, so
the rung-2 CPU-sanity post-grow crash is untouched and would reproduce again
today. That defect is real and stays open (out of this issue's scope — it
does not block clause (d)).

Why the crash does not block clause (d): CHK clause (d)'s own text (this
repo's scripts/ember_totality/test_c_base.py docstring) is "a grow-operator
DRY-RUN produces a valid larger-shape checkpoint that replays" — nothing
about continued post-grow training. Issue #785's own deliverable spec
(section 2) asks for exactly: "Function-preserving grow (net2net-class), then
REPLAY: load the grown checkpoint and verify function preservation on a fixed
probe batch." That is PART A plus a save/reload/re-forward replay check — no
training loop. The already-built, already-PASSING, SMALLEST available rung
pair already proves exactly this:
receipts/cbase-grow-dryrun-20260702T190532Z.json (net2net FF-widening
4096->8192 on the owned from-scratch cbase-v0 / cbase-smoke-run checkpoint,
466,658,304 params total — the smallest grow-dryrun scale in this repo,
smaller than rung-1's ~1.19B or rung-2's ~2.2B), verdict GROW_DRYRUN_PASS,
fp_diff=3.337860107421875e-06, replay_diff=0.0. It only predates the hardened
receipt schema (no grow_operator_evidence split receipt, no top-level
api_spend_usd / paid_api_surface_used pair) — "the probe correctly skips it"
per issue #785's own ground-truth section.

This script re-runs THAT SAME smallest-rung-pair grow (identical seed
checkpoint, identical net2net surgery, identical fixed-probe-batch
convention, identical frozen tolerances) and re-emits it as the hardened
receipt PAIR clause (d)'s probe (_validate_grow_operator_evidence /
_candidate_self_declares_pass / _marker_satisfied in test_c_base.py)
requires. It does not touch, retry, or paper over the separate, still-open
rung-2 CPU-training crash.

Frozen tolerances (quoted verbatim from the existing contract in the prior
receipts — never invented):
  - function-preservation: pass_tolerance = 1e-4
    (cbase_grow_dryrun.PASS_TOL; identical value used in
    cbase-grow-dryrun-20260702T190532Z.json,
    grow-operator-dryrun-20260708T060841Z.json,
    grow-op-verify-20260708T060841Z.json).
  - replay-across-shape-change (bf16 round-trip):
    replay_tolerance_bf16_roundtrip = 0.05
    (cbase-grow-dryrun-20260702T190532Z.json's replay_across_shape_change
    block — the only prior receipt that actually measured a save/reload/
    re-forward replay; the rung-2 receipts' "replays" field measures a
    DIFFERENT thing entirely — CPU post-grow training-segment completion —
    not this reload-replay).

Reuse discipline (no duplicated math — same rule every script in this family
states for itself): imports sha256_file / widen_state_dict / build_model /
PASS_TOL from cbase_grow_dryrun.py verbatim (the exact net2net surgery + CPU
probe-model builder already proven on this checkpoint on 2026-07-02);
measure_tied_duplicate_numel from cbase_grow_rung.py (data_ptr-aliasing
dedup, never a hardcoded literal); INVARIANT_SHA256 imported from
receipt_check.py (never hand-typed); checked_write from receipt_write.py
(fail-closed schema validation, same as every other receipt writer here).

No git commits from this script. No founder/user names. api_spend_usd=0,
paid_api_surface_used=false (no paid API surface touched anywhere in this
script). Device: cpu only, no GPU touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbase_grow_dryrun import sha256_file, widen_state_dict, build_model, PASS_TOL  # noqa: E402
from cbase_grow_rung import measure_tied_duplicate_numel  # noqa: E402
from receipt_check import INVARIANT_SHA256  # noqa: E402
from receipt_write import checked_write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
# Frozen: cbase-grow-dryrun-20260702T190532Z.json replay_across_shape_change block.
REPLAY_TOL_BF16_ROUNDTRIP = 0.05

SEED_CKPT_DEFAULT = REPO / "models" / "cbase-smoke-run" / "checkpoints" / "step-00000610"
PRETRAIN_RECEIPT_REF = ("receipts/v0-live-20260623T105829Z.json (contract repo import: "
                         "v0 survivor-stack pretrain segment, loss 13.75->7.25, 610 steps, governed)")


def _repo_relative_models_path(p: Path) -> str:
    """Portable repo-relative display for a checkpoint path that may
    physically live under a DIFFERENT tree root (e.g. this script's own
    isolated worktree reading the main tree's gitignored models/ directory
    read-only, since `git worktree add` never copies untracked artifact
    bytes) than this script's own REPO. Never emit a raw absolute/drive
    path into a receipt — find the 'models' path segment and keep only
    from there; falls back to relative-to-REPO when the path really is
    under this script's own REPO."""
    if p.is_relative_to(REPO):
        return str(p.relative_to(REPO)).replace("\\", "/")
    parts = p.parts
    if "models" in parts:
        idx = parts.index("models")
        return "/".join(parts[idx:])
    raise ValueError(f"cannot derive a repo-relative path for {p} (no 'models' segment found)")


def check_state_dict_load(label: str, missing: list, unexpected: list) -> None:
    """[falsifier finding (c), PR #799, 2026-07-11] Shared guard for every
    strict=False load_state_dict call in this script (seed/grown/replay --
    previously the replay call's return was discarded entirely, and this
    function is what makes that structurally impossible to repeat: every
    load site MUST route its (missing, unexpected) tuple through here).
    "head.weight" is the one known-benign exclusion (the tied-embedding
    alias is commonly absent from an on-disk state dict's own key set,
    see module docstring); any OTHER missing or unexpected key -- an
    mtp_heads key included -- raises. Pure function, no torch import
    needed by callers: exercised directly by the negative-fixture harness
    (scripts/cbase_clause_d_negative_fixtures.py) against the exact
    production code path, not a re-description of it.
    """
    real_missing = [k for k in missing if k != "head.weight"]
    if real_missing or unexpected:
        raise SystemExit(f"{label} load mismatch: missing={real_missing} unexpected={unexpected}")


def check_mtp_keyset(mtp_keys_seed: list, mtp_keys_grown: list, mtp_keys_replay: list) -> dict:
    """[falsifier finding (c), PR #799, 2026-07-11] mtp_heads never
    participates in .logits() (see build_model / _V0.logits), so the
    function-preservation and replay forward-pass diffs cannot detect a
    silently-dropped or randomized mtp_heads key at any of the three
    loads. Independent, forward-pass-blind identity check: the keyset
    must be present and IDENTICAL (same key names) across seed/grown/
    replay -- net2net FF-widening never touches mtp_heads. Returns the
    keyset_summary dict on success; raises SystemExit otherwise. Pure
    function (sorted key-name lists in, no torch) -- exercised directly
    by the negative-fixture harness.
    """
    if not mtp_keys_seed or mtp_keys_seed != mtp_keys_grown or mtp_keys_seed != mtp_keys_replay:
        raise SystemExit(
            "mtp_heads keyset mismatch across seed/grown/replay state dicts "
            f"(counts: seed={len(mtp_keys_seed)} grown={len(mtp_keys_grown)} "
            f"replay={len(mtp_keys_replay)}) -- an unused key going missing/"
            "randomized would otherwise be invisible to the forward-pass-only "
            "replay check")
    return {
        "n_mtp_heads_keys": len(mtp_keys_seed),
        "identical_across_seed_grown_replay": True,
        "not_exercised_by_logits_forward_pass": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed-ckpt", default=str(SEED_CKPT_DEFAULT),
                     help="Absolute path accepted (read-only) -- e.g. the main tree's "
                          "models/ when running from an isolated worktree where models/ "
                          "(gitignored) was not copied by `git worktree add`.")
    ap.add_argument("--out-dir", default=str(REPO / "models" / "cbase-grow-clause-d-dryrun"))
    ap.add_argument("--receipt-dir", default=str(REPO / "receipts"))
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--seqlen", type=int, default=128)
    args = ap.parse_args()

    ts_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    torch.manual_seed(42)

    seed_ckpt = Path(args.seed_ckpt)
    model_pt = seed_ckpt / "model.pt"
    manifest = json.loads((seed_ckpt / "manifest.json").read_text(encoding="utf-8"))
    seed_sha = sha256_file(model_pt)
    claimed = (manifest.get("files") or {}).get("model.pt")
    if not (isinstance(claimed, str) and seed_sha == claimed):
        raise SystemExit(f"CBASE-GROW-CLAUSE-D-DRYRUN: seed checkpoint hash mismatch: "
                          f"manifest={claimed} actual={seed_sha}")
    print(f"[{ts_stamp}] seed checkpoint SHA verified: {seed_sha}", flush=True)

    cfg = json.loads((REPO / "configs" / "v0-pretrain-config.json").read_text(encoding="utf-8"))
    m = cfg["model"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]

    sd_bf16_raw = torch.load(model_pt, map_location="cpu", weights_only=True)
    dup_numel, tied_pairs = measure_tied_duplicate_numel(sd_bf16_raw)
    sd = {k: v.float() for k, v in sd_bf16_raw.items()}
    ff_seed = int(sd["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])
    ff_grown = ff_seed * 2
    print(f"[{ts_stamp}] ff_seed={ff_seed} ff_grown={ff_grown} (strict doubling)", flush=True)

    # --- pre_grow: seed model forward on a fixed recorded batch ---------------
    ids = torch.randint(0, m["vocab"], (args.batch, args.seqlen),
                         generator=torch.Generator().manual_seed(42))
    batch_sha = hashlib.sha256(ids.numpy().tobytes()).hexdigest()

    seed_model = build_model(m, n_mtp, ff_seed)
    missing, unexpected = seed_model.load_state_dict(sd, strict=False)
    check_state_dict_load("seed", missing, unexpected)
    seed_model.eval()
    logits_pre = seed_model.logits(ids)
    pre_grow = True

    # --- grow_operator: net2net FF widening + post_grow forward ---------------
    grown_sd = widen_state_dict(sd, m["layers"])
    grown_model = build_model(m, n_mtp, ff_grown)
    missing, unexpected = grown_model.load_state_dict(grown_sd, strict=False)
    check_state_dict_load("grown", missing, unexpected)
    grown_model.eval()
    logits_post = grown_model.logits(ids)
    post_grow = True

    fp_diff = float((logits_post - logits_pre).abs().max())
    function_preserving = bool(fp_diff <= PASS_TOL)
    print(f"[{ts_stamp}] fp_diff={fp_diff:.3e} tol={PASS_TOL} "
          f"function_preserving={function_preserving}", flush=True)

    # --- replay: save the grown larger-shape checkpoint, reload, re-forward ---
    out_dir = Path(args.out_dir) / f"grown-ff{ff_grown}-{ts_stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    grown_path = out_dir / "model.pt"
    torch.save({k: v.to(torch.bfloat16) for k, v in grown_sd.items()}, grown_path)
    grown_sha = sha256_file(grown_path)
    grown_manifest_path = out_dir / "manifest.json"
    grown_manifest_path.write_text(json.dumps({
        "ticket": "CBASE-GROW-CLAUSE-D-DRYRUN-CHECKPOINT",
        "ts": ts_stamp,
        "sha_convention": SHA_CONVENTION,
        "files": {"model.pt": grown_sha},
        "arch": {**{k: m[k] for k in ("hidden", "layers", "heads", "vocab", "seq")},
                 "intermediate": ff_grown},
        "grown_from": {"checkpoint": _repo_relative_models_path(seed_ckpt),
                        "model_pt_sha256": seed_sha, "intermediate": ff_seed},
        "mechanism": "ff_widening_net2net",
    }, indent=2) + "\n", encoding="utf-8")
    # [falsifier finding (a), PR #799, 2026-07-11] the manifest FILE's own
    # bytes are hashed too -- computed AFTER the write above, over the bytes
    # actually on disk (never the in-memory dict), same convention as every
    # other hash in this script.
    grown_manifest_sha = sha256_file(grown_manifest_path)

    reload_sd = {k: v.float() for k, v in
                 torch.load(grown_path, map_location="cpu", weights_only=True).items()}
    replay_model = build_model(m, n_mtp, ff_grown)
    # [falsifier finding (c), PR #799, 2026-07-11] this call's return was
    # previously discarded entirely -- capture and check it exactly like the
    # seed/grown loads above. Not cosmetic: replay_model loads from the
    # ON-DISK saved-and-reloaded checkpoint, a distinct load from the
    # in-memory grown_sd, so a save/reload key-loss (e.g. an alias broken by
    # the bf16 cast) is only observable at THIS load.
    missing, unexpected = replay_model.load_state_dict(reload_sd, strict=False)
    check_state_dict_load("replay", missing, unexpected)
    replay_model.eval()
    logits_replay = replay_model.logits(ids)
    replay_diff = float((logits_replay - logits_post).abs().max())
    replays = bool(replay_diff <= REPLAY_TOL_BF16_ROUNDTRIP)
    print(f"[{ts_stamp}] replay_diff={replay_diff:.3e} tol={REPLAY_TOL_BF16_ROUNDTRIP} "
          f"replays={replays}", flush=True)

    # [falsifier finding (c), PR #799, 2026-07-11] mtp_heads never
    # participates in .logits() (see build_model / _V0.logits), so the
    # function-preservation and replay forward-pass diffs above CANNOT
    # detect a silently-dropped or randomized mtp_heads key at any of the
    # three loads. This is an independent, forward-pass-blind identity
    # check: the mtp_heads keyset must be present and IDENTICAL (same key
    # names) across the seed state dict, the grown state dict, and the
    # reloaded-from-disk state dict -- net2net FF-widening never touches
    # mtp_heads, so their keys must survive every stage unchanged.
    mtp_keys_seed = sorted(k for k in sd.keys() if k.startswith("mtp_heads."))
    mtp_keys_grown = sorted(k for k in grown_sd.keys() if k.startswith("mtp_heads."))
    mtp_keys_replay = sorted(k for k in reload_sd.keys() if k.startswith("mtp_heads."))
    mtp_keyset_check = check_mtp_keyset(mtp_keys_seed, mtp_keys_grown, mtp_keys_replay)

    n_seed = int(sum(v.numel() for v in sd.values()))
    n_grown = int(sum(v.numel() for v in grown_sd.values()))
    params_unique_before = n_seed - dup_numel
    params_unique_after = n_grown - dup_numel

    verify_pass = bool(function_preserving and replays)

    seed_identity = {
        "checkpoint": _repo_relative_models_path(seed_ckpt),
        "model_pt_sha256": seed_sha,
        "manifest_claim_verified": True,
        "segment_id": manifest.get("extra", {}).get("segment_id"),
        "step": manifest.get("step"),
        "pretrain_receipt": PRETRAIN_RECEIPT_REF,
    }

    # [falsifier finding (a), PR #799, 2026-07-11] the GROWN artifact was
    # previously referenced by path only -- no model.pt hash, no manifest
    # hash, no shapes/keyset summary bound into the receipt. This block is
    # the fix: everything scripts/ember_totality/test_c_base.py's clause-(d)
    # leg now independently re-derives and checks (grown_model_pt_sha256 at
    # top level, mirroring seed_identity.model_pt_sha256's "source SHA" role)
    # plus the fuller evidence trail for human/audit inspection.
    grown_checkpoint_evidence = {
        "path": _repo_relative_models_path(grown_path),
        "model_pt_sha256": grown_sha,
        "manifest_path": _repo_relative_models_path(grown_manifest_path),
        "manifest_sha256": grown_manifest_sha,
        "source_model_pt_sha256": seed_sha,
        "keyset_summary": {
            "n_tensors": len(grown_sd),
            "ff_grown": ff_grown,
            "mtp_heads_check": mtp_keyset_check,
        },
    }

    # ---- grow-op-verify evidence receipt --------------------------------------
    evidence_filename = f"grow-op-verify-{ts_stamp}.json"
    evidence_receipt = {
        "ticket": "CBASE-GROW-CLAUSE-D-OP-VERIFY",
        "ts": timestamp_iso,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "experiment": "C-BASE-clause-d",
        "arm": "grow-op-verify",
        "scope": (f"deterministic net2net FF-widening ({ff_seed}->{ff_grown}) "
                  f"function-preservation AND save/reload/re-forward "
                  f"replay-across-shape-change check on the REAL owned from-scratch "
                  f"cbase-v0 seed checkpoint's real weights -- smallest available rung "
                  f"pair (issue #785)"),
        "seed_identity": seed_identity,
        "grow-operator": True,
        "grow_dry_run": True,
        "net2net": True,
        "ff_seed": ff_seed,
        "ff_grown": ff_grown,
        "net2net_assertion": {
            "passed": function_preserving,
            "max_abs_diff": fp_diff,
            "tolerance": PASS_TOL,
            "method": ("same fixed recorded token batch through pre-grow vs "
                       "freshly-grown (pre-training) models; net2net FF-widening "
                       "is function-preserving by construction (duplicated "
                       "gate/up rows produce duplicated SwiGLU activations; the "
                       "halved, duplicated down columns sum them back to the "
                       "exact seed output)"),
            "input_batch": {"batch": args.batch, "seqlen": args.seqlen,
                             "token_ids_sha256": batch_sha, "generator_seed": 42},
        },
        "replay_assertion": {
            "passed": replays,
            "procedure": ("save grown checkpoint -> reload into fresh larger-shape "
                          "model -> re-forward same recorded batch; the grown "
                          "checkpoint replays"),
            "max_abs_diff_vs_post_grow": replay_diff,
            "tolerance_bf16_roundtrip": REPLAY_TOL_BF16_ROUNDTRIP,
        },
        "params_unique_before": params_unique_before,
        "params_unique_after": params_unique_after,
        "grown_checkpoint": _repo_relative_models_path(grown_path),
        "grown_model_pt_sha256": grown_sha,
        "grown_checkpoint_evidence": grown_checkpoint_evidence,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "device": "cpu",
        "invalid_tokens_present": [],
        "verdict": "PASS" if verify_pass else "FAIL",
    }
    evidence_path = Path(args.receipt_dir) / evidence_filename
    checked_write(str(evidence_path), evidence_receipt)
    print(f"  written: {evidence_path}", flush=True)

    # ---- main dry-run receipt (clause (d) is exactly this: function-preserving
    #      grow that replays -- no post-grow continued-training segment, see
    #      module docstring for why that extra bar is not clause (d)'s own) ----
    main_pass = verify_pass
    main_receipt = {
        "ticket": "CBASE-GROW-CLAUSE-D-DRYRUN",
        "ts": timestamp_iso,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "experiment": "C-BASE-clause-d-dryrun",
        "arm": "grow-operator-dryrun",
        "spec_ref": ("cbase_grow_dryrun.PASS_TOL=1e-4 (function-preservation) + "
                     "replay_across_shape_change.replay_tolerance_bf16_roundtrip=0.05 "
                     "(reload replay) -- both frozen, quoted verbatim from the existing "
                     "contract in receipts/cbase-grow-dryrun-20260702T190532Z.json, never "
                     "invented (issue #785)"),
        "scope": (f"C-BASE clause (d): net2net FF-widening ({ff_seed}->{ff_grown}) "
                  f"grow-operator dry-run on the REAL owned from-scratch cbase-v0 seed "
                  f"checkpoint, the SMALLEST available rung pair in this repo "
                  f"({n_seed} params). Re-runs the exact grow already proven PASS on "
                  f"2026-07-02 (receipts/cbase-grow-dryrun-20260702T190532Z.json), "
                  f"re-emitted under the hardened receipt schema. Deliberately excludes "
                  f"the rung-2 CPU sanity post-grow TRAINING segment (a separate, "
                  f"still-open, unrelated crash class -- see module docstring) since "
                  f"clause (d)'s own text does not require it."),
        "grow-operator": True, "grow_dry_run": True, "grow-dry-run": True, "net2net": True,
        "larger-shape": True, "larger_shape": True,
        # These are OUTCOME claims (measured), never hardcoded regardless of result --
        # the exact incoherence this whole clause-(d) rebuild was commissioned to fix.
        "pre_grow": pre_grow,
        "post_grow": post_grow,
        "replays": replays,
        "replay_across_shape": replays,
        "grow_operator_evidence": f"receipts/{evidence_filename}",
        "seed_identity": seed_identity,
        "ff_seed": ff_seed, "ff_grown": ff_grown,
        "param_count_before": n_seed, "param_count_after": n_grown,
        "params_unique_before": params_unique_before, "params_unique_after": params_unique_after,
        "params_dedup": {"measured_duplicate_numel": dup_numel, "tied_pairs_detected": tied_pairs},
        "function_preservation_check": {
            "mechanism": ("same fixed recorded token batch through pre-grow vs "
                          "freshly-grown (pre-training) models; net2net FF-widening "
                          "is function-preserving by construction"),
            "input_batch": {"batch": args.batch, "seqlen": args.seqlen,
                             "token_ids_sha256": batch_sha, "generator_seed": 42},
            "logit_max_abs_diff": fp_diff,
            "pass_tolerance": PASS_TOL,
            "function_preserving": function_preserving,
        },
        "replay_across_shape_change": {
            "procedure": ("save grown checkpoint -> reload into fresh larger-shape "
                          "model -> re-forward same recorded batch; the grown "
                          "checkpoint replays"),
            "logit_max_abs_diff_vs_post_grow": replay_diff,
            "replay_tolerance_bf16_roundtrip": REPLAY_TOL_BF16_ROUNDTRIP,
            "replays": replays,
        },
        "grown_checkpoint": _repo_relative_models_path(grown_path),
        "grown_model_pt_sha256": grown_sha,
        "grown_checkpoint_evidence": grown_checkpoint_evidence,
        "mtp_heads_keyset_check": mtp_keyset_check,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "device": "cpu",
        "measured_on_train_daemon": False,
        "script": "scripts/cbase_grow_clause_d_dryrun.py",
        "scope_line_eps_sigma": (
            "eps_sigma=0 clears serialization/interface function-preserving "
            "replay ONLY -- it cannot evidence effective capacity or barrier "
            "reduction (#280)."),
        "pass": main_pass,
        "verdict": "PASS" if main_pass else "FAIL",
        "kill_criterion": None if main_pass else (
            "function_preservation_failed" if not function_preserving else "replay_failed"),
    }
    out_main = Path(args.receipt_dir) / f"grow-operator-dryrun-{ts_stamp}.json"
    checked_write(str(out_main), main_receipt)
    print(f"\n{'CBASE_GROW_CLAUSE_D_DRYRUN_PASS' if main_pass else 'CBASE_GROW_CLAUSE_D_DRYRUN_FAIL'} "
          f"fp_diff={fp_diff:.3e} replay_diff={replay_diff:.3e} "
          f"params_unique_after={params_unique_after} receipt={out_main}")
    return 0 if main_pass else 2


if __name__ == "__main__":
    sys.exit(main())
