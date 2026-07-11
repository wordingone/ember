"""w1_fullstate_resume_verify.py -- W1 leg-A full-state resume verifier
(#735 supplementary; coordinator erratum, issue #735 comment 4942417647).

REPLAY, NEVER REIMPLEMENTATION: model/optimizer/checkpoint construction is
imported from w1_collapse_control_run.py and timeshare_pretrain.py -- the
SAME historical modules scripts/w1_baseline_replay_closure.py (#738) and
the original live run used. Tiny-fixture sizing (_tiny_real_arch,
PHASE2_SEED_HISTORICAL) and path defaults are imported from
w1_baseline_replay_closure itself (its sibling, same issue #735 toolchain)
rather than duplicated. This file adds NO new model/optimizer/RNG code
path -- it adds a recursive, value-level hash comparison the closure
verifier never performed.

WHY: PR #755's landed closure receipt (w1-baseline-replay-closure-
20260711T025650Z.json, verdict REPLAY_TRUSTWORTHY) was narrowed post-merge
by an external falsifier + coordinator adjudication. Two named defects in
the closure verifier's resumability leg:

  (a) optimizer_state_shape_parity (w1_collapse_control_run.py) compares
      state KEYS + tensor SHAPES only, never VALUES -- a same-shape
      corrupted optimizer-state tensor passes silently. Named
      counterexample: momentum [1,2] vs [999,-7] both report
      shapes_match: True.
  (b) reload_bit_exact_vs_pre_save_bf16 compares ONE primary BF16
      eval-loss float via eval_loss_fn, which computes cross-entropy over
      the model's PRIMARY logits only -- RealW1Model.forward's mtp_heads
      are never touched by that path, so a same-shape corruption of
      mtp_heads.<k>.weight preserves eval loss identically while silently
      changing resumable training state.

This script closes both gaps directly: it fresh-loads the exact same
checkpoint files via load_checkpoint() -- never any in-memory object a
prior process held -- which IS the exact pre-save state (save_checkpoint
torch.saves these objects with no transformation; load_checkpoint
torch.loads them back with no transformation). It then recursively hashes
EVERY model state_dict tensor (mtp_heads included), EVERY optimizer state
scalar/tensor (dtype+shape+device-normalized bytes, never shape alone),
and the RNG state -- and requires exact hash equality between that raw
on-disk state and a POST-APPLY state: a freshly built model/optimizer/RNG,
loaded via load_state_dict/load_optimizers_state/restore_rng (the SAME
resume path production code uses), then re-extracted via
state_dict()/save_optimizers_state()/capture_rng() and re-hashed.

No GPU re-run needed: device="cpu" throughout -- this is a pure
state-application + hash comparison, no forward/backward pass required.

--selftest: CPU-only synthetic fixtures (tiny real_arch, no real corpus
beyond an in-memory synthetic shard, no real checkpoints):
  (a) positive -- a saved tiny checkpoint (model+optimizer+RNG, one real
      train step so optimizer momentum state is populated) hashes
      bit-identical end to end; verdict FULLSTATE_RESUME_EXACT.
  (b) negative -- same-shape altered mtp_heads tensor: perturbs ONE
      mtp_heads weight on disk after save. Per-tensor hash comparison
      flips (model.exact False); the OLD eval-loss-based check
      (eval_loss_fn) is shown UNCHANGED on the same corrupted checkpoint,
      demonstrating the exact silent-pass this verifier closes.
  (c) negative -- same-shape altered optimizer tensor: perturbs ONE
      optimizer momentum/exp_avg buffer's bytes on disk after save.
      Per-key hash comparison flips (optimizer.exact False); the OLD
      optimizer_state_shape_parity check is shown STILL reporting
      shapes_match: True on the same corrupted checkpoint.

--live: loads the REAL custody-pinned leg-A checkpoint (default: the
#735 leg-A custody dir) and, before the resume-hash comparison, asserts
the checkpoint's 4 files independently re-hash to the EXPECTED_CUSTODY_
SHA256 pins below (never trusting the checkpoint's own manifest.json as
ground truth -- same discipline as the closure script's preflight leg).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import torch  # noqa: E402

from w1_collapse_control_run import (  # noqa: E402 -- reused, never edited
    load_json, sha256_file, build_real_model, verify_checkpoint_key_shape_parity,
    eval_loss_fn, optimizer_state_shape_parity, derive_real_arch_config,
    derive_rung_receipt_from_manifest, apply_cosine_warmup,
    train_step_matched_recipe, resolve_ce_impl, DEFAULT_PRICING_RECEIPT,
)
from timeshare_pretrain import (  # noqa: E402 -- reused, never edited
    load_checkpoint, save_checkpoint, capture_rng, restore_rng,
    PackedShardLoader, build_split_optimizer, save_optimizers_state,
    load_optimizers_state, CONTRACT_PATH as PRETRAIN_CONTRACT_PATH,
)
from receipt_write import checked_write  # noqa: E402

# Sibling import (same #735 toolchain, never duplicated): tiny-fixture
# sizing + path/seed defaults the closure script already established.
from w1_baseline_replay_closure import (  # noqa: E402
    _tiny_real_arch, _build_tiny_shard_dir, resolve as closure_resolve,
    PHASE2_SEED_HISTORICAL, DEFAULT_RUNG_MANIFEST,
)

ISSUE_REF = "#735"
SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending "
    "normalization) for checkpoint files; sha256 over device-normalized "
    "(cpu, contiguous, bitcast-to-uint8) tensor bytes prefixed with shape+"
    "dtype for every model/optimizer state tensor and RNG buffer hashed "
    "below (the tensor_hash convention used throughout this receipt)")

# --- #735 leg-A custody pins (receipts/ember-c-scale/w1-baseline-replay-
# closure-20260711T025650Z.json's own "custody" section, files_sha256_
# post_move -- re-cited here, never re-derived from the checkpoint's own
# manifest.json, so a tampered custody copy cannot self-certify). ---
DEFAULT_CUSTODY_DIR = os.path.join(
    "models", "w1-baseline-replay-custody",
    "w1-baseline-replay-step50-20260711T025650Z")
EXPECTED_CUSTODY_SHA256 = {
    "model.pt": "8055a9f4b67711b8f1103dcf76228c5f303ba6d6170af17243b17b7c5289ea54",
    "optimizer.pt": "324b988f73b8741bc3b04c4a18bf0823ec271d56ecc1c6608b269121524da250",
    "rng.pt": "c9ca61ab0e5fb9661e54dc9bb2df294f3828390829c997330f9290a02aabc379",
    "manifest.json": "af828fd6388c7d0c00ec688bf291f474b0158c308a022f3d19fffc58b6b68504",
}


def resolve(repo_root: str, path: str) -> str:
    return closure_resolve(repo_root, path)


# ---------------------------------------------------------------------------
# Custody pin check -- never trusts the checkpoint's own manifest.json as
# ground truth (same discipline as the closure script's
# _verify_checkpoint_manifest).
# ---------------------------------------------------------------------------

def verify_custody_pins(ckpt_dir: str, expected: dict) -> dict:
    measured = {fname: sha256_file(os.path.join(ckpt_dir, fname)) for fname in expected}
    per_file_match = {fname: measured[fname] == expected[fname] for fname in expected}
    return {"dir": ckpt_dir, "measured_sha256": measured, "expected_sha256": expected,
            "per_file_match": per_file_match, "pass": all(per_file_match.values())}


# ---------------------------------------------------------------------------
# Device-normalized recursive hashing -- the load-bearing addition. A
# tensor's hash is dtype+shape+raw-bytes after moving to CPU, making
# contiguous, and bitcasting to uint8 (Tensor.view(dtype) reinterprets
# bits without value conversion, so this covers bf16/fp32/fp16/int* alike
# without a numpy dtype-support special case). A non-tensor optimizer-
# state leaf (e.g. a plain-int "step" counter, version-dependent) is
# type-tagged and repr-hashed rather than silently skipped -- this is
# exactly the class optimizer_state_shape_parity's `if not
# isinstance(orig_t, torch.Tensor): continue` drops.
# ---------------------------------------------------------------------------

def _tensor_hash(t: "torch.Tensor") -> str:
    t_cpu = t.detach().to("cpu").contiguous().reshape(-1)
    raw = t_cpu.view(torch.uint8).numpy().tobytes()
    h = hashlib.sha256()
    h.update(str(tuple(t.shape)).encode())
    h.update(str(t.dtype).encode())
    h.update(raw)
    return h.hexdigest()


def _hash_value(v) -> str:
    if torch.is_tensor(v):
        return "tensor:" + _tensor_hash(v)
    return f"{type(v).__name__}:{v!r}"


def _hash_model_state(state: dict) -> dict:
    return {k: _tensor_hash(state[k]) for k in sorted(state.keys())}


def _hash_optimizer_state(bundle: dict) -> dict:
    """Recursively hashes EVERY optimizer-state leaf (state + param_groups
    hyperparameters, params-list excluded since it is an index list, not
    a value) for every optimizer key in a save_optimizers_state() bundle."""
    out = {}
    for opt_key in sorted(bundle.keys()):
        opt_sd = bundle[opt_key]
        state = opt_sd.get("state", {})
        per_param = {}
        for pidx in sorted(state.keys(), key=str):
            pstate = state[pidx]
            per_param[str(pidx)] = {
                buf: _hash_value(val) for buf, val in sorted(pstate.items())}
        pg_repr = json.dumps(
            [{k: v for k, v in g.items() if k != "params"}
             for g in opt_sd.get("param_groups", [])],
            sort_keys=True, default=str)
        out[opt_key] = {
            "n_params": len(state),
            "per_param_hashes": per_param,
            "param_groups_hash": hashlib.sha256(pg_repr.encode()).hexdigest(),
        }
    return out


def _hash_rng_state(state: dict) -> str:
    h = hashlib.sha256()
    h.update(repr(state["py_random"]).encode())
    h.update(_tensor_hash(state["torch_cpu"]).encode())
    if "np_random" in state:
        a0, a1, a2, a3, a4 = state["np_random"]
        h.update(repr(a0).encode())
        h.update(np.ascontiguousarray(a1).tobytes())
        h.update(repr((a2, a3, a4)).encode())
    if "torch_cuda" in state:
        for t in state["torch_cuda"]:
            h.update(_tensor_hash(t).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Comparison primitives -- pure functions over two hash-dicts, reused for
# BOTH gates below (never duplicated logic between them).
# ---------------------------------------------------------------------------

def _compare_model_hashes(hashes_a: dict, hashes_b: dict) -> dict:
    keys_a, keys_b = set(hashes_a), set(hashes_b)
    key_mismatch = sorted(keys_a ^ keys_b)
    tensor_mismatches = sorted(
        k for k in (keys_a & keys_b) if hashes_a[k] != hashes_b[k])
    mtp_keys = sorted(k for k in hashes_a if "mtp_heads." in k)
    return {
        "n_tensors_checked": len(keys_a),
        "n_mtp_head_tensors_checked": len(mtp_keys),
        "mtp_head_keys": mtp_keys,
        "key_set_mismatch": key_mismatch,
        "tensor_hash_mismatches": tensor_mismatches,
        "exact": not key_mismatch and not tensor_mismatches,
    }


def _compare_optimizer_hashes(hashes_a: dict, hashes_b: dict) -> dict:
    mismatches: list = []
    for opt_key in sorted(set(hashes_a) | set(hashes_b)):
        a, b = hashes_a.get(opt_key), hashes_b.get(opt_key)
        if a is None or b is None:
            mismatches.append(f"{opt_key}: missing on one side "
                               f"(a={a is not None} b={b is not None})")
            continue
        if a["param_groups_hash"] != b["param_groups_hash"]:
            mismatches.append(f"{opt_key}: param_groups_hash differs")
        a_params, b_params = a["per_param_hashes"], b["per_param_hashes"]
        for pidx in sorted(set(a_params) | set(b_params)):
            ap, bp = a_params.get(pidx, {}), b_params.get(pidx, {})
            for buf in sorted(set(ap) | set(bp)):
                if ap.get(buf) != bp.get(buf):
                    mismatches.append(f"{opt_key}[{pidx}].{buf}: hash differs")
    return {
        "n_optimizer_keys_checked": len(hashes_a),
        "n_params_per_key": {k: v["n_params"] for k, v in hashes_a.items()},
        "mismatches": mismatches,
        "exact": len(mismatches) == 0,
    }


# ---------------------------------------------------------------------------
# Core verifier -- fresh-load the checkpoint, apply it to a NEW model/
# optimizer/RNG via the SAME resume path production code uses, re-extract,
# re-hash. Two independent gates:
#
#   1. LOAD-PATH FIDELITY (always run): raw on-disk state (what
#      load_checkpoint() returns directly -- a straight torch.load with no
#      transformation) vs the load_state_dict/load_optimizers_state/
#      restore_rng -> re-extract round trip. Proves resuming from this
#      checkpoint via the production apply path does not silently drop,
#      truncate, misalign, or coerce ANY tensor/scalar -- covering every
#      model tensor (mtp_heads included) and every optimizer value (not
#      shape alone), which is what the landed closure receipt's verifier
#      never checked.
#
#   2. SAVE FIDELITY (only when pre_save_hashes is supplied): the raw
#      on-disk state vs a hash captured DIRECTLY from the in-memory
#      objects immediately before save_checkpoint wrote them, in the SAME
#      process. This is the literal "compare against the exact pre-save
#      state" the erratum names -- catches corruption introduced at
#      save time or by post-write tampering, which gate 1 (a purely
#      self-referential comparison against the same file) cannot see by
#      construction. Only available where the pre-save objects still
#      exist to hash (selftest fixtures, same process); the real --live
#      leg-A checkpoint was produced by an already-finished process, so
#      no such in-memory reference survives for it -- main()'s
#      independent custody-sha pin check (verify_custody_pins, comparing
#      against hashes recorded in a SEPARATE receipt at save time) is the
#      achievable equivalent for that case, disclosed as such in the
#      receipt rather than silently substituted.
# ---------------------------------------------------------------------------

def verify_fullstate_resume(*, real_arch: dict, pretrain_contract: dict,
                             ckpt_dir: str, seed: int, device: str = "cpu",
                             pre_save_hashes: "dict | None" = None) -> dict:
    m_state, o_state, r_state, manifest = load_checkpoint(ckpt_dir)

    model_hashes_saved = _hash_model_state(m_state)
    optimizer_hashes_saved = _hash_optimizer_state(o_state)
    rng_hash_saved = _hash_rng_state(r_state)

    model = build_real_model(real_arch, device, seed=seed)
    verify_checkpoint_key_shape_parity(m_state, model)
    model.load_state_dict(m_state, strict=True)
    optimizers, _base_lrs, _routing = build_split_optimizer(
        model, pretrain_contract, force_fallback=False)
    load_optimizers_state(optimizers, o_state)
    restore_rng(r_state)

    model_hashes_applied = _hash_model_state(model.state_dict())
    optimizer_hashes_applied = _hash_optimizer_state(save_optimizers_state(optimizers))
    rng_hash_applied = _hash_rng_state(capture_rng())
    del model, optimizers
    if device == "cuda":
        torch.cuda.empty_cache()

    load_path_fidelity = {
        "model": _compare_model_hashes(model_hashes_saved, model_hashes_applied),
        "optimizer": _compare_optimizer_hashes(optimizer_hashes_saved, optimizer_hashes_applied),
        "rng": {"hash_on_disk": rng_hash_saved, "hash_after_apply": rng_hash_applied,
                "exact": rng_hash_saved == rng_hash_applied},
    }
    load_path_exact = (load_path_fidelity["model"]["exact"]
                        and load_path_fidelity["optimizer"]["exact"]
                        and load_path_fidelity["rng"]["exact"])

    # save_fidelity_exact is None (never True) when unchecked -- a bare
    # default of True here would be a VACUOUS pass indistinguishable in
    # the receipt from "checked and matched", exactly the kind of silent
    # trivial-pass this whole supplementary verifier exists to eliminate
    # elsewhere. save_fidelity_gate_satisfied is the internal value used
    # for the verdict (unchecked = does not block, since its absence is
    # separately and honestly disclosed via save_fidelity_checked).
    save_fidelity = None
    save_fidelity_exact = None
    save_fidelity_gate_satisfied = True
    if pre_save_hashes is not None:
        save_fidelity = {
            "model": _compare_model_hashes(pre_save_hashes["model"], model_hashes_saved),
            "optimizer": _compare_optimizer_hashes(pre_save_hashes["optimizer"], optimizer_hashes_saved),
            "rng": {"hash_pre_save": pre_save_hashes["rng"], "hash_on_disk": rng_hash_saved,
                    "exact": pre_save_hashes["rng"] == rng_hash_saved},
        }
        save_fidelity_exact = (save_fidelity["model"]["exact"]
                                and save_fidelity["optimizer"]["exact"]
                                and save_fidelity["rng"]["exact"])
        save_fidelity_gate_satisfied = save_fidelity_exact

    verdict = ("FULLSTATE_RESUME_EXACT" if load_path_exact and save_fidelity_gate_satisfied
               else "FULLSTATE_RESUME_DIVERGED")

    return {
        "ckpt_dir": ckpt_dir,
        "manifest_step": manifest.get("step"),
        "load_path_fidelity": load_path_fidelity,
        "load_path_exact": load_path_exact,
        "save_fidelity": save_fidelity,
        "save_fidelity_checked": pre_save_hashes is not None,
        "save_fidelity_exact": save_fidelity_exact,
        "model": load_path_fidelity["model"],
        "optimizer": load_path_fidelity["optimizer"],
        "rng": load_path_fidelity["rng"],
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Negative-fixture corruption helpers (TEST-ONLY, never called from the
# real --live path). Generic key-substring targeting -- never a hardcoded
# key name that could drift if the model/optimizer internals change.
# ---------------------------------------------------------------------------

def _corrupt_model_tensor_by_key_substring(ckpt_dir: str, substring: str) -> str:
    """Perturbs the FIRST float tensor in model.pt whose key contains
    `substring`, same shape, and rewrites manifest.json's model.pt sha so
    load_checkpoint's own sha-integrity check still passes. Returns the
    corrupted key name."""
    model_pt_path = os.path.join(ckpt_dir, "model.pt")
    state = torch.load(model_pt_path, map_location="cpu")
    target_key = None
    for key, tensor in state.items():
        if substring in key and torch.is_tensor(tensor) and tensor.is_floating_point():
            state[key] = tensor + 1.0
            target_key = key
            break
    if target_key is None:
        raise AssertionError(
            f"W1_FULLSTATE_TEST_CORRUPT_NO_MATCH: substring={substring!r} "
            f"keys={list(state.keys())!r}")
    torch.save(state, model_pt_path)
    _rewrite_manifest_sha(ckpt_dir, "model.pt")
    return target_key


def _corrupt_optimizer_tensor(ckpt_dir: str) -> str:
    """Perturbs the FIRST float tensor found anywhere inside optimizer.pt's
    per-param 'state' dicts (any optimizer key, any buffer name), same
    shape, and rewrites manifest.json's optimizer.pt sha. Returns a
    'opt_key[pidx].buf_name' descriptor of the corrupted leaf."""
    optimizer_pt_path = os.path.join(ckpt_dir, "optimizer.pt")
    bundle = torch.load(optimizer_pt_path, map_location="cpu")
    target_desc = None
    for opt_key, opt_sd in bundle.items():
        state = opt_sd.get("state", {})
        for pidx, pstate in state.items():
            for buf, val in pstate.items():
                if torch.is_tensor(val) and val.is_floating_point():
                    pstate[buf] = val + 1.0
                    target_desc = f"{opt_key}[{pidx}].{buf}"
                    break
            if target_desc:
                break
        if target_desc:
            break
    if target_desc is None:
        raise AssertionError(
            "W1_FULLSTATE_TEST_CORRUPT_OPTIMIZER_NO_FLOAT_TENSOR_FOUND: "
            f"bundle_keys={list(bundle.keys())!r}")
    torch.save(bundle, optimizer_pt_path)
    _rewrite_manifest_sha(ckpt_dir, "optimizer.pt")
    return target_desc


def _rewrite_manifest_sha(ckpt_dir: str, fname: str) -> None:
    manifest_path = os.path.join(ckpt_dir, "manifest.json")
    new_sha = sha256_file(os.path.join(ckpt_dir, fname))
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["files"][fname] = new_sha
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, sort_keys=True, separators=(",", ": "), indent=2)


# ---------------------------------------------------------------------------
# --selftest
# ---------------------------------------------------------------------------

def _build_tiny_stepped_checkpoint(tmp: str, *, real_arch: dict,
                                    pretrain_contract: dict, seed: int) -> tuple:
    """Builds a tiny model+optimizer, runs ONE real train step (so
    optimizer momentum/exp_avg state is actually populated -- an
    unstepped optimizer's state_dict()['state'] is empty, which would
    make the optimizer-corruption negative fixture vacuous), saves a
    checkpoint, and returns (ckpt_dir, eval_x, eval_y) for the caller's
    own eval_loss_fn contrast check), plus pre_save_hashes captured
    DIRECTLY from the exact same in-memory objects handed to
    save_checkpoint (never a second, separately-computed read) -- the
    "exact pre-save state" reference the erratum names, only obtainable
    because this selftest controls the whole process end to end."""
    shard_dir = _build_tiny_shard_dir(tmp, vocab=real_arch["vocab"])
    loader = PackedShardLoader(shard_dir, real_arch["seq"], n_mtp=real_arch["n_mtp"])
    device = "cpu"
    model = build_real_model(real_arch, device, seed=seed)
    optimizers, base_lrs, _routing = build_split_optimizer(
        model, pretrain_contract, force_fallback=False,
        deviation_dir=os.path.join(tmp, "deviations"))
    _ce_impl, ce_fn = resolve_ce_impl(prefer_liger=False)
    x, y0, y_mtp = loader.batch(0, real_arch["batch"])
    apply_cosine_warmup(optimizers, base_lrs, 0, 40)
    mtp_cfg = pretrain_contract["objective"]["mtp_aux_heads"]
    train_step_matched_recipe(
        model, optimizers, ce_fn, x=x, y0=y0, y_mtp=y_mtp,
        mtp_enabled=bool(mtp_cfg["enabled"]), mtp_weight=mtp_cfg["weight"])

    xs_np, ys_np = [], []
    for j in range(real_arch["batch"]):
        xw, yw, _ = loader.window_np(1000 + j)
        xs_np.append(xw)
        ys_np.append(yw)
    eval_x = torch.as_tensor(np.stack(xs_np), dtype=torch.long, device=device)
    eval_y = torch.as_tensor(np.stack(ys_np), dtype=torch.long, device=device)

    model_state_pre_save = model.state_dict()
    optimizer_bundle_pre_save = save_optimizers_state(optimizers)
    rng_pre_save = capture_rng()
    pre_save_hashes = {
        "model": _hash_model_state(model_state_pre_save),
        "optimizer": _hash_optimizer_state(optimizer_bundle_pre_save),
        "rng": _hash_rng_state(rng_pre_save),
    }
    ckpt_dir = save_checkpoint(
        os.path.join(tmp, "run"), 10, model_state_pre_save,
        optimizer_bundle_pre_save, rng_pre_save,
        extra={"segment_id": "fullstate-verify-selftest"})
    return (ckpt_dir, eval_x, eval_y, model, eval_loss_fn(model, eval_x, eval_y),
            pre_save_hashes)


def _selftest() -> None:
    import shutil
    import tempfile
    print("[w1-fullstate-resume-verify-selftest] starting CPU-only synthetic-fixture selftest")
    with tempfile.TemporaryDirectory(prefix="w1fullstate-selftest-") as tmp:
        real_arch = _tiny_real_arch()
        pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)
        seed = 1234

        (ckpt_dir, eval_x, eval_y, _model, eval_loss_clean,
         pre_save_hashes) = _build_tiny_stepped_checkpoint(
            tmp, real_arch=real_arch, pretrain_contract=pretrain_contract, seed=seed)

        # --- (a) positive: unmodified fresh checkpoint hashes bit-exact
        # end to end, BOTH gates (load-path fidelity AND save fidelity
        # against the true pre-save in-memory state). ---
        result_pos = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=ckpt_dir, seed=seed, device="cpu",
            pre_save_hashes=pre_save_hashes)
        assert result_pos["verdict"] == "FULLSTATE_RESUME_EXACT", (
            f"W1_FULLSTATE_SELFTEST_POSITIVE_UNEXPECTED_VERDICT: {result_pos}")
        assert result_pos["load_path_exact"], result_pos["load_path_fidelity"]
        assert result_pos["save_fidelity_checked"] and result_pos["save_fidelity_exact"], (
            result_pos["save_fidelity"])
        assert result_pos["model"]["n_mtp_head_tensors_checked"] == real_arch["n_mtp"], (
            f"W1_FULLSTATE_SELFTEST_MTP_KEY_COUNT_MISMATCH: "
            f"expected {real_arch['n_mtp']} got {result_pos['model']}")
        assert result_pos["optimizer"]["n_optimizer_keys_checked"] >= 1
        print(f"[selftest] (a) POSITIVE leg PASS -- verdict={result_pos['verdict']} "
              f"n_tensors={result_pos['model']['n_tensors_checked']} "
              f"n_mtp_heads={result_pos['model']['n_mtp_head_tensors_checked']} "
              f"n_optimizer_keys={result_pos['optimizer']['n_optimizer_keys_checked']} "
              "-- load-path fidelity AND save fidelity (vs true pre-save "
              "in-memory state) both exact")

        # --- (b) negative: same-shape altered mtp_heads tensor, applied to
        # the ON-DISK FILE after save (simulating save-time/post-write
        # corruption -- the class the erratum names). Copy the clean
        # checkpoint (never mutate the fixture (a) verified) into a fresh
        # dir, corrupt one mtp_heads weight there, re-verify against the
        # SAME pre_save_hashes captured before any corruption existed. ---
        neg_mtp_dir = os.path.join(tmp, "ckpt-neg-mtp")
        shutil.copytree(ckpt_dir, neg_mtp_dir)
        corrupted_key = _corrupt_model_tensor_by_key_substring(neg_mtp_dir, "mtp_heads.")
        result_neg_mtp = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=neg_mtp_dir, seed=seed, device="cpu",
            pre_save_hashes=pre_save_hashes)
        assert result_neg_mtp["verdict"] == "FULLSTATE_RESUME_DIVERGED", (
            f"W1_FULLSTATE_SELFTEST_NEG_MTP_DID_NOT_FLIP: {result_neg_mtp}")
        assert not result_neg_mtp["save_fidelity_exact"]
        assert not result_neg_mtp["save_fidelity"]["model"]["exact"]
        assert corrupted_key in result_neg_mtp["save_fidelity"]["model"]["tensor_hash_mismatches"], (
            f"W1_FULLSTATE_SELFTEST_NEG_MTP_WRONG_KEY: corrupted={corrupted_key} "
            f"mismatches={result_neg_mtp['save_fidelity']['model']['tensor_hash_mismatches']}")
        # load-path fidelity ALONE (raw-on-disk vs load-apply-re-extract,
        # no pre-save reference) does NOT see this corruption -- both
        # sides of that comparison read the SAME already-corrupted file.
        # This is the honest limit of gate 1 and precisely why gate 2
        # (save fidelity against the true pre-save state) exists.
        assert result_neg_mtp["load_path_exact"], (
            "W1_FULLSTATE_SELFTEST_NEG_MTP_LOAD_PATH_UNEXPECTEDLY_FLIPPED: "
            f"{result_neg_mtp['load_path_fidelity']}")
        # Contrast proof: the OLD eval-loss-based check (what the landed
        # closure receipt actually gated on) is ALSO unchanged by this
        # exact corruption -- eval_loss_fn's forward path never touches
        # mtp_heads, so it silently passes the same defect this verifier
        # catches via the save-fidelity gate.
        m_state_corrupt, _o, _r, _mf = load_checkpoint(neg_mtp_dir)
        model_reload = build_real_model(real_arch, "cpu", seed=seed)
        model_reload.load_state_dict(m_state_corrupt, strict=True)
        eval_loss_corrupted = eval_loss_fn(model_reload, eval_x, eval_y)
        assert eval_loss_corrupted == eval_loss_clean, (
            "W1_FULLSTATE_SELFTEST_NEG_MTP_CONTRAST_UNEXPECTED: eval_loss_fn "
            "changed on an mtp_heads-only corruption -- contrast fixture invalid "
            f"(clean={eval_loss_clean} corrupted={eval_loss_corrupted})")
        print(f"[selftest] (b) NEGATIVE mtp_heads leg PASS -- verdict="
              f"{result_neg_mtp['verdict']} corrupted_key={corrupted_key} -- "
              f"save-fidelity gate FLIPPED (caught it); load-path-fidelity "
              "gate alone stayed exact (self-referential, cannot see it); "
              f"OLD eval_loss_fn check ALSO unchanged ({eval_loss_clean}) -- "
              "both prior checks silently pass this exact corruption")

        # --- (c) negative: same-shape altered optimizer tensor, same
        # post-save-corruption shape as (b). ---
        neg_opt_dir = os.path.join(tmp, "ckpt-neg-opt")
        shutil.copytree(ckpt_dir, neg_opt_dir)
        corrupted_desc = _corrupt_optimizer_tensor(neg_opt_dir)
        result_neg_opt = verify_fullstate_resume(
            real_arch=real_arch, pretrain_contract=pretrain_contract,
            ckpt_dir=neg_opt_dir, seed=seed, device="cpu",
            pre_save_hashes=pre_save_hashes)
        assert result_neg_opt["verdict"] == "FULLSTATE_RESUME_DIVERGED", (
            f"W1_FULLSTATE_SELFTEST_NEG_OPT_DID_NOT_FLIP: {result_neg_opt}")
        assert not result_neg_opt["save_fidelity_exact"]
        assert not result_neg_opt["save_fidelity"]["optimizer"]["exact"]
        assert result_neg_opt["save_fidelity"]["optimizer"]["mismatches"], (
            result_neg_opt["save_fidelity"]["optimizer"])
        assert result_neg_opt["load_path_exact"], (
            "W1_FULLSTATE_SELFTEST_NEG_OPT_LOAD_PATH_UNEXPECTEDLY_FLIPPED: "
            f"{result_neg_opt['load_path_fidelity']}")
        # Contrast proof: the OLD optimizer_state_shape_parity check
        # (shape-only) is UNCHANGED (still reports shapes_match: True) on
        # this exact same-shape corruption.
        _m2, o_state_clean, _r2, _mf2 = load_checkpoint(ckpt_dir)
        _m3, o_state_corrupt, _r3, _mf3 = load_checkpoint(neg_opt_dir)
        old_parity = optimizer_state_shape_parity(o_state_corrupt, o_state_clean)
        assert old_parity["shapes_match"], (
            "W1_FULLSTATE_SELFTEST_NEG_OPT_CONTRAST_UNEXPECTED: "
            "optimizer_state_shape_parity flipped on a same-shape-only "
            f"corruption -- contrast fixture invalid ({old_parity})")
        print(f"[selftest] (c) NEGATIVE optimizer leg PASS -- verdict="
              f"{result_neg_opt['verdict']} corrupted={corrupted_desc} -- "
              "save-fidelity gate FLIPPED (caught it); load-path-fidelity "
              "gate alone stayed exact; OLD optimizer_state_shape_parity "
              f"check ALSO UNCHANGED (shapes_match={old_parity['shapes_match']}) "
              "on this exact same-shape corruption")

    print("W1_FULLSTATE_RESUME_VERIFY_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only synthetic-fixture selftest; never touches "
                         "the real checkpoint/GPU.")
    ap.add_argument("--live", action="store_true",
                    help="Verify the real #735 leg-A custody checkpoint. "
                         "CPU-only, no GPU, no training -- pure state-load "
                         "+ hash comparison.")
    ap.add_argument("--ckpt-dir", default=DEFAULT_CUSTODY_DIR)
    ap.add_argument("--pricing-receipt", default=DEFAULT_PRICING_RECEIPT)
    ap.add_argument("--rung-manifest", default=DEFAULT_RUNG_MANIFEST)
    ap.add_argument("--phase2-seed", type=int, default=PHASE2_SEED_HISTORICAL)
    ap.add_argument("--out-dir", default=None,
                    help="defaults to receipts/ember-c-scale/")
    return ap


def main(argv: "list[str] | None" = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        print("W1_FULLSTATE_RESUME_VERIFY_SELFTEST_PASS")
        return 0

    if not args.live:
        print("Nothing to do: pass --selftest or --live.")
        return 0

    repo_root = REPO_ROOT
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ckpt_dir = resolve(repo_root, args.ckpt_dir)
    pricing_receipt_path = resolve(repo_root, args.pricing_receipt)
    rung_manifest_path = resolve(repo_root, args.rung_manifest)

    custody_check = verify_custody_pins(ckpt_dir, EXPECTED_CUSTODY_SHA256)
    if not custody_check["pass"]:
        raise SystemExit(
            f"W1_FULLSTATE_CUSTODY_PIN_MISMATCH: {ckpt_dir!r} -- "
            f"{custody_check!r}")

    pricing_receipt = load_json(pricing_receipt_path)
    rung_receipt = derive_rung_receipt_from_manifest(rung_manifest_path)
    real_arch = derive_real_arch_config(pricing_receipt, rung_receipt)
    pretrain_contract = load_json(PRETRAIN_CONTRACT_PATH)

    result = verify_fullstate_resume(
        real_arch=real_arch, pretrain_contract=pretrain_contract,
        ckpt_dir=ckpt_dir, seed=args.phase2_seed, device="cpu")

    receipt = {
        "ticket": "W1-FULLSTATE-RESUME-VERIFY", "ts": ts, "issue": ISSUE_REF,
        "schema": "w1-fullstate-resume-verify/v1",
        "sha_convention": SHA_CONVENTION,
        "ref": "issue #735 comment 4942417647 (coordinator erratum + "
               "scope-narrowing on the landed w1-baseline-replay-closure-"
               "20260711T025650Z.json receipt); supplements, never "
               "retro-edits, that receipt -- append-only evidence.",
        "custody_pin_check": custody_check,
        "verification": result,
        "verdict": result["verdict"],
        "verdict_language": (
            "FULLSTATE_RESUME_EXACT closes both named defects in the "
            "landed closure receipt's resumability leg: (a) optimizer "
            "state is compared by VALUE (device-normalized tensor hash), "
            "never shape alone; (b) EVERY model state_dict tensor "
            "including mtp_heads is hashed, never only the primary-logits "
            "eval-loss path. This receipt does not re-assert or widen the "
            "closure receipt's REPLAY_TRUSTWORTHY language (model BF16/"
            "FP32 replay + eval identity) -- it verifies the checkpoint IS "
            "a genuine bit-exact resume point, the claim the closure "
            "receipt's verdict string implied but its verifier did not "
            "check."),
        "api_spend_usd": 0.0, "paid_api_surface_used": False,
    }
    out_dir = (resolve(repo_root, args.out_dir) if args.out_dir else
               os.path.join(repo_root, "receipts", "ember-c-scale"))
    os.makedirs(out_dir, exist_ok=True)
    receipt_path = os.path.join(out_dir, f"w1-fullstate-resume-verify-{ts}.json")
    checked_write(receipt_path, receipt)
    print(json.dumps({
        "receipt": os.path.relpath(receipt_path, repo_root),
        "verdict": receipt["verdict"],
        "model_exact": result["model"]["exact"],
        "optimizer_exact": result["optimizer"]["exact"],
        "rng_exact": result["rng"]["exact"],
    }, indent=2))
    return 0 if result["verdict"] == "FULLSTATE_RESUME_EXACT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
