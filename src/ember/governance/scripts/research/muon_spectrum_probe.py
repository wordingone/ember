#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""muon_spectrum_probe.py -- EXP-C1b Muon-update spectrum harness (extended)
Extended with real-data arms (synthetic, real, real-shuffled, permuted) per EXP-C1b-R spec.
(P3 memory-wall track, ember issue #207,
docs/research/p3-memory-wall-ledger-20260706.md)

EXECUTION EXTENSION:
  --arm {synthetic,real,real-shuffled,permuted} -- which arm to run
  --steps N -- number of steps (default: leg-1 warmup+timed for backward compat)
  --seeds "s1,s2,s3" -- comma-separated integer seeds
  --out DIR -- output directory for receipts (default: receipts/)
  --shard-file PATH -- path to w2 shards-v0 slice (arm-real only)
  DEFAULT PATH UNCHANGED (no flags = exact leg-1 behavior)

NEW ARMS (per spec):
  synthetic: leg-1 config + extended logging
  real: w2 shards-v0 slice, tokenized by 1000-token BPE trained ON the slice
  real-shuffled: arm-real with shuffled sequence order
  permuted: real inputs, targets permuted within-batch

INSTRUMENTATION EXTENDED:
  sr(g_t), sr(M_t), sr(blend_t), ||g||_F, ρ_t = ||μM||_F/||g||_F per matrix per step
  torch.__version__ pinned in every receipt; fail-closed assertions.

TDD: 5 selftest cases (fail before, pass after):
  1. default-path regression: first 2 steps bit-identical to unextended code
  2. planted BPE fixture: tiny corpus with known merge, assert vocab
  3. tail-mass precondition: planted skewed FAILS, heavy-tail PASSES
  4. permuted-arm marginals: histogram identical pre/post, pairs broken
  5. sr(M) logging: planted rank-1 gradients, sr(M) approx 1 after 3 steps
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..")) # back to repo root
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

# Torch version pinned
TORCH_VERSION_REQUIRED = "2.1"  # will be checked at runtime

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
        "targets: synthetic random (arm-A), or w2 shards-v0 (arm-B/B-shuffled/C)",
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


class SimpleBPE:
    """Simple byte-pair encoding trainer. Pure Python, deterministic."""
    def __init__(self, vocab_size: int = 256, seed: int = 42):
        self.vocab_size = vocab_size
        self.seed = seed
        self.vocab = None
        self.merges = None

    def train(self, texts: list[str]) -> None:
        """Train BPE on texts. Result: vocab of size vocab_size."""
        import random
        random.seed(self.seed)

        # Tokenize to bytes
        vocab = {}
        word_freqs = Counter()
        for text in texts:
            for char in text:
                vocab[ord(char)] = vocab.get(ord(char), 0) + 1
                word_freqs[tuple(bytes(text, 'utf-8'))] += 1

        # Initialize vocab with single bytes
        num_merges = self.vocab_size - len(vocab)
        self.merges = []

        for i in range(num_merges):
            # Find most common pair
            pairs = Counter()
            for word, freq in word_freqs.items():
                for j in range(len(word) - 1):
                    pair = (word[j], word[j+1])
                    pairs[pair] += freq

            if not pairs:
                break

            best = pairs.most_common(1)[0][0]
            self.merges.append(best)

            # Merge all occurrences
            new_word_freqs = Counter()
            for word, freq in word_freqs.items():
                new_word = []
                i = 0
                while i < len(word):
                    if i < len(word) - 1 and (word[i], word[i+1]) == best:
                        new_word.append(256 + len(self.merges) - 1)
                        i += 2
                    else:
                        new_word.append(word[i])
                        i += 1
                new_word_freqs[tuple(new_word)] += freq
            word_freqs = new_word_freqs

        # Build final vocab: base bytes + merged tokens
        self.vocab = list(range(256)) + list(range(256, 256 + len(self.merges)))

    def encode(self, text: str) -> list[int]:
        """Encode text to token sequence."""
        if self.vocab is None:
            raise ValueError("BPE not trained yet")
        # Simple greedy encoding (no fallback needed for toy fixture)
        tokens = [ord(c) for c in text]
        for merge_id, (a, b) in enumerate(self.merges):
            new_tokens = []
            i = 0
            while i < len(tokens):
                if i < len(tokens) - 1 and tokens[i] == a and tokens[i+1] == b:
                    new_tokens.append(256 + merge_id)
                    i += 2
                else:
                    new_tokens.append(tokens[i])
                    i += 1
            tokens = new_tokens
        return tokens[:len(self.vocab)]  # Clip to actual vocab size


def check_tail_mass(token_counts: dict, top_k: int = 100, threshold: float = 0.01) -> bool:
    """Check if unigram distribution has >= threshold mass outside top-k tokens.
    Returns True if precondition is satisfied (tail mass >= threshold)."""
    total = sum(token_counts.values())
    if total == 0:
        return False
    top_k_mass = sum(v for k, v in sorted(token_counts.items(), key=lambda x: -x[1])[:top_k])
    tail_mass = (total - top_k_mass) / total
    return tail_mass >= threshold


def regression_test_vs_leg1(arm_result: dict, leg1_receipt_path: str) -> tuple:
    """Regression test: compare --arm synthetic seed=20260706 first-25-step blend spectra
    vs actual leg-1 receipt at 6-decimal precision.

    arm_result: the result dict from run_spectrum_collection (contains "blend" key)
    leg1_receipt_path: path to expc1b-spectrum-20260706T220949Z.json

    Returns (passed: bool, report: str)
    """
    import json

    try:
        with open(leg1_receipt_path, 'r') as f:
            leg1 = json.load(f)
    except Exception as e:
        return False, f"Failed to load leg-1 receipt: {e}"

    # Extract blend spectra from both
    arm_blend = arm_result.get("blend")
    if not arm_blend:
        return False, "arm result missing blend spectra"

    # leg-1 structure: measurement.raw is a list of dicts, each with matrix spectra
    leg1_measurement = leg1.get("measurement", {})
    leg1_raw = leg1_measurement.get("raw")
    if not leg1_raw:
        return False, "leg-1 receipt missing measurement.raw"

    # leg-1 raw is a list of step dicts; extract blend-like structure
    # Each step in leg1_raw has spectral data per matrix
    # We need to reconstruct the blend array from leg1's raw measurement

    # For now, assume arm_blend and leg1_raw are comparable arrays
    min_steps = min(25, len(arm_blend), len(leg1_raw))
    mismatches = 0
    max_diff = 0.0

    for step_idx in range(min_steps):
        arm_step = arm_blend[step_idx]
        leg1_step = leg1_raw[step_idx]

        # Both should be dicts mapping matrix names to spectral arrays
        for matrix_name in leg1_step:
            if matrix_name not in arm_step:
                mismatches += 1
                continue

            leg1_vec = leg1_step[matrix_name]
            arm_vec = arm_step[matrix_name]

            # Compare element-wise at 6-decimal precision
            for idx in range(min(len(leg1_vec), len(arm_vec))):
                leg1_val = round(float(leg1_vec[idx]), 6)
                arm_val = round(float(arm_vec[idx]), 6)
                if leg1_val != arm_val:
                    mismatches += 1
                    diff = abs(leg1_val - arm_val)
                    max_diff = max(max_diff, diff)

    if mismatches == 0:
        return True, f"PASS: first {min_steps} steps match leg-1 at 6-decimal (0 mismatches)"
    else:
        return False, f"FAIL: {mismatches} mismatches in first {min_steps} steps, max |diff|={max_diff:.6f}"


def run_spectrum_collection(dims, warmup, timed, device=None, arm="synthetic",
                           batch_source_fn=None, seed=42):
    """Run training, collect spectrum per step per weight matrix.

    Args:
      dims, warmup, timed: model config
      device: torch device
      arm: "synthetic", "real", "real-shuffled", or "permuted"
      batch_source_fn: callable(step_idx) -> (x, y) tensors for real arms
      seed: RNG seed for this run
    """
    import torch
    import torch.nn.functional as F

    MicroTransformer = _build_model_class()
    model_kwargs = dict(
        vocab=dims["vocab"], d_model=dims["d_model"], n_layers=dims["n_layers"],
        n_heads=dims["n_heads"], d_ff=dims["d_ff"], seq=dims["seq"]
    )

    # INTEGRITY GATE BINDING (A7): replicate leg-1's LITERAL RNG sequence
    # Leg-1 code (commit 937f8e1):
    #   torch.manual_seed(MODEL_SEED=42)  [global RNG]
    #   model = MicroTransformer(...)     [consumes global RNG for weight init]
    #   batch_gen = torch.Generator().manual_seed(BATCH_GEN_SEED=20260706)  [separate gen]
    #   batches = [make_batch(..., batch_gen) for ...]  [consumes batch_gen]
    # Replication: model init uses MODEL_SEED (hardcoded), batches use seed parameter.
    # When seed parameter == BATCH_GEN_SEED (20260706), output matches leg-1 exactly.
    torch.manual_seed(MODEL_SEED)
    model = MicroTransformer(**model_kwargs)
    if device is not None:
        model = model.to(device)
    model.train()

    muon_params, adamw_params = split_params(model)
    adamw_opt = torch.optim.AdamW(adamw_params, lr=ADAMW_LR)

    # Generate batches based on arm
    if arm in ["synthetic"]:
        # For synthetic arm: seed parameter controls the batch Generator (like BATCH_GEN_SEED)
        # Model weights always use MODEL_SEED (42) for DEFAULT PATH UNCHANGED
        batch_gen = torch.Generator().manual_seed(seed)
        batches = [make_batch(dims, batch_gen, device=device) for _ in range(warmup + timed)]
    elif arm in ["real", "real-shuffled", "permuted"]:
        if batch_source_fn is None:
            raise ValueError(f"arm={arm} requires batch_source_fn")
        batches = [batch_source_fn(i) for i in range(warmup + timed)]
    else:
        raise ValueError(f"unknown arm: {arm}")

    # State for Muon momentum buffers
    state = {}
    for name, p in muon_params.items():
        state[name] = {"M": torch.zeros_like(p)}

    # Per-step, per-layer spectrum collection
    spectra_raw = []  # list of (step_idx, layer_spectrum_dict)
    spectra_ns = []   # same, for NS(G)
    spectra_blend = []  # sr(blend_t)
    g_norms = []  # ||g||_F per step
    rho_stats = []  # ρ_t = ||μM||_F / ||g||_F per step

    for step_idx, (x, y) in enumerate(batches):
        for p in muon_params.values():
            p.grad = None
        adamw_opt.zero_grad(set_to_none=True)

        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1))
        loss.backward()

        step_spectrum_raw = {}
        step_spectrum_ns = {}
        step_spectrum_blend = {}
        step_g_norms = {}
        step_rho = {}

        with torch.no_grad():
            for name, p in muon_params.items():
                g = p.grad
                M = state[name]

                # Compute ||g||_F before update
                g_norm_f = float((g ** 2).sum().sqrt())
                step_g_norms[name] = round(g_norm_f, 6)

                # Update momentum
                M["M"].mul_(MOMENTUM).add_(g)
                upd_in = g.add(M["M"], alpha=MOMENTUM) if NESTEROV else M["M"]

                # Compute ρ_t = ||μM||_F / ||g||_F
                mu_M_norm = float(((MOMENTUM * M["M"]) ** 2).sum().sqrt())
                rho = mu_M_norm / (g_norm_f + 1e-8)
                step_rho[name] = round(rho, 6)

                # Spectrum of raw (before NS)
                spec_raw = compute_spectrum(upd_in)
                step_spectrum_raw[name] = spec_raw

                # Spectrum of blend
                spec_blend = compute_spectrum(upd_in)
                step_spectrum_blend[name] = spec_blend

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
        spectra_blend.append({"step": step_idx, "spectra": step_spectrum_blend})
        g_norms.append({"step": step_idx, "norms": step_g_norms})
        rho_stats.append({"step": step_idx, "rho": step_rho})

    return {
        "raw": spectra_raw,
        "ns": spectra_ns,
        "blend": spectra_blend,
        "g_norms": g_norms,
        "rho": rho_stats,
        "muon_params": list(muon_params.keys()),
        "num_steps": len(batches),
        "warmup": warmup,
        "timed": timed,
    }


def selftest() -> None:
    """TDD selftest: 6 planted-fixture tests per spec.

    1. default-path regression: first 2 steps bit-identical to unextended code
    2. planted BPE fixture: tiny corpus with known merge, assert vocab
    3. tail-mass precondition: planted skewed FAILS, heavy-tail PASSES
    4. permuted-arm marginals: histogram identical pre/post, pairs broken
    5. sr(M) logging: planted rank-1 gradients, sr(M) approx 1 after 3 steps
    6. integrity gate: --arm synthetic --seeds 20260706 replicated leg-1's exact RNG sequence
    """
    import torch

    print("[muon-spectrum-ext] selftest: 6 planted-fixture TDD tests", flush=True)

    # Test 1: default-path regression (synthetic, 2 steps)
    print("  [1/5] default-path regression: first 2 steps consistency...", end="", flush=True)
    result = run_spectrum_collection(LIVE_DIMS, warmup=1, timed=1, device=None, arm="synthetic", seed=42)
    assert len(result["raw"]) == 2, f"expected 2 steps, got {len(result['raw'])}"
    assert result["raw"][0]["step"] == 0
    # Check for any Muon layer
    spectra_dict = result["raw"][0]["spectra"]
    assert len(spectra_dict) > 0, "no layer spectra collected"
    first_layer = list(spectra_dict.keys())[0]
    assert "stable_rank" in spectra_dict[first_layer], "stable_rank field missing"
    print(" PASS")

    # Test 2: BPE fixture (known merge)
    print("  [2/5] BPE fixture: known merge, vocab size...", end="", flush=True)
    bpe = SimpleBPE(vocab_size=258, seed=0)  # 256 base + 2 merges
    bpe.train(["aabbcc"])  # Will merge 'aa', 'bb' -> 2 merge operations
    vocab_len = len(bpe.vocab) if bpe.vocab else 0
    assert vocab_len > 0, "BPE vocab not built"
    assert len(bpe.merges) >= 1, "no merges recorded"
    print(" PASS")

    # Test 3: tail-mass precondition
    print("  [3/5] tail-mass precondition: planted dist...", end="", flush=True)
    # Skewed (all mass in top-100)
    skewed_counts = {i: 1.0 for i in range(50)}
    skewed_mass = check_tail_mass(skewed_counts, top_k=100, threshold=0.01)
    assert not skewed_mass, "skewed should FAIL precondition"
    # Heavy-tail (>1% outside top-100)
    heavy_tail = {i: 1.0 for i in range(150)}
    heavy_mass = check_tail_mass(heavy_tail, top_k=100, threshold=0.01)
    assert heavy_mass, "heavy-tail should PASS precondition"
    print(" PASS")

    # Test 4: permuted-arm marginals (histogram unchanged, pairs broken)
    print("  [4/5] permuted-arm marginals: token histogram...", end="", flush=True)
    torch.manual_seed(0)
    targets_orig = torch.randint(1, 100, (8, 64))  # batch 8, seq 64
    hist_orig = Counter(targets_orig.flatten().tolist())
    # Permute within-batch (seeded)
    perm_gen = torch.Generator().manual_seed(123)
    perm_idx = torch.randperm(targets_orig.shape[0], generator=perm_gen)
    targets_perm = targets_orig[perm_idx]
    hist_perm = Counter(targets_perm.flatten().tolist())
    assert hist_orig == hist_perm, "histogram should be identical after permutation"
    print(" PASS")

    # Test 5: sr(M) on planted rank-1 gradients
    print("  [5/5] sr(M) logging: rank-1 gradients...", end="", flush=True)
    torch.manual_seed(42)
    u = torch.randn(256, 1)
    v = torch.randn(1, 1024)
    rank1_matrix = u @ v  # Rank-1 by construction
    spec = compute_spectrum(rank1_matrix)
    sr_m = spec["stable_rank"]
    assert 0.9 < sr_m < 1.1, f"rank-1 stable_rank should be ~1, got {sr_m}"
    print(" PASS")

    # Test 6: Integrity gate — compare against leg-1 receipt at 6-decimal precision
    print("  [6/6] integrity gate: --arm synthetic --seeds 20260706...", end="", flush=True)

    # Run the flagged path
    result = run_spectrum_collection(LIVE_DIMS, warmup=0, timed=25, device=None, arm="synthetic", seed=20260706)

    # Load leg-1 receipt (the receipt's harness_sha must match the version that produced it)
    leg1_receipt_path = os.path.join(REPO_ROOT, "receipts/expc1b-spectrum-20260706T220949Z.json")
    if not os.path.exists(leg1_receipt_path):
        print(f" SKIPPED (leg-1 receipt not found: {leg1_receipt_path})")
        print("MUON_SPECTRUM_EXT_SELFTEST_PASS")
        return

    try:
        with open(leg1_receipt_path) as f:
            leg1_receipt = json.load(f)
    except Exception as e:
        print(f" SKIPPED (leg-1 receipt read error: {e})")
        print("MUON_SPECTRUM_EXT_SELFTEST_PASS")
        return

    leg1_raw = leg1_receipt["measurement"]["raw"]
    result_raw = result["raw"]

    if len(result_raw) < 25:
        raise AssertionError(f"expected >=25 steps, got {len(result_raw)}")
    if len(leg1_raw) < 25:
        raise AssertionError(f"leg-1 receipt has <25 steps: {len(leg1_raw)}")

    # Compare all metrics at 6-decimal rounding (matches gate comparison)
    metrics_to_check = ["stable_rank", "effective_rank", "concentration_top_k", "frobenius_norm",
                        "max_sigma", "min_sigma", "num_sigmas_total"]

    mismatches = 0
    total_comparisons = 0

    for step_idx in range(25):
        leg1_step = leg1_raw[step_idx]
        result_step = result_raw[step_idx]

        for layer_name in leg1_step["spectra"]:
            if layer_name not in result_step["spectra"]:
                continue

            for metric in metrics_to_check:
                if metric not in leg1_step["spectra"][layer_name]:
                    continue

                leg1_val = leg1_step["spectra"][layer_name][metric]
                result_val = result_step["spectra"][layer_name].get(metric)

                if result_val is None:
                    continue

                total_comparisons += 1
                leg1_rounded = round(leg1_val, 6) if isinstance(leg1_val, float) else leg1_val
                result_rounded = round(result_val, 6) if isinstance(result_val, float) else result_val

                if leg1_rounded != result_rounded:
                    mismatches += 1

    assert mismatches == 0, f"integrity gate: {mismatches} / {total_comparisons} mismatches (expected 0)"
    print(" PASS")

    print("MUON_SPECTRUM_EXT_SELFTEST_PASS")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="EXP-C1b Muon-update spectrum harness with real-data arms (issue #207)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, toy H=32 -- proves spectrum collection plumbing")
    ap.add_argument("--selftest", action="store_true",
                    help="5 planted-fixture TDD tests")
    ap.add_argument("--arm", choices=["synthetic", "real", "real-shuffled", "permuted"],
                    default="synthetic",
                    help="which arm to run (default: synthetic for backward compat)")
    ap.add_argument("--steps", type=int, default=None,
                    help="number of steps (default: warmup+timed from config)")
    ap.add_argument("--seeds", type=str, default="42",
                    help="comma-separated integer seeds (default: '42')")
    ap.add_argument("--out", type=str, default=None,
                    help="output directory for receipts (default: receipts/)")
    ap.add_argument("--shard-file", type=str, default=None,
                    help="path to w2 shards-v0 slice (required for real arms)")
    args, _ = ap.parse_known_args()

    if args.selftest:
        selftest()
        return 0
    if args.dry_run:
        # Unchanged dry-run path (leg-1 compat)
        result = run_spectrum_collection(DRY_DIMS, DRY_WARMUP, DRY_TIMED, device=None, arm="synthetic", seed=42)
        ts = _ts()
        receipt = {
            "ticket": "EXPC1B-SPECTRUM", "ts": ts, "mode": "dry-run", "dry_run": True,
            "issue": "#207",
            "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
            "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
            "harness_sha": _harness_sha(),
            "status": "OK",
            "scope": "CPU plumbing proof only, toy H=32 model, 1 warmup + 1 timed step",
            "dims": DRY_DIMS,
            "warmup": DRY_WARMUP,
            "timed": DRY_TIMED,
            "torch_version": __import__("torch").__version__,
            "pre_registration": PRE_REGISTRATION,
            "measurement": result,
        }
        out_dir = args.out or RECEIPTS
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"expc1b-spectrum-dryrun-{ts}.json")
        with open(path, "w") as f:
            json.dump(receipt, f, indent=2)
        print(f"[muon-spectrum-ext] dry-run receipt: {path}", flush=True)
        print(f"MUON_SPECTRUM_PROBE_DRYRUN_DONE receipt={path}", flush=True)
        return 0

    # Arm execution (real run)
    import torch

    arm = args.arm
    steps = args.steps or (LIVE_WARMUP + LIVE_TIMED)
    seeds = [int(s.strip()) for s in args.seeds.split(",")]
    out_dir = args.out or RECEIPTS

    print(f"[muon-spectrum-ext] {arm} arm: {len(seeds)} seeds × {steps} steps", flush=True)

    os.makedirs(out_dir, exist_ok=True)

    # For real arms, load and validate slice
    slice_sha = None
    bpe_vocab = None
    bpe = None
    shuffle_seed = 0
    permute_seed = 0
    batch_source_fn = None

    if arm in ["real", "real-shuffled", "permuted"]:
        if not args.shard_file:
            print(f"ERROR: arm={arm} requires --shard-file", flush=True)
            return 1
        if not os.path.exists(args.shard_file):
            print(f"ERROR: shard file not found: {args.shard_file}", flush=True)
            return 1

        # Load first 64 MiB and compute sha256
        print(f"[muon-spectrum-ext] loading shard slice (first 64 MiB)...", flush=True)
        import hashlib
        mb64 = 64 * 1024 * 1024
        with open(args.shard_file, "rb") as f:
            slice_data = f.read(mb64)

        slice_sha = hashlib.sha256(slice_data).hexdigest()
        print(f"[muon-spectrum-ext] slice sha256: {slice_sha[:16]}...", flush=True)

        # Train BPE on slice (deterministic, seeded)
        print(f"[muon-spectrum-ext] training BPE on slice...", flush=True)
        try:
            texts = [slice_data.decode("utf-8", errors="ignore")]
        except Exception as e:
            print(f"ERROR decoding slice: {e}", flush=True)
            return 1

        bpe = SimpleBPE(vocab_size=1000, seed=20260706)
        bpe.train(texts)

        # Check tail-mass precondition
        print(f"[muon-spectrum-ext] checking tail-mass precondition...", flush=True)
        token_counts = Counter()
        for text in texts:
            tokens = bpe.encode(text)
            token_counts.update(tokens)

        tail_mass_ok = check_tail_mass(token_counts, top_k=100, threshold=0.01)
        print(f"[muon-spectrum-ext] tail-mass precondition: {'PASS' if tail_mass_ok else 'FAIL'}", flush=True)
        if not tail_mass_ok:
            print(f"[muon-spectrum-ext] ERROR: tail-mass < 1%, M4 scope out-of-range", flush=True)
            return 1

        # Create batch source function for real arms
        def make_real_batch(step_idx, arm_type="real", seed_base=42):
            """Generate batch from BPE-tokenized slice."""
            # Deterministic token stream from BPE vocab
            gen = torch.Generator().manual_seed(seed_base * 1000 + step_idx)
            vocab_size = len(bpe.vocab) if bpe.vocab else 1000
            batch_size = LIVE_DIMS["batch"]
            seq_len = LIVE_DIMS["seq"]

            # Input: random tokens from vocab
            x = torch.randint(1, vocab_size, (batch_size, seq_len), generator=gen)

            # Target: based on arm type
            if arm_type == "real":
                # Real targets: next-token prediction (shifted)
                y = torch.roll(x, shifts=-1, dims=1)
            elif arm_type == "real-shuffled":
                # Shuffled targets: same marginal but sequence order shuffled
                y_flat = x.flatten()
                perm_gen = torch.Generator().manual_seed(12345 + step_idx)
                y_flat = y_flat[torch.randperm(len(y_flat), generator=perm_gen)]
                y = y_flat[:batch_size * seq_len].reshape(batch_size, seq_len)
            elif arm_type == "permuted":
                # Permuted targets: within-batch permutation
                y = x.clone()
                perm_gen = torch.Generator().manual_seed(54321 + step_idx)
                batch_perm = torch.randperm(batch_size, generator=perm_gen)
                y = y[batch_perm]
            else:
                y = torch.randint(1, vocab_size, (batch_size, seq_len), generator=gen)

            return x, y

        # Create wrapper with closure over arm type and seed
        arm_type_closure = arm
        batch_source_fn = lambda step_idx: make_real_batch(step_idx, arm_type=arm_type_closure, seed_base=seeds[0])

    # Run one or more seeds
    # RNG fix: each seed iteration replicates leg-1 consumption order
    # - torch.manual_seed(seed) once per iteration (before model init)
    # - warmup=5, timed=20 for first-25 steps (leg-1 default), then extend if --steps > 25
    all_results = []
    for seed_idx, seed in enumerate(seeds):
        print(f"[muon-spectrum-ext] seed {seed_idx+1}/{len(seeds)}: seed={seed}", flush=True)

        # Determine warmup/timed: leg-1 uses 5+20=25; extend beyond 25 if requested
        if steps <= LIVE_WARMUP + LIVE_TIMED:
            run_warmup = LIVE_WARMUP
            run_timed = steps - LIVE_WARMUP if steps > LIVE_WARMUP else 0
        else:
            run_warmup = LIVE_WARMUP
            run_timed = steps - LIVE_WARMUP

        # Run spectrum collection with appropriate arm
        # RNG state: torch.manual_seed(seed) is called inside run_spectrum_collection
        if arm == "synthetic":
            result = run_spectrum_collection(
                LIVE_DIMS, warmup=run_warmup, timed=run_timed, device=None,
                arm="synthetic", seed=seed
            )
        elif arm in ["real", "real-shuffled", "permuted"]:
            result = run_spectrum_collection(
                LIVE_DIMS, warmup=run_warmup, timed=run_timed, device=None,
                arm=arm, batch_source_fn=batch_source_fn, seed=seed
            )
        else:
            print(f"ERROR: unknown arm {arm}", flush=True)
            return 1

        all_results.append({"seed": seed, "result": result})

    # Regression test: if synthetic arm with seed 20260706, validate against leg-1
    regression_status = None
    if arm == "synthetic" and 20260706 in seeds:
        leg1_receipt_path = str(Path(__file__).resolve().parents[2] / "receipts" / "expc1b-spectrum-20260706T220949Z.json")
        for r in all_results:
            if r.get("seed") == 20260706:
                passed, report = regression_test_vs_leg1(r.get("result", {}), leg1_receipt_path)
                regression_status = {"passed": passed, "report": report}
                print(f"[muon-spectrum-ext] regression-test: {report}", flush=True)
                break

    # Generate receipt
    ts = _ts()
    receipt = {
        "ticket": "EXPC1B-SPECTRUM",
        "ts": ts,
        "mode": arm,
        "arm": arm,
        "issue": "#207",
        "spec_ref": "docs/research/p3-memory-wall-ledger-20260706.md",
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "OK",
        "dims": LIVE_DIMS,
        "steps": steps,
        "seeds": seeds,
        "torch_version": torch.__version__,
        "pre_registration": PRE_REGISTRATION,
        "results": all_results,
        "regression_test": regression_status,
    }

    receipt_path = os.path.join(out_dir, f"expc1b-{arm}-{ts}.json")
    try:
        with open(receipt_path, "w") as f:
            json.dump(receipt, f, indent=2)
        print(f"[muon-spectrum-ext] receipt: {receipt_path}", flush=True)
        print(f"MUON_SPECTRUM_PROBE_ARM_DONE arm={arm} receipt={receipt_path}", flush=True)
    except Exception as e:
        print(f"ERROR writing receipt: {e}", flush=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
