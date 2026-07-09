"""W1b fp32 bf16-tie discriminator (issue #355): seed checkpoint (unwidened
continuation source) vs grown checkpoint (grow arm), same certified eval
batch, forward-only.

Committed per the reproducibility gap the prior W1 fp32-check left open --
that one-off script (which produced receipts/ember-c-scale/w1-fp32-check-
20260707T114517Z.json) was never committed anywhere, so its own numbers
could not be independently re-derived. This script IS that re-derivation
path, generalized to any two checkpoint dirs sharing the same real_arch
family (differing only in FF width across a grow step), and is itself the
artifact that closes the gap for future re-checks.

Same protocol both times: all model/eval code imported from
scripts/w1_collapse_control_run.py and scripts/timeshare_pretrain.py, never
reimplemented. eval_loss_fn is the SAME function both arms and both dtypes
use; only the model's parameter dtype differs between the bf16 and fp32
evals of a given arm. The certified eval batch is rebuilt via
rebuild_batch_from_decontam_receipt() over --shard-dir and the given
decontam receipt; its sha256 is asserted equal to --expected-batch-sha
before any loss is computed (skip the assert by omitting the flag).

Usage (this landing's exact invocation):

    python scripts/w1b_fp32_check.py \
        --shard-dir <external-shard-mount>/shards-v0 \
        --decontam-receipt receipts/ember-c-scale/w2-heldout-decontam-20260707T055843Z.json \
        --rung-manifest models/cbase-grow-rung/rung1-20260703T155447Z/stabilize/checkpoints/step-00000766/manifest.json \
        --seed-checkpoint-dir models/cbase-smoke-run/checkpoints/step-00000610 \
        --grown-checkpoint-dir models/cbase-grow-rung/rung1-20260703T155447Z/stabilize/checkpoints/step-00000766 \
        --expected-batch-sha 91069e33b402b6a91267e59dfbeb02da96ddcbe683bc091817461fad79358929 \
        --out-dir scratch/w1-control/receipts \
        --device cuda
"""
import argparse
import datetime
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import torch  # noqa: E402
from w1_collapse_control_run import (  # noqa: E402
    load_json, derive_real_arch_config, derive_continuation_arch,
    build_real_model, load_continuation_checkpoint,
    verify_checkpoint_key_shape_parity, eval_loss_fn,
    rebuild_batch_from_decontam_receipt, DEFAULT_PRICING_RECEIPT,
    derive_rung_receipt_from_manifest,
)
from timeshare_pretrain import load_checkpoint, PackedShardLoader  # noqa: E402


def resolve(repo_root: str, path: str) -> str:
    """Repo-relative paths resolve under repo_root; an already-absolute path
    (an external shard mount, e.g. a junction outside the repo) passes
    through unchanged."""
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


# Sentinel distinguishing "caller did not pass mmap_cache_dir at all" from an
# explicit None (legacy opt-out) or an explicit path (opt-in to a specific
# dir) -- same convention as timeshare_pretrain.run_v0_segment's
# _RUN_V0_SEGMENT_MMAP_CACHE_DIR_UNSET (issue #570/#573); a plain `= None`
# default can't express "omitted" separately from "explicit None" (issue
# #575: this real-external-shard-mount call site rode the legacy
# np.fromfile+np.concatenate path unconditionally before this fix).
_W1B_FP32_CHECK_MMAP_CACHE_DIR_UNSET = object()


def run_paired_fp32_check(*, repo_root: str, shard_dir: str,
                           decontam_receipt_path: str, rung_manifest: str,
                           seed_checkpoint_dir: str, grown_checkpoint_dir: str,
                           pricing_receipt_path: str, expected_batch_sha: str | None,
                           device: str, out_dir: str, seed: int = 4242,
                           mmap_cache_dir: str | None = _W1B_FP32_CHECK_MMAP_CACHE_DIR_UNSET,
                           ) -> dict:
    pricing_receipt = load_json(pricing_receipt_path)
    rung_receipt = derive_rung_receipt_from_manifest(rung_manifest)
    real_arch = derive_real_arch_config(pricing_receipt, rung_receipt)

    # mmap_cache_dir (issue #575): omitted -> sane default under THIS run's
    # own out_dir (`<out_dir>/mmap_cache`), so the CLI's real invocation
    # (which never passed the parameter at all) automatically gets the
    # fragmentation-safe streamed-memmap path over the real external
    # shard-mount corpus this script reads. Explicit None still preserves
    # the legacy np.fromfile+np.concatenate path byte-for-byte.
    if mmap_cache_dir is _W1B_FP32_CHECK_MMAP_CACHE_DIR_UNSET:
        mmap_cache_dir = os.path.join(out_dir, "mmap_cache")
    eval_loader = PackedShardLoader(shard_dir, real_arch["seq"],
                                    n_mtp=real_arch["n_mtp"],
                                    mmap_cache_dir=mmap_cache_dir)
    decontam_receipt = load_json(decontam_receipt_path)
    eval_x, eval_y, eval_sha = rebuild_batch_from_decontam_receipt(
        eval_loader, decontam_receipt, device)

    if expected_batch_sha:
        assert eval_sha == expected_batch_sha, (
            f"CERTIFIED_BATCH_SHA_MISMATCH: rebuilt={eval_sha!r} "
            f"expected={expected_batch_sha!r}")

    # --- grown arm (real_arch's own grow-target architecture) ---
    model_grown = build_real_model(real_arch, device, seed=seed)
    g_state, _o, _r, _manifest = load_checkpoint(grown_checkpoint_dir)
    verify_checkpoint_key_shape_parity(g_state, model_grown)
    model_grown.load_state_dict(g_state, strict=True)
    eval_loss_bf16_grown = eval_loss_fn(model_grown, eval_x, eval_y)
    model_grown = model_grown.to(torch.float32)
    eval_loss_fp32_grown = eval_loss_fn(model_grown, eval_x, eval_y)
    del model_grown, g_state
    if device == "cuda":
        torch.cuda.empty_cache()

    # --- seed arm (unwidened continuation source; own narrower FF width) ---
    continuation_arch = derive_continuation_arch(seed_checkpoint_dir, real_arch)
    model_seed = build_real_model(continuation_arch, device, seed=seed)
    load_continuation_checkpoint(seed_checkpoint_dir, model_seed)
    eval_loss_bf16_seed = eval_loss_fn(model_seed, eval_x, eval_y)
    model_seed = model_seed.to(torch.float32)
    eval_loss_fp32_seed = eval_loss_fn(model_seed, eval_x, eval_y)
    del model_seed
    if device == "cuda":
        torch.cuda.empty_cache()

    receipt = {
        "ticket": "W1B-FP32-REEVAL-CHECK",
        "issue": "#355",
        "schema": "w1b-fp32-check/v1",
        "method": ("All model/eval code imported from scripts/w1_collapse_control_run.py "
                   "and scripts/timeshare_pretrain.py, never reimplemented. eval_loss_fn is "
                   "the SAME function both arms and both dtypes use; only the model's "
                   "parameter dtype differs between the bf16 and fp32 evals of a given arm. "
                   "Certified eval batch rebuilt via rebuild_batch_from_decontam_receipt() "
                   "over the given --shard-dir and --decontam-receipt; its sha256 asserted "
                   "equal to --expected-batch-sha (when given) before any loss was computed."),
        "certified_batch_check": {
            "eval_batch_sha256": eval_sha,
            "expected_batch_sha256": expected_batch_sha,
            "matches_expected": (expected_batch_sha is None) or (eval_sha == expected_batch_sha),
        },
        "grown_arm": {
            "checkpoint_dir": os.path.relpath(grown_checkpoint_dir, repo_root),
            "eval_loss_bf16": eval_loss_bf16_grown,
            "eval_loss_fp32": eval_loss_fp32_grown,
            "fp32_minus_bf16": eval_loss_fp32_grown - eval_loss_bf16_grown,
        },
        "seed_arm": {
            "checkpoint_dir": os.path.relpath(seed_checkpoint_dir, repo_root),
            "eval_loss_bf16": eval_loss_bf16_seed,
            "eval_loss_fp32": eval_loss_fp32_seed,
            "fp32_minus_bf16": eval_loss_fp32_seed - eval_loss_bf16_seed,
        },
        "margins": {
            "bf16_margin_grown_minus_seed": eval_loss_bf16_grown - eval_loss_bf16_seed,
            "fp32_margin_grown_minus_seed": eval_loss_fp32_grown - eval_loss_fp32_seed,
        },
        "seeds": 1,
        "seed_sensitivity_unmeasured": True,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "verdict_language": ("None -- this receipt reports measured numbers only. No "
                              "pass/fail, significance, or collapse-claim language is "
                              "asserted here; reading against #339/#355's pre-registered "
                              "rules is out of this receipt's scope."),
    }

    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(out_dir, f"w1b-fp32-check-{ts}.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
        f.write("\n")

    return {"receipt_path": out_path, **receipt}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard-dir", required=True,
                     help="Packed shard directory (may be outside the repo, e.g. a junction).")
    ap.add_argument("--decontam-receipt", required=True,
                     help="Path to the w2-heldout-decontam receipt (repo-relative or absolute).")
    ap.add_argument("--rung-manifest", required=True,
                     help="manifest.json of the grow-target rung checkpoint.")
    ap.add_argument("--seed-checkpoint-dir", required=True,
                     help="Checkpoint dir of the unwidened continuation source.")
    ap.add_argument("--grown-checkpoint-dir", required=True,
                     help="Checkpoint dir of the grow arm's terminal checkpoint.")
    ap.add_argument("--pricing-receipt", default=None,
                     help="Defaults to DEFAULT_PRICING_RECEIPT from w1_collapse_control_run.py.")
    ap.add_argument("--expected-batch-sha", default=None,
                     help="If given, asserts the rebuilt certified batch sha256 matches.")
    ap.add_argument("--out-dir", default=os.path.join("scratch", "w1-control", "receipts"),
                     help="Receipt output dir (repo-relative or absolute); scratch by "
                          "convention -- canonical landing is a separate, reviewed step.")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seed", type=int, default=4242)
    args = ap.parse_args()

    pricing_receipt_path = args.pricing_receipt or DEFAULT_PRICING_RECEIPT
    result = run_paired_fp32_check(
        repo_root=REPO_ROOT,
        shard_dir=resolve(REPO_ROOT, args.shard_dir),
        decontam_receipt_path=resolve(REPO_ROOT, args.decontam_receipt),
        rung_manifest=resolve(REPO_ROOT, args.rung_manifest),
        seed_checkpoint_dir=resolve(REPO_ROOT, args.seed_checkpoint_dir),
        grown_checkpoint_dir=resolve(REPO_ROOT, args.grown_checkpoint_dir),
        pricing_receipt_path=resolve(REPO_ROOT, pricing_receipt_path),
        expected_batch_sha=args.expected_batch_sha,
        device=args.device,
        out_dir=resolve(REPO_ROOT, args.out_dir),
        seed=args.seed,
    )
    print(json.dumps({
        "receipt_path": os.path.relpath(result["receipt_path"], REPO_ROOT),
        "eval_loss_bf16_grown": result["grown_arm"]["eval_loss_bf16"],
        "eval_loss_fp32_grown": result["grown_arm"]["eval_loss_fp32"],
        "eval_loss_bf16_seed": result["seed_arm"]["eval_loss_bf16"],
        "eval_loss_fp32_seed": result["seed_arm"]["eval_loss_fp32"],
        "fp32_margin_grown_minus_seed": result["margins"]["fp32_margin_grown_minus_seed"],
    }, indent=2))


if __name__ == "__main__":
    main()
