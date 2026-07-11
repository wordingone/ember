#!/usr/bin/env python3
"""
#703 PPM apparatus, stage 1: bounded-lookahead token-event marginalization
+ the P2 blend-definition harness skeleton.

Implements, against the frozen prereg (issue #703 coordinator comment
4942030643, section 3 "Mechanism"):

  P_ppm_tok(t | F_{k-1}) := P_ppm(E_k(t) intersect F_{k-1}) / P_ppm(F_{k-1})

where E_k(t) = {byte continuations w : seg(doc-from-0 . w) has k-th token = t}
and F_{k-1} = E_1(t_1) n ... n E_{k-1}(t_{k-1}) is the realized boundary
history. Two INDEPENDENT computations of the cylinder mass P_ppm(event) are
provided and cross-checked to 1e-9 on every named P2 lattice
(exp703_lattices.py):

  1. `cylinder_mass_ground_truth` -- a deliberately dumb, unpruned recursive
     enumeration: at every context it tries EVERY alphabet symbol (including
     EOT) and recurses to the symbol's true EOT termination before
     classifying via seg(.). No vocab/trie structure is consulted. This is
     the "enumerate all strings" ground truth the mission specifies.

  2. `cylinder_mass_bounded_lookahead` -- the production-shaped algorithm:
     identical recursive structure, but once depth >= L_eff (the frozen
     prereg's effective-lookahead bound for the given tokenizer/vocab -- see
     LatticeCase.L_eff) it STOPS extending non-EOT branches and instead
     attributes the entire remaining subtree mass directly using the
     already-settled token-k classification, exploiting exactly the
     boundedness property P1 requires the tokenizer to satisfy (or REFUSE).
     This is a genuinely different, terminating-early code path -- not the
     same function called twice -- so equality with (1) is real evidence,
     not a tautology.

Both functions operate on the SAME model / seg_fn interface used by the real
PPM component (exp703_ppm_model.PpmModel implements next_byte_probs) and the
real tokenizer classes (exp703_lattices.GreedyLongestMatchTokenizer /
BpeMergeTokenizer implement segment()), so the toy lattices exercise actual
production code, not a parallel reimplementation.
"""

from __future__ import annotations


def _is_target_regular(boundary_tokens: tuple, k: int, candidate: tuple):
    target_prefix = tuple(boundary_tokens) + (candidate,)

    def is_target(tokens: list) -> bool:
        return len(tokens) >= k and tuple(tokens[:k]) == target_prefix

    return is_target


def _is_target_eot_event(boundary_tokens: tuple, k: int, eot_symbol: int):
    def is_target(tokens: list) -> bool:
        return (len(tokens) == k
                and tuple(tokens[:k - 1]) == tuple(boundary_tokens)
                and tokens[k - 1] == (eot_symbol,))

    return is_target


def make_is_target(boundary_tokens: tuple, k: int, candidate: tuple, eot_symbol: int):
    if candidate == (eot_symbol,):
        return _is_target_eot_event(boundary_tokens, k, eot_symbol)
    return _is_target_regular(boundary_tokens, k, candidate)


def _classification_locked(tokenizer, boundary_bytes: tuple, ext: tuple, alphabet_symbols: list,
                            eot_symbol: int, is_target, verify_depth: int):
    """Adaptive lock verification used ONLY by ground truth: is `is_target`
    guaranteed constant for every continuation of `ext` by 0..verify_depth
    more non-EOT symbols (each hypothetically followed by EOT)? This is a
    purely SYNTACTIC check (calls tokenizer.segment, never the probability
    model) -- it does not depend on EOT ever being reachable with positive
    probability, so it terminates even for fixtures like case (i) where
    P(EOT | context ending in a repeated symbol) is exactly 0 forever.
    Returns (True, classification) if locked, else (False, None)."""
    base_tokens = tokenizer.segment(boundary_bytes + ext + (eot_symbol,))
    base_cls = is_target(base_tokens)

    def rec(e: tuple) -> bool:
        if len(e) >= verify_depth:
            return True
        for sym in alphabet_symbols:
            e2 = e + (sym,)
            tokens = tokenizer.segment(boundary_bytes + ext + e2 + (eot_symbol,))
            if is_target(tokens) != base_cls:
                return False
            if not rec(e2):
                return False
        return True

    if rec(()):
        return True, base_cls
    return False, None


def cylinder_mass_ground_truth(model, tokenizer, boundary_bytes: tuple, boundary_tokens: tuple,
                                k: int, candidate: tuple, alphabet_symbols: list, eot_symbol: int,
                                max_depth: int = 200, prob_floor: float = 1e-15) -> float:
    """Exhaustive enumeration, independent of any production lookahead
    assumption: at every node, first handle the genuine-EOT-now branch
    exactly (real tokens, real probability), then for the remaining
    (non-EOT-here) mass, dispatch on `tokenizer.safe_lock_horizon()`:

    - If it returns an int H (a PROVEN, tokenizer-derived bound --
      GreedyLongestMatchTokenizer returns its own `max_len`, the longest
      vocab entry, since greedy matching commits within that many bytes and
      never revisits an earlier decision): check via `_classification_locked`
      -- a purely syntactic local brute force over EXACTLY H additional
      bytes, no more, no fewer -- whether the token-k classification is
      ALREADY fixed regardless of what happens next. If so, attribute the
      remaining mass directly (exact, by total-probability). This replaces
      a fixed `verify_depth` magic constant (issue #703 PR #759 coordinator
      gate blocker 1: a hardcoded default of 6 undershoots a 7-symbol vocab
      entry by exactly one byte and produces a premature false lock,
      PPM703_FINITE_LOCK_COUNTEREXAMPLE_PASS) with a per-fixture PROVEN
      bound -- H is a property of the tokenizer under test, never guessed.
    - If it returns None (no tokenizer-provided bound exists -- e.g.
      BpeMergeTokenizer, where a merge decision can depend on the WHOLE
      open chunk and there is no vocab-length-style constant to derive a
      bound from): apply NO lock shortcut at all. Recurse genuinely,
      following every alphabet symbol, until each branch reaches either a
      real emitted EOT (handled exactly, every step, via the `p_eot`
      branch above) or its CUMULATIVE probability (`prob_so_far * remaining`)
      drops below `prob_floor` -- a bounded NUMERICAL truncation (the
      omitted mass is smaller than `prob_floor`, far below the 1e-9
      tolerance every caller in this module checks against), never a
      CLASSIFICATION assumption: this branch makes no claim about what
      `is_target` would evaluate to, it only stops enumerating a subtree
      whose total contribution to `total` -- true or false -- is already
      numerically negligible. This is the module's own documented 'dumb,
      unpruned, recurse to true EOT' design goal, finally applied only to
      the tokenizer class that actually needs it
      (PPM703_OWN_BPE_FINITE_LOCK_COUNTEREXAMPLE_PASS).

    No vocab/trie structure is consulted anywhere in this function -- only
    the model's raw probabilities and the tokenizer's own segment() output
    (plus, for the horizon case, the tokenizer's own derived `max_len`)."""
    is_target = make_is_target(boundary_tokens, k, candidate, eot_symbol)
    total = 0.0
    horizon = getattr(tokenizer, "safe_lock_horizon", lambda: None)()

    def rec(ext: tuple, prob_so_far: float, context: tuple, depth: int):
        nonlocal total
        probs = model.next_byte_probs(context)
        p_eot = probs.get(eot_symbol, 0.0)
        if p_eot > 0.0:
            full = boundary_bytes + ext + (eot_symbol,)
            tokens = tokenizer.segment(full)
            if is_target(tokens):
                total += prob_so_far * p_eot
        remaining = 1.0 - p_eot
        if remaining <= 1e-15:
            return
        if horizon is not None:
            locked, cls = _classification_locked(tokenizer, boundary_bytes, ext, alphabet_symbols,
                                                  eot_symbol, is_target, horizon)
            if locked:
                if cls:
                    total += prob_so_far * remaining
                return
        elif prob_so_far * remaining <= prob_floor:
            # No proven horizon (e.g. BpeMergeTokenizer): bounded numerical
            # truncation only, NOT a classification assumption -- see
            # docstring. The omitted mass is < prob_floor.
            return
        if depth > max_depth:
            raise AssertionError(
                f"cylinder_mass_ground_truth: max_depth {max_depth} exceeded without "
                f"locking or negligible-probability termination (ext={ext}, "
                f"cumulative_prob={prob_so_far * remaining:.3e}, horizon={horizon}) -- "
                f"lattice fixture under-specified")
        for sym in alphabet_symbols:
            p_sym = probs.get(sym, 0.0)
            if p_sym <= 0.0:
                continue
            rec(ext + (sym,), prob_so_far * p_sym, context + (sym,), depth + 1)

    # Seed with P_ppm(F_{k-1}) itself, NOT 1.0: this function returns the
    # JOINT mass P_ppm(E_k(candidate) n F_{k-1}) -- the prereg's own
    # numerator (section 3) -- not a conditional. For an empty boundary
    # P_ppm(F_{k-1}) == 1 and the distinction is invisible; for a non-empty
    # boundary_bytes (lattice cases ii/iii) omitting this seed silently
    # computed a conditional instead of a joint, which then double-divided
    # inside p_ppm_tok(). See PR description for the receipt.
    boundary_mass = model.prefix_probability(boundary_bytes) if boundary_bytes else 1.0
    rec((), boundary_mass, boundary_bytes, 0)
    return total


def cylinder_mass_bounded_lookahead(model, tokenizer, boundary_bytes: tuple, boundary_tokens: tuple,
                                     k: int, candidate: tuple, alphabet_symbols: list, eot_symbol: int,
                                     L_eff: int, max_depth: int = 60) -> float:
    """Production-shaped algorithm: extends only up to L_eff non-EOT bytes
    past the boundary before treating the token-k classification as settled
    and attributing the remaining subtree mass directly (vocab-trie-frontier
    boundedness), instead of recursing all the way to a real EOT."""
    is_target = make_is_target(boundary_tokens, k, candidate, eot_symbol)
    total = 0.0

    def rec(ext: tuple, prob_so_far: float, context: tuple, depth: int):
        nonlocal total
        if depth > max_depth:
            raise AssertionError(
                f"cylinder_mass_bounded_lookahead: max_depth {max_depth} exceeded "
                f"(ext={ext})")
        probs = model.next_byte_probs(context)
        p_eot = probs.get(eot_symbol, 0.0)
        if p_eot > 0.0:
            full = boundary_bytes + ext + (eot_symbol,)
            tokens = tokenizer.segment(full)
            if is_target(tokens):
                total += prob_so_far * p_eot
        if depth >= L_eff:
            remaining = 1.0 - p_eot
            if remaining > 1e-15:
                # classification is settled by the L_eff boundedness property:
                # tokens[:k] from a hypothetical immediate EOT is identical to
                # tokens[:k] under any real continuation from here.
                hypothetical = tokenizer.segment(boundary_bytes + ext + (eot_symbol,))
                if is_target(hypothetical):
                    total += prob_so_far * remaining
            return
        for sym in alphabet_symbols:
            p_sym = probs.get(sym, 0.0)
            if p_sym <= 0.0:
                continue
            rec(ext + (sym,), prob_so_far * p_sym, context + (sym,), depth + 1)

    # See cylinder_mass_ground_truth: this returns the JOINT mass, seeded
    # with P_ppm(F_{k-1}).
    boundary_mass = model.prefix_probability(boundary_bytes) if boundary_bytes else 1.0
    rec((), boundary_mass, boundary_bytes, 0)
    return total


def p_ppm_tok(model, tokenizer, boundary_bytes: tuple, boundary_tokens: tuple, k: int,
              candidate: tuple, alphabet_symbols: list, eot_symbol: int, L_eff: int,
              boundary_mass: float | None = None) -> float:
    """P2 blend-definition harness: THE definition from section 3 of the
    frozen prereg, implemented definition-first --

        P_ppm_tok(t | F_{k-1}) := P_ppm(E_k(t) n F_{k-1}) / P_ppm(F_{k-1})

    computed via the bounded-lookahead (production-shaped) cylinder-mass
    engine. This is the function the eventual blend surface
    (P_blend = lambda * P_ppm_tok + (1-lambda) * P_neural) will call; this
    PR proves its correctness against ground truth, it does not wire the
    neural side (out of scope: no eval pass, no claim, stage 1 only).

    `boundary_mass`, if given, is used as P_ppm(F_{k-1}) directly instead of
    recomputing it from `boundary_bytes` via a naive byte-prefix chain-rule
    product. This distinction is NOT cosmetic: for a tokenizer where a
    realized token does not "self-lock" from its own bytes alone (e.g. the
    BPE lattice's bare token (X,), which is also a strict prefix of the
    document-continuing branch that resolves to token1=(X,Y) later --
    P_ppm("starts with byte X") = 0.6 but P_ppm(F_1 = "token1 is exactly
    X") = 0.516), naive_prefix_probability(boundary_bytes) computes
    P_ppm(superset) rather than P_ppm(F_{k-1}) and silently returns a wrong
    conditional. A caller walking a document token-by-token has the correct
    value on hand for free: by the telescoping identity itself,
    P_ppm(F_{k-1}) == the running product of the prior k-1 P_ppm_tok
    factors (each of those factors' NUMERATOR is independently correct
    regardless of this issue -- is_target always checks the full
    tokens[:k] prefix, not just byte containment -- only the denominator
    needs this correction). See exp703_selftest.py's _telescope_product for
    the caller-side usage; this bug and its fix are receipted in the PR
    description."""
    numerator = cylinder_mass_bounded_lookahead(
        model, tokenizer, boundary_bytes, boundary_tokens, k, candidate,
        alphabet_symbols, eot_symbol, L_eff)
    if boundary_mass is None:
        boundary_mass = model.prefix_probability(boundary_bytes) if boundary_bytes else 1.0
    if boundary_mass <= 0.0:
        raise ZeroDivisionError("P_ppm(F_{k-1}) == 0 -- boundary history has zero PPM mass")
    return numerator / boundary_mass


def naive_renormalized_scores(model, boundary_bytes: tuple, candidates: list) -> dict:
    """BLOCK_NAIVE_BYTE_STRING_RENORMALIZATION: the banned construction --
    score each candidate token by the raw chain-rule prefix probability of
    boundary_bytes + bytes(candidate) (ignoring the tokenizer event
    partition entirely: no exclusion of longer/competing vocab entries), then
    renormalize the scores to sum to 1. Summing to 1 is NOT correctness --
    this appears in the correctness harness ONLY as the negative control."""
    raw = {}
    for cand in candidates:
        raw[cand] = model.prefix_probability(boundary_bytes + cand)
    total = sum(raw.values())
    if total <= 0.0:
        raise ZeroDivisionError("naive_renormalized_scores: raw scores sum to 0")
    return {c: v / total for c, v in raw.items()}


def l1_error(dist_a: dict, dist_b: dict) -> float:
    keys = set(dist_a) | set(dist_b)
    return sum(abs(dist_a.get(k, 0.0) - dist_b.get(k, 0.0)) for k in keys)
