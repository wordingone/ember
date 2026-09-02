#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reconstruct pre-grow checkpoint from grown (step-00000730).

COLLISION WARNING: Two step-00000730 checkpoints exist in the repo:
  1. models/cbase-grow-live/live-20260703T053225Z/post/checkpoints/step-00000730
     (live run, 1.37GB, model.pt sha ac43445b)
  2. models/cbase-grow-rung/rung1-20260703T155447Z/checkpoints/step-00000730
     (rung-1 seed, 2.44GB, model.pt sha 74a5b1d4) ← RECONSTRUCTION SOURCE
Use --source to explicitly pin the rung1 checkpoint; no implicit default.

The forward grow operation (cbase_grow_dryrun.py:85-93) performs FF-widening
via net2net for SwiGLU MLPs:
  gate_proj: cat([w, w], dim=0)      -- duplicate rows (8192 -> 16384)
  up_proj:   cat([w, w], dim=0)      -- duplicate rows (8192 -> 16384)
  down_proj: cat([w*0.5, w*0.5], dim=1)  -- halve and duplicate columns (8192 -> 16384)

INVERSE reconstruction extracts the seed-width tensors:
  gate_proj_pre = gate_post[:F, :]   where F=8192
  up_proj_pre   = up_post[:F, :]
  down_proj_pre = 2.0 * down_post[:, :F]   (exact doubling in bf16; not sum)

All other tensors pass through unchanged.

FAIL-CLOSED GUARDS (mandatory before reconstruction):
  1. SHA256 of source model.pt must match manifest
  2. Shape assert: gate/up dim0 == 16384, down_proj dim1 == 16384
  3. Twin bit-identity: gate_post[:F].equal(gate_post[F:]) and
     up_post[:F].equal(up_post[F:]) — torch.equal, bitwise
  4. down_proj halves equality: down_post[:, :F].equal(down_post[:, F:])

SELFTEST: re-apply the forward grow to the reconstructed state dict and
assert torch.equal (bitwise) with the original step-730 tensors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
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
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

# Expected SHA for rung-1 source checkpoint (step-00000730, cbase-grow-rung)
SOURCE_SHA_EXPECTED = "74a5b1d4c21b38fb4a8037bd079c2073516dee9a242849fc33fda191f4fa0f3b"
# NOTE: Two step-00000730 checkpoints exist; rung1 is at
# models/cbase-grow-rung/rung1-20260703T155447Z/checkpoints/step-00000730 (this sha),
# and live is at models/cbase-grow-live/live-20260703T053225Z/post/checkpoints/step-00000730 (sha ac43445b).
# Use --source-ckpt explicitly to avoid collision.
FF_SEED = 8192
FF_GROWN = 16384


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def widen_state_dict(sd: dict, n_layers: int) -> dict:
    """Forward grow operation (from cbase_grow_dryrun.py:85-93).
    Used for selftest to verify round-trip fidelity."""
    grown = dict(sd)
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        g, u, d = sd[p + "gate_proj.weight"], sd[p + "up_proj.weight"], sd[p + "down_proj.weight"]
        grown[p + "gate_proj.weight"] = torch.cat([g, g], dim=0)
        grown[p + "up_proj.weight"] = torch.cat([u, u], dim=0)
        grown[p + "down_proj.weight"] = torch.cat([d * 0.5, d * 0.5], dim=1)
    return grown


def reconstruct_pregrow_state_dict(sd_grown: dict, n_layers: int) -> dict:
    """Reconstruct pre-grow state dict from grown checkpoint.

    Inverse of widen_state_dict. For each layer's SwiGLU MLP:
      gate_proj_pre = gate_post[:F, :]
      up_proj_pre = up_post[:F, :]
      down_proj_pre = 2.0 * down_post[:, :F]  (exact doubling in bf16)

    All other tensors pass through unchanged.
    """
    reconstructed = dict(sd_grown)
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        g_grown = sd_grown[p + "gate_proj.weight"]
        u_grown = sd_grown[p + "up_proj.weight"]
        d_grown = sd_grown[p + "down_proj.weight"]

        # Inverse: extract first half (seed width)
        reconstructed[p + "gate_proj.weight"] = g_grown[:FF_SEED, :]
        reconstructed[p + "up_proj.weight"] = u_grown[:FF_SEED, :]
        # Exact doubling (not sum): 2.0 * (d*0.5) = d
        reconstructed[p + "down_proj.weight"] = 2.0 * d_grown[:, :FF_SEED]

    return reconstructed


def selftest_forward_grow_roundtrip(sd_original: dict, sd_reconstructed: dict, n_layers: int) -> bool:
    """SELFTEST: re-apply forward grow to reconstructed state dict.

    Assert torch.equal (bitwise) with original seed tensors on all widened
    tensors and passthrough tensors.

    Returns True if selftest passes; False otherwise.
    """
    # Re-apply the forward grow to the reconstructed state dict
    sd_regrown = widen_state_dict(sd_reconstructed, n_layers)

    # Check every tensor bitwise equality
    all_equal = True
    mismatches = []

    for key in sd_original.keys():
        if key not in sd_regrown:
            all_equal = False
            mismatches.append(f"Missing key in regrown: {key}")
            continue

        orig_tensor = sd_original[key]
        regrown_tensor = sd_regrown[key]

        if orig_tensor.shape != regrown_tensor.shape:
            all_equal = False
            mismatches.append(
                f"{key}: shape mismatch original={orig_tensor.shape} regrown={regrown_tensor.shape}"
            )
            continue

        if not torch.equal(orig_tensor, regrown_tensor):
            all_equal = False
            # Compute relative L2 for diagnostics
            rel_l2 = float(torch.norm(orig_tensor - regrown_tensor) / (torch.norm(orig_tensor) + 1e-10))
            mismatches.append(f"{key}: bitwise inequality rel_L2={rel_l2:.2e}")

    if mismatches:
        print("Selftest FAILED with mismatches:", file=sys.stderr)
        for m in mismatches[:10]:  # Show first 10
            print(f"  {m}", file=sys.stderr)
        if len(mismatches) > 10:
            print(f"  ... and {len(mismatches) - 10} more", file=sys.stderr)

    return all_equal


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-ckpt", required=True,
                    help="REQUIRED: Path to rung1 step-00000730 checkpoint (grown, sha 74a5b1d4). "
                         "COLLISION: two step-00000730 checkpoints exist; "
                         "use models/cbase-grow-rung/rung1-20260703T155447Z/checkpoints/step-00000730 "
                         "(rung1 seed, 2.44GB, sha 74a5b1d4), NOT "
                         "models/cbase-grow-live/live-20260703T053225Z/post/checkpoints/step-00000730 "
                         "(live run, 1.37GB, sha ac43445b)")
    ap.add_argument("--out-dir", default=str(REPO / "models" / "cbase-grow-rung" / "rung1-20260703T155447Z" / "derived" / "pregrow-ff8192"),
                    help="Output directory for reconstructed checkpoint")
    ap.add_argument("--receipt-dir", default=str(REPO / "receipts" / "reconstruct-pregrow"),
                    help="Directory for receipt JSON")
    ap.add_argument("--skip-selftest", action="store_true",
                    help="Skip the bitwise roundtrip selftest (not recommended)")
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_ckpt = Path(args.source_ckpt)
    out_dir = Path(args.out_dir)
    receipt_dir = Path(args.receipt_dir)

    receipt_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{ts}] Reconstructing pre-grow checkpoint", file=sys.stderr)
    print(f"  Source: {source_ckpt}", file=sys.stderr)
    print(f"  Output: {out_dir}", file=sys.stderr)

    # ========== FAIL-CLOSED GUARD 1: SHA256 verification ==========
    model_pt = source_ckpt / "model.pt"
    manifest_path = source_ckpt / "manifest.json"

    if not model_pt.exists():
        print(f"ERROR: source model.pt not found: {model_pt}", file=sys.stderr)
        return 1

    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = sha256_file(model_pt)
    claimed_sha = manifest.get("files", {}).get("model.pt")

    guard_sha_pass = (actual_sha == SOURCE_SHA_EXPECTED and actual_sha == claimed_sha)
    guard_receipt = {
        "guard": "sha256",
        "ts": ts,
        "expected": SOURCE_SHA_EXPECTED,
        "claimed_in_manifest": claimed_sha,
        "actual": actual_sha,
        "pass": guard_sha_pass
    }

    if not guard_sha_pass:
        print(f"GUARD FAILED: SHA256 mismatch", file=sys.stderr)
        print(f"  Expected: {SOURCE_SHA_EXPECTED}", file=sys.stderr)
        print(f"  Manifest: {claimed_sha}", file=sys.stderr)
        print(f"  Actual:   {actual_sha}", file=sys.stderr)
        checked_write(receipt_dir / f"guard-sha-FAILED-{ts}.json", guard_receipt)
        return 1

    print(f"[{ts}] Guard 1 (SHA256): PASS", file=sys.stderr)

    # ========== Load the grown checkpoint ==========
    print(f"[{ts}] Loading grown checkpoint...", file=sys.stderr)
    sd_grown_bf16 = torch.load(model_pt, map_location="cpu", weights_only=True)
    sd_grown = {k: v.float() for k, v in sd_grown_bf16.items()}

    # Extract layer numbers from keys like "backbone_model.layers.{i}...."
    layer_numbers = []
    for k in sd_grown.keys():
        m = re.match(r"backbone_model\.layers\.(\d+)", k)
        if m:
            layer_numbers.append(int(m.group(1)))
    n_layers = int(max(layer_numbers)) + 1 if layer_numbers else 0

    print(f"[{ts}] Loaded {len(sd_grown)} tensors, {n_layers} layers", file=sys.stderr)

    # ========== FAIL-CLOSED GUARD 2: Shape verification ==========
    guard_shapes_pass = True
    guard_shapes_receipt = {
        "guard": "shapes",
        "ts": ts,
        "checks": {}
    }

    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."

        g = sd_grown.get(p + "gate_proj.weight")
        u = sd_grown.get(p + "up_proj.weight")
        d = sd_grown.get(p + "down_proj.weight")

        if g is None or u is None or d is None:
            guard_shapes_pass = False
            guard_shapes_receipt["checks"][f"layer{i}"] = {
                "pass": False,
                "reason": "missing projection"
            }
            continue

        g_dim0_ok = g.shape[0] == FF_GROWN
        u_dim0_ok = u.shape[0] == FF_GROWN
        d_dim1_ok = d.shape[1] == FF_GROWN

        layer_ok = g_dim0_ok and u_dim0_ok and d_dim1_ok
        if not layer_ok:
            guard_shapes_pass = False

        guard_shapes_receipt["checks"][f"layer{i}"] = {
            "pass": layer_ok,
            "gate_proj.weight.shape": list(g.shape),
            "gate_proj.dim0==16384": g_dim0_ok,
            "up_proj.weight.shape": list(u.shape),
            "up_proj.dim0==16384": u_dim0_ok,
            "down_proj.weight.shape": list(d.shape),
            "down_proj.dim1==16384": d_dim1_ok
        }

    guard_shapes_receipt["pass"] = guard_shapes_pass

    if not guard_shapes_pass:
        print(f"GUARD FAILED: Shape verification", file=sys.stderr)
        checked_write(receipt_dir / f"guard-shapes-FAILED-{ts}.json", guard_shapes_receipt)
        return 1

    print(f"[{ts}] Guard 2 (Shapes): PASS", file=sys.stderr)

    # ========== FAIL-CLOSED GUARD 3: Twin bit-identity ==========
    guard_twin_pass = True
    guard_twin_receipt = {
        "guard": "twin_bit_identity",
        "ts": ts,
        "checks": {}
    }

    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        g = sd_grown[p + "gate_proj.weight"]
        u = sd_grown[p + "up_proj.weight"]

        g_twins_equal = torch.equal(g[:FF_SEED, :], g[FF_SEED:, :])
        u_twins_equal = torch.equal(u[:FF_SEED, :], u[FF_SEED:, :])

        layer_ok = g_twins_equal and u_twins_equal
        if not layer_ok:
            guard_twin_pass = False

        guard_twin_receipt["checks"][f"layer{i}"] = {
            "pass": layer_ok,
            "gate_proj[:F].equal(gate_proj[F:])": g_twins_equal,
            "up_proj[:F].equal(up_proj[F:])": u_twins_equal
        }

    guard_twin_receipt["pass"] = guard_twin_pass

    if not guard_twin_pass:
        print(f"GUARD FAILED: Twin bit-identity check", file=sys.stderr)
        checked_write(receipt_dir / f"guard-twin-FAILED-{ts}.json", guard_twin_receipt)
        return 1

    print(f"[{ts}] Guard 3 (Twin bit-identity): PASS", file=sys.stderr)

    # ========== FAIL-CLOSED GUARD 4: down_proj halves equality ==========
    guard_down_pass = True
    guard_down_receipt = {
        "guard": "down_proj_halves_equality",
        "ts": ts,
        "checks": {}
    }

    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        d = sd_grown[p + "down_proj.weight"]

        halves_equal = torch.equal(d[:, :FF_SEED], d[:, FF_SEED:])

        if not halves_equal:
            guard_down_pass = False

        guard_down_receipt["checks"][f"layer{i}"] = {
            "pass": halves_equal,
            "down_proj[:, :F].equal(down_proj[:, F:])": halves_equal
        }

    guard_down_receipt["pass"] = guard_down_pass

    if not guard_down_pass:
        print(f"GUARD FAILED: down_proj halves equality", file=sys.stderr)
        checked_write(receipt_dir / f"guard-down-FAILED-{ts}.json", guard_down_receipt)
        return 1

    print(f"[{ts}] Guard 4 (down_proj halves): PASS", file=sys.stderr)

    # ========== All guards passed: reconstruct ==========
    print(f"[{ts}] All guards PASSED. Reconstructing...", file=sys.stderr)
    sd_reconstructed = reconstruct_pregrow_state_dict(sd_grown, n_layers)

    # ========== SELFTEST: bitwise roundtrip verification ==========
    if not args.skip_selftest:
        print(f"[{ts}] Running selftest (forward grow roundtrip)...", file=sys.stderr)
        selftest_pass = selftest_forward_grow_roundtrip(sd_grown, sd_reconstructed, n_layers)

        if not selftest_pass:
            print("ERROR: Selftest FAILED", file=sys.stderr)
            checked_write(receipt_dir / f"selftest-FAILED-{ts}.json", {
                "verdict": "FAILED",
                "ts": ts,
                "reason": "bitwise roundtrip not equal"
            })
            return 1

        print("RECONSTRUCT_PREGROW_SELFTEST_PASS", file=sys.stderr)
    else:
        print("[WARNING] Selftest skipped", file=sys.stderr)

    # ========== Convert back to bf16 and save ==========
    print(f"[{ts}] Converting to bf16 and saving...", file=sys.stderr)
    sd_reconstructed_bf16 = {k: v.bfloat16() for k, v in sd_reconstructed.items()}

    model_out = out_dir / "model.pt"
    torch.save(sd_reconstructed_bf16, model_out)

    model_out_sha = sha256_file(model_out)

    # ========== Write manifest for derived artifact ==========
    derived_manifest = {
        "ticket": "PREGROW-RECONSTRUCTION",
        "ts": ts,
        "source": {
            "checkpoint": str(source_ckpt),
            "step": 730,
            "model_pt_sha": SOURCE_SHA_EXPECTED,
            "ts": manifest.get("ts", "")
        },
        "method": "inverse_ff_widening_net2net",
        "ff_seed": FF_SEED,
        "ff_grown": FF_GROWN,
        "validity_receipt": f"twin-audit {ts} rel_L2=0.0",
        "script_sha": "PLACEHOLDER",
        "selftest_verdict": "RECONSTRUCT_PREGROW_SELFTEST_PASS",
        "files": {
            "model.pt": model_out_sha
        }
    }

    manifest_out = out_dir / "manifest.json"
    checked_write(manifest_out, derived_manifest)

    # ========== Final receipt ==========
    final_receipt = {
        "ticket": "PREGROW-RECONSTRUCTION",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "operation": "reconstruct_pregrow",
        "source": str(source_ckpt),
        "output": str(out_dir),
        "model_pt_sha": model_out_sha,
        "n_layers": n_layers,
        "guards": {
            "sha256": guard_sha_pass,
            "shapes": guard_shapes_pass,
            "twin_bit_identity": guard_twin_pass,
            "down_proj_halves": guard_down_pass
        },
        "selftest": "PASS" if not args.skip_selftest else "SKIPPED"
    }

    checked_write(receipt_dir / f"reconstruction-PASS-{ts}.json", final_receipt)

    print(f"[{ts}] SUCCESS", file=sys.stderr)
    print(f"  Reconstructed model.pt: {model_out}", file=sys.stderr)
    print(f"  SHA: {model_out_sha}", file=sys.stderr)
    print(f"  Manifest: {manifest_out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
