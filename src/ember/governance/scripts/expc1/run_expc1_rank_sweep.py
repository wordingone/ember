#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""run_expc1_rank_sweep.py -- EXP-C1 rank-sweep harness + B0 8-bit-momentum arm
(P3 memory-wall track, ember issue #207,
docs/research/p3-memory-wall-ledger-20260706.md).

WHAT THIS TESTS (the ledger's own framing, "EXP-A" in the pre-registered
queue, "EXP-C1" as the tick-2 dispatch name):

  The composed P3 design stores Muon momentum in a rank-r SUBSPACE (an
  (out_dim x r) projection P with orthonormal columns, momentum buffer M_r
  kept at shape (r x in_dim) -- the whole memory saving is r*in_dim instead
  of out_dim*in_dim per weight). Applying the update requires lifting M_r
  back into the ambient (out_dim x in_dim) space and orthogonalizing it
  there (polar(P . M_r), the expensive/correct way), OR orthogonalizing the
  small M_r directly in the r-dim coordinate space and lifting the RESULT
  (P . polar(M_r), the cheap way this design actually needs to use). These
  are equal EXACTLY when P is a full square orthonormal basis (r = out_dim
  -- polar decomposition is equivariant under a left orthogonal transform,
  a 5-line proof, verified numerically in --selftest) but are NOT
  guaranteed equal for r < out_dim; how close they stay, and whether
  training quality survives the gap, is the empirical question this file
  answers.

PRE-REGISTRATION (frozen before any run -- see PRE_REGISTRATION dict below
for the machine-checkable copy embedded in every receipt):

  Hypotheses:
    H1 (identity): the relative Frobenius gap between polar(P.M_r) and
      P.polar(M_r) ("identity_gap") is ~0 at r=full (exact, orthogonal
      equivariance) and grows as r shrinks / as P misaligns with M's
      dominant subspace.
    H2 (quality): some rank r < full preserves eval-loss within 2% of the
      full-Muon control over a short matched training window.
    H3 (rho monotonicity): rho -- the fraction of the CONTROL arm's TRUE
      update norm that falls outside a rank-r random subspace -- decreases
      as r grows (a sanity check on the projection mechanism itself, not a
      kill criterion).

  Arms (uniform rank across every Muon-eligible weight matrix; effective
  rank is clamped to that matrix's own out_dim when the requested rank
  exceeds it -- reported per-param, never silently):
    full        -- control: standard full-rank Muon, no projection at all.
                   ALSO the r=full sweep point (see H1 exactness above);
                   no separate run needed, aliased to control's own result.
    r8          -- rank-8 lifted-NS projected Muon momentum.
    r32         -- rank-32 lifted-NS projected Muon momentum.
    r128        -- rank-128 lifted-NS projected Muon momentum.
    B0_r32_int8 -- rank-32 projected Muon, momentum buffer STORED as
                   symmetric per-tensor int8 + fp32 scale between steps
                   (genuine storage dtype round-trip, not injected noise
                   on an fp32 tensor).

  Kill criteria (frozen, embedded in every receipt's per-arm
  "kill_criteria" block; either failing => REJECT for that rank):
    (a) eval_loss_delta_pct_le_2: abs(arm eval_loss_last - control
        eval_loss_last) / abs(control eval_loss_last) * 100 <= 2.0,
        measured at the end of the TIMED window (post-warmup), matched
        step-for-step against control (same init, same batch sequence).
    (b) rho_sustained_le_half: fraction of TIMED-window steps with
        rho > 0.5 must be <= 0.5 ("sustained" = frozen as a bare majority
        of measured steps breaching the 0.5 threshold) -- "projection is
        fiction" per the team-lead's own framing.

  Eval protocol: ONE frozen held-out batch (EVAL_SEED, generated once,
    NEVER drawn into the training batch stream), eval_loss measured before
    any training step (eval_loss_first) and after the full warmup+timed
    window (eval_loss_last). IDENTICAL model init (deep-copied state_dict,
    loaded fresh into every arm's own model instance) and IDENTICAL
    training-batch sequence reused across every arm -- matched control, one
    variable (the Muon momentum projection/quantization scheme).

  Seeds (frozen, never reused): MODEL_SEED, BATCH_GEN_SEED, EVAL_SEED,
    PROJECTION_SEED -- see constants below.

  Scope disclosures (design simplifications, stated plainly, not hidden):
    - The projection subspace P is FIXED for the entire run (frozen at
      init from a QR of a seeded Gaussian). Periodic subspace resampling
      with momentum rotated across subspace switches -- the fuller
      production mechanism the P3 ledger names -- is explicitly OUT OF
      SCOPE for this rank-sweep harness. It tests the static-subspace
      identity/quality question first; subspace-switch dynamics are a
      disclosed follow-on, not exercised here.
    - Targets are synthetic random tokens independent of inputs -- this is
      adequate for a matched-condition optimizer-equivalence test (every
      arm sees literally the same difficulty, since batches are identical
      across arms) but is NOT a language-modeling capability claim.
    - The toy model's output head and token embedding are UNTIED (the
      production c03 config ties them); immaterial to the Muon-eligible
      hidden-weight rank-sweep question this harness tests, since
      embeddings/heads are already routed to AdamW (excluded from Muon)
      either way.
    - VRAM sizing on the (held) live GPU path uses an nvidia-smi subprocess
      call ONLY, NEVER torch.cuda.mem_get_info() -- the P3 ledger's own
      Deviation 2 finding measured a ~17 GiB discrepancy between the two on
      this box (WDDM GPU-memory virtualization), making torch's self-report
      an unsafe sizing basis here.

  Newton-Schulz orthogonalization: the quintic iteration
  (zeropower_via_newtonschulz5 below) is COPIED VERBATIM (byte-identical
  algorithm, not re-derived) from scripts/timeshare_pretrain.py's own
  _zeropower_via_newtonschulz5 -- reused literally since it is the exact
  same math, kept as a self-contained copy (rather than an import) so this
  micro-scale research harness stays decoupled from timeshare_pretrain's
  production config/contract loading machinery.

GOVERNOR / LAUNCH-GATE (never loosened; --dry-run and --selftest touch
  neither CUDA nor nvidia-smi):
  The live path (no flags -- mirrors every other microbench harness in this
  repo, e.g. ember_d6_bf16_momentum_ab.py) requires EMBER_GATE_AUTHORIZED=1
  (env) or refuses closed (status BLOCKED, receipt WRITTEN, bench NOT
  executed). ONE GPU job at a time on this box. NOT fired by this authoring
  session -- the GPU launch is held for the maintainer's explicit
  authorization (one-GPU-job serialization; do not touch any resident
  llama-server / inference process).

MODES:
  --selftest   Pure Python/math + CPU-only torch checks: Newton-Schulz
               orthogonality, the r=full orthogonal-equivariance identity
               (the exact case of H1), projection-matrix orthonormality,
               int8 momentum quantize/dequantize round-trip (genuinely
               lossy, not silently full precision), kill-criteria pure
               logic, receipt-schema round trip. Prints
               EXPC1_RANK_SWEEP_SELFTEST_PASS.
  --dry-run    CPU only, toy H=64 model, 2 warmup + 3 timed steps per arm --
               proves the harness plumbing end-to-end (projection math,
               momentum quantization round-trip, rho/identity_gap
               computation, kill-criteria + verdict logic, receipt JSON
               emission) at zero real-experiment weight. Numbers here are
               NOT research-conclusive (see the receipt's own "note"
               field). Receipt -> receipts/expc1-dryrun-<ts>.json.
  (no flag)    The real run at the live H=256 shape. HARD-FAILS (status
               FAILED, receipt written, no CPU fallback) if CUDA is
               unavailable -- a mode="live" receipt that never touched a GPU
               would be a false claim. Fail-closed device-engagement
               assertions (#216 rule) check every model parameter and batch
               tensor is on a CUDA device at step 1 and the final step of
               every arm; device, torch.version.cuda, GPU name, and
               nvidia-smi memory-used before/after/delta are recorded in the
               receipt and asserted present before it is written. NOT fired
               by this authoring session -- see GOVERNOR / LAUNCH-GATE above.

No git commits from inside this file. No downloads. No founder/user names
anywhere in this file or its receipts. UTF-8 / plain-ASCII source.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))          # scripts/expc1
SCRIPTS_DIR = os.path.dirname(HERE)                         # scripts/
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..")) # repo root
RECEIPTS = os.path.join(REPO_ROOT, "receipts")
sys.path.insert(0, SCRIPTS_DIR)

from receipt_write import checked_write  # noqa: E402  (light; no torch)

# ---------------------------------------------------------------------------
# Frozen constants (pre-registration) -- never change without a new ticket.
# ---------------------------------------------------------------------------

RANKS = [8, 32, 128, "full"]
B0_RANK = 32

MOMENTUM = 0.95
NESTEROV = True
NS_STEPS = 5
MUON_LR = 0.02
ADAMW_LR = 3e-4

MODEL_SEED = 42
BATCH_GEN_SEED = 20260706
EVAL_SEED = 20260707
PROJECTION_SEED = 20260708

EVAL_LOSS_DELTA_PCT_MAX = 2.0
RHO_THRESHOLD = 0.5
RHO_SUSTAINED_FRACTION_MAX = 0.5

# Live shape -- H=256, same transformer family as the cgrow/D6 harnesses.
# NOT fired this authoring session -- GPU launch held for maintainer auth.
LIVE_DIMS = dict(vocab=1000, d_model=256, n_layers=4, n_heads=4, d_ff=1024, seq=64, batch=8)
LIVE_WARMUP, LIVE_TIMED = 5, 20

# CPU dry-run toy shape.
DRY_DIMS = dict(vocab=64, d_model=64, n_layers=2, n_heads=2, d_ff=128, seq=16, batch=4)
DRY_WARMUP, DRY_TIMED = 2, 3

PRE_REGISTRATION = {
    "hypotheses": {
        "H1_identity": "relative Frobenius gap between polar(P.M_r) and P.polar(M_r) "
                       "('identity_gap') is ~0 at r=full (exact, orthogonal equivariance "
                       "of the polar decomposition under a left orthogonal transform) and "
                       "grows as r shrinks / as P misaligns with M's dominant subspace.",
        "H2_quality": "some rank r < full preserves eval-loss within 2%% of the full-Muon "
                       "control over a short matched training window.",
        "H3_rho_monotone": "rho (fraction of the CONTROL arm's true update norm falling "
                       "outside a rank-r random subspace) decreases as r grows -- a sanity "
                       "check on the projection mechanism, not a kill criterion.",
    },
    "arms": {
        "full": "control: standard full-rank Muon, no projection. Also the r=full sweep "
                "point by the exact orthogonal-equivariance identity (verified numerically "
                "in --selftest) -- aliased to control's own result, no separate run.",
        "r8": "rank-8 lifted-NS projected Muon momentum",
        "r32": "rank-32 lifted-NS projected Muon momentum",
        "r128": "rank-128 lifted-NS projected Muon momentum (clamped to a parameter's own "
                "out_dim when out_dim < 128, reported per-param)",
        "B0_r32_int8": "rank-32 lifted-NS projected Muon momentum, with the (r x in_dim) "
                       "momentum buffer STORED as symmetric per-tensor int8 + fp32 scale "
                       "between steps (genuine storage dtype, not injected fp32 noise)",
    },
    "kill_criteria": {
        "eval_loss_delta_pct_le_2": "abs(arm_eval_loss_last - control_eval_loss_last) / "
            "abs(control_eval_loss_last) * 100 <= " + str(EVAL_LOSS_DELTA_PCT_MAX) +
            " at the end of the TIMED window -- REJECT that rank if violated",
        "rho_sustained_le_half": "fraction of TIMED-window steps with rho > " +
            str(RHO_THRESHOLD) + " must be <= " + str(RHO_SUSTAINED_FRACTION_MAX) +
            " -- REJECT ('projection is fiction') if violated",
    },
    "eval_protocol": "one frozen held-out batch (EVAL_SEED, generated once, never drawn "
        "into the training stream); eval_loss measured before any step (eval_loss_first) "
        "and after the full warmup+timed window (eval_loss_last); identical model init and "
        "identical training-batch sequence reused across every arm.",
    "seeds": {"model_seed": MODEL_SEED, "batch_gen_seed": BATCH_GEN_SEED,
              "eval_seed": EVAL_SEED, "projection_seed": PROJECTION_SEED},
    "scope_disclosures": [
        "projection subspace P is FIXED for the entire run (frozen at init) -- periodic "
        "subspace resampling / momentum rotation across subspace switches (the fuller "
        "production mechanism) is OUT OF SCOPE here; disclosed follow-on, not tested.",
        "targets are synthetic random tokens independent of inputs -- adequate for a "
        "matched-condition optimizer-equivalence test, not a language-modeling claim.",
        "toy model's head/embedding are UNTIED (production c03 ties them) -- immaterial "
        "since both are routed to AdamW (excluded from Muon) either way.",
        "VRAM sizing on the (held) live GPU path uses nvidia-smi subprocess ONLY, never "
        "torch.cuda.mem_get_info -- WDDM over-reports ~17 GiB free on this box per the P3 "
        "ledger's Deviation 2 finding.",
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


def _nvidia_smi_free_mib():
    """VRAM sizing for the (held) live path ONLY -- subprocess to nvidia-smi,
    NEVER torch.cuda.mem_get_info (see module docstring / P3 ledger Deviation
    2: WDDM over-reports ~17 GiB free on this box). Never called by
    --dry-run or --selftest."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True)
        return float(out.stdout.strip().splitlines()[0])
    except Exception as e:
        return {"error": str(e)}


def _nvidia_smi_used_mib():
    """Memory-USED sizing for the live path's before/after receipt fields --
    subprocess to nvidia-smi ONLY, same discipline as _nvidia_smi_free_mib
    (never torch.cuda.mem_get_info)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True)
        return float(out.stdout.strip().splitlines()[0])
    except Exception as e:
        return {"error": str(e)}


def _assert_cuda_engaged(model, batch, label: str) -> None:
    """Fail-closed device-engagement assertion (#216 rule): every model
    parameter and every batch tensor must actually be resident on a CUDA
    device. Called at step 1 and at the final step of the live path only --
    never for --dry-run/--selftest, which stay CPU by design."""
    for name, p in model.named_parameters():
        assert p.device.type == "cuda", f"{label}: param {name!r} on {p.device}, expected cuda"
    for t in batch:
        assert t.device.type == "cuda", f"{label}: batch tensor on {t.device}, expected cuda"


# ---------------------------------------------------------------------------
# Newton-Schulz polar-orthogonalization -- copied verbatim from
# scripts/timeshare_pretrain.py::_zeropower_via_newtonschulz5 (see module
# docstring for why this is a self-contained copy, not an import).
# ---------------------------------------------------------------------------

def zeropower_via_newtonschulz5(G, steps: int = NS_STEPS, eps: float = 1e-7):
    """Orthogonalize a 2D matrix via the quintic Newton-Schulz iteration
    (Muon / Bernstein-Newhouse). float32, deterministic matmuls on CPU.
    Pushes the singular values of G toward 1 (semi-orthogonal update)."""
    import torch
    assert G.ndim == 2, "Newton-Schulz operates on 2D matrices only"
    a, b, c = 3.4445, -4.7750, 2.0315
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


# ---------------------------------------------------------------------------
# Micro transformer -- self-contained toy model, same family (attention +
# MLP blocks with 2D hidden weights routed to Muon) as the production model
# this design targets, at a scale small enough for a CPU dry-run.
# ---------------------------------------------------------------------------

def _build_model_class():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class MicroBlock(nn.Module):
        def __init__(self, d_model, n_heads, d_ff):
            super().__init__()
            assert d_model % n_heads == 0, "d_model must divide evenly by n_heads"
            self.n_heads = n_heads
            self.head_dim = d_model // n_heads
            self.ln1 = nn.LayerNorm(d_model)
            self.qkv = nn.Linear(d_model, 3 * d_model, bias=False)
            self.attn_out = nn.Linear(d_model, d_model, bias=False)
            self.ln2 = nn.LayerNorm(d_model)
            self.fc1 = nn.Linear(d_model, d_ff, bias=False)
            self.fc2 = nn.Linear(d_ff, d_model, bias=False)

        def forward(self, x):
            b, t, d = x.shape
            h = self.ln1(x)
            qkv = self.qkv(h)
            q, k, v = qkv.split(d, dim=-1)

            def split_heads(z):
                return z.view(b, t, self.n_heads, self.head_dim).transpose(1, 2)

            q, k, v = split_heads(q), split_heads(k), split_heads(v)
            o = F.scaled_dot_product_attention(q, k, v, is_causal=True)
            o = o.transpose(1, 2).reshape(b, t, d)
            x = x + self.attn_out(o)
            h2 = self.ln2(x)
            x = x + self.fc2(F.gelu(self.fc1(h2)))
            return x

    class MicroTransformer(nn.Module):
        def __init__(self, vocab, d_model, n_layers, n_heads, d_ff, seq):
            super().__init__()
            self.tok_emb = nn.Embedding(vocab, d_model)
            self.pos_emb = nn.Embedding(seq, d_model)
            self.blocks = nn.ModuleList(
                [MicroBlock(d_model, n_heads, d_ff) for _ in range(n_layers)])
            self.ln_f = nn.LayerNorm(d_model)
            # UNTIED head (disclosed simplification, see module docstring) --
            # both are routed to AdamW regardless, immaterial to the Muon
            # rank-sweep question this harness tests.
            self.head = nn.Linear(d_model, vocab, bias=False)

        def forward(self, idx):
            b, t = idx.shape
            pos = torch.arange(t, device=idx.device)
            x = self.tok_emb(idx) + self.pos_emb(pos)[None, :, :]
            for blk in self.blocks:
                x = blk(x)
            x = self.ln_f(x)
            return self.head(x)

    return MicroTransformer


def split_params(model):
    """Route params per the same contract production uses: a 2D weight that
    is NOT an embedding and NOT the head goes to Muon; everything else
    (embeddings, 1D norms, the head) goes to AdamW."""
    muon, adamw = {}, []
    for name, p in model.named_parameters():
        if p.ndim == 2 and not (name.startswith("tok_emb") or name.startswith("pos_emb")
                                 or name.startswith("head")):
            muon[name] = p
        else:
            adamw.append(p)
    return muon, adamw


def make_batch(dims, generator, device=None):
    """Synthetic batch: random tokens, targets independent of inputs (see
    module docstring's scope disclosure on why this is adequate here).
    Generation is always on CPU (the seeded Generator is CPU-bound, keeping
    reproducibility identical whether or not device is set); the result is
    moved to device afterward when one is given."""
    import torch
    vocab, seq, batch = dims["vocab"], dims["seq"], dims["batch"]
    x = torch.randint(1, vocab, (batch, seq), generator=generator)
    y = torch.randint(1, vocab, (batch, seq), generator=generator)
    if device is not None:
        x, y = x.to(device), y.to(device)
    return x, y


def make_projection(out_dim, r, generator, device=None):
    """QR of a seeded Gaussian -> (out_dim, r_eff) matrix with orthonormal
    columns. r_eff = min(r, out_dim) -- clamped, never silently ignored
    (caller records r_eff in the receipt). Generation is always on CPU (the
    seeded Generator is CPU-bound); the result is moved to device afterward
    when one is given."""
    import torch
    r_eff = min(r, out_dim)
    g = torch.randn(out_dim, r_eff, generator=generator)
    Q, _ = torch.linalg.qr(g)
    if device is not None:
        Q = Q.to(device)
    return Q, r_eff


def quantize_int8(t):
    """Symmetric per-tensor int8 quantization. Returns (int8 tensor, float
    scale). Genuine storage dtype -- caller keeps ONLY the int8 tensor +
    scale between steps, dequantizing transiently for compute."""
    import torch
    max_abs = float(t.abs().max())
    scale = max(max_abs, 1e-8) / 127.0
    q = torch.clamp(torch.round(t / scale), -127, 127).to(torch.int8)
    return q, scale


def dequantize_int8(q, scale):
    return q.to(dtype=__import__("torch").float32) * scale


# ---------------------------------------------------------------------------
# Per-arm training loop -- matched control, one variable (the Muon momentum
# projection/quantization scheme). CONTROL must run first; its per-step,
# per-param full updates are cached and handed to every other arm for the
# rho off-subspace diagnostic.
# ---------------------------------------------------------------------------

def run_arm(arm_id, rank_or_full, quantize_momentum, model, batches, eval_batch,
            warmup, timed, control_updates=None, device=None):
    import torch
    import torch.nn.functional as F

    is_control = (rank_or_full == "full")
    muon_params, adamw_params = split_params(model)
    adamw_opt = torch.optim.AdamW(adamw_params, lr=ADAMW_LR)

    require_cuda_engaged = device is not None and torch.device(device).type == "cuda"

    proj_gen = torch.Generator().manual_seed(PROJECTION_SEED)
    state = {}
    rank_effective = {}
    for name, p in muon_params.items():
        out_dim, in_dim = p.shape
        if is_control:
            state[name] = {"M_full": torch.zeros(out_dim, in_dim, device=device)}
            rank_effective[name] = out_dim
        else:
            P, r_eff = make_projection(out_dim, rank_or_full, proj_gen, device=device)
            rank_effective[name] = r_eff
            if quantize_momentum:
                q0, sc0 = quantize_int8(torch.zeros(r_eff, in_dim, device=device))
                state[name] = {"P": P, "M_r_int8": q0, "M_r_scale": sc0}
            else:
                state[name] = {"P": P, "M_r": torch.zeros(r_eff, in_dim, device=device)}

    def eval_loss(batch):
        model.eval()
        with torch.no_grad():
            x, y = batch
            logits = model(x)
            loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1))
        model.train()
        return float(loss.item())

    eval_loss_first = eval_loss(eval_batch)

    train_losses = []
    rho_per_step = []
    identity_gap_per_step = []
    step_updates_cache = [] if is_control else None
    quant_check = None

    n_steps = len(batches)
    for step_idx, (x, y) in enumerate(batches):
        if require_cuda_engaged and (step_idx == 0 or step_idx == n_steps - 1):
            _assert_cuda_engaged(model, (x, y), f"arm={arm_id} step={step_idx}")

        for p in muon_params.values():
            p.grad = None
        adamw_opt.zero_grad(set_to_none=True)

        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1))
        loss.backward()

        step_update_record = {} if is_control else None
        rho_num, rho_den = 0.0, 0.0
        gap_num, gap_den = 0.0, 0.0

        with torch.no_grad():
            for name, p in muon_params.items():
                g = p.grad
                st = state[name]
                if is_control:
                    buf = st["M_full"]
                    buf.mul_(MOMENTUM).add_(g)
                    upd_in = g.add(buf, alpha=MOMENTUM) if NESTEROV else buf
                    O = zeropower_via_newtonschulz5(upd_in, steps=NS_STEPS)
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    p.add_(O, alpha=-MUON_LR * scale)
                    step_update_record[name] = O.detach().clone()
                else:
                    P = st["P"]
                    if quantize_momentum:
                        M_r_prev = dequantize_int8(st["M_r_int8"], st["M_r_scale"])
                    else:
                        M_r_prev = st["M_r"]
                    g_r = P.transpose(0, 1) @ g
                    M_r_new = MOMENTUM * M_r_prev + g_r
                    upd_r_in = g_r.add(M_r_new, alpha=MOMENTUM) if NESTEROV else M_r_new
                    O_r = zeropower_via_newtonschulz5(upd_r_in, steps=NS_STEPS)
                    O_lifted = P @ O_r
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    p.add_(O_lifted, alpha=-MUON_LR * scale)

                    if quantize_momentum:
                        q_new, sc_new = quantize_int8(M_r_new)
                        st["M_r_int8"], st["M_r_scale"] = q_new, sc_new
                        if quant_check is None:
                            dequant_err = float((dequantize_int8(q_new, sc_new) - M_r_new).abs().max())
                            quant_check = {
                                "sample_param": name, "dtype_after_store": str(q_new.dtype),
                                "scale_sample": sc_new, "dequant_max_abs_error": dequant_err,
                                "roundtrip_is_lossy": bool(dequant_err > 0.0),
                            }
                    else:
                        st["M_r"] = M_r_new

                    if control_updates is not None:
                        U_full = control_updates[step_idx][name]
                        proj = P @ (P.transpose(0, 1) @ U_full)
                        off = U_full - proj
                        rho_num += float((off ** 2).sum())
                        rho_den += float((U_full ** 2).sum())

                    lifted_M = P @ M_r_new
                    LHS = zeropower_via_newtonschulz5(lifted_M, steps=NS_STEPS)
                    gap = LHS - O_lifted
                    gap_num += float((gap ** 2).sum())
                    gap_den += float((O_lifted ** 2).sum())

        adamw_opt.step()
        train_losses.append(float(loss.detach().item()))

        if is_control:
            step_updates_cache.append(step_update_record)
        else:
            rho_per_step.append((rho_num / rho_den) ** 0.5 if rho_den > 0 and control_updates is not None else None)
            identity_gap_per_step.append((gap_num / gap_den) ** 0.5 if gap_den > 0 else None)

    eval_loss_last = eval_loss(eval_batch)

    timed_rho = rho_per_step[-timed:] if not is_control else []
    timed_gap = identity_gap_per_step[-timed:] if not is_control else []

    result = {
        "arm": arm_id,
        "is_control": is_control,
        "rank_requested": rank_or_full,
        "rank_effective_per_param": rank_effective,
        "quantize_momentum": bool(quantize_momentum),
        "n_muon": len(muon_params), "n_adamw": len(adamw_params),
        "train_loss_first": round(train_losses[0], 6) if train_losses else None,
        "train_loss_last": round(train_losses[-1], 6) if train_losses else None,
        "train_loss_trajectory": [round(v, 6) for v in train_losses],
        "eval_loss_first": round(eval_loss_first, 6),
        "eval_loss_last": round(eval_loss_last, 6),
        "rho_per_step": [round(v, 6) if v is not None else None for v in rho_per_step],
        "identity_gap_per_step": [round(v, 6) if v is not None else None for v in identity_gap_per_step],
        "rho_timed_window": [round(v, 6) if v is not None else None for v in timed_rho],
        "identity_gap_timed_window": [round(v, 6) if v is not None else None for v in timed_gap],
        "momentum_quant_check": quant_check,
    }
    return result, step_updates_cache


# ---------------------------------------------------------------------------
# Kill criteria + verdict.
# ---------------------------------------------------------------------------

def eval_loss_delta_conjunct(control_eval_last, arm_eval_last):
    denom = max(abs(control_eval_last), 1e-12)
    delta_pct = abs(arm_eval_last - control_eval_last) / denom * 100.0
    return {"value_pct": round(delta_pct, 4), "threshold_pct": EVAL_LOSS_DELTA_PCT_MAX,
            "pass": bool(delta_pct <= EVAL_LOSS_DELTA_PCT_MAX)}


def rho_sustained_conjunct(rho_timed_window):
    valid = [r for r in rho_timed_window if r is not None]
    if not valid:
        return {"fraction_over_threshold": None, "rho_threshold": RHO_THRESHOLD,
                "sustained_fraction_max": RHO_SUSTAINED_FRACTION_MAX, "pass": True,
                "note": "no rho samples available (no control reference supplied)"}
    frac_over = sum(1 for r in valid if r > RHO_THRESHOLD) / len(valid)
    return {"fraction_over_threshold": round(frac_over, 4), "rho_threshold": RHO_THRESHOLD,
            "sustained_fraction_max": RHO_SUSTAINED_FRACTION_MAX,
            "pass": bool(frac_over <= RHO_SUSTAINED_FRACTION_MAX)}


def compute_arm_verdict(arm_id, kill_criteria: dict) -> str:
    all_pass = all(v.get("pass") for v in kill_criteria.values())
    return f"EXPC1_{arm_id}_OK" if all_pass else f"EXPC1_{arm_id}_REJECT"


def score_arm(control_result, arm_result):
    kc = {
        "eval_loss_delta_pct_le_2": eval_loss_delta_conjunct(
            control_result["eval_loss_last"], arm_result["eval_loss_last"]),
        "rho_sustained_le_half": rho_sustained_conjunct(arm_result["rho_timed_window"]),
    }
    verdict = compute_arm_verdict(arm_result["arm"], kc)
    return kc, verdict


# ---------------------------------------------------------------------------
# Sweep orchestration.
# ---------------------------------------------------------------------------

def run_sweep(dims, warmup, timed, device=None):
    import torch

    MicroTransformer = _build_model_class()
    model_kwargs = dict(vocab=dims["vocab"], d_model=dims["d_model"], n_layers=dims["n_layers"],
                         n_heads=dims["n_heads"], d_ff=dims["d_ff"], seq=dims["seq"])

    torch.manual_seed(MODEL_SEED)
    base_model = MicroTransformer(**model_kwargs)
    init_state = copy.deepcopy(base_model.state_dict())

    batch_gen = torch.Generator().manual_seed(BATCH_GEN_SEED)
    batches = [make_batch(dims, batch_gen, device=device) for _ in range(warmup + timed)]
    eval_gen = torch.Generator().manual_seed(EVAL_SEED)
    eval_batch = make_batch(dims, eval_gen, device=device)

    control_model = MicroTransformer(**model_kwargs)
    control_model.load_state_dict(init_state)
    if device is not None:
        control_model = control_model.to(device)
    control_result, control_updates = run_arm(
        "full", "full", False, control_model, batches, eval_batch, warmup, timed,
        control_updates=None, device=device)

    arms = {"full": control_result}
    for r in [8, 32, 128]:
        m = MicroTransformer(**model_kwargs)
        m.load_state_dict(init_state)
        if device is not None:
            m = m.to(device)
        res, _ = run_arm(f"r{r}", r, False, m, batches, eval_batch, warmup, timed,
                          control_updates=control_updates, device=device)
        kc, verdict = score_arm(control_result, res)
        res["kill_criteria"] = kc
        res["verdict"] = verdict
        arms[f"r{r}"] = res

    m = MicroTransformer(**model_kwargs)
    m.load_state_dict(init_state)
    if device is not None:
        m = m.to(device)
    res_b0, _ = run_arm("B0_r32_int8", B0_RANK, True, m, batches, eval_batch, warmup, timed,
                         control_updates=control_updates, device=device)
    kc_b0, verdict_b0 = score_arm(control_result, res_b0)
    res_b0["kill_criteria"] = kc_b0
    res_b0["verdict"] = verdict_b0
    arms["B0_r32_int8"] = res_b0

    return control_result, arms


# ---------------------------------------------------------------------------
# Live GPU run -- NOT fired this authoring session. GOVERNOR / LAUNCH-GATE.
# ---------------------------------------------------------------------------

def run_and_emit_live() -> Path:
    ts = _ts()
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not authorized:
        msg = ("EXPC1_INTERLOCK_REFUSED: requires EMBER_GATE_AUTHORIZED=1 (env) -- one-GPU-"
               "job serialization on this box; GPU launch is held for the maintainer's "
               "explicit authorization (P3 tick-1 dispatch).")
        receipt = {
            "ticket": "EXPC1-RANK-SWEEP", "ts": ts, "mode": "live", "dry_run": False,
            "issue": "#207",
            "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
            "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
            "harness_sha": _harness_sha(),
            "status": "BLOCKED",
            "interlock": {"authorized": False, "detail": msg},
            "pre_registration": PRE_REGISTRATION,
        }
        os.makedirs(RECEIPTS, exist_ok=True)
        path = os.path.join(RECEIPTS, f"expc1-rank-sweep-BLOCKED-{ts}.json")
        checked_write(path, receipt)
        print(f"[expc1-rank-sweep] LAUNCH_BLOCKED: {msg}", flush=True)
        print(f"EXPC1_RANK_SWEEP_DONE status=BLOCKED receipt={path}", flush=True)
        return Path(path)

    # Reachable only under explicit maintainer authorization (never set by
    # this authoring session). VRAM margin check uses nvidia-smi ONLY.
    import torch

    # HARD FAIL if CUDA is unavailable -- no CPU fallback for mode="live".
    # A "live" receipt that never touched a GPU is a false claim; this path
    # writes a FAILED receipt and stops rather than silently running on CPU.
    if not torch.cuda.is_available():
        ts = _ts()
        receipt = {
            "ticket": "EXPC1-RANK-SWEEP", "ts": ts, "mode": "live", "dry_run": False,
            "issue": "#207",
            "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
            "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
            "harness_sha": _harness_sha(),
            "status": "FAILED",
            "failure_reason": "CUDA not available in this process/environment -- the live "
                "path requires CUDA with NO CPU fallback (a mode='live' receipt that never "
                "touched a GPU would be a false claim). Not retried with modifications; this "
                "is itself the plumbing finding.",
            "pre_registration": PRE_REGISTRATION,
        }
        os.makedirs(RECEIPTS, exist_ok=True)
        path = os.path.join(RECEIPTS, f"expc1-rank-sweep-FAILED-{ts}.json")
        checked_write(path, receipt)
        print(f"[expc1-rank-sweep] CUDA_UNAVAILABLE: {receipt['failure_reason']}", flush=True)
        print(f"EXPC1_RANK_SWEEP_DONE status=FAILED receipt={path}", flush=True)
        return Path(path)

    device = torch.device("cuda")
    gpu_name = torch.cuda.get_device_name(device)
    torch_cuda_version = torch.version.cuda
    free_mib = _nvidia_smi_free_mib()
    used_mib_before = _nvidia_smi_used_mib()

    control_result, arms = run_sweep(LIVE_DIMS, LIVE_WARMUP, LIVE_TIMED, device=device)

    torch.cuda.synchronize(device)
    used_mib_after = _nvidia_smi_used_mib()
    used_mib_delta = (
        used_mib_after - used_mib_before
        if isinstance(used_mib_before, (int, float)) and isinstance(used_mib_after, (int, float))
        else None
    )

    ts = _ts()
    receipt = {
        "ticket": "EXPC1-RANK-SWEEP", "ts": ts, "mode": "live", "dry_run": False,
        "issue": "#207",
        "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "OK",
        "device": str(device),
        "torch_version_cuda": torch_cuda_version,
        "gpu_name": gpu_name,
        "nvidia_smi_free_mib_at_start": free_mib,
        "nvidia_smi_memory_used_mib_before": used_mib_before,
        "nvidia_smi_memory_used_mib_after": used_mib_after,
        "nvidia_smi_memory_used_delta_mib": used_mib_delta,
        "dims": LIVE_DIMS, "warmup": LIVE_WARMUP, "timed": LIVE_TIMED,
        "pre_registration": PRE_REGISTRATION,
        "control": control_result,
        "arms": arms,
    }

    # Fail-closed device-engagement field check (#216 rule) BEFORE any
    # artifact write: a live receipt without these fields is invalid by
    # construction. The per-step tensor-residency assertions already ran
    # inside run_arm (step 1 + final step, every arm); this is the
    # receipt-level companion check.
    required_live_fields = [
        "device", "torch_version_cuda", "gpu_name",
        "nvidia_smi_memory_used_mib_before", "nvidia_smi_memory_used_mib_after",
        "nvidia_smi_memory_used_delta_mib",
    ]
    for f in required_live_fields:
        assert receipt.get(f) is not None, f"live receipt missing required field: {f}"
    assert receipt["device"].startswith("cuda"), receipt["device"]

    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"expc1-rank-sweep-{ts}.json")
    checked_write(path, receipt)
    print(f"[expc1-rank-sweep] receipt: {path}", flush=True)
    print(f"EXPC1_RANK_SWEEP_DONE status=OK receipt={path}", flush=True)
    return Path(path)


# ---------------------------------------------------------------------------
# CPU dry-run.
# ---------------------------------------------------------------------------

def run_and_emit_dry() -> Path:
    control_result, arms = run_sweep(DRY_DIMS, DRY_WARMUP, DRY_TIMED)
    ts = _ts()
    receipt = {
        "ticket": "EXPC1-RANK-SWEEP", "ts": ts, "mode": "dry-run", "dry_run": True,
        "issue": "#207",
        "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
        "scope": "CPU plumbing proof only, toy H=64 shape, 2 warmup + 3 timed steps per arm "
                 "-- proves projection math, momentum quantization round-trip, rho/"
                 "identity_gap computation, kill-criteria + verdict logic, and receipt "
                 "shape end-to-end. NOT the real EXP-C1 evidence; per-arm kill_criteria "
                 "values below are plumbing artifacts of a toy 3-step run, not research-"
                 "conclusive. The real run requires the live H=256 shape (LIVE_DIMS) with "
                 "LIVE_WARMUP+LIVE_TIMED=25 steps, held for maintainer GPU authorization.",
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "flags": ["NO torch.cuda.* call anywhere in this mode",
                  "self-contained toy MicroTransformer, no production-module coupling",
                  "control arm run first; per-step per-param full updates cached for every "
                  "other arm's rho off-subspace diagnostic"],
        "dims": DRY_DIMS, "warmup": DRY_WARMUP, "timed": DRY_TIMED,
        "pre_registration": PRE_REGISTRATION,
        "control": control_result,
        "arms": arms,
        "note": "dry-run at toy H=64 scale over 3 timed steps -- per-arm kill_criteria "
                "values are NOT research-conclusive; they demonstrate the harness computes "
                "and gates on them correctly, nothing more.",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"expc1-dryrun-{ts}.json")
    checked_write(path, receipt)
    print(f"[expc1-rank-sweep] dry-run receipt: {path}", flush=True)
    for arm_id, res in arms.items():
        v = res.get("verdict", "N/A (control)")
        print(f"[expc1-rank-sweep] arm {arm_id}: eval_loss_last={res['eval_loss_last']} "
              f"verdict={v}", flush=True)
    print(f"EXPC1_RANK_SWEEP_DRYRUN_DONE receipt={path}", flush=True)
    return Path(path)


# ---------------------------------------------------------------------------
# Selftest -- pure Python/math + CPU-only torch checks (no CUDA anywhere).
# ---------------------------------------------------------------------------

def selftest() -> None:
    import torch

    print("[expc1-rank-sweep] selftest: NS orthogonality + r=full identity + projection "
          "orthonormality + int8 round-trip + kill-criteria logic + receipt schema", flush=True)

    # 1. Newton-Schulz pushes a random matrix toward semi-orthogonality
    #    (singular values -> a band around 1). This fixed 5-term quintic
    #    (Keller Jordan's Muon coefficients) is an APPROXIMATE orthogonalizer
    #    by design -- it does not fully converge to exact orthogonality even
    #    with many more steps (empirically confirmed: 5/10/20/40 steps all
    #    plateau at the same ~0.32 max singular-value deviation for this
    #    matrix, and this file's copy matches timeshare_pretrain.py's own
    #    _zeropower_via_newtonschulz5 bit-for-bit on the same input -- this
    #    is the known behavior of the algorithm, not a harness bug). The
    #    honest check is "pushed into a bounded band around 1", not "near 1".
    torch.manual_seed(0)
    M = torch.randn(16, 12)
    O = zeropower_via_newtonschulz5(M, steps=NS_STEPS)
    svals = torch.linalg.svdvals(O)
    assert float((svals - 1.0).abs().max()) < 0.5, svals
    print(f"  Newton-Schulz semi-orthogonality: singular values within 0.5 of 1.0 "
          f"(min={float(svals.min()):.3f}, max={float(svals.max()):.3f})  PASS")

    # 2. r=full orthogonal-equivariance identity: for a SQUARE random
    #    orthogonal P (r = out_dim), polar(P @ M) == P @ polar(M) exactly
    #    (up to float32 numerical precision). This is the exact case of H1.
    out_dim, in_dim = 10, 14
    M2 = torch.randn(out_dim, in_dim)
    P_square, _ = torch.linalg.qr(torch.randn(out_dim, out_dim))
    lhs = zeropower_via_newtonschulz5(P_square @ M2, steps=NS_STEPS)
    rhs = P_square @ zeropower_via_newtonschulz5(M2, steps=NS_STEPS)
    gap = float((lhs - rhs).abs().max())
    assert gap < 1e-4, gap
    print(f"  r=full orthogonal-equivariance identity: max abs gap={gap:.2e} < 1e-4  PASS")

    # 3. make_projection produces near-orthonormal columns (P.T @ P ~= I_r).
    gen = torch.Generator().manual_seed(PROJECTION_SEED)
    P, r_eff = make_projection(64, 32, gen)
    assert r_eff == 32
    ortho_err = float((P.transpose(0, 1) @ P - torch.eye(32)).abs().max())
    assert ortho_err < 1e-5, ortho_err
    print(f"  make_projection orthonormality: max abs (P^T P - I)={ortho_err:.2e}  PASS")

    # 3b. clamping: requesting a rank larger than out_dim clamps, never
    #     silently ignored (caller records rank_effective_per_param).
    P2, r_eff2 = make_projection(16, 128, gen)
    assert r_eff2 == 16, r_eff2
    print(f"  make_projection clamps r=128 request to out_dim=16 -> r_eff={r_eff2}  PASS")

    # 4. int8 quantize/dequantize round-trip: correct storage dtype, and
    #    genuinely lossy (not silently full precision).
    t = torch.randn(32, 14) * 3.0
    q, scale = quantize_int8(t)
    assert q.dtype == torch.int8, q.dtype
    deq = dequantize_int8(q, scale)
    err = float((deq - t).abs().max())
    assert err > 0.0, "int8 round-trip must be lossy, not silently exact"
    assert err <= scale + 1e-6, (err, scale)
    print(f"  int8 quantize/dequantize: dtype={q.dtype}, max abs error={err:.4f} "
          f"(scale={scale:.4f}), lossy=True  PASS")

    # 5. Kill-criteria pure logic.
    d_ok = eval_loss_delta_conjunct(2.000, 2.010)   # 0.5% delta
    assert d_ok["pass"] is True, d_ok
    d_fail = eval_loss_delta_conjunct(2.000, 2.100)  # 5% delta
    assert d_fail["pass"] is False, d_fail
    print("  eval_loss_delta_conjunct: 0.5%->PASS, 5%->FAIL  PASS")

    r_ok = rho_sustained_conjunct([0.1, 0.2, 0.6, 0.3])   # 1/4 over 0.5
    assert r_ok["pass"] is True, r_ok
    r_fail = rho_sustained_conjunct([0.6, 0.7, 0.2, 0.9])  # 3/4 over 0.5
    assert r_fail["pass"] is False, r_fail
    r_none = rho_sustained_conjunct([None, None])
    assert r_none["pass"] is True, r_none
    print("  rho_sustained_conjunct: minority-over->PASS, majority-over->FAIL, "
          "no-samples->PASS(vacuous)  PASS")

    all_pass = {"a": {"pass": True}, "b": {"pass": True}}
    one_fail = {"a": {"pass": True}, "b": {"pass": False}}
    assert compute_arm_verdict("r32", all_pass) == "EXPC1_r32_OK"
    assert compute_arm_verdict("r32", one_fail) == "EXPC1_r32_REJECT"
    print("  compute_arm_verdict: all-pass->EXPC1_<arm>_OK, any-fail->EXPC1_<arm>_REJECT  PASS")

    # 6. Receipt-shape round trip via the shared schema-floor validator.
    import receipt_check
    synth = {
        "ticket": "EXPC1-RANK-SWEEP", "ts": "20260706T000000Z", "mode": "dry-run",
        "sha_convention": "bytes on disk as-is", "harness_sha": "a" * 64,
        "verdict": "EXPC1_r32_OK",
    }
    findings = receipt_check.validate_receipt(synth)
    assert findings == [], findings
    print("  receipt-shape round trip passes receipt_check schema floor  PASS")

    print("EXPC1_RANK_SWEEP_SELFTEST_PASS")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="EXP-C1 lifted-NS rank-sweep + B0 8-bit-momentum harness "
                    "(P3 memory-wall track, issue #207)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, toy H=64 -- proves plumbing + receipt shape")
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
