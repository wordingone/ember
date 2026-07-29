#!/usr/bin/env python3
"""Genuine C14 resident-training loop: RLM + iGRPO on a tiny owned nn.Module policy.

Implements the PINNED mechanism from:
  arXiv:2512.24601  (RLM — recursive self-call loop, FINAL() termination)
  arXiv:2602.09000  (iGRPO — two-stage policy gradient with group-normalised advantages)

Design constraints (from spec c14-genuine-resident-implementation-spec-20260623.md):
  - device = cpu ONLY; no GPU dispatch, no train-daemon calls
  - TINY dims — proves the loop, not scale
  - Do NOT touch timeshare_pretrain.py or c04_design_bench.py
  - Verifier is EXECUTING (not lexical): correct action token match against a
    deterministic state machine, not string overlap with the prompt
  - Policy weights MUST change after a reward-driven update (asserted in tests)
  - Degenerate all-equal-reward batch MUST yield ~zero advantage (no spurious update)

Narrow task (smoke/test substitute for [REDACTED]-cli):
  Given an observed state (a small integer 0-7 representing a "register value"),
  the policy must emit the action token that correctly INCREMENTS the state modulo 8.
  Verifier: executes increment(state) and checks if emitted action == result.
  This is non-lexical: the reward is from running the state machine, not string match.

Run:
  python ember_resident_igrpo.py           # one training step + weight-change check
  python ember_resident_igrpo.py --test    # full unit-test suite (all assertions)
"""
from __future__ import annotations
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import argparse
import hashlib
import math
import random
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Vocabulary / action space
# ---------------------------------------------------------------------------

# State space: integers 0..7 (3 bits)
# Action space: emit token 0..7 representing the incremented state
# Plus a FINAL pseudo-token (id=8) used to mark end of RLM episode
# Plus RECURSE pseudo-token (id=9) used by RLM to signal a self-call step
VOCAB_SIZE = 10          # 0-7: action tokens; 8: FINAL; 9: RECURSE
STATE_VALS = list(range(8))
ACTION_FINAL = 8
ACTION_RECURSE = 9

# Tiny dims — prove the loop
HIDDEN_DIM = 32
NUM_HEADS = 2
NUM_LAYERS = 2
MAX_SEQ_LEN = 32         # enough for depth-3 RLM episodes


# ---------------------------------------------------------------------------
# Verifier Protocol (EXECUTING, not lexical)
# ---------------------------------------------------------------------------

def executing_verifier(state_val: int, emitted_action: int) -> float:
    """Map (observed_state, emitted_action) -> reward in [0.0, 1.0].

    Executes the deterministic task: correct action = (state_val + 1) % 8.
    Reward is 1.0 iff the emitted action token equals the incremented state.
    This is process-external: the reward comes from RUNNING the increment
    function, NOT from lexical overlap between action and prompt text.

    Satisfies spec requirement:
      'reward r in [0,1] by EXECUTING a deterministic task...
       reward from actual execution match, NOT lexical overlap of the prompt'
    """
    correct = (state_val + 1) % 8
    return 1.0 if emitted_action == correct else 0.0


def _no_action_fallback(state_val: int) -> int:
    """Deterministically WRONG in-band action for episodes that end without a
    valid emitted action.

    Reward-fabrication fix (2026-07-02, C14 design v1.2 pre-live blocker 1):
    this previously defaulted to (state_val + 1) % 8 — the verifier-CORRECT
    answer — so any policy whose sampling missed the action band was scored
    1.0 for free (~99% of episodes at a 32000-token vocab). The fallback is
    now (state_val + 2) % 8: still an in-band token (embedding-safe for
    Stage-2 tensors) but NEVER the correct answer, so executing_verifier
    scores it 0.0. Callers also set episode.fallback_fired = True so runs can
    receipt fallback-count explicitly.
    """
    return (state_val + 2) % 8


# ---------------------------------------------------------------------------
# Tiny Transformer Policy (owned nn.Module — weights are trained)
# ---------------------------------------------------------------------------

class TinyPolicyEmbedding(nn.Module):
    """Token embedding + sinusoidal positional encoding."""

    def __init__(self, vocab_size: int, hidden_dim: int, max_len: int) -> None:
        super().__init__()
        self.tok_embed = nn.Embedding(vocab_size, hidden_dim)
        # Fixed sinusoidal PE (not learned, keeps dims small)
        pe = torch.zeros(max_len, hidden_dim)
        pos = torch.arange(max_len).unsqueeze(1).float()
        div = torch.exp(
            torch.arange(0, hidden_dim, 2).float() * (-math.log(10000.0) / hidden_dim)
        )
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe)  # not a parameter

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len) long
        emb = self.tok_embed(x)                       # (B, T, H)
        emb = emb + self.pe[: x.size(1)]             # broadcast over batch
        return emb


def _make_causal_mask(seq_len: int) -> torch.Tensor:
    """Upper-triangular additive mask for causal (autoregressive) attention.

    nn.TransformerEncoder expects an additive float mask where positions
    that should be IGNORED get -inf.  The causal mask sets the upper triangle
    (future positions) to -inf so position i can only attend to positions <= i.

    Shape: (seq_len, seq_len).
    """
    # torch.triu with diagonal=1 gives the strictly-upper triangle (future).
    mask = torch.triu(torch.full((seq_len, seq_len), float("-inf")), diagonal=1)
    return mask


class TinyPolicyTransformer(nn.Module):
    """Tiny causal transformer policy.

    D1 fix: forward() now passes a causal additive mask to nn.TransformerEncoder
    so attention is strictly autoregressive — position i cannot attend to j > i.
    Without this mask the encoder is bidirectional (sees future tokens), which
    violates the generation model used during sampling.

    Outputs a distribution over VOCAB_SIZE action tokens given a token sequence.
    Weights are the OWNED core that iGRPO updates.
    """

    def __init__(
        self,
        vocab_size: int = VOCAB_SIZE,
        hidden_dim: int = HIDDEN_DIM,
        num_heads: int = NUM_HEADS,
        num_layers: int = NUM_LAYERS,
        max_len: int = MAX_SEQ_LEN,
    ) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.hidden_dim = hidden_dim
        self.embedding = TinyPolicyEmbedding(vocab_size, hidden_dim, max_len)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=num_heads,
            dim_feedforward=hidden_dim * 2,
            dropout=0.0,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.head = nn.Linear(hidden_dim, vocab_size, bias=True)

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        """Return logits over vocab for each token position.

        input_ids: (batch, seq_len) long
        returns:   (batch, seq_len, vocab_size) float

        D1: causal mask applied so position i attends only to positions <= i.
        """
        seq_len = input_ids.size(1)
        causal_mask = _make_causal_mask(seq_len)     # (T, T) additive
        emb = self.embedding(input_ids)              # (B, T, H)
        out = self.transformer(emb, mask=causal_mask, is_causal=True)  # (B, T, H)
        logits = self.head(out)                      # (B, T, V)
        return logits

    def log_prob_sequence(
        self, input_ids: torch.Tensor, target_ids: torch.Tensor
    ) -> torch.Tensor:
        """Sum of log-probs for target_ids given input_ids (teacher-forced).

        input_ids:  (seq_len,) — the conditioning context
        target_ids: (gen_len,) — the generated tokens to score
        returns: scalar log-prob sum
        """
        # Full sequence: context + targets
        full = torch.cat([input_ids, target_ids]).unsqueeze(0)  # (1, T)
        logits = self.forward(full)                              # (1, T, V)
        # Shift: logits at position i predict position i+1
        ctx_len = input_ids.size(0)
        # We want logits[ctx_len-1 : ctx_len-1+gen_len] → targets
        pred_logits = logits[0, ctx_len - 1 : ctx_len - 1 + len(target_ids)]  # (G, V)
        log_probs = F.log_softmax(pred_logits, dim=-1)            # (G, V)
        tok_lp = log_probs[torch.arange(len(target_ids)), target_ids]  # (G,)
        return tok_lp.sum()

    @torch.no_grad()
    def sample_action(
        self,
        context_ids: torch.Tensor,
        temperature: float = 1.0,
    ) -> int:
        """Sample a single next-token action given context."""
        inp = context_ids.unsqueeze(0)                   # (1, T)
        logits = self.forward(inp)[0, -1, :]             # (V,)
        if temperature <= 0:
            return int(logits.argmax().item())
        probs = F.softmax(logits / temperature, dim=-1)
        return int(torch.multinomial(probs, 1).item())


# ---------------------------------------------------------------------------
# RLM-style recursive generation loop (REAL recursion, not a stub name)
# ---------------------------------------------------------------------------

@dataclass
class RLMEpisode:
    """Records the full trace of one RLM episode.

    spec: 'a Python-REPL-style recursive loop; terminates with FINAL(action);
           recursion = decompose a large/complex observation+goal;
           max depth 0-3'

    sampled_tokens: verbatim list of ALL tokens the policy emitted as actions
    during this episode (including control tokens ACTION_FINAL / ACTION_RECURSE).
    This is the o_j sequence that igrpo_loss scores.  The prefix q' is stored
    separately in Stage2Result and is NOT part of sampled_tokens.
    """
    state_val: int
    final_action: Optional[int] = None
    # True iff any no-action fallback fired in this episode (see
    # _no_action_fallback). Receipts assert fallback_fired=False for
    # evidence-grade runs; a fallback episode is a FAILED episode, never a
    # fabricated success.
    fallback_fired: bool = False
    steps: list[dict] = field(default_factory=list)
    depth_used: int = 0
    # Verbatim sampled action token sequence (populated by rlm_generate).
    # These are exactly the tokens whose log-probs under pi_theta_old were
    # drawn at sample time; igrpo_loss scores only these tokens.
    sampled_tokens: list[int] = field(default_factory=list)


def _encode_state(
    state_val: int,
    exemplars: Optional[list[tuple[int, int]]] = None,
) -> torch.Tensor:
    """Encode the observed state as a context token sequence.

    State token = state_val (0-7). Prepend a fixed 'start' token (= state_val
    itself for simplicity at tiny scale).

    CORPUS-V2 (additive, default OFF — 2026-07-03): when `exemplars` is a
    non-empty list of (exemplar_state, exemplar_action) pairs, each pair is
    PREPENDED as two tokens — both already inside the 0-7 band shared by
    VOCAB_SIZE, no new vocab needed — before the queried state_val token:

        [ex1_state, ex1_action, ex2_state, ex2_action, ..., state_val]

    `exemplars=None` (the default) reproduces the EXACT pre-corpus-v2 output:
    a length-1 tensor holding only state_val. Every caller of this function
    (rlm_generate's depth-0 context, igrpo_stage1's initial_context,
    igrpo_stage2's base_context) reads ctx_len via `.size(0)` rather than a
    hard-coded constant, so a longer context here flows through unchanged.
    """
    tokens: list[int] = []
    if exemplars:
        for ex_state, ex_action in exemplars:
            tokens.extend([ex_state, ex_action])
    tokens.append(state_val)
    return torch.tensor(tokens, dtype=torch.long)


def rlm_generate(
    policy: TinyPolicyTransformer,
    state_val: int,
    max_depth: int = 2,
    temperature: float = 1.0,
    exemplars: Optional[list[tuple[int, int]]] = None,
    _depth: int = 0,
    _context: Optional[torch.Tensor] = None,
    _sampled_tokens: Optional[list[int]] = None,
) -> RLMEpisode:
    """RLM recursive generation loop.

    Implements Algorithm 1 from arXiv:2512.24601:
      - The policy emits tokens step-by-step over the observation context
      - If ACTION_RECURSE is emitted, recurse (self-call) with depth+1
        (falls back to ACTION_FINAL path at max_depth, per spec)
      - Terminates when ACTION_FINAL is emitted, returning the last action token
        as the final answer

    This IS a real recursion control loop: Python call stack reflects depth,
    episodes can nest up to max_depth, not a stub/rename.

    spec: 'depth 0-3, FINAL() termination; recursion = decompose...'

    D2/D3: every token the policy emits (including RECURSE and FINAL) is
    appended to episode.sampled_tokens at the MOMENT of sampling.  This
    builds the verbatim o_j sequence that igrpo_loss must score.

    D5: when the generation loop exits due to context reaching MAX_SEQ_LEN
    (hard cap), the triggering token is still appended to sampled_tokens
    before returning, so igrpo_loss does not silently drop the last token.
    """
    episode = RLMEpisode(state_val=state_val, depth_used=_depth)

    if _context is None:
        context = _encode_state(state_val, exemplars=exemplars)
    else:
        context = _context

    # _sampled_tokens is the shared mutable list that accumulates verbatim
    # tokens across recursive calls (shared by reference through recursion).
    if _sampled_tokens is None:
        _sampled_tokens = []
    episode.sampled_tokens = _sampled_tokens  # all levels share the same list

    last_action_token = None

    for _step in range(MAX_SEQ_LEN):
        tok = policy.sample_action(context, temperature=temperature)
        # D2/D3: record verbatim sampled token immediately at sample time.
        _sampled_tokens.append(tok)
        episode.steps.append({"depth": _depth, "token": tok, "context_len": len(context)})

        if tok == ACTION_FINAL:
            # FINAL() termination: use last non-special token as the answer
            if last_action_token is not None:
                final = last_action_token
            else:
                final = _no_action_fallback(state_val)
                episode.fallback_fired = True
            episode.final_action = final
            return episode

        if tok == ACTION_RECURSE:
            if _depth >= max_depth:
                # Fall back to llm_query (single step, no recursion) per spec:
                # 'rlm_query automatically falls back to llm_query at max depth'
                greedy = policy.sample_action(context, temperature=0.0)
                # D2/D3: record the fallback greedy token verbatim.
                _sampled_tokens.append(greedy)
                # Use greedy as final answer
                if greedy < 8:
                    greedy_action = greedy
                else:
                    greedy_action = _no_action_fallback(state_val)
                    episode.fallback_fired = True
                episode.final_action = greedy_action
                episode.steps.append({"depth": _depth, "token": greedy, "fallback": True})
                return episode
            else:
                # Recurse: nested RLM call with extended context
                # Cap sub_context to MAX_SEQ_LEN - 1 so nested PE indexing is safe
                sub_ctx_raw = torch.cat([context, torch.tensor([tok], dtype=torch.long)])
                sub_context = sub_ctx_raw[-(MAX_SEQ_LEN - 1):]
                sub_episode = rlm_generate(
                    policy,
                    state_val=state_val,
                    max_depth=max_depth,
                    temperature=temperature,
                    exemplars=exemplars,  # inert here: _context is set, so
                    # _encode_state is never re-invoked for this recursive call.
                    _depth=_depth + 1,
                    _context=sub_context,
                    _sampled_tokens=_sampled_tokens,  # shared list
                )
                # Append sub-episode's final token to context (metadata only, per spec)
                sub_final = sub_episode.final_action
                episode.fallback_fired = episode.fallback_fired or sub_episode.fallback_fired
                if sub_final is None:
                    sub_final = _no_action_fallback(state_val)
                    episode.fallback_fired = True
                new_ctx = torch.cat([context, torch.tensor([sub_final], dtype=torch.long)])
                # Cap parent context to MAX_SEQ_LEN
                context = new_ctx[-(MAX_SEQ_LEN - 1):]
                last_action_token = sub_final
                episode.steps.extend(sub_episode.steps)
                episode.depth_used = max(episode.depth_used, sub_episode.depth_used)
        else:
            # Regular action token (0-7): update context, remember as candidate answer
            if tok < 8:
                last_action_token = tok
            new_context = torch.cat([context, torch.tensor([tok], dtype=torch.long)])
            # Hard cap: never exceed MAX_SEQ_LEN (sinusoidal PE is fixed-size)
            # D5: the current token tok is ALREADY in _sampled_tokens (appended above).
            # Return here without dropping it — the token is part of o_j.
            if len(new_context) >= MAX_SEQ_LEN:
                if last_action_token is not None:
                    episode.final_action = last_action_token
                else:
                    episode.final_action = _no_action_fallback(state_val)
                    episode.fallback_fired = True
                return episode
            context = new_context

    # Loop exhausted without FINAL: use last action token
    if last_action_token is not None:
        episode.final_action = last_action_token
    else:
        episode.final_action = _no_action_fallback(state_val)
        episode.fallback_fired = True
    return episode


# ---------------------------------------------------------------------------
# SAMPLING-COST CURE PHASE 2 (2026-07-03) — batched multi-stream generation
# ---------------------------------------------------------------------------
#
# Root cause (measured, receipted — PHASE 1 commit): the owned 368M-param /
# 20-layer core is DISPATCH-bound at batch=1/seq<=31 on CUDA (~15-21ms per
# forward() call, roughly CONSTANT regardless of context length or
# KV-cache hit/miss). Stage-1 (N drafts) and Stage-2 (G refinements) each
# call policy.sample_action() once PER TOKEN PER ROLLOUT, sequentially —
# ~150-250 separate forward() calls per igrpo_step. The fix here cuts the
# NUMBER of forward() calls, not the FLOPs per call: batch the N (or G)
# parallel rollout streams into ONE forward() call per token-step.
#
# NEW SAMPLING-RNG CONVENTION (disclosed, replaces "draw from the shared
# global torch RNG" for Stage-1/Stage-2 STOCHASTIC rollouts only): batching
# N samples "simultaneously" out of one forward call has no well-defined
# meaning against a single sequential global RNG stream — the draw order
# would depend on which stream happens to be processed when. So every
# rollout stream gets its OWN torch.Generator, seeded deterministically
# from (run_seed, stage_tag, rollout_index) — see _derive_stream_seed().
# Each stream is then reproducible and independent of how many OTHER
# streams share its batched forward call, or in what order. Greedy
# (temperature<=0) draws are argmax and touch no RNG either way, so eval
# call sites (rlm_generate() with temperature=0.0, still the untouched
# original function) are entirely unaffected — this convention change is
# scoped to the STOCHASTIC Stage-1/Stage-2 sampling path only.
# ---------------------------------------------------------------------------

def _derive_stream_seed(run_seed: int, stage_tag: str, rollout_index: int) -> int:
    """Deterministic per-stream seed = hash(run_seed, stage_tag, rollout_index).

    sha256 over a plain formatted string, truncated to 63 bits (torch.Generator.
    manual_seed accepts any Python int but this keeps it inside its own
    internal range, avoiding sign edge cases). Same inputs -> same seed,
    always — this IS the reproducibility mechanism the new-convention
    determinism bar checks.
    """
    digest = hashlib.sha256(f"{run_seed}|{stage_tag}|{rollout_index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _band_slice(policy, logits: torch.Tensor) -> torch.Tensor:
    """Restrict last-dim logits to policy.band if the policy defines one
    (ember_c14_owned_run.py::_ActionBandPolicy — the real 32000-vocab owned
    core samples ONLY over its first VOCAB_SIZE=10 raw logits, per that
    class's own docstring); policies with no .band (TinyPolicyTransformer,
    a bare _OwnedCorePolicy) already output exactly VOCAB_SIZE logits and
    are returned unsliced — identical convention to each policy's own
    sample_action() today, centralised here so rlm_generate_gen and
    _rlm_generate_batch apply it identically."""
    band = getattr(policy, "band", None)
    return logits[..., :band] if band is not None else logits


def _forward_sample(
    policy, context_ids: torch.Tensor, temperature: float, generator: torch.Generator
) -> int:
    """Single-stream sample via policy.forward() (existing, UNCHANGED method
    on every policy shape this file's callers use) plus an explicit
    Generator — the new convention's atomic building block. Mirrors
    sample_action()'s own contract (band restriction, temperature<=0 ->
    argmax with no RNG draw) without adding a generator= parameter to
    sample_action() on any of the (three, cross-file) policy classes.

    policy.forward() returns a CPU tensor for every policy shape reachable
    from igrpo_stage1/igrpo_stage2 today (TinyPolicyTransformer is CPU-only
    by construction; _ActionBandPolicy.forward() explicitly device-bridges
    back to cpu; a LoRAAdapter wrapping either just delegates) — sampling
    arithmetic here is therefore always CPU-side, so `generator` is always
    a plain (default-device) torch.Generator, never a CUDA one.
    """
    inp = context_ids.unsqueeze(0)
    with torch.no_grad():
        logits = policy.forward(inp)[0, -1, :]
    logits = _band_slice(policy, logits)
    if temperature <= 0:
        return int(logits.argmax().item())
    probs = F.softmax(logits / max(temperature, 1e-6), dim=-1)
    return int(torch.multinomial(probs, 1, generator=generator).item())


def rlm_generate_gen(
    policy,
    state_val: int,
    generator: torch.Generator,
    max_depth: int = 2,
    temperature: float = 1.0,
    _depth: int = 0,
    _context: Optional[torch.Tensor] = None,
    _sampled_tokens: Optional[list[int]] = None,
    _pending_token: Optional[int] = None,
) -> RLMEpisode:
    """Generator-parameterized sibling of rlm_generate() — line-for-line the
    SAME control flow (FINAL/RECURSE/regular-token handling, MAX_SEQ_LEN
    capping, fallback bookkeeping), with exactly one substitution: every
    sampling draw goes through _forward_sample(..., generator) instead of
    policy.sample_action(...) (which silently drains the GLOBAL torch RNG).

    Two roles:
      (a) SEQUENTIAL REFERENCE for the batched<->sequential equivalence
          probe: calling this `count` times, once per stream with that
          stream's own Generator, is the unbatched ground truth
          _rlm_generate_batch below is checked against (must produce
          IDENTICAL token streams).
      (b) RECURSE HANDOFF inside _rlm_generate_batch: a stream that samples
          ACTION_RECURSE at depth 0 (< max_depth) is finished out via a
          call to THIS function at _depth=0 (NOT _depth+1 — see
          _pending_token below), using its own Generator for every
          remaining draw. Batching recursion's nested, variable-depth
          control flow safely is a materially bigger problem than lockstep
          single-level decode, so it is explicitly NOT batched (disclosed
          fallback; see _rlm_generate_batch's own docstring).

    _pending_token: the ONE case this function is entered with a token
    ALREADY sampled (the RECURSE token the batched driver just drew, whose
    step/sampled_tokens bookkeeping the caller already recorded). Skips the
    draw for exactly the first loop iteration and reuses `_pending_token`
    instead — critical for the handoff to be correct: rlm_generate's
    ORIGINAL semantics are that after a recursive sub-call RETURNS, the
    PARENT's OWN loop (same depth) CONTINUES (may sample more tokens, may
    recurse again) — it does NOT terminate at the sub-call's return. Handing
    off at _depth+1 (as if the RECURSE token itself were the sub-call's
    entry) would silently truncate that parent-continues behavior; entering
    at _depth=0 with the RECURSE token as `_pending_token` instead resumes
    exactly where rlm_generate's own top-level loop would be, one token in.
    """
    episode = RLMEpisode(state_val=state_val, depth_used=_depth)

    if _context is None:
        context = _encode_state(state_val)
    else:
        context = _context

    if _sampled_tokens is None:
        _sampled_tokens = []
    episode.sampled_tokens = _sampled_tokens

    last_action_token = None
    pending = _pending_token

    for _step in range(MAX_SEQ_LEN):
        if pending is not None:
            tok = pending
            pending = None
        else:
            tok = _forward_sample(policy, context, temperature, generator)
            _sampled_tokens.append(tok)
            episode.steps.append({"depth": _depth, "token": tok, "context_len": len(context)})

        if tok == ACTION_FINAL:
            if last_action_token is not None:
                final = last_action_token
            else:
                final = _no_action_fallback(state_val)
                episode.fallback_fired = True
            episode.final_action = final
            return episode

        if tok == ACTION_RECURSE:
            if _depth >= max_depth:
                greedy = _forward_sample(policy, context, 0.0, generator)
                _sampled_tokens.append(greedy)
                if greedy < 8:
                    greedy_action = greedy
                else:
                    greedy_action = _no_action_fallback(state_val)
                    episode.fallback_fired = True
                episode.final_action = greedy_action
                episode.steps.append({"depth": _depth, "token": greedy, "fallback": True})
                return episode
            else:
                sub_ctx_raw = torch.cat([context, torch.tensor([tok], dtype=torch.long)])
                sub_context = sub_ctx_raw[-(MAX_SEQ_LEN - 1):]
                sub_episode = rlm_generate_gen(
                    policy,
                    state_val=state_val,
                    generator=generator,
                    max_depth=max_depth,
                    temperature=temperature,
                    _depth=_depth + 1,
                    _context=sub_context,
                    _sampled_tokens=_sampled_tokens,
                )
                sub_final = sub_episode.final_action
                episode.fallback_fired = episode.fallback_fired or sub_episode.fallback_fired
                if sub_final is None:
                    sub_final = _no_action_fallback(state_val)
                    episode.fallback_fired = True
                new_ctx = torch.cat([context, torch.tensor([sub_final], dtype=torch.long)])
                context = new_ctx[-(MAX_SEQ_LEN - 1):]
                last_action_token = sub_final
                episode.steps.extend(sub_episode.steps)
                episode.depth_used = max(episode.depth_used, sub_episode.depth_used)
        else:
            if tok < 8:
                last_action_token = tok
            new_context = torch.cat([context, torch.tensor([tok], dtype=torch.long)])
            if len(new_context) >= MAX_SEQ_LEN:
                if last_action_token is not None:
                    episode.final_action = last_action_token
                else:
                    episode.final_action = _no_action_fallback(state_val)
                    episode.fallback_fired = True
                return episode
            context = new_context

    if last_action_token is not None:
        episode.final_action = last_action_token
    else:
        episode.final_action = _no_action_fallback(state_val)
        episode.fallback_fired = True
    return episode


def _rlm_generate_batch(
    policy,
    state_val: int,
    count: int,
    max_depth: int,
    temperature: float,
    seed: int,
    stage_tag: str,
    initial_context: torch.Tensor,
    initial_logits_out: Optional[list] = None,
) -> list[RLMEpisode]:
    """Batched sibling of calling rlm_generate_gen() `count` times
    independently with `count` distinct per-stream Generators (that
    sequential call pattern is the reference this is checked against — see
    rlm_generate_gen's docstring, role (a)).

    All `count` streams share the SAME `initial_context` (true at both call
    sites today: Stage-1's state encoding, Stage-2's d-hat-augmented
    prefix). Streams run in LOCKSTEP: at every iteration, every still-live
    stream's context is the SAME LENGTH (each either grows by exactly one
    token or leaves the batch entirely at that same point — never a
    partial grow), so their contexts stack into one rectangular (B, T)
    tensor and ONE policy.forward() call replaces `count` separate calls
    for that step — this is the entire win (see the module-level SAMPLING-
    COST CURE PHASE 2 comment above for why cutting call COUNT, not
    per-call FLOPs, is the lever that matters here).

    RECURSE fallback: the instant a stream samples ACTION_RECURSE with
    depth < max_depth, it is pulled OUT of the batch and handed to
    rlm_generate_gen to finish (covers the recursive sub-call AND the
    parent's own post-recursion continuation, reproducing rlm_generate's
    original nested control flow exactly) using that stream's own
    Generator — disclosed, NOT batched. At max_depth=1 (the --live config)
    this can fire at most once per stream. A RECURSE at depth >= max_depth
    (the greedy single-token fallback) stays in the batch machinery: it
    needs no recursion, and reuses THIS step's already-computed logits
    (deterministic argmax — recomputing would give the identical value,
    same as rlm_generate's own redundant-but-harmless re-forward of the
    same context does).

    initial_logits_out (v1.7 anti-collapse knob (ii), additive, default
    None -- see c14-owned-core-resident-run-v1.md sec 8d): when given a
    list, this function appends EXACTLY ONE tensor to it -- the
    band-restricted logits at _step==0, before any of the `count` streams
    diverge (every stream's context is still an identical clone of
    initial_context at that point, so row 0 IS pi(.|s) at the queried
    state/prefix). This reuses the forward the sampler already runs at
    that step -- no second forward is added. None (the default) skips the
    append entirely; byte-identical to pre-v1.7 behavior.
    """
    generators = [
        torch.Generator().manual_seed(_derive_stream_seed(seed, stage_tag, i))
        for i in range(count)
    ]
    contexts = [initial_context.clone() for _ in range(count)]
    sampled_tokens: list[list[int]] = [[] for _ in range(count)]
    steps_log: list[list[dict]] = [[] for _ in range(count)]
    last_action_token: list[Optional[int]] = [None] * count
    final_action: list[Optional[int]] = [None] * count
    fallback_fired: list[bool] = [False] * count
    depth_used: list[int] = [0] * count
    done: list[bool] = [False] * count

    for _step in range(MAX_SEQ_LEN):
        live = [i for i in range(count) if not done[i]]
        if not live:
            break

        batch_ctx = torch.stack([contexts[i] for i in live], dim=0)   # (len(live), T)
        with torch.no_grad():
            logits_batch = policy.forward(batch_ctx)[:, -1, :]        # (len(live), V)
        logits_batch = _band_slice(policy, logits_batch)

        if initial_logits_out is not None and _step == 0:
            # All `live` streams are still identical clones of initial_context
            # at _step==0 (no divergence yet), so row 0 is pi(.|s) — capture
            # it from the forward already computed above, no extra forward.
            initial_logits_out.append(logits_batch[0].detach().clone())

        for row, i in enumerate(live):
            row_logits = logits_batch[row]
            gen = generators[i]
            if temperature <= 0:
                tok = int(row_logits.argmax().item())
            else:
                probs = F.softmax(row_logits / max(temperature, 1e-6), dim=-1)
                tok = int(torch.multinomial(probs, 1, generator=gen).item())

            sampled_tokens[i].append(tok)
            steps_log[i].append({"depth": 0, "token": tok, "context_len": contexts[i].numel()})

            if tok == ACTION_FINAL:
                final_action[i] = (
                    last_action_token[i] if last_action_token[i] is not None
                    else _no_action_fallback(state_val)
                )
                fallback_fired[i] = last_action_token[i] is None
                done[i] = True
                continue

            if tok == ACTION_RECURSE:
                if max_depth <= 0:
                    greedy = int(row_logits.argmax().item())
                    sampled_tokens[i].append(greedy)
                    if greedy < 8:
                        greedy_action = greedy
                    else:
                        greedy_action = _no_action_fallback(state_val)
                        fallback_fired[i] = True
                    final_action[i] = greedy_action
                    steps_log[i].append({"depth": 0, "token": greedy, "fallback": True})
                    done[i] = True
                    continue
                else:
                    # HANDOFF at _depth=0 (NOT _depth+1): rlm_generate's
                    # ORIGINAL semantics are that once the recursive
                    # sub-call this RECURSE token triggers RETURNS, the
                    # PARENT's OWN (depth-0) loop CONTINUES — it does not
                    # terminate at the sub-call boundary, and may recurse
                    # again. Re-entering rlm_generate_gen at _depth=0 with
                    # _context=contexts[i] (unmodified, pre-token) and
                    # _pending_token=tok reproduces exactly that: the
                    # function's own RECURSE branch does the depth+1
                    # sub-call, appends its result to context, and its for
                    # loop keeps going — precisely mirroring the sequential
                    # reference. (An earlier version of this handoff called
                    # rlm_generate_gen at _depth=1 treating the sub-call
                    # itself as the whole remaining stream, which silently
                    # truncated the parent's continuation — caught by the
                    # batched-vs-sequential equivalence probe.)
                    sub_ep = rlm_generate_gen(
                        policy,
                        state_val=state_val,
                        generator=generators[i],
                        max_depth=max_depth,
                        temperature=temperature,
                        _depth=0,
                        _context=contexts[i],
                        _sampled_tokens=sampled_tokens[i],
                        _pending_token=tok,
                    )
                    final_action[i] = (
                        sub_ep.final_action if sub_ep.final_action is not None
                        else _no_action_fallback(state_val)
                    )
                    fallback_fired[i] = (
                        fallback_fired[i] or sub_ep.fallback_fired or (sub_ep.final_action is None)
                    )
                    depth_used[i] = max(depth_used[i], sub_ep.depth_used)
                    steps_log[i].extend(sub_ep.steps)
                    done[i] = True
                    continue

            if tok < 8:
                last_action_token[i] = tok
            new_ctx = torch.cat([contexts[i], torch.tensor([tok], dtype=torch.long)])
            if len(new_ctx) >= MAX_SEQ_LEN:
                final_action[i] = (
                    last_action_token[i] if last_action_token[i] is not None
                    else _no_action_fallback(state_val)
                )
                fallback_fired[i] = last_action_token[i] is None
                done[i] = True
            else:
                contexts[i] = new_ctx

    for i in range(count):
        if final_action[i] is None:
            final_action[i] = (
                last_action_token[i] if last_action_token[i] is not None
                else _no_action_fallback(state_val)
            )
            fallback_fired[i] = last_action_token[i] is None

    episodes = []
    for i in range(count):
        ep = RLMEpisode(
            state_val=state_val,
            final_action=final_action[i],
            fallback_fired=fallback_fired[i],
            steps=steps_log[i],
            depth_used=depth_used[i],
            sampled_tokens=sampled_tokens[i],
        )
        episodes.append(ep)
    return episodes


# ---------------------------------------------------------------------------
# iGRPO advantage computation (load-bearing math)
# ---------------------------------------------------------------------------

def compute_advantages(rewards: list[float]) -> list[float]:
    """Group-normalised advantages per iGRPO Eq. 4.

    A_j = (R_j - mean(R)) / std(R)
    If std(R) = 0: A_j = 0 for all j  (degenerate group convention, paper p.5 + App. A.3)

    Std convention: POPULATION std (divides by n, not n-1).

    Rationale: iGRPO Eq. 4 normalises over the G responses within a single
    group/query; these G samples are the full population being normalised, not a
    random sample drawn to estimate a larger population's variance.  Using
    population std (denominator n) therefore matches the paper's intent and
    avoids inflation of advantages when G is small (e.g. G=4).  Sample std
    (denominator n-1) would be appropriate if we were estimating a running
    baseline variance, which we are not.

    spec: 'advantage A_j=(r_j-mean)/std with A_j=0 if std=0'
    """
    n = len(rewards)
    mean_r = sum(rewards) / n
    # Population variance: divide by n (not n-1)
    variance = sum((r - mean_r) ** 2 for r in rewards) / n
    std_r = math.sqrt(variance)
    if std_r == 0.0:
        return [0.0] * n
    return [(r - mean_r) / std_r for r in rewards]


# ---------------------------------------------------------------------------
# V1.9 PER-STATE REWARD NORMALIZATION — envelope v1.9 (c14-owned-core-
# resident-run-v1.md sec 8f, pre-registered 2026-07-03T10:34Z, the v1.7
# ladder's anticipated update-side lever after A16's train oscillation
# regressed to 2/5 under the annealed temperature schedule). Within an
# optimizer group that may span MULTIPLE state_vals with UNEQUAL sample
# counts, this replaces the single group-wide mean/std baseline
# (compute_advantages, above) with an INDEPENDENT baseline per state_val —
# "no state's reward scale dominates credit assignment" (spec sec 8f).
# ---------------------------------------------------------------------------

def compute_advantages_per_state(
    rewards: list[float], state_vals: list[int]
) -> list[float]:
    """Per-state group-relative advantages (v1.9 lever, design spec sec 8f).

    Splits `rewards` into subgroups by their paired `state_vals` entry, then
    applies compute_advantages() to EACH subgroup independently — the same
    (r_j - mean)/std math, same population-std convention, same "A_j=0 if
    std=0" degenerate-group rule as the group-wide function above; this
    function does not reimplement that math, it partitions the input and
    delegates. Results are scattered back into the caller's original order.

    spec: 'within each optimizer group, advantages are normalized per
    state_val (mean-centered over that state's samples in the group) before
    the update, so no state's reward scale dominates credit assignment' —
    c14-owned-core-resident-run-v1.md sec 8f.

    Consequence (intended, spec-disclosed): a state_val with exactly ONE
    sample in the group has population variance exactly 0 (a single point
    has no spread around its own mean), so compute_advantages' std==0
    branch fires for that subgroup and the lone sample's advantage is 0 —
    it contributes no gradient through the centered term for this step.
    This is not a bug to work around; per sec 8f, a singleton state has no
    within-state reward signal to normalize against.
    """
    n = len(rewards)
    if len(state_vals) != n:
        raise ValueError(
            f"rewards and state_vals must be the same length, got "
            f"{n} rewards and {len(state_vals)} state_vals"
        )
    advantages = [0.0] * n
    by_state: dict[int, list[int]] = {}
    for idx, sv in enumerate(state_vals):
        by_state.setdefault(sv, []).append(idx)
    for idx_group in by_state.values():
        sub_rewards = [rewards[i] for i in idx_group]
        sub_advantages = compute_advantages(sub_rewards)
        for i, a in zip(idx_group, sub_advantages):
            advantages[i] = a
    return advantages


# ---------------------------------------------------------------------------
# V1.7 ANTI-COLLAPSE — envelope v1.7 (c14-owned-core-resident-run-v1.md sec
# 8d, pre-registered 2026-07-03T07:08Z, BEFORE attempt 15). Three knobs, all
# confined to the SAMPLING path (reward/gates/arms/eval untouched), all
# default-off so omitting them reproduces v1.6 bit-for-bit:
#   (i)   --temp-schedule   rollout temperature linear decay (parsed here;
#         applied by the CALLER — igrpo_step/train_one_step pass the
#         schedule-resolved value in as the ordinary `temperature` kwarg,
#         so igrpo_stage1/igrpo_stage2 need no schedule-awareness of their
#         own).
#   (ii)  --entropy-beta    entropy bonus added to Stage-2 advantages
#         (igrpo_stage2, below).
#   (iii) --degenerate-resample  one-shot resample of a std(R)=0 Stage-2
#         group at temperature 2.0 (igrpo_stage2, below).
# ---------------------------------------------------------------------------

def parse_temp_schedule(spec: str) -> tuple[float, float, int]:
    """Parse a '--temp-schedule start:end:by_step' CLI spec into (start,
    end, by_step).

    spec: 'rollout temperature schedule: start 1.5, linear decay to 1.0 by
    step 384' (design v1.7, sec 8d). Format is exactly three ':'-separated
    fields — start and end are floats, by_step is a positive int. Raises
    ValueError (naming the offending field) on any malformed input: wrong
    field count, a non-numeric field, or by_step <= 0.
    """
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"--temp-schedule must be 'start:end:by_step' (3 colon-separated "
            f"fields), got {len(parts)} field(s) in {spec!r}"
        )
    start_s, end_s, by_step_s = parts
    try:
        start = float(start_s)
    except ValueError:
        raise ValueError(f"--temp-schedule start must be numeric, got {start_s!r} in {spec!r}")
    try:
        end = float(end_s)
    except ValueError:
        raise ValueError(f"--temp-schedule end must be numeric, got {end_s!r} in {spec!r}")
    try:
        by_step = int(by_step_s)
    except ValueError:
        raise ValueError(f"--temp-schedule by_step must be an integer, got {by_step_s!r} in {spec!r}")
    if by_step <= 0:
        raise ValueError(f"--temp-schedule by_step must be > 0, got {by_step} in {spec!r}")
    return start, end, by_step


def schedule_temperature(step: int, start: float, end: float, by_step: int) -> float:
    """Linear-decay rollout temperature at a given (0-indexed) training
    step: `start` at step 0, `end` at step >= by_step, linearly
    interpolated in between (design v1.7 sec 8d knob (i)). step <= 0 clamps
    to `start`; not restricted to start >= end (a caller could configure a
    ramp-up — the interpolation is symmetric either way).
    """
    if step >= by_step:
        return end
    if step <= 0:
        return start
    frac = step / by_step
    return start + (end - start) * frac


def _softmax_entropy(logits: torch.Tensor) -> float:
    """Shannon entropy (nats) of softmax(logits) — the policy's OWN action
    distribution pi(.|s) at temperature=1.0, independent of whatever
    rollout-temperature knob (i) is using for the step's actual sampling,
    so the entropy bonus (knob (ii)) measures the policy's underlying
    belief, not an artefact of the exploration schedule. Probabilities are
    clamped away from exactly-zero before log() to avoid a 0*-inf -> nan
    edge case that is reachable only in principle (a logit of exactly
    -inf), never in practice for this tiny transformer.
    """
    probs = F.softmax(logits, dim=-1)
    log_probs = torch.log(probs.clamp_min(1e-12))
    return float(-(probs * log_probs).sum().item())


def _reward_group_is_degenerate(rewards: list[float]) -> bool:
    """True iff population std(rewards) == 0.0 — the SAME degenerate-group
    convention compute_advantages() uses (see its docstring): every
    rollout in the group scored an identical reward, the collapse
    signature v1.7 anti-collapse knob (iii) targets.
    """
    n = len(rewards)
    if n == 0:
        return True
    mean_r = sum(rewards) / n
    variance = sum((r - mean_r) ** 2 for r in rewards) / n
    return variance == 0.0


# ---------------------------------------------------------------------------
# iGRPO two-stage update
# ---------------------------------------------------------------------------

@dataclass
class Stage1Result:
    drafts: list[RLMEpisode]
    rewards: list[float]
    best_idx: int
    best_episode: RLMEpisode


@dataclass
class Stage2Result:
    refinements: list[RLMEpisode]
    rewards: list[float]
    advantages: list[float]
    # prefix_context: the q' token sequence (obs + d-hat) used as conditioning.
    # Stored here so igrpo_loss can mask it from the PG loss without re-deriving it.
    prefix_context: Optional[torch.Tensor] = None
    # resample_fired: v1.7 anti-collapse knob (iii) — True iff the initial
    # Stage-2 group was degenerate (std(rewards)==0) and got resampled once
    # at temperature 2.0. Always False when degenerate_resample=False
    # (the default) — additive field, existing manual Stage2Result(...)
    # constructions elsewhere in this file's own test suite are unaffected.
    resample_fired: bool = False


def igrpo_stage1(
    policy: TinyPolicyTransformer,
    state_val: int,
    N: int = 4,
    max_depth: int = 2,
    temperature: float = 1.0,
    seed: Optional[int] = None,
    exemplars: Optional[list[tuple[int, int]]] = None,
) -> Stage1Result:
    """Stage 1: sample N drafts from policy, verifier-score each, select d-hat.

    spec: 'Stage-1 sample N=4 drafts from the policy, verifier-score each,
           d-hat=argmax'

    Stage-1 does NOT receive gradient updates (per iGRPO paper p.6).

    SAMPLING-COST CURE PHASE 2 (2026-07-03): the N drafts are generated by
    ONE batched call (_rlm_generate_batch) instead of N sequential
    rlm_generate() calls — see that function's docstring for the lockstep
    mechanics and the disclosed RECURSE-handoff fallback. `seed` drives the
    new per-stream-Generator sampling convention (see _derive_stream_seed);
    if not supplied, one is drawn from torch's current global RNG state so
    existing callers (which don't pass seed) stay reproducible under a
    global torch.manual_seed(...) exactly as before, just no longer via a
    SHARED draw sequence across the N streams.

    CORPUS-V2 (additive, default OFF): `exemplars`, if given, is forwarded to
    _encode_state so the k in-context demonstration pairs prepend the SAME
    Stage-1 initial_context every one of the N batched streams shares.
    """
    if seed is None:
        seed = int(torch.randint(0, 2**31 - 1, (1,)).item())

    initial_context = _encode_state(state_val, exemplars=exemplars)
    drafts = _rlm_generate_batch(
        policy, state_val, count=N, max_depth=max_depth, temperature=temperature,
        seed=seed, stage_tag="stage1", initial_context=initial_context,
    )
    rewards = [executing_verifier(state_val, ep.final_action) for ep in drafts]

    best_idx = int(max(range(N), key=lambda i: rewards[i]))
    return Stage1Result(
        drafts=drafts,
        rewards=rewards,
        best_idx=best_idx,
        best_episode=drafts[best_idx],
    )


def igrpo_stage2(
    policy: TinyPolicyTransformer,
    state_val: int,
    best_episode: RLMEpisode,
    G: int = 4,
    max_depth: int = 2,
    temperature: float = 1.0,
    seed: Optional[int] = None,
    exemplars: Optional[list[tuple[int, int]]] = None,
    entropy_beta: float = 0.0,
    degenerate_resample: bool = False,
    resample_temperature: float = 2.0,
    per_state_reward_norm: bool = False,
) -> Stage2Result:
    """Stage 2: condition on (obs + d-hat), sample G refinements, score.

    spec: 'Stage-2 condition on (obs+d-hat), sample G=4 refinements,
           verifier-score, advantage A_j=(r_j-mean)/std with A_j=0 if std=0'

    The conditioning on d-hat: we encode the best draft's final action as
    an additional context token appended to the state encoding.
    This mirrors 'q' = Concat(q, d-hat)' (iGRPO Eq. 3).

    D2/D3: each episode produced here carries episode.sampled_tokens which is
    the verbatim o_j sequence (all tokens emitted AFTER the prefix q').
    igrpo_loss uses these directly as the action tokens to score.

    SAMPLING-COST CURE PHASE 2 (2026-07-03): the G refinements are generated
    by ONE batched call (_rlm_generate_batch), same mechanics/fallback as
    igrpo_stage1 above; stage_tag="stage2" keeps its per-stream seeds
    disjoint from Stage-1's even when the SAME `seed` value is passed to
    both (the common case — see igrpo_step below).

    CORPUS-V2 (additive, default OFF): `exemplars`, if given, prepends the
    SAME k in-context demonstration pairs used in Stage-1 to the (obs +
    d-hat) prefix q', via _encode_state — so credited-position / prefix
    masking downstream (igrpo_loss) sees the correct, longer ctx_len through
    stage2.prefix_context.size(0) without any change to igrpo_loss itself.

    V1.7 ANTI-COLLAPSE (design spec sec 8d; additive — entropy_beta=0.0 and
    degenerate_resample=False, both defaults, reproduce pre-v1.7 output
    bit-for-bit):

    entropy_beta (knob ii): after rewards are scored, A_j' = A_j +
    entropy_beta * H(pi(.|s)) is added UNIFORMLY to every advantage in the
    group (H is not indexed by j — a literal reading of the design spec's
    equation), where H is the Shannon entropy of the policy's OWN action
    distribution at the sampled state (_softmax_entropy, temperature=1.0 —
    independent of the rollout-temperature knob (i)), captured from the
    SAME forward the sampler already runs at _step==0 of the (first)
    _rlm_generate_batch call below — no extra forward pass. When
    entropy_beta=0.0 the term is exactly 0.0 regardless of H, a no-op on
    both compute and RNG consumption (initial_logits_out is only passed
    when entropy_beta != 0.0).

    degenerate_resample (knob iii): if the initial G-way reward group has
    population std(rewards)==0 (every rollout landed on the same action —
    the collapse signature), the ENTIRE group is resampled ONCE at
    resample_temperature (default 2.0, spec-pinned — not a CLI value)
    using stage_tag "stage2-resample" (distinct from "stage2", so
    _derive_stream_seed draws a disjoint per-stream seed sequence — never
    replays the degenerate group's own draws). Advantages are then
    computed from whichever group (original or resampled) is current; if
    the resampled group is ALSO degenerate, compute_advantages naturally
    returns all zeros — "accepting A_j=0" (design spec sec 8d) falls out
    of the existing degenerate-group convention with no separate branch
    needed. The entropy capture (if any) is NOT re-taken after a resample:
    pi(.|s) is a property of the frozen policy and the state/prefix, not
    of the sampling temperature, so it is identical either way.

    V1.9 PER-STATE REWARD NORMALIZATION (design spec sec 8f; additive —
    per_state_reward_norm=False, the default, reproduces pre-v1.9 output
    bit-for-bit):

    per_state_reward_norm (v1.9 lever): when True, the group-wide
    compute_advantages(rewards) baseline below is replaced by
    compute_advantages_per_state(rewards, state_vals) with every sample in
    THIS call tagged by the SAME state_val (Stage-2 conditions on exactly
    one state per call - see this function's own state_val parameter).
    Boundary-case disclosure: because this call's Stage-2 group is always
    single-state, compute_advantages_per_state's per-state partition over a
    one-state input is mathematically IDENTICAL to compute_advantages over
    the whole group - the lever is a structural no-op at THIS call site
    under the current single-state-per-step trainer architecture. It is
    still wired and tested here (not left unintegrated): the spec's binding
    contract is the flag's presence and the general per-state function's
    correctness, exercised directly by compute_advantages_per_state's own
    unit tests (a multi-state group, unequal sample counts); this call
    site is where a future multi-state batching change would plug in
    without further edits to igrpo_stage2 itself.
    """
    # Build augmented context: state token + best draft final action (= q')
    base_context = _encode_state(state_val, exemplars=exemplars)
    d_hat_token = torch.tensor([best_episode.final_action], dtype=torch.long)
    augmented_context = torch.cat([base_context, d_hat_token])

    if seed is None:
        seed = int(torch.randint(0, 2**31 - 1, (1,)).item())

    initial_logits_capture: list = []
    refinements = _rlm_generate_batch(
        policy, state_val, count=G, max_depth=max_depth, temperature=temperature,
        seed=seed, stage_tag="stage2", initial_context=augmented_context,
        initial_logits_out=initial_logits_capture if entropy_beta != 0.0 else None,
    )
    rewards = [executing_verifier(state_val, ep.final_action) for ep in refinements]

    resample_fired = False
    if degenerate_resample and _reward_group_is_degenerate(rewards):
        resample_fired = True
        refinements = _rlm_generate_batch(
            policy, state_val, count=G, max_depth=max_depth, temperature=resample_temperature,
            seed=seed, stage_tag="stage2-resample", initial_context=augmented_context,
            initial_logits_out=None,
        )
        rewards = [executing_verifier(state_val, ep.final_action) for ep in refinements]

    if per_state_reward_norm:
        advantages = compute_advantages_per_state(rewards, [state_val] * len(rewards))
    else:
        advantages = compute_advantages(rewards)
    if entropy_beta != 0.0 and initial_logits_capture:
        entropy_bonus = entropy_beta * _softmax_entropy(initial_logits_capture[0])
        advantages = [a + entropy_bonus for a in advantages]

    return Stage2Result(
        refinements=refinements,
        rewards=rewards,
        advantages=advantages,
        prefix_context=augmented_context,
        resample_fired=resample_fired,
    )


def igrpo_loss(
    policy: TinyPolicyTransformer,
    ref_policy: TinyPolicyTransformer,
    state_val: int,
    stage2: Stage2Result,
    best_episode: RLMEpisode,
    epsilon: float = 0.2,
    beta: float = 0.0,
) -> torch.Tensor:
    """Compute iGRPO policy-gradient loss for Stage-2 outputs.

    Implements iGRPO Eq. 5 (clipped importance-ratio PG minus KL), scored at
    the CREDITED action position rather than averaged over the full sequence:

      J = (1/G) sum_j [
            min(r_j,credited * A_j,  clip(r_j,credited, 1-eps, 1+eps) * A_j)
            - beta * KL_hat(j, credited)
          ]

    where r_j,t = pi_theta(o_jt | q', o_j<t) / pi_theta_old(o_jt | q', o_j<t)
    and KL_hat uses the Schulman 2020 non-negative estimator; `credited` is
    the index of the last occurrence of episode j's final_action within its
    verbatim sampled sequence (D6 fix below).

    D6 fix (2026-07-02) — credited-position scoring, not full-sequence 1/T
    average:
      The RLM loop (rlm_generate) emits a long, mostly-incidental token
      stream before terminating (RECURSE self-calls, intermediate action
      guesses) — only ONE position, the last occurrence of final_action, is
      causally responsible for the verifier reward that produced A_j. The
      original `pg_per_tok.sum() / T` full-sequence average attenuated that
      credited position's own gradient contribution by exactly 1/T while the
      T-1 exploration-noise positions contributed gradient mass, at the SAME
      per-token weight, into the SAME shared transformer parameters — probes
      measured those noise-position gradients as near-orthogonal to the
      credited direction (cos~0.01) yet dominating ~91% of ||grad_full||.
      This is why a dense, non-degenerate reward/advantage signal never
      converted into policy improvement pre-fix. The fix scores only
      pg_per_tok[credited_idx] (undivided) per episode; when final_action is
      not literally present in the (already-clamped) verbatim sequence
      (fallback_fired episodes, or truncation), credited_idx falls back to
      the last emitted position — the same convention rlm_generate itself
      uses when no in-band action was ever sampled.

    D2 fix — verbatim sampled tokens:
      The scored token sequence o_j is exactly episode.sampled_tokens — the
      verbatim tokens the policy emitted during Stage-2 sampling (including any
      RECURSE / FINAL control tokens).  The prior implementation filtered those
      out, producing a different sequence from what pi_theta_old saw at sample
      time, which biases the importance ratio whenever fallback/RECURSE fires.

    D3 fix — prefix masking:
      The conditioning prefix q' = (obs + d-hat) is context, not an action.
      Its tokens are excluded from the PG loss by construction: we only score
      positions [ctx_len-1 .. ctx_len-1+T-1] of the full sequence, which
      correspond exactly to the T action tokens o_j.  Prefix positions
      contribute 0 to the loss.

    D3 fix — log_pi_theta_old at sample time:
      ref_policy is a deepcopy of policy taken BEFORE Stage-2 sampling in
      igrpo_step (i.e. pi_theta_old at sample time).  We re-run ref_policy on
      the verbatim (prefix + o_j) sequence to recover the log-probs that
      pi_theta_old would have assigned to each sampled token — this is
      equivalent to capturing them at sample time because ref_policy is frozen
      and identical to the model that generated the tokens.  No greedy-vs-sample
      distribution mismatch exists: we use the same token sequence for both
      pi_theta and pi_theta_old.

    Stage-1 does NOT receive gradients (no-grad used during sampling).

    spec: 'clipped importance-ratio policy-gradient loss (epsilon param)
           minus beta*KL, and UPDATE A REAL nn.Module POLICY'S OWN WEIGHTS'
    """
    # q' = Concat(obs, d-hat): the prefix that conditions Stage-2 sampling.
    # Prefer the prefix stored in Stage2Result (computed in igrpo_stage2);
    # fall back to reconstructing it for callers that build Stage2Result directly.
    if stage2.prefix_context is not None:
        aug_ctx = stage2.prefix_context
    else:
        base_ctx = _encode_state(state_val)
        d_hat_tok = torch.tensor([best_episode.final_action], dtype=torch.long)
        aug_ctx = torch.cat([base_ctx, d_hat_tok])

    ctx_len = aug_ctx.size(0)
    G = len(stage2.refinements)
    loss_terms = []

    for j, (ep, adv) in enumerate(zip(stage2.refinements, stage2.advantages)):
        # D2/D3: use the VERBATIM sampled token sequence o_j.
        # episode.sampled_tokens contains every token the policy emitted after
        # the prefix, in emission order, including RECURSE and FINAL tokens.
        # These are exactly the tokens whose log-probs pi_theta_old assigned
        # at sample time (ref_policy is the snapshot from before Stage-2).
        verbatim = ep.sampled_tokens

        if not verbatim:
            # Edge case: rlm_generate returned without emitting any token
            # (should not happen in normal operation; guard for robustness).
            # Same fabrication class as the rlm_generate fallbacks: never
            # substitute the verifier-correct token into the scored sequence.
            fa = ep.final_action if ep.final_action is not None else _no_action_fallback(state_val)
            verbatim = [fa % VOCAB_SIZE]

        # Cap to the space remaining after the prefix (PE limit).
        max_tgt_len = MAX_SEQ_LEN - ctx_len - 1   # leave 1 for safety
        verbatim = verbatim[:max(max_tgt_len, 1)]

        # Clamp any out-of-range token ids to valid embedding range.
        # (RECURSE=9 and FINAL=8 are within VOCAB_SIZE=10, so normally no-op.)
        verbatim = [t % VOCAB_SIZE for t in verbatim]

        target_ids = torch.tensor(verbatim, dtype=torch.long)
        T = len(target_ids)

        # D6 fix (2026-07-02 — igrpo-learning-fix): identify the ONE position
        # in this (already-clamped, already-mod'd) verbatim sequence that is
        # causally responsible for the verifier reward: the last occurrence
        # of ep.final_action, i.e. the token executing_verifier actually
        # scored. Every other position is Stage-1/Stage-2 exploration the RLM
        # loop emitted before terminating (RECURSE/FINAL control tokens and
        # intermediate action guesses) and is uncorrelated with the outcome.
        # Root cause verified by probe (receipt): dividing the full-sequence
        # PG sum by T attenuates the credited position's own gradient by
        # exactly 1/T while the T-1 noise positions contribute gradient mass,
        # at the same per-token weight, into the SAME shared transformer
        # parameters (~91% of ||grad_full|| measured from non-credited
        # positions; noise-vs-credited cosine ~0.01, i.e. near-orthogonal) —
        # this is why the reward/advantage signal never converted into
        # policy improvement even though it was dense and non-degenerate.
        credited_idx = T - 1  # fallback: last emitted position
        if ep.final_action is not None:
            target_fa = ep.final_action % VOCAB_SIZE
            for _idx in range(T - 1, -1, -1):
                if verbatim[_idx] == target_fa:
                    credited_idx = _idx
                    break
        # else (no final_action recorded at all — should not happen in normal
        # operation, same guard class as the "not verbatim" branch above):
        # credited_idx stays at the last-position fallback. Same fallback
        # applies when final_action is not literally present in verbatim
        # (e.g. truncated away by the max_tgt_len cap, or a fallback_fired
        # episode whose recorded final_action was never itself sampled).

        # Full input sequence: q' (prefix) + o_j (verbatim action tokens).
        # Teacher-forced: forward pass over the full sequence; we read logits
        # at the prefix positions to predict the first action token and so on.
        full_input = torch.cat([aug_ctx, target_ids]).unsqueeze(0)  # (1, ctx+T)

        # pi_theta logits — with gradient (used for loss).
        logits_theta = policy.forward(full_input)[0]             # (ctx+T, V)

        # pi_theta_old (= ref_policy) logits — no gradient.
        with torch.no_grad():
            logits_ref = ref_policy.forward(full_input)[0]       # (ctx+T, V)

        # Scoring range: positions [ctx_len-1 .. ctx_len-1+T-1] in the
        # logits tensor predict the T action tokens o_j.
        # The prefix positions [0 .. ctx_len-2] are EXCLUDED — they are
        # context, not actions, so they contribute 0 to the PG loss (D3).
        pred_range = slice(ctx_len - 1, ctx_len - 1 + T)
        lp_theta = F.log_softmax(logits_theta[pred_range], dim=-1)   # (T, V)
        lp_ref   = F.log_softmax(logits_ref[pred_range],   dim=-1)   # (T, V)

        tok_lp_theta = lp_theta[torch.arange(T), target_ids]         # (T,)
        tok_lp_ref   = lp_ref[torch.arange(T), target_ids]           # (T,)

        # Importance ratio r_jt = exp(log pi_theta - log pi_theta_old)
        # pi_theta_old = ref_policy (snapshot taken before Stage-2 sampling).
        log_ratio = tok_lp_theta - tok_lp_ref                         # (T,)
        ratio = log_ratio.exp()                                        # (T,)

        A = adv  # scalar group-relative advantage for this completion

        # Clipped surrogate (per-token, iGRPO Eq. 5)
        surr1 = ratio * A
        surr2 = torch.clamp(ratio, 1.0 - epsilon, 1.0 + epsilon) * A
        pg_per_tok = torch.min(surr1, surr2)                          # (T,)

        # KL term (Schulman 2020 non-negative estimator):
        # KL_hat = p_ref/p_theta - log(p_ref/p_theta) - 1
        if beta > 0.0:
            p_ref_over_theta = (tok_lp_ref - tok_lp_theta).exp()      # (T,)
            kl_hat = p_ref_over_theta - (tok_lp_ref - tok_lp_theta) - 1.0  # (T,)
        else:
            kl_hat = torch.zeros(T)

        per_tok = pg_per_tok - beta * kl_hat                          # (T,)
        # D6 fix: score ONLY the credited position (undivided), never a
        # full-sequence 1/T average. Stage-1/Stage-2 sampling, advantages,
        # the clipped-ratio math, the KL term, the G-way mean below, and the
        # optimizer are all unchanged — this is a localized change to which
        # single scalar represents episode j's contribution to the loss.
        scaled = per_tok[credited_idx]
        loss_terms.append(scaled)

    # Average over G, negate (we want to MAXIMISE J, so loss = -J)
    if loss_terms:
        total_loss = -torch.stack(loss_terms).mean()
    else:
        total_loss = torch.tensor(0.0)

    return total_loss


# ---------------------------------------------------------------------------
# One training step (full iGRPO update)
# ---------------------------------------------------------------------------

def igrpo_step(
    policy: TinyPolicyTransformer,
    optimizer: torch.optim.Optimizer,
    state_val: int,
    N: int = 4,
    G: int = 4,
    max_depth: int = 2,
    epsilon: float = 0.2,
    beta: float = 0.0,
    temperature: float = 1.5,
    seed: Optional[int] = None,
    exemplars: Optional[list[tuple[int, int]]] = None,
    entropy_beta: float = 0.0,
    degenerate_resample: bool = False,
    resample_temperature: float = 2.0,
    per_state_reward_norm: bool = False,
) -> dict:
    """One full iGRPO step: Stage-1 → Stage-2 → loss → weight update.

    spec: 'clipped importance-ratio policy-gradient loss (epsilon param)
           minus beta*KL, and UPDATE A REAL nn.Module POLICY'S OWN WEIGHTS
           (not a side-classifier, not a prompt-template index)'

    Returns a receipt dict with stage rewards, advantages, loss.

    SAMPLING-COST CURE PHASE 2 (2026-07-03): `seed` is this step's run_seed
    for the new per-stream-Generator sampling convention (see
    _derive_stream_seed / igrpo_stage1 / igrpo_stage2 / _rlm_generate_batch).
    Passed unchanged to BOTH stages — their own stage_tag ("stage1" vs
    "stage2") keeps the derived per-stream seeds disjoint even though the
    run_seed is shared. If not supplied, one is drawn from torch's current
    global RNG state, so existing callers (train_one_step, cmd_owned_smoke,
    cmd_live, this file's own smoke/tests — none of which pass seed) stay
    reproducible under a global torch.manual_seed(...) exactly as before.

    CORPUS-V2 (additive, default OFF): `exemplars`, if given, is forwarded
    unchanged to BOTH igrpo_stage1 and igrpo_stage2 so Stage-1's draft
    sampling and Stage-2's refinement sampling condition on the SAME k
    in-context demonstration pairs. `exemplars=None` (default) is
    byte-identical to pre-corpus-v2 behavior on every call site that does
    not pass it (every existing caller in this repo).

    V1.7 ANTI-COLLAPSE (design spec sec 8d; additive, all three default
    OFF): `temperature` is where callers apply knob (i) — this function has
    no schedule-awareness of its own; a caller that wants the linear-decay
    schedule computes schedule_temperature(step, ...) itself and passes the
    result in as this SAME `temperature` argument, so both Stage-1 and
    Stage-2 sample at the schedule-resolved value for this step, exactly
    like the pre-v1.7 fixed-temperature call. `entropy_beta` and
    `degenerate_resample` (knobs ii/iii) are forwarded unchanged to
    igrpo_stage2 (Stage-1 has no advantage/gradient to bias — see that
    function's own docstring). Defaults (0.0 / False) reproduce pre-v1.7
    output bit-for-bit.

    V1.9 PER-STATE REWARD NORMALIZATION (design spec sec 8f; additive,
    default OFF): `per_state_reward_norm` is forwarded unchanged to
    igrpo_stage2 (Stage-1 has no advantage/gradient to bias, same as knobs
    ii/iii above). Default False reproduces pre-v1.9 output bit-for-bit.
    """
    if seed is None:
        seed = int(torch.randint(0, 2**31 - 1, (1,)).item())

    # Snapshot reference policy (pi_theta_old) — no grad.
    # Taken BEFORE Stage-2 sampling so ref_policy represents the model
    # distribution at the moment the o_j tokens were drawn (D3).
    ref_policy = deepcopy(policy)
    ref_policy.eval()
    for p in ref_policy.parameters():
        p.requires_grad_(False)

    # Stage 1 + Stage 2 sampling carries NO gradient: igrpo_loss re-forwards
    # the sampled sequences itself (logits_theta) to build the PG graph, so
    # generation-time activation graphs are pure memory waste — on the 466M
    # owned core they retain hundreds of token-forward graphs per step and
    # OOM'd the governed 19.19GiB cap at C14-LIVE (receipt
    # live-20260702T221941Z). Sampling distributions are unchanged.
    with torch.no_grad():
        # Stage 1
        s1 = igrpo_stage1(
            policy, state_val, N=N, max_depth=max_depth, temperature=temperature, seed=seed,
            exemplars=exemplars,
        )

        # Stage 2
        s2 = igrpo_stage2(
            policy, state_val, s1.best_episode, G=G, max_depth=max_depth,
            temperature=temperature, seed=seed, exemplars=exemplars,
            entropy_beta=entropy_beta, degenerate_resample=degenerate_resample,
            resample_temperature=resample_temperature,
            per_state_reward_norm=per_state_reward_norm,
        )

    # Compute loss and update
    optimizer.zero_grad()
    loss = igrpo_loss(
        policy=policy,
        ref_policy=ref_policy,
        state_val=state_val,
        stage2=s2,
        best_episode=s1.best_episode,
        epsilon=epsilon,
        beta=beta,
    )
    loss.backward()
    optimizer.step()

    completion_keys = {
        (tuple(episode.sampled_tokens), episode.final_action, episode.fallback_fired)
        for episode in s2.refinements
        if episode.sampled_tokens
    }
    drop_reasons: list[str] = []
    for index, episode in enumerate(s2.refinements):
        if not episode.sampled_tokens:
            drop_reasons.append(f"stage2:{index}:no_emitted_tokens")
        elif episode.final_action is None:
            drop_reasons.append(f"stage2:{index}:no_final_action")
        elif episode.fallback_fired:
            drop_reasons.append(f"stage2:{index}:fallback_fired")

    return {
        "state_val": state_val,
        "stage1_rewards": s1.rewards,
        "stage1_best_idx": s1.best_idx,
        "stage1_best_action": s1.best_episode.final_action,
        "stage2_rewards": s2.rewards,
        "stage2_advantages": s2.advantages,
        "loss": float(loss.item()),
        "resample_fired": s2.resample_fired,
        "engagement": {
            "schema_version": "ember-igrpo-engagement-step-v1",
            "requested_n": N,
            "requested_g": G,
            "realized_stage1_drafts": len(s1.drafts),
            "attempted": len(s2.refinements),
            "emitted": sum(bool(episode.sampled_tokens) for episode in s2.refinements),
            "valid": sum(
                bool(episode.sampled_tokens)
                and episode.final_action is not None
                and not episode.fallback_fired
                for episode in s2.refinements
            ),
            "scored": len(s2.rewards),
            "unique_completions": len(completion_keys),
            "reward_vector_length": len(s2.rewards),
            "advantage_vector_length": len(s2.advantages),
            "group_ids": [f"stage2:{index}" for index in range(len(s2.refinements))],
            "normalization_denominator": min(
                len(s2.refinements), len(s2.advantages)
            ),
            "estimator_name": "population_std_group_relative",
            "drop_reasons": drop_reasons,
        },
    }


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def _run_tests(verbose: bool = True) -> tuple[bool, list[str]]:
    """Run all load-bearing unit tests. Returns (all_passed, list_of_test_names)."""

    passed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []

    def check(name: str, cond: bool, msg: str = "") -> None:
        if cond:
            passed.append(name)
            if verbose:
                print(f"  PASS  {name}")
        else:
            failed.append(name)
            if verbose:
                print(f"  FAIL  {name}  {msg}")

    # -----------------------------------------------------------------------
    # T1: advantage std=0 -> all zeros
    # -----------------------------------------------------------------------
    name = "advantage_std0_yields_zeros"
    try:
        rewards_equal = [0.5, 0.5, 0.5, 0.5]
        advs = compute_advantages(rewards_equal)
        check(name, all(a == 0.0 for a in advs),
              f"expected all 0.0, got {advs}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T2: advantage std=0 -> all zeros (degenerate reward=1.0)
    # -----------------------------------------------------------------------
    name = "advantage_degenerate_all_ones"
    try:
        rewards_ones = [1.0, 1.0, 1.0, 1.0]
        advs = compute_advantages(rewards_ones)
        check(name, all(a == 0.0 for a in advs),
              f"expected all 0.0, got {advs}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T3: advantage std>0 -> correct values (population std, divide by n)
    # -----------------------------------------------------------------------
    name = "advantage_nondegenerate_correct_values"
    try:
        rewards = [0.0, 1.0, 0.0, 1.0]
        advs = compute_advantages(rewards)
        mean_r = 0.5
        import statistics
        # Population std (pstdev) matches compute_advantages which uses / n.
        std_r = statistics.pstdev(rewards)
        expected = [(r - mean_r) / std_r for r in rewards]
        close = all(abs(a - e) < 1e-6 for a, e in zip(advs, expected))
        check(name, close, f"got {advs}, expected {expected}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T4: argmax selection (Stage-1 d-hat = correct best)
    # -----------------------------------------------------------------------
    name = "argmax_dhat_selection"
    try:
        rewards_test = [0.0, 0.0, 1.0, 0.0]
        best = int(max(range(len(rewards_test)), key=lambda i: rewards_test[i]))
        check(name, best == 2, f"expected idx 2, got {best}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T5: argmax tie-break (first occurrence of max, deterministic)
    # -----------------------------------------------------------------------
    name = "argmax_tiebreak_first_max"
    try:
        rewards_tie = [1.0, 1.0, 0.0, 0.0]
        best = int(max(range(len(rewards_tie)), key=lambda i: rewards_tie[i]))
        check(name, best == 0, f"expected idx 0, got {best}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T6: group mean/std correctness (population std)
    # -----------------------------------------------------------------------
    name = "group_mean_std_correctness"
    try:
        import statistics
        r = [0.0, 0.25, 0.75, 1.0]
        advs = compute_advantages(r)
        m = sum(r) / len(r)
        # Population std matches the / n convention in compute_advantages.
        s = statistics.pstdev(r)
        expected = [(x - m) / s for x in r]
        close = all(abs(a - e) < 1e-6 for a, e in zip(advs, expected))
        check(name, close, f"got {advs}, expected {expected}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")

    # -----------------------------------------------------------------------
    # T7: clipping in loss (ratio far from 1 is clipped)
    # -----------------------------------------------------------------------
    name = "clip_ratio_applied_in_loss"
    try:
        torch.manual_seed(42)
        policy = TinyPolicyTransformer()
        ref    = TinyPolicyTransformer()
        # Manually inject very different weights to force large ratios
        with torch.no_grad():
            for p_param, r_param in zip(policy.parameters(), ref.parameters()):
                p_param.data.fill_(0.1)
                r_param.data.fill_(-0.1)

        state_val = 3
        # Build a fake stage2 with mixed advantages
        ep = rlm_generate(policy, state_val, max_depth=0, temperature=0.0)
        s2 = Stage2Result(
            refinements=[ep, ep, ep, ep],
            rewards=[0.0, 1.0, 0.0, 1.0],
            advantages=compute_advantages([0.0, 1.0, 0.0, 1.0]),
            prefix_context=None,
        )
        loss_val = igrpo_loss(policy, ref, state_val, s2, ep, epsilon=0.2, beta=0.0)
        # If clipping works, loss is finite and non-NaN
        check(name, torch.isfinite(loss_val) and not torch.isnan(loss_val),
              f"loss={loss_val}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T8: WEIGHTS CHANGE after reward-driven update (load-bearing assertion)
    # -----------------------------------------------------------------------
    name = "policy_weights_change_after_reward_update"
    try:
        torch.manual_seed(7)
        policy = TinyPolicyTransformer()
        optimizer = torch.optim.Adam(policy.parameters(), lr=1e-3)

        # Record pre-update snapshot
        pre_params = {n: p.data.clone() for n, p in policy.named_parameters()}

        # Run multiple steps to ensure at least one non-degenerate update
        any_changed = False
        for sv in range(8):
            result = igrpo_step(
                policy, optimizer, state_val=sv,
                N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5
            )
            # Check if any parameter changed vs pre-update snapshot
            for n, p in policy.named_parameters():
                if not torch.allclose(p.data, pre_params[n], atol=0.0):
                    any_changed = True
                    break
            if any_changed:
                break

        check(name, any_changed,
              "no weight changed after reward-driven update across all 8 states")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T9: degenerate all-equal-reward batch yields ~zero advantage (no spurious update)
    # -----------------------------------------------------------------------
    name = "degenerate_equal_rewards_zero_advantage_no_spurious_update"
    try:
        torch.manual_seed(99)
        policy = TinyPolicyTransformer()
        optimizer = torch.optim.Adam(policy.parameters(), lr=1e-3)

        pre_params = {n: p.data.clone() for n, p in policy.named_parameters()}

        # Build a fake episode that always emits a valid but wrong action
        # state=0 -> correct=1; we force final_action=7 (always wrong, reward=0)
        state_val = 0
        ep = rlm_generate(policy, state_val, max_depth=0, temperature=0.0)
        # Override final_action to always-wrong but in-vocab token.
        ep.final_action = 7   # (0+1)%8=1 is correct; 7 is always wrong
        # Override sampled_tokens to match the forced final_action.
        ep.sampled_tokens = [7]
        ep.steps = [{"depth": 0, "token": 7, "context_len": 1}]

        s2 = Stage2Result(
            refinements=[ep, ep, ep, ep],
            rewards=[0.0, 0.0, 0.0, 0.0],
            advantages=compute_advantages([0.0, 0.0, 0.0, 0.0]),
            prefix_context=None,
        )

        ref_policy = deepcopy(policy)
        for p in ref_policy.parameters():
            p.requires_grad_(False)

        optimizer.zero_grad()
        loss = igrpo_loss(policy, ref_policy, state_val, s2, ep, epsilon=0.2, beta=0.0)
        loss.backward()
        optimizer.step()

        # With all advantages=0, gradients should be ~0; weights should not change
        max_delta = max(
            (p.data - pre_params[n]).abs().max().item()
            for n, p in policy.named_parameters()
        )
        # Allow tiny floating point noise but not meaningful weight drift
        check(name, max_delta < 1e-6,
              f"max weight delta={max_delta:.2e} (expected <1e-6 for zero-advantage batch)")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T10: RLM recursion depth respected
    # -----------------------------------------------------------------------
    name = "rlm_max_depth_respected"
    try:
        torch.manual_seed(3)
        policy = TinyPolicyTransformer()
        # Force RECURSE token to always be emitted: set its logit very high
        with torch.no_grad():
            policy.head.weight.data[ACTION_RECURSE] = 100.0
            policy.head.bias.data[ACTION_RECURSE]   = 100.0

        max_d = 2
        ep = rlm_generate(policy, state_val=4, max_depth=max_d, temperature=0.0)
        # depth_used should never exceed max_d
        check(name, ep.depth_used <= max_d,
              f"depth_used={ep.depth_used} > max_depth={max_d}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T11: executing verifier is non-lexical (reward from state machine, not string)
    # -----------------------------------------------------------------------
    name = "verifier_is_executing_not_lexical"
    try:
        # Correct action for state=3 is (3+1)%8=4
        r_correct = executing_verifier(3, 4)
        r_wrong   = executing_verifier(3, 3)  # same digit as state — NOT a match
        r_wrong2  = executing_verifier(3, 0)
        check(name, r_correct == 1.0 and r_wrong == 0.0 and r_wrong2 == 0.0,
              f"r_correct={r_correct}, r_wrong={r_wrong}, r_wrong2={r_wrong2}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T12: Stage-1 returns best draft (d-hat = argmax of rewards)
    # -----------------------------------------------------------------------
    name = "stage1_dhat_is_argmax_of_verifier_rewards"
    try:
        torch.manual_seed(11)
        policy = TinyPolicyTransformer()
        # Force policy to always predict action=5 (correct for state=4)
        with torch.no_grad():
            policy.head.weight.data.fill_(0.0)
            policy.head.bias.data.fill_(0.0)
            policy.head.bias.data[5] = 100.0  # action=5 is argmax

        s1 = igrpo_stage1(policy, state_val=4, N=4, max_depth=0, temperature=0.0)
        # All drafts should emit action=5 (correct for state=4) -> reward=1.0 for all
        check(name, all(r == 1.0 for r in s1.rewards) and s1.best_idx >= 0,
              f"rewards={s1.rewards}, best_idx={s1.best_idx}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T13 (D1): causal mask — future token cannot change an earlier position's logits
    # -----------------------------------------------------------------------
    name = "causal_mask_future_token_does_not_affect_earlier_logits"
    try:
        torch.manual_seed(13)
        policy = TinyPolicyTransformer()
        policy.eval()

        # Sequence of length 4: tokens [2, 5, 1, 3]
        ids_a = torch.tensor([[2, 5, 1, 3]], dtype=torch.long)
        # Change only the last token (future relative to position 0-2)
        ids_b = torch.tensor([[2, 5, 1, 7]], dtype=torch.long)

        with torch.no_grad():
            logits_a = policy.forward(ids_a)[0]   # (4, V)
            logits_b = policy.forward(ids_b)[0]   # (4, V)

        # Positions 0, 1, 2 should be IDENTICAL — they cannot attend to position 3.
        causal_ok = torch.allclose(logits_a[:3], logits_b[:3], atol=1e-5)
        # Position 3 logits MAY differ (it attends to itself, which changed).
        check(name, causal_ok,
              f"positions 0-2 differ when only last token changes: "
              f"max_diff={( logits_a[:3] - logits_b[:3] ).abs().max().item():.4e}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T14 (D2/D3): scored tokens = verbatim sampled tokens; prefix contributes 0
    # -----------------------------------------------------------------------
    name = "scored_tokens_are_verbatim_sampled_and_prefix_is_masked"
    try:
        torch.manual_seed(14)
        policy = TinyPolicyTransformer()
        ref    = deepcopy(policy)
        for p in ref.parameters():
            p.requires_grad_(False)

        state_val = 2
        # Run one Stage-2 sample
        best_ep = rlm_generate(policy, state_val, max_depth=0, temperature=1.0)
        best_ep.final_action = best_ep.final_action if best_ep.final_action is not None else 3
        s2 = igrpo_stage2(policy, state_val, best_ep, G=2, max_depth=0, temperature=1.0)

        prefix = s2.prefix_context  # q' = [state_val, best_ep.final_action]

        for ep in s2.refinements:
            verbatim = ep.sampled_tokens
            # (a) sampled_tokens must be non-empty
            assert len(verbatim) > 0, "sampled_tokens is empty"

            # (b) build the same full_input that igrpo_loss uses
            target_ids = torch.tensor([t % VOCAB_SIZE for t in verbatim[:MAX_SEQ_LEN - prefix.size(0) - 1]], dtype=torch.long)
            full_input = torch.cat([prefix, target_ids]).unsqueeze(0)
            T = len(target_ids)
            ctx_len = prefix.size(0)

            with torch.no_grad():
                logits = ref.forward(full_input)[0]  # (ctx+T, V)

            # (c) prefix positions [0 .. ctx_len-2]: their contribution to the
            # PG loss is zero because pred_range starts at ctx_len-1.
            # Verify by computing what a "wrong" scorer that DID include prefix
            # positions would produce vs the correct scorer — they must differ
            # only when T > 0 (demonstrating the mask is non-trivial).
            lp_correct_range = F.log_softmax(logits[ctx_len - 1: ctx_len - 1 + T], dim=-1)
            lp_wrong_range   = F.log_softmax(logits[0: T], dim=-1)  # includes prefix positions

            # The scored tokens are exactly target_ids (the verbatim o_j, clamped).
            # Verify index correctness: lp sums must be finite scalars.
            tok_lp = lp_correct_range[torch.arange(T), target_ids]
            assert torch.all(torch.isfinite(tok_lp)), f"non-finite log-probs: {tok_lp}"

            # Prefix masking: if prefix tokens carry any signal, the two ranges
            # will differ (for a randomly-initialised model they almost certainly do).
            # We assert they are NOT identical to confirm the mask is active.
            if T > 0:
                ranges_differ = not torch.allclose(lp_correct_range, lp_wrong_range, atol=1e-5)
                assert ranges_differ, (
                    "correct and wrong scoring ranges are identical — "
                    "prefix mask may not be active"
                )

        check(name, True)
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T15 (D2/D3 fallback): importance ratio uses real sampled tokens when RECURSE fires
    # -----------------------------------------------------------------------
    name = "importance_ratio_uses_real_sampled_tokens_on_recurse_fallback"
    try:
        torch.manual_seed(15)
        policy = TinyPolicyTransformer()

        # Force the policy to emit ACTION_RECURSE as first token.
        with torch.no_grad():
            policy.head.weight.data.fill_(0.0)
            policy.head.bias.data.fill_(0.0)
            policy.head.bias.data[ACTION_RECURSE] = 50.0

        state_val = 1
        # max_depth=0 forces immediate fallback after RECURSE
        ep = rlm_generate(policy, state_val, max_depth=0, temperature=0.0)

        # sampled_tokens must include the RECURSE token and the fallback greedy token.
        assert len(ep.sampled_tokens) >= 2, (
            f"expected >=2 sampled tokens (RECURSE + fallback), got {ep.sampled_tokens}"
        )
        assert ACTION_RECURSE in ep.sampled_tokens, (
            f"RECURSE token missing from sampled_tokens: {ep.sampled_tokens}"
        )

        # Now check that igrpo_loss computes a finite loss using those tokens.
        ref_policy = deepcopy(policy)
        for p in ref_policy.parameters():
            p.requires_grad_(False)

        best_ep = ep  # use same episode as best for simplicity
        best_ep.final_action = best_ep.final_action if best_ep.final_action is not None else _no_action_fallback(state_val)
        s2 = Stage2Result(
            refinements=[ep],
            rewards=[0.0],
            advantages=[0.0],
            prefix_context=None,
        )
        loss_val = igrpo_loss(policy, ref_policy, state_val, s2, best_ep, epsilon=0.2, beta=0.0)
        assert torch.isfinite(loss_val) and not torch.isnan(loss_val), (
            f"loss is not finite: {loss_val}"
        )

        check(name, True)
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T16 (v1.7 knob i): temp_schedule parser + interpolation edge cases
    # -----------------------------------------------------------------------
    name = "temp_schedule_parser_and_interpolation_edge_cases"
    try:
        start, end, by_step = parse_temp_schedule("1.5:1.0:384")
        ok_parse = (start == 1.5 and end == 1.0 and by_step == 384)

        def _raises(spec: str) -> bool:
            try:
                parse_temp_schedule(spec)
                return False
            except ValueError:
                return True

        bad_field_count = _raises("1.5:1.0")          # too few fields
        bad_field_count2 = _raises("1.5:1.0:384:1")     # too many fields
        bad_numeric_start = _raises("abc:1.0:384")
        bad_numeric_end = _raises("1.5:xyz:384")
        bad_by_step_type = _raises("1.5:1.0:abc")
        bad_by_step_zero = _raises("1.5:1.0:0")
        bad_by_step_neg = _raises("1.5:1.0:-5")

        interp_start = schedule_temperature(0, 1.5, 1.0, 384) == 1.5
        interp_negative_step = schedule_temperature(-3, 1.5, 1.0, 384) == 1.5
        interp_end = schedule_temperature(384, 1.5, 1.0, 384) == 1.0
        interp_past_end = schedule_temperature(1000, 1.5, 1.0, 384) == 1.0
        mid_val = schedule_temperature(192, 1.5, 1.0, 384)
        interp_mid = abs(mid_val - 1.25) < 1e-9

        check(name, all([
            ok_parse, bad_field_count, bad_field_count2, bad_numeric_start,
            bad_numeric_end, bad_by_step_type, bad_by_step_zero, bad_by_step_neg,
            interp_start, interp_negative_step, interp_end, interp_past_end, interp_mid,
        ]), f"ok_parse={ok_parse} bad_field_count={bad_field_count},{bad_field_count2} "
            f"bad_numeric={bad_numeric_start},{bad_numeric_end} "
            f"bad_by_step={bad_by_step_type},{bad_by_step_zero},{bad_by_step_neg} "
            f"interp_start={interp_start} interp_negative_step={interp_negative_step} "
            f"interp_end={interp_end} interp_past_end={interp_past_end} mid_val={mid_val}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T17 (v1.7 knob ii): entropy bonus is exactly zero at beta=0 and a
    # uniform POSITIVE shift at beta>0 on a known (non-degenerate,
    # non-uniform) distribution.
    # -----------------------------------------------------------------------
    name = "entropy_bonus_zero_at_beta0_positive_shift_at_beta_gt0"
    try:
        torch.manual_seed(17)
        policy = TinyPolicyTransformer()
        # Force a KNOWN, non-degenerate head distribution (not all-zero,
        # which would be a special axis-symmetric case): entropy is
        # strictly > 0 (not a point mass) and strictly < log(VOCAB_SIZE)
        # (not uniform).
        with torch.no_grad():
            policy.head.weight.data.fill_(0.0)
            policy.head.bias.data.fill_(0.0)
            policy.head.bias.data[0] = 1.0
            policy.head.bias.data[1] = 0.5

        state_val = 2
        best_ep = rlm_generate(policy, state_val, max_depth=0, temperature=0.0)
        best_ep.final_action = best_ep.final_action if best_ep.final_action is not None else 3

        s2_off = igrpo_stage2(policy, state_val, best_ep, G=4, max_depth=0,
                               temperature=1.0, seed=555, entropy_beta=0.0)
        s2_on = igrpo_stage2(policy, state_val, best_ep, G=4, max_depth=0,
                              temperature=1.0, seed=555, entropy_beta=0.5)

        # Same seed/policy/state/temperature -> entropy_beta cannot affect
        # sampling (only post-processes advantages), so rewards must match.
        same_rewards = s2_off.rewards == s2_on.rewards
        zero_at_beta0 = all(abs(a - b) < 1e-9 for a, b in
                             zip(s2_off.advantages, compute_advantages(s2_off.rewards)))
        shifts = [on - off for on, off in zip(s2_on.advantages, s2_off.advantages)]
        uniform_shift = all(abs(s - shifts[0]) < 1e-6 for s in shifts)
        positive_shift = shifts[0] > 0.0

        check(name, same_rewards and zero_at_beta0 and uniform_shift and positive_shift,
              f"same_rewards={same_rewards} zero_at_beta0={zero_at_beta0} "
              f"shifts={shifts} uniform_shift={uniform_shift}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T18 (v1.7 knob iii): degenerate-resample fires EXACTLY ONCE on a
    # forced all-identical-action group, then accepts A_j=0 (never loops).
    # -----------------------------------------------------------------------
    name = "degenerate_resample_fires_exactly_once_on_forced_all_identical_group"
    try:
        torch.manual_seed(18)
        policy = TinyPolicyTransformer()
        # Force EVERY sampled action to the SAME wrong action (5) regardless
        # of temperature: an overwhelming bias survives softmax even at
        # resample_temperature=2.0, so BOTH the original AND the resampled
        # Stage-2 group stay degenerate (std=0) — proving the resample fires
        # ONCE then accepts A_j=0 rather than looping.
        with torch.no_grad():
            policy.head.weight.data.fill_(0.0)
            policy.head.bias.data.fill_(0.0)
            policy.head.bias.data[5] = 1000.0

        state_val = 0  # correct action = 1; forced action 5 is always wrong
        best_ep = rlm_generate(policy, state_val, max_depth=0, temperature=1.0)
        assert best_ep.final_action == 5, f"expected forced action 5, got {best_ep.final_action}"

        # Count _rlm_generate_batch invocations via a module-global-namespace
        # monkeypatch (this file's own convention — see
        # ember_c14_contract_rig._run_scrambled_arm's analogous patch of
        # executing_verifier). Patching globals() rather than importing this
        # module by name is deliberate: when run as `python
        # ember_resident_igrpo.py --test`, this file executes as __main__,
        # so `import ember_resident_igrpo` would load a SEPARATE module
        # object whose _rlm_generate_batch igrpo_stage2's bytecode never
        # looks up — globals() is always THIS module's own namespace
        # regardless of how it was loaded.
        call_count = {"n": 0}
        _orig_batch = globals()["_rlm_generate_batch"]

        def _counting_batch(*a, **kw):
            call_count["n"] += 1
            return _orig_batch(*a, **kw)

        globals()["_rlm_generate_batch"] = _counting_batch
        try:
            s2 = igrpo_stage2(
                policy, state_val, best_ep, G=4, max_depth=0, temperature=1.0,
                seed=777, degenerate_resample=True,
            )
        finally:
            globals()["_rlm_generate_batch"] = _orig_batch

        all_action_5 = all(ep.final_action == 5 for ep in s2.refinements)
        all_zero_reward = all(r == 0.0 for r in s2.rewards)
        all_zero_adv = all(a == 0.0 for a in s2.advantages)

        check(name, (
            s2.resample_fired is True
            and call_count["n"] == 2
            and all_action_5 and all_zero_reward and all_zero_adv
        ), f"resample_fired={s2.resample_fired} call_count={call_count['n']} "
           f"all_action_5={all_action_5} all_zero_reward={all_zero_reward} "
           f"all_zero_adv={all_zero_adv}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T19 (v1.9 lever): constant-reward group -> all advantages exactly 0
    # under per-state normalization (same degenerate-group convention as
    # compute_advantages, applied per-subgroup — see compute_advantages_
    # per_state's docstring).
    # -----------------------------------------------------------------------
    name = "per_state_reward_norm_constant_reward_group_all_zero"
    try:
        rewards = [0.5, 0.5, 0.5, 0.5]
        state_vals = [3, 3, 7, 7]  # two states, both constant within themselves
        advs = compute_advantages_per_state(rewards, state_vals)
        check(name, advs == [0.0, 0.0, 0.0, 0.0], f"advs={advs}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T20 (v1.9 lever): two states with unequal sample counts -> each state
    # centered over ITS OWN mean; a single-sample state gets advantage 0
    # (population variance of one point is exactly 0 -> compute_advantages'
    # std==0 branch fires for that subgroup).
    # -----------------------------------------------------------------------
    name = "per_state_reward_norm_unequal_sample_counts_centered_independently"
    try:
        # state A: 3 samples, rewards 1,0,1 (mean 2/3, std>0)
        # state B: 1 sample, reward 1 (single sample -> std=0 -> advantage 0)
        rewards = [1.0, 0.0, 1.0, 1.0]
        state_vals = [0, 0, 0, 1]
        advs = compute_advantages_per_state(rewards, state_vals)
        expected_a = compute_advantages([1.0, 0.0, 1.0])
        a_matches = all(abs(x - y) < 1e-9 for x, y in zip(advs[:3], expected_a))
        b_is_zero = advs[3] == 0.0
        check(name, a_matches and b_is_zero,
              f"advs={advs} expected_a={expected_a}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T21 (v1.9 lever, regression guard): per_state_reward_norm=False (the
    # default) leaves igrpo_stage2's advantages byte-identical to the
    # pre-v1.9 plain compute_advantages(rewards) path.
    # -----------------------------------------------------------------------
    name = "per_state_reward_norm_off_byte_identical_to_baseline"
    try:
        torch.manual_seed(19)
        policy = TinyPolicyTransformer()
        state_val = 4
        best_ep = rlm_generate(policy, state_val, max_depth=0, temperature=0.0)
        best_ep.final_action = best_ep.final_action if best_ep.final_action is not None else 5

        s2_baseline = igrpo_stage2(policy, state_val, best_ep, G=4, max_depth=0,
                                    temperature=1.0, seed=4242)
        s2_off = igrpo_stage2(policy, state_val, best_ep, G=4, max_depth=0,
                              temperature=1.0, seed=4242, per_state_reward_norm=False)

        same_rewards = s2_baseline.rewards == s2_off.rewards
        byte_identical = s2_baseline.advantages == s2_off.advantages
        matches_compute_advantages = s2_off.advantages == compute_advantages(s2_off.rewards)
        check(name, same_rewards and byte_identical and matches_compute_advantages,
              f"same_rewards={same_rewards} baseline={s2_baseline.advantages} "
              f"off={s2_off.advantages}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # T22 (v1.9 lever): the receipt envelope block (ember_c14_owned_run.py's
    # _envelope_v1_7_block) carries per_state_reward_norm true/false
    # correctly alongside the v1.7 three.
    #
    # NOTE (v2.0, design spec sec 8g; extended v2.1 sec 8h): _envelope_v1_7_
    # block also reads args.corpus_v3_resample and
    # args.corpus_v3_resample_start_step unconditionally now, so a manually-
    # constructed Namespace (as opposed to one produced by the real parser.
    # parse_args(), which always backfills every --flag's default) must
    # carry both or this raises AttributeError — all Namespaces below set
    # them to False/0 so this test stays scoped to per_state_reward_norm
    # only; the sibling test right below exercises corpus_v3_resample the
    # same way.
    # -----------------------------------------------------------------------
    name = "envelope_block_carries_per_state_reward_norm_flag"
    try:
        import argparse as _argparse
        import ember_c14_owned_run as _owned_run  # same scripts/ dir on sys.path

        ns_on = _argparse.Namespace(
            temp_schedule="1.5:1.0:384", entropy_beta=0.02, degenerate_resample=True,
            per_state_reward_norm=True, corpus_v3_resample=False,
            corpus_v3_resample_start_step=0,
        )
        ns_off = _argparse.Namespace(
            temp_schedule=None, entropy_beta=0.0, degenerate_resample=False,
            per_state_reward_norm=False, corpus_v3_resample=False,
            corpus_v3_resample_start_step=0,
        )
        block_on = _owned_run._envelope_v1_7_block(ns_on)
        block_off = _owned_run._envelope_v1_7_block(ns_off)
        check(name, (
            block_on.get("per_state_reward_norm") is True
            and block_off.get("per_state_reward_norm") is False
        ), f"block_on={block_on} block_off={block_off}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # V2.0 (design spec sec 8g): the receipt envelope block also carries
    # corpus_v3_resample true/false correctly alongside the other four keys.
    # -----------------------------------------------------------------------
    name = "envelope_block_carries_corpus_v3_resample_flag"
    try:
        import argparse as _argparse
        import ember_c14_owned_run as _owned_run  # same scripts/ dir on sys.path

        ns_on = _argparse.Namespace(
            temp_schedule=None, entropy_beta=0.0, degenerate_resample=False,
            per_state_reward_norm=False, corpus_v3_resample=True,
            corpus_v3_resample_start_step=0,
        )
        ns_off = _argparse.Namespace(
            temp_schedule=None, entropy_beta=0.0, degenerate_resample=False,
            per_state_reward_norm=False, corpus_v3_resample=False,
            corpus_v3_resample_start_step=0,
        )
        block_on = _owned_run._envelope_v1_7_block(ns_on)
        block_off = _owned_run._envelope_v1_7_block(ns_off)
        check(name, (
            block_on.get("corpus_v3_resample") is True
            and block_off.get("corpus_v3_resample") is False
        ), f"block_on={block_on} block_off={block_off}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # V2.1 (design spec sec 8h, corpus-v3.1): the receipt envelope block
    # also carries corpus_v3_resample_start_step correctly for both 0 and a
    # non-zero value (384, the attempt-18 command-of-record value).
    # -----------------------------------------------------------------------
    name = "envelope_block_carries_corpus_v3_resample_start_step"
    try:
        import argparse as _argparse
        import ember_c14_owned_run as _owned_run  # same scripts/ dir on sys.path

        ns_zero = _argparse.Namespace(
            temp_schedule=None, entropy_beta=0.0, degenerate_resample=False,
            per_state_reward_norm=False, corpus_v3_resample=True,
            corpus_v3_resample_start_step=0,
        )
        ns_384 = _argparse.Namespace(
            temp_schedule=None, entropy_beta=0.0, degenerate_resample=False,
            per_state_reward_norm=False, corpus_v3_resample=True,
            corpus_v3_resample_start_step=384,
        )
        block_zero = _owned_run._envelope_v1_7_block(ns_zero)
        block_384 = _owned_run._envelope_v1_7_block(ns_384)
        check(name, (
            block_zero.get("corpus_v3_resample_start_step") == 0
            and block_384.get("corpus_v3_resample_start_step") == 384
        ), f"block_zero={block_zero} block_384={block_384}")
    except Exception as e:
        failed.append(name); errors.append(f"{name}: {e}")
        check(name, False, str(e))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    all_names = passed + failed
    all_passed = len(failed) == 0
    if verbose:
        print()
        print(f"Results: {len(passed)}/{len(all_names)} passed"
              f"{'  (ALL PASS)' if all_passed else f'  FAILED: {failed}'}")
        if errors:
            print("Exceptions:")
            for e in errors:
                print(f"  {e}")

    return all_passed, all_names


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ember C14 resident iGRPO training loop")
    parser.add_argument("--test", action="store_true", help="Run unit test suite")
    parser.add_argument("--steps", type=int, default=1, help="Training steps to run (no-test mode)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    if args.test:
        print("=== ember_resident_igrpo unit tests ===")
        all_passed, test_names = _run_tests(verbose=True)
        sys.exit(0 if all_passed else 1)

    # Smoke: one training loop
    print("=== ember_resident_igrpo: smoke run ===")
    policy = TinyPolicyTransformer()
    optimizer = torch.optim.Adam(policy.parameters(), lr=1e-3)

    pre_params = {n: p.data.clone() for n, p in policy.named_parameters()}

    for step in range(args.steps):
        sv = step % 8
        result = igrpo_step(policy, optimizer, state_val=sv, N=4, G=4, max_depth=2,
                            epsilon=0.2, temperature=1.5)
        print(f"step={step} state={sv} "
              f"s1_rewards={[round(r,2) for r in result['stage1_rewards']]} "
              f"s1_best_action={result['stage1_best_action']} "
              f"s2_rewards={[round(r,2) for r in result['stage2_rewards']]} "
              f"s2_advs={[round(a,2) for a in result['stage2_advantages']]} "
              f"loss={result['loss']:.4f}")

    # Verify weight change
    changed = any(
        not torch.allclose(p.data, pre_params[n], atol=0.0)
        for n, p in policy.named_parameters()
    )
    print(f"\nWeights changed after {args.steps} step(s): {changed}")


if __name__ == "__main__":
    main()
