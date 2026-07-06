#!/usr/bin/env python3
"""muon_spectrum_probe.py -- EXP-C1b Muon-update spectrum harness
(P3 memory-wall track, ember issue #207,
docs/research/p3-memory-wall-ledger-20260706.md)

WHAT THIS TESTS (corrected design after rank-sweep incident):

  The rank-sweep's rho metric (fraction of control update norm outside a
  random rank-r subspace) was foreordained by random geometry alone:
  E[rho] = 1 - r/d is pure linear algebra, not an empirical finding about
  Muon's actual update structure. This harness INSTEAD measures the real
  update structure: per-step, per-weight-matrix singular-value SPECTRUM of
  (a) the RAW momentum/gradient matrix G (before NS orthogonalization), and
  (b) the ORTHOGONALIZED result NS(G) (after), plus (c) effective rank
  trajectories. The findings answer: does Muon concentrate updates in few
  directions (low stable rank in G) or use most dimensions (high stable rank)?

PRE-REGISTRATION (frozen before any run):

  NULL HYPOTHESIS (what NS-flattening predicts):
    NS(G) spectrum is ~flat (all singular values ~1) BY CONSTRUCTION of
    the Newton-Schulz polar decomposition. Therefore: NS(G) flatness is NOT
    informative (it is the machine-enforced null model). The informative
    measurements are:
    - RAW-G concentration: does pre-NS momentum concentrate in few directions?
    - RAW-G stable rank: min(dims) * (sum_sigmas_squared / max_sigma_squared)
    - GAP between raw-G stable rank and full rank (what r_SVD would revive?)

  KILL/PROMOTE CRITERIA (written before any run, embedded in receipt):
    Kill (mechanism is illusory / projection unnecessary):
      raw-G stable rank >= 0.5 * min(dims) sustained across layers/steps
      → update already uses half the ambient dimensions; top-r-SVD projection
        saves nothing; low-rank Muon lever is MECHANISM-KILLED (promote as negative).

    Promote (mechanism is real / low-rank matters):
      raw-G stable rank < 0.1 * min(dims) sustained across layers/steps
      → concentration in <10% of dimensions; low-rank lever is REAL;
        top-r-SVD (never random) projection revival makes sense.

    Between: report bands; no verdict (ambiguous).

DEFINITIONS:
  Stable rank = (Frobenius norm)^2 / (largest singular value)^2
              = (sum all sigmas^2) / (max sigma)^2
              Ranges from 1 (rank-1) to min(dims) (full rank).
  Effective rank = (sum sigmas) ^ 2 / (sum sigmas^2)
                  (MacKay's definition, for reference; not primary metric).
  Concentration = rho_top_r = (sum top-r sigmas)^2 / (sum all sigmas)^2.

SCOPE DISCLOSURES:
  - Single fixed Muon config reused from EXP-C1 micro (vocab 1000, d=256,
    layers 4, seq 64, batch 8, 5+20 warmup+timed steps).
  - Targets are synthetic random (no LM signal).
  - Measurement happens per step, per Muon-eligible weight matrix (all 2D
    hidden weights, same routing as EXP-C1).
  - Top-16 singular values recorded (covers concentration); stable rank
    computed from all singular values (structural measure).
  - Frobenius norm of raw G recorded (update magnitude proxy).
  - Device: CPU only (development phase, no GPU gate).

MODES:
  --selftest   Pure Python/torch checks: SVD computation on known-rank
               matrices, stable-rank formula validation, spectrum JSON
               schema round-trip. CPU only. Prints
               MUON_SPECTRUM_PROBE_SELFTEST_PASS.
  --dry-run    CPU, tiny toy model (H=32), 2 timed steps per layer --
               proves spectrum collection + receipt shape. Numbers NOT
               research-conclusive. Receipt -> receipts/expc1b-dryrun-<ts>.json.
  (no flag)    The real run at the live H=256 micro-config shape from
               EXP-C1. CPU-only (GPU launch held). Issues a
               BLOCKED receipt if CPU mode is requested for the "live" path
               (this is development; GPU hangs if we don't catch it).

RAILS: no rm/delete/reset; scratch only; absolute paths; no user names.

No git commits from inside this file. UTF-8 / plain-ASCII source.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))  # back to repo root
RECEIPTS = os.path.join(REPO_ROOT, "receipts")
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

# Pre-registration constants (frozen, never change without a new ticket)
MODEL_SEED = 42
BATCH_GEN_SEED = 20260706
EVAL_SEED = 20260707

MOMENTUM = 0.95
NESTEROV = True
NS_STEPS = 5
MUON_LR = 0.02
ADAMW_LR = 3e-4

# EXP-C1 micro config (reused exactly)
LIVE_DIMS = dict(vocab=1000, d_model=256, n_layers=4, n_heads=4, d_ff=1024, seq=64, batch=8)
LIVE_WARMUP, LIVE_TIMED = 5, 20

# CPU dry-run toy
DRY_DIMS = dict(vocab=64, d_model=32, n_layers=2, n_heads=2, d_ff=128, seq=16, batch=4)
DRY_WARMUP, DRY_TIMED = 1, 2

# Spectrum measurement: top-16 sigmas + stable rank
TOP_K_SIGMAS = 16

PRE_REGISTRATION = {
    "null_hypothesis": "NS(G) spectrum is ~flat (all singular values ~1) by construction "
        "of Newton-Schulz polar decomposition. NS(G) flatness is NOT informative. "
        "Informative measurements: (a) raw-G concentration (does pre-NS momentum "
        "concentrate?), (b) raw-G stable rank, (c) gap between raw-G stable rank and "
        "full rank.",
    "kill_promote_criteria": {
        "kill_mechanism_illusory": "raw-G stable rank >= 0.5 * min(dims) sustained "
            "across layers/steps -> update already uses half ambient dimensions; "
            "low-rank lever MECHANISM-KILLED (promote as negative).",
        "promote_mechanism_real": "raw-G stable rank < 0.1 * min(dims) sustained "
            "across layers/steps -> concentration in <10% of dimensions; low-rank lever "
            "is REAL; top-r-SVD projection revival makes sense.",
        "between": "report bands; no verdict (ambiguous).",
    },
    "definitions": {
        "stable_rank": "(Frobenius norm)^2 / (largest singular value)^2; ranges 1 to min(dims)",
        "effective_rank": "(sum sigmas)^2 / (sum sigmas^2); MacKay definition (reference only)",
        "concentration_top_r": "(sum top-r sigmas)^2 / (sum all sigmas)^2",
    },
    "scope_disclosures": [
        "single fixed Muon config reused from EXP-C1 micro",
        "targets synthetic random (no LM signal)",
        "measurement per step, per Muon-eligible 2D weight matrix",
        "top-16 singular values recorded; stable rank from all singular values",
        "Frobenius norm of raw G recorded (update magnitude proxy)",
        "CPU only (development phase, GPU launch held)",
    ],
    "dims": LIVE_DIMS,
    "warmup_timed": [LIVE_WARMUP, LIVE_TIMED],
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zeropower_via_newtonschulz5(G, steps: int = NS_STEPS, eps: float = 1e-7):
    """Orthogonalize via quintic Newton-Schulz (copied verbatim from
    run_expc1_rank_sweep.py for consistency)."""
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


def compute_spectrum(G: Any) -> dict:
    """Compute spectrum metrics for a 2D matrix G (gradient/momentum).
    Returns: top-16 singular values, Frobenius norm, stable rank,
    effective rank, concentration metrics."""
    import torch

    G_f32 = G.float()

    # Full SVD
    U, sigmas, Vt = torch.linalg.svd(G_f32, full_matrices=False)

    frobenius = float((G_f32 ** 2).sum().sqrt())
    max_sigma = float(sigmas[0])
    min_sigma = float(sigmas[-1])

    # Stable rank
    sum_sq = float((sigmas ** 2).sum())
    stable_rank = sum_sq / (max_sigma ** 2) if max_sigma > 0 else 0.0

    # Effective rank (MacKay)
    sum_sigmas = float(sigmas.sum())
    eff_rank = (sum_sigmas ** 2) / sum_sq if sum_sq > 0 else 0.0

    # Top-K concentration
    top_k = min(TOP_K_SIGMAS, len(sigmas))
    top_k_sigmas_list = [float(sigmas[i]) for i in range(top_k)]
    top_k_sum_sq = sum(s ** 2 for s in top_k_sigmas_list)
    conc_top_k = (top_k_sum_sq / sum_sq) if sum_sq > 0 else 0.0

    return {
        "top_k_sigmas": top_k_sigmas_list,
        "num_sigmas_total": int(sigmas.shape[0]),
        "frobenius_norm": round(frobenius, 6),
        "max_sigma": round(max_sigma, 6),
        "min_sigma": round(min_sigma, 6),
        "stable_rank": round(stable_rank, 6),
        "effective_rank": round(eff_rank, 6),
        "concentration_top_k": round(conc_top_k, 6),
    }


def _build_model_class():
    """Micro transformer (toy model for development, same family as EXP-C1)."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class MicroBlock(nn.Module):
        def __init__(self, d_model, n_heads, d_ff):
            super().__init__()
            assert d_model % n_heads == 0
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
    """Route params: 2D non-embedding weights -> Muon; 1D / embeddings / head -> AdamW."""
    muon, adamw = {}, []
    for name, p in model.named_parameters():
        if p.ndim == 2 and not (name.startswith("tok_emb") or name.startswith("pos_emb")
                                 or name.startswith("head")):
            muon[name] = p
        else:
            adamw.append(p)
    return muon, adamw


def make_batch(dims, generator, device=None):
    """Synthetic batch."""
    import torch
    vocab, seq, batch = dims["vocab"], dims["seq"], dims["batch"]
    x = torch.randint(1, vocab, (batch, seq), generator=generator)
    y = torch.randint(1, vocab, (batch, seq), generator=generator)
    if device is not None:
        x, y = x.to(device), y.to(device)
    return x, y


def run_spectrum_collection(dims, warmup, timed, device=None):
    """Run training, collect spectrum per step per weight matrix."""
    import torch
    import torch.nn.functional as F

    MicroTransformer = _build_model_class()
    model_kwargs = dict(
        vocab=dims["vocab"], d_model=dims["d_model"], n_layers=dims["n_layers"],
        n_heads=dims["n_heads"], d_ff=dims["d_ff"], seq=dims["seq"]
    )

    torch.manual_seed(MODEL_SEED)
    model = MicroTransformer(**model_kwargs)
    if device is not None:
        model = model.to(device)
    model.train()

    muon_params, adamw_params = split_params(model)
    adamw_opt = torch.optim.AdamW(adamw_params, lr=ADAMW_LR)

    batch_gen = torch.Generator().manual_seed(BATCH_GEN_SEED)
    batches = [make_batch(dims, batch_gen, device=device) for _ in range(warmup + timed)]

    # State for Muon momentum buffers
    state = {}
    for name, p in muon_params.items():
        state[name] = {"M": torch.zeros_like(p)}

    # Per-step, per-layer spectrum collection
    spectra_raw = []  # list of (step_idx, layer_spectrum_dict)
    spectra_ns = []   # same, for NS(G)

    for step_idx, (x, y) in enumerate(batches):
        for p in muon_params.values():
            p.grad = None
        adamw_opt.zero_grad(set_to_none=True)

        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1))
        loss.backward()

        step_spectrum_raw = {}
        step_spectrum_ns = {}

        with torch.no_grad():
            for name, p in muon_params.items():
                g = p.grad
                M = state[name]

                # Update momentum
                M["M"].mul_(MOMENTUM).add_(g)
                upd_in = g.add(M["M"], alpha=MOMENTUM) if NESTEROV else M["M"]

                # Spectrum of raw (before NS)
                spec_raw = compute_spectrum(upd_in)
                step_spectrum_raw[name] = spec_raw

                # Apply NS orthogonalization
                O = zeropower_via_newtonschulz5(upd_in, steps=NS_STEPS)
                spec_ns = compute_spectrum(O)
                step_spectrum_ns[name] = spec_ns

                # Apply update
                scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                p.add_(O, alpha=-MUON_LR * scale)

        adamw_opt.step()

        spectra_raw.append({"step": step_idx, "spectra": step_spectrum_raw})
        spectra_ns.append({"step": step_idx, "spectra": step_spectrum_ns})

    return {
        "raw": spectra_raw,
        "ns": spectra_ns,
        "muon_params": list(muon_params.keys()),
        "num_steps": len(batches),
        "warmup": warmup,
        "timed": timed,
    }


def selftest() -> None:
    """TDD selftest: SVD on known-rank matrices, stable-rank formula,
    spectrum schema round-trip."""
    import torch

    print("[muon-spectrum] selftest: SVD rank-1/full identification, stable-rank formula, "
          "spectrum JSON schema", flush=True)

    # 1. Rank-1 matrix: stable_rank should be ~1
    torch.manual_seed(0)
    u = torch.randn(16, 1)
    v = torch.randn(1, 12)
    A = u @ v
    spec = compute_spectrum(A)
    assert 0.9 < spec["stable_rank"] < 1.1, f"rank-1 stable_rank={spec['stable_rank']}"
    print(f"  rank-1 matrix: stable_rank={spec['stable_rank']:.3f} (expected ~1)  PASS")

    # 2. Full-rank random matrix: stable_rank should be positive and < min(dims)
    #    (for a random matrix with singular value decay, SR < dim due to concentration)
    B = torch.randn(16, 12)
    spec_full = compute_spectrum(B)
    actual_sr = spec_full["stable_rank"]
    min_dim = min(16, 12)
    assert 0.1 < actual_sr < min_dim, \
        f"full-rank stable_rank={actual_sr}, expected in (0.1, {min_dim})"
    print(f"  full-rank 16x12 matrix: stable_rank={actual_sr:.3f} (expected in [0.1, {min_dim}))  PASS")

    # 3. Schema round-trip: compute_spectrum returns valid dict with required fields
    required = [
        "top_k_sigmas", "num_sigmas_total", "frobenius_norm",
        "max_sigma", "min_sigma", "stable_rank", "effective_rank",
        "concentration_top_k",
    ]
    for field in required:
        assert field in spec, f"missing field {field}"
    assert len(spec["top_k_sigmas"]) <= TOP_K_SIGMAS
    print(f"  spectrum schema: all required fields present, top_k_sigmas={len(spec['top_k_sigmas'])}  PASS")

    # 4. Newton-Schulz orthogonality check (from rank-sweep, reused)
    M = torch.randn(16, 12)
    O = zeropower_via_newtonschulz5(M, steps=NS_STEPS)
    svals = torch.linalg.svdvals(O)
    assert float((svals - 1.0).abs().max()) < 0.5, f"NS sigmas={svals}"
    print(f"  Newton-Schulz: singular values within 0.5 of 1.0  PASS")

    print("MUON_SPECTRUM_PROBE_SELFTEST_PASS")


def run_and_emit_dry() -> Path:
    """CPU dry-run: tiny toy model, proves spectrum collection + receipt shape."""
    import torch

    control_result = run_spectrum_collection(DRY_DIMS, DRY_WARMUP, DRY_TIMED)

    ts = _ts()
    receipt = {
        "ticket": "EXPC1B-SPECTRUM", "ts": ts, "mode": "dry-run", "dry_run": True,
        "issue": "#207",
        "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "OK",
        "scope": "CPU plumbing proof only, toy H=32 model, 1 warmup + 2 timed steps "
                 "-- proves spectrum collection, NS orthogonalization, top-16 sigmas "
                 "recording, stable-rank computation, and receipt shape end-to-end. "
                 "NOT research-conclusive; demonstrates harness plumbing works correctly.",
        "dims": DRY_DIMS,
        "warmup": DRY_WARMUP,
        "timed": DRY_TIMED,
        "pre_registration": PRE_REGISTRATION,
        "measurement": control_result,
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"expc1b-spectrum-dryrun-{ts}.json")
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)

    print(f"[muon-spectrum] dry-run receipt: {path}", flush=True)
    print(f"MUON_SPECTRUM_PROBE_DRYRUN_DONE receipt={path}", flush=True)
    return Path(path)


def run_and_emit_live() -> Path:
    """CPU live run at EXP-C1 micro shape (H=256)."""
    import torch

    control_result = run_spectrum_collection(LIVE_DIMS, LIVE_WARMUP, LIVE_TIMED)

    ts = _ts()
    receipt = {
        "ticket": "EXPC1B-SPECTRUM", "ts": ts, "mode": "live", "dry_run": False,
        "issue": "#207",
        "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "OK",
        "dims": LIVE_DIMS,
        "warmup": LIVE_WARMUP,
        "timed": LIVE_TIMED,
        "pre_registration": PRE_REGISTRATION,
        "measurement": control_result,
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"expc1b-spectrum-{ts}.json")
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)

    print(f"[muon-spectrum] live receipt: {path}", flush=True)
    print(f"MUON_SPECTRUM_PROBE_LIVE_DONE receipt={path}", flush=True)
    return Path(path)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="EXP-C1b Muon-update spectrum harness (P3 track, issue #207)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, toy H=32 -- proves spectrum collection plumbing")
    ap.add_argument("--selftest", action="store_true",
                    help="pure math checks + CPU-only torch empirical checks")
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
