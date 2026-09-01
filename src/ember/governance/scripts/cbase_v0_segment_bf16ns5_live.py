# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_v0_segment_bf16ns5_live.py — daemon-exec wrapper for C-BASE v0 pretrain.

This script is exec'd by the train-daemon (operator-local train-daemon server process)
with NO CLI args.  All configuration is injected via environment variables.

RECIPE (frozen — self-consistent C-EFF closure receipt
  receipts/ceff-closure-gate9-shatter-bf16ns5-20260623T132000Z.json +
  the corresponding operator-local ember-run closure record for the same gate)
----------------------------------------------------------------------

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- the daemon/receipt-path citations above and the
EMBER_SHARD_DIR / EMBER_RUN_DIR fallback defaults below carried absolute
drive-letter-rooted / WSL-mount literals pointing at an operator-local tree
outside this repo (no repo-relative default applies). Fallback defaults
dropped to empty string; EMBER_SHARD_DIR / EMBER_RUN_DIR (already the
primary source, set by the daemon dispatch payload) are unaffected. See
receipts/ember-c-scale/land210g-*.
Model:        c03-h1024-d20  (hidden=1024, layers=20, heads=16, vocab=32000, seq=1024)
Precision:    bf16 fwd/bwd (NO QAT, NO torch.compile)
Optimizer:    muon_split_bf16ns5 — muon_split with NS5 orthogonalization matmuls
              running in bf16 (tensor-core path) instead of fp32.
              Monkey-patched via ts._zeropower_via_newtonschulz5 = _zeropower_bf16
              BEFORE ts.main() so every Muon.step() call uses the bf16 variant.
ce_chunk:     1024 (ce_chunk_tokens=1024 via --ce-chunk-tokens 1024)
Grad-ckpt:    True (batch=16 arm; enabled unconditionally in build_v0_model)
Batch:        16, Seq: 1024
WSD:          YES — run_v0_segment calls apply_wsd at every step
From-scratch: YES — no borrowed weights (NC2 own-component)

Env vars
--------
EMBER_GATE_AUTHORIZED     set to "1" by this wrapper (interlock)
EMBER_SHARD_DIR           WSL path to shards-v0 dir (no default; set by the
                          daemon dispatch payload -- empty fails fast downstream)
EMBER_RUN_DIR             checkpoint output dir (no default; set by the
                          daemon dispatch payload -- empty fails fast downstream)
EMBER_SEGMENT_TOKENS      tokens for this segment (default 100000000)
EMBER_SMOKE_TOKENS        if >0 and <EMBER_SEGMENT_TOKENS, cap to this value (default 0)
EMBER_TOTAL_STEPS         WSD schedule denominator; default 100M // (16*1024) = 6103
PYTORCH_CUDA_ALLOC_CONF   defaults to expandable_segments:True

NC2 manifest
------------
After each checkpoint, writes nc2-manifest.json into the checkpoint directory.
Fields: arch, token_count, weight_hashes{model.pt sha256}, training_recipe,
no_borrowed_weights=true.  sha_convention consistent with the checkpoint manifest.
"""
import hashlib
import json
import os
import sys

# ---------------------------------------------------------------------------
# Gate + interlock
# ---------------------------------------------------------------------------
os.environ["EMBER_GATE_AUTHORIZED"] = "1"

# Allocator — reduces fragmentation on large models.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# ---------------------------------------------------------------------------
# Resolve env vars
# ---------------------------------------------------------------------------
_SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
_RUN_DIR = os.environ.get("EMBER_RUN_DIR", "")
_SEGMENT_TOKENS_STR = os.environ.get("EMBER_SEGMENT_TOKENS", "")
_SMOKE_TOKENS_STR = os.environ.get("EMBER_SMOKE_TOKENS", "0")
_TOTAL_STEPS_STR = os.environ.get("EMBER_TOTAL_STEPS", "")
_RESUME_CKPT_DIR = os.environ.get("EMBER_RESUME_CKPT_DIR", "")

# ---------------------------------------------------------------------------
# Derived step counts — batch=16, seq=1024 (frozen recipe)
# ---------------------------------------------------------------------------
_BATCH = 16
_SEQ = 1024
_TOKENS_PER_STEP = _BATCH * _SEQ  # 16384

_segment_tokens = int(_SEGMENT_TOKENS_STR) if _SEGMENT_TOKENS_STR else 100_000_000
_smoke_tokens = int(_SMOKE_TOKENS_STR) if _SMOKE_TOKENS_STR else 0
if _smoke_tokens > 0 and _smoke_tokens < _segment_tokens:
    _segment_tokens = _smoke_tokens

_n_steps = max(1, _segment_tokens // _TOKENS_PER_STEP)

if _TOTAL_STEPS_STR:
    _total_steps = int(_TOTAL_STEPS_STR)
else:
    # 100M-pilot WSD denominator: 100_000_000 // 16384 = 6103
    _total_steps = max(1, 100_000_000 // _TOKENS_PER_STEP)  # 6103

# ---------------------------------------------------------------------------
# Import timeshare_pretrain BEFORE patching (module object must exist first).
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
# issue2015 exact-local-import-end:scripts/timeshare_pretrain.py  # noqa: E402

# ---------------------------------------------------------------------------
# BF16 Newton-Schulz5 — replicated from conv_c03_muon_split_bf16ns5.py.
#
# External contract preserved:
#   - Accepts G (any 2D tensor).
#   - Returns orthogonalized update with the same shape as G.
#   - Returned dtype is G.dtype (bfloat16 on the live path).
#   - ns_steps=5, eps=1e-7 — identical to the original NS5.
#
# PATCH TARGET: ts._zeropower_via_newtonschulz5 (module-level global).
# The _Muon.step() method (timeshare_pretrain line 782) calls
#   upd = _zeropower_via_newtonschulz5(upd, steps=ns_steps)
# as a global name lookup in timeshare_pretrain's namespace.  Replacing
# ts._zeropower_via_newtonschulz5 BEFORE ts.main() causes every subsequent
# Muon.step() call to use this bf16 variant, regardless of whether
# _MUON_CLS has already been cached (the cached class still looks up
# _zeropower_via_newtonschulz5 from the module globals at call time,
# not at class-definition time — Python name resolution semantics).
# ---------------------------------------------------------------------------
def _zeropower_bf16(G, steps: int = 5, eps: float = 1e-7):
    """BF16 Newton-Schulz5 orthogonalization (tensor-core path).

    Identical to timeshare_pretrain._zeropower_via_newtonschulz5 except
    the internal matmuls run in bfloat16 instead of float32.
    External contract: same shape returned; dtype = G.dtype."""
    import torch
    assert G.ndim == 2, "Newton-Schulz operates on 2D matrices only"
    a, b, c = 3.4445, -4.7750, 2.0315
    orig_dtype = G.dtype
    X = G.to(torch.bfloat16)          # BF16 cast — tensor-core path
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
    return X.to(orig_dtype)            # restore caller's dtype


# Monkey-patch the module-level NS5 function BEFORE ts.main() is called.
ts._zeropower_via_newtonschulz5 = _zeropower_bf16

# ---------------------------------------------------------------------------
# NC2 own-component manifest writer.
#
# Called post-checkpoint in the wrapper (after ts.main() returns) if the run
# produced a checkpoint, OR injected into run_v0_segment via a checkpoint hook.
# Written to <ckpt_dir>/nc2-manifest.json alongside manifest.json.
#
# Fields:
#   arch                 — c03-h1024-d20 spec (hidden 1024, layers 20, heads 16,
#                          vocab 32000, seq 1024)
#   token_count          — tokens trained this segment
#   weight_hashes        — {model.pt: sha256} (same sha_convention as manifest.json)
#   training_recipe      — frozen bf16-NS5 recipe identifiers
#   no_borrowed_weights  — true (from-scratch pretrain, no fine-tuning init)
#   sha_convention       — same as checkpoint manifest.json
# ---------------------------------------------------------------------------
_SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
)
_ARCH = {
    "hidden": 1024,
    "layers": 20,
    "heads": 16,
    "vocab": 32000,
    "seq": 1024,
}
_TRAINING_RECIPE = {
    "opt_variant": "muon_split_bf16ns5",
    "precision": "bf16+qat",
    "ce_chunk_tokens": 1024,
    "no_qat": False,
    "qat": "int8-grid fake-quant STE on linear weights (fp19_bench shape); "
           "applied pre-forward per step via run_v0_segment QAT gate; "
           "receipt: receipts/c04-bf16ns5-qat-probe-20260623T155353Z.json "
           "eff_days=0.924 FITS (floor 1.0)",
    "no_compile": True,
    "grad_ckpt": True,
}


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_nc2_manifest(ckpt_dir: str, token_count: int) -> None:
    """Write nc2-manifest.json into ckpt_dir.

    This is an additive file alongside manifest.json; it does NOT modify the
    existing checkpoint manifest (which is already sha-pinned).
    """
    model_pt = os.path.join(ckpt_dir, "model.pt")
    if not os.path.exists(model_pt):
        return  # safety: no checkpoint file yet
    model_sha = _sha256_file(model_pt)
    nc2 = {
        "ticket": "NC2-OWN-COMPONENT-MANIFEST",
        "ts": None,  # filled below
        "arch": _ARCH,
        "token_count": token_count,
        "weight_hashes": {
            "model.pt": model_sha,
        },
        "training_recipe": _TRAINING_RECIPE,
        "no_borrowed_weights": True,
        "sha_convention": _SHA_CONVENTION,
    }
    from datetime import datetime, timezone
    nc2["ts"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(ckpt_dir, "nc2-manifest.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(nc2, f, sort_keys=True, indent=2)


# ---------------------------------------------------------------------------
# Build sys.argv for timeshare_pretrain.main() — the --live path.
# --ce-chunk-tokens 1024: the additive CLI arg wired in timeshare_pretrain.py
# (default 256; this wrapper sets it to 1024 per the frozen recipe).
# ---------------------------------------------------------------------------
_argv = [
    "timeshare_pretrain.py",
    "--live",                              # -> run_v0_segment (WSD + resume + ckpt)
    "--steps", str(_n_steps),             # steps this segment
    "--total-steps", str(_total_steps),   # WSD schedule denominator
    "--shard-dir", _SHARD_DIR,            # shards-v0 dir (real packed uint16 shards)
    "--seed", "42",
    "--segment-id", "cbase-v0-bf16ns5",
    "--ce-chunk-tokens", "1024",          # frozen recipe: ce_chunk_tokens=1024
    "--run-dir", _RUN_DIR,
]

if _RESUME_CKPT_DIR:
    _argv += ["--resume-ckpt", _RESUME_CKPT_DIR]

sys.argv = _argv

# ---------------------------------------------------------------------------
# Run timeshare_pretrain.main() with the patched NS5 and the bf16ns5 argv.
# After main() returns, write NC2 manifests to all checkpoints produced.
# ---------------------------------------------------------------------------
ts.main()

# Post-run: write NC2 manifests for any checkpoints under _RUN_DIR.
# The checkpoint subdirs are run_dir/checkpoints/step-XXXXXXXX/.
import glob as _glob
_ckpt_dirs = sorted(
    _glob.glob(os.path.join(_RUN_DIR, "checkpoints", "step-*"))
)
_tokens_per_ckpt = _n_steps * _BATCH * _SEQ  # approximate (all steps)
for _ckpt in _ckpt_dirs:
    if os.path.isdir(_ckpt):
        _write_nc2_manifest(_ckpt, _tokens_per_ckpt)
