#!/usr/bin/env python3
"""
#703 PPM apparatus, stage 1 -- selftest entry point.

Runs, and prints one marker line per leg (raw output is the receipt --
nothing here is claim-bearing; this is apparatus correctness only, no eval
pass, no slice measurement, no Claim A/B number):

  PPM703_P1_EXHAUSTIVE_EQUALITY_PASS
      ground-truth (dumb, unpruned, recurse-to-true-EOT) cylinder masses vs
      bounded-lookahead (trie/L_eff-bounded) cylinder masses agree to 1e-9
      on every candidate of every P2 lattice (i)-(v), AND each lattice's
      Sigma_t P_ppm_tok(t|F) = 1 to 1e-9 under BOTH computations, AND the
      telescoping identity (token-sequence product == independently
      enumerated byte measure of the full document) holds to 1e-9.

  PPM703_P1_NAIVE_RENORM_NEGATIVE_CONTROL_PASS
      BLOCK_NAIVE_BYTE_STRING_RENORMALIZATION reproduces the frozen fixture's
      L1 error (0.589655) on the coordinator's own vocab{a,ab,b} fixture.

  PPM703_P2_BLEND_DEFINITION_PASS
      P_ppm_tok(t|F) := P_ppm(E_k(t) n F_{k-1}) / P_ppm(F_{k-1}), implemented
      definition-first (exp703_marginalization.p_ppm_tok), matches ground
      truth on every lattice to 1e-9.

  PPM703_STATE_CAP_ASSERT_PASS
      PpmModel refuses (raises PpmStateCapExceeded) once estimated resident
      state exceeds a configured cap.

Usage: python scripts/exp703_selftest.py
"""

from __future__ import annotations

import sys

from exp703_ppm_model import PpmModel, PpmStateCapExceeded
from exp703_lattices import ALL_CASES, case_i_prefix_antichain
from exp703_marginalization import (
    cylinder_mass_ground_truth,
    cylinder_mass_bounded_lookahead,
    p_ppm_tok,
    naive_renormalized_scores,
    l1_error,
)

EQ_TOL = 1e-9
HAND_TOL = 1e-6


def _fmt(x: float) -> str:
    return f"{x:.12f}"


def run_p1_exhaustive_equality() -> bool:
    ok = True
    details = []
    for case_fn in ALL_CASES:
        case = case_fn()
        # Sigma-check candidate set: every named candidate plus the explicit
        # EOT-event candidate (the token alphabet always includes EOT).
        eot_cand = (case.eot_symbol,)
        sigma_candidates = list(case.candidates)
        if eot_cand not in sigma_candidates:
            sigma_candidates = sigma_candidates + [eot_cand]

        gt_masses = {}
        bl_masses = {}
        for cand in sigma_candidates:
            gt = cylinder_mass_ground_truth(
                case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
                case.k, cand, case.alphabet_symbols, case.eot_symbol)
            bl = cylinder_mass_bounded_lookahead(
                case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
                case.k, cand, case.alphabet_symbols, case.eot_symbol, case.L_eff)
            gt_masses[cand] = gt
            bl_masses[cand] = bl
            diff = abs(gt - bl)
            passed = diff < EQ_TOL
            ok = ok and passed
            details.append(
                f"  [{case.name}] candidate={cand} ground_truth={_fmt(gt)} "
                f"bounded_lookahead={_fmt(bl)} diff={diff:.3e} "
                f"{'PASS' if passed else 'FAIL'}")
            if case.expected is not None and cand in case.expected:
                exp = case.expected[cand]
                hand_diff = abs(gt - exp)
                hand_passed = hand_diff < HAND_TOL
                ok = ok and hand_passed
                details.append(
                    f"    hand-derived expected={_fmt(exp)} diff={hand_diff:.3e} "
                    f"{'PASS' if hand_passed else 'FAIL'}")

        # Sigma_t P_ppm_tok(t|F) = 1 (frozen prereg section 3, consequence
        # (c)): the CONDITIONAL masses must sum to 1, not the raw joint
        # masses (which sum to P_ppm(F_{k-1}), equal to 1 only for an empty
        # boundary). Divide each joint mass by the boundary's own prior mass
        # before summing.
        boundary_mass = (case.model.prefix_probability(case.boundary_bytes)
                          if case.boundary_bytes else 1.0)
        sigma_gt = sum(gt_masses.values()) / boundary_mass
        sigma_bl = sum(bl_masses.values()) / boundary_mass
        sigma_gt_ok = abs(sigma_gt - 1.0) < EQ_TOL
        sigma_bl_ok = abs(sigma_bl - 1.0) < EQ_TOL
        ok = ok and sigma_gt_ok and sigma_bl_ok
        details.append(
            f"  [{case.name}] boundary_mass={_fmt(boundary_mass)} "
            f"Sigma_t(conditional) ground_truth={_fmt(sigma_gt)} "
            f"({'PASS' if sigma_gt_ok else 'FAIL'}) "
            f"Sigma_t(conditional) bounded_lookahead={_fmt(sigma_bl)} "
            f"({'PASS' if sigma_bl_ok else 'FAIL'})")

        # Telescoping check: pick the highest-mass reachable full document
        # under ground truth's own construction and verify the token-product
        # equals the direct chain-rule byte probability of that exact
        # document. We build one by walking the greedy/BPE argmax path from
        # the boundary to a real EOT.
        full_bytes, full_tokens = _walk_argmax_document(case)
        telescoped = _telescope_product(case, full_tokens)
        direct = case.model.prefix_probability(full_bytes)
        tel_diff = abs(telescoped - direct)
        tel_ok = tel_diff < EQ_TOL
        ok = ok and tel_ok
        details.append(
            f"  [{case.name}] telescoping: product={_fmt(telescoped)} "
            f"direct_prefix_prob={_fmt(direct)} diff={tel_diff:.3e} "
            f"{'PASS' if tel_ok else 'FAIL'} (doc_tokens={full_tokens})")

    print("\n".join(details))
    print(f"PPM703_P1_EXHAUSTIVE_EQUALITY_PASS={ok}")
    return ok


def _walk_argmax_document(case):
    """Deterministically construct one complete (EOT-terminated) document
    from a FRESH (empty) context by always choosing the argmax-probability
    next symbol (ties broken deterministically toward EOT first, so the
    walk terminates promptly), for use as the telescoping-check example.
    Telescoping validates a whole-document identity (product of per-token
    P_ppm_tok factors, j=1..m, == direct byte probability of the full
    document from position 0) -- it is deliberately independent of
    case.boundary_bytes/boundary_tokens, which instead fix a SPECIFIC
    mid-document boundary used only by the P1 cylinder-mass equality check
    for cases (ii)/(iii). Returns (full_bytes, tokens)."""
    context: tuple = ()
    ext: tuple = ()
    for _ in range(40):
        probs = case.model.next_byte_probs(context)
        candidates = [(s, p) for s, p in probs.items() if p > 0]
        if not candidates:
            break
        # tie-break toward EOT so the walk terminates as soon as EOT is
        # among the argmax-probability options, rather than looping forever
        # on a symbol that ties with EOT under a uniform default.
        best_p = max(p for _, p in candidates)
        tied = [s for s, p in candidates if p == best_p]
        sym = case.eot_symbol if case.eot_symbol in tied else tied[0]
        ext = ext + (sym,)
        if sym == case.eot_symbol:
            break
        context = context + (sym,)
    full_bytes = ext
    if not full_bytes or full_bytes[-1] != case.eot_symbol:
        full_bytes = full_bytes + (case.eot_symbol,)
    tokens = case.tokenizer.segment(full_bytes)
    return full_bytes, tokens


def _telescope_product(case, full_tokens: list) -> float:
    """Product of P_ppm_tok(t_j | F_{j-1}) for j=1..m over the full realized
    token sequence, each factor computed via the bounded-lookahead engine --
    this is the frozen prereg's telescoping consequence (c), verified
    independently against the direct chain-rule byte probability of the same
    document in run_p1_exhaustive_equality."""
    product = 1.0
    boundary_tokens: tuple = ()
    boundary_bytes: tuple = ()
    for j, tok in enumerate(full_tokens, start=1):
        # boundary_mass=product: P_ppm(F_{j-1}) is, by the telescoping
        # identity itself, exactly the running product of the prior j-1
        # factors -- NOT the naive byte-prefix probability of
        # boundary_bytes (see p_ppm_tok's docstring: those differ whenever
        # a realized token does not self-lock from its own bytes alone,
        # which the BPE lattice exercises).
        factor = p_ppm_tok(case.model, case.tokenizer, boundary_bytes, boundary_tokens, j,
                            tok, case.alphabet_symbols, case.eot_symbol, case.L_eff,
                            boundary_mass=product)
        product *= factor
        boundary_tokens = boundary_tokens + (tok,)
        if tok != (case.eot_symbol,):
            boundary_bytes = boundary_bytes + tok
    return product


def run_p1_naive_renorm_negative_control() -> bool:
    case = case_i_prefix_antichain()
    naive = naive_renormalized_scores(case.model, case.boundary_bytes, case.candidates)
    naive_sum = sum(naive.values())
    correct = {}
    for cand in case.candidates:
        correct[cand] = cylinder_mass_ground_truth(
            case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
            case.k, cand, case.alphabet_symbols, case.eot_symbol)
    l1 = l1_error(naive, correct)
    naive_sums_to_one = abs(naive_sum - 1.0) < 1e-9
    l1_matches_known = abs(l1 - 0.589655) < 1e-6
    ok = naive_sums_to_one and l1_matches_known
    print(f"  naive scores: { {k: _fmt(v) for k, v in naive.items()} }")
    print(f"  naive sum-to-1: {_fmt(naive_sum)} ({'PASS' if naive_sums_to_one else 'FAIL'} "
          f"-- summing to 1 is NOT correctness, see below)")
    print(f"  correct (event-partition) scores: { {k: _fmt(v) for k, v in correct.items()} }")
    print(f"  L1 error = {_fmt(l1)} (known frozen value 0.589655) "
          f"{'PASS' if l1_matches_known else 'FAIL'}")
    print(f"PPM703_P1_NAIVE_RENORM_NEGATIVE_CONTROL_PASS={ok}")
    return ok


def run_p2_blend_definition() -> bool:
    ok = True
    details = []
    for case_fn in ALL_CASES:
        case = case_fn()
        for cand in case.candidates:
            blend_val = p_ppm_tok(case.model, case.tokenizer, case.boundary_bytes,
                                   case.boundary_tokens, case.k, cand,
                                   case.alphabet_symbols, case.eot_symbol, case.L_eff)
            gt = cylinder_mass_ground_truth(
                case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
                case.k, cand, case.alphabet_symbols, case.eot_symbol)
            denom = case.model.prefix_probability(case.boundary_bytes) if case.boundary_bytes else 1.0
            gt_conditional = gt / denom if denom > 0 else float("nan")
            diff = abs(blend_val - gt_conditional)
            passed = diff < EQ_TOL
            ok = ok and passed
            details.append(
                f"  [{case.name}] candidate={cand} p_ppm_tok={_fmt(blend_val)} "
                f"ground_truth_conditional={_fmt(gt_conditional)} diff={diff:.3e} "
                f"{'PASS' if passed else 'FAIL'}")
    print("\n".join(details))
    print(f"PPM703_P2_BLEND_DEFINITION_PASS={ok}")
    return ok


def run_state_cap_assert() -> bool:
    # Deliberately tiny cap so training a modest toy corpus overflows it
    # deterministically. order_cap kept small (3) to make node/entry growth
    # fast relative to the tiny cap.
    tiny_cap_bytes = 2000
    model = PpmModel(alphabet_size=257, order_cap=3, state_cap_bytes=tiny_cap_bytes)
    raised = False
    n_trained = 0
    try:
        # deterministic pseudo-random-looking byte stream (LCG) covering a
        # wide symbol range to force many distinct trie nodes quickly.
        state = 12345
        for i in range(200000):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            b = state % 256  # never emits EOT (256), stays mid-document
            model.train_symbol_stream_byte(b)
            n_trained += 1
    except PpmStateCapExceeded as e:
        raised = True
        print(f"  PpmStateCapExceeded raised after {n_trained} symbols: {e}")
    ok = raised
    print(f"  cap_bytes={tiny_cap_bytes} approx_state_bytes_at_raise="
          f"{model.approx_state_bytes()}")
    print(f"PPM703_STATE_CAP_ASSERT_PASS={ok}")
    return ok


def main() -> int:
    results = []
    print("=== PPM703 P1 exhaustive equality (ground truth vs bounded lookahead) ===")
    results.append(run_p1_exhaustive_equality())
    print()
    print("=== PPM703 P1 naive-renorm negative control ===")
    results.append(run_p1_naive_renorm_negative_control())
    print()
    print("=== PPM703 P2 blend definition (P_ppm_tok) vs ground truth ===")
    results.append(run_p2_blend_definition())
    print()
    print("=== PPM703 state cap hard assert ===")
    results.append(run_state_cap_assert())
    print()
    all_ok = all(results)
    print(f"PPM703_SELFTEST_ALL_PASS={all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
