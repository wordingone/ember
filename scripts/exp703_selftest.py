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
      enumerated byte measure of the full document) holds to 1e-9, AND the
      ground-truth oracle's own EXPOSED `truncated_mass_bound` (see
      PPM703_FLOOR_BITES_BOUND_EXPOSURE_PASS below) is asserted < 1e-9
      explicitly on every candidate -- not merely trusted never to bite.

  PPM703_P1_NAIVE_RENORM_NEGATIVE_CONTROL_PASS
      BLOCK_NAIVE_BYTE_STRING_RENORMALIZATION reproduces the frozen fixture's
      L1 error (0.589655) on the coordinator's own vocab{a,ab,b} fixture.

  PPM703_FINITE_LOCK_COUNTEREXAMPLE_PASS
  PPM703_OWN_BPE_FINITE_LOCK_COUNTEREXAMPLE_PASS
      Mandatory-negative regression fixtures (issue #703 PR #759 coordinator
      gate blocker 1): the OLD `_classification_locked(verify_depth=6)`
      oracle falsely locked classification without examining byte 7+,
      reporting 0.0 (premature false lock) on both fixtures instead of the
      analytic 0.5**7 == 0.0078125 -- receipted OLD-code failure in
      scratchpad/repro_blocker1_negative.py. The CURRENT
      `safe_lock_horizon()`-dispatched oracle (exp703_lattices.py +
      exp703_marginalization.cylinder_mass_ground_truth) must report the
      exact analytic value on both, permanently.

  PPM703_FLOOR_BITES_BOUND_EXPOSURE_PASS
      Gate note follow-up on the blocker-1 cure: `cylinder_mass_ground_truth`
      now returns a `CylinderMassResult(value, truncated_mass_bound)` -- the
      horizon=None numerical-floor shortcut (`prob_floor`) EXPOSES an exact
      upper bound on the error it could introduce, rather than an implicit
      "trust the floor never bites" assumption ("an oracle whose error bound
      is implicit is one config change away from silently lying"). This leg
      constructs a fixture (memoryless {A,EOT} model + an EMPTY-merges
      BpeMergeTokenizer, no natural termination, no lock shortcut) where the
      floor GENUINELY fires around depth ~49, and asserts the reported bound
      is both nonzero (the mechanism actually engaged) and still < 1e-9 (the
      floor is tight enough not to matter) while `value` remains accurate to
      the analytic 0.5.

  PPM703_GLOBAL_MASS_100_BRANCH_COUNTEREXAMPLE_PASS
  PPM703_BOUND_REFUSAL_MECHANISM_PASS
      External re-audit block (PR comment 4943538820, executed against the
      PRE-exposure head 299b3c2 -- moot against this PR's own exposure
      commit 08d3dc9, since `truncated_mass_bound` is already a `nonlocal`
      accumulator shared by every branch of the recursion, not reset per
      pruned node; verified here as a PERMANENT fixture rather than trusted
      by inspection): a 100-disjoint-root-branch / prob_floor=0.01 fixture
      (every branch pruned before any EOT, each contributing exactly 0.01)
      must report `truncated_mass_bound~=1.0` (the SUM across all 100
      pruned subtrees), not a single node's local 0.01, with `value=0.0`
      honestly unresolved and the true analytic (0.01) bracketed by
      [value, value+bound]. `require_bound_within_tolerance` -- a new
      structural enforcement primitive, `CylinderMassBoundExceeded` raised
      whenever `truncated_mass_bound` exceeds a caller's declared tolerance
      -- must REFUSE on this result at EQ_TOL, and a decoupled
      non-recursive unit fixture proves the raise/pass-through boundary
      sits exactly at `bound > tolerance` in both directions. This
      primitive is now wired into every `cylinder_mass_ground_truth` call
      site across P0/P1/P2 (issue #703 PR #759 external re-audit: "require
      truncated_mass_upper <= caller_tolerance before equality can pass").

  PPM703_P2_BLEND_DEFINITION_PASS
      P_ppm_tok(t|F) := P_ppm(E_k(t) n F_{k-1}) / P_ppm(F_{k-1}), implemented
      definition-first (exp703_marginalization.p_ppm_tok), matches ground
      truth on every lattice to 1e-9.

  PPM703_STATE_CAP_ASSERT_PASS
      PpmModel refuses (raises PpmStateCapExceeded) once estimated resident
      state exceeds a configured cap. Includes two external-re-audit
      mandatory-negative legs (PR comment 4943548456, executed against head
      299b3c2):

        PPM703_FOREIGN_ALLOCATION_ISOLATION_PASS -- the OLD `live_state_bytes`
        returned `tracemalloc.get_traced_memory()[0]`, the PROCESS-WIDE
        traced total, mislabeled as PPM state; an unrelated 2MB bytearray
        allocated before model construction inflated it by >99% of its
        value and triggered a false-positive refusal at symbol 52 while
        true PPM state was 5,840 bytes. The cure splits this into
        `isolated_ppm_state_bytes()` (a tracemalloc snapshot filtered to
        THIS FILE's own allocation sites, diffed against a per-instance
        baseline -- the authoritative figure `state_cap_bytes` is enforced
        against for PPM-state claims) and `process_live_bytes_governor()`
        (the same process-wide reading, honestly renamed and documented as
        a conservative SECOND safety rail, never itself a PPM-state claim).

        PPM703_STABLE_CONTEXT_PERIODIC_CHECK_PASS -- `LIVE_CHECK_INTERVAL`
        is documented as "every N training calls" but the OLD counter only
        incremented inside the growth-triggered `_check_cap()`, so a
        stable-context stream (same symbol repeated, no new node/entry
        after the first call) reached it exactly once regardless of call
        count -- receipted: 500 training calls, counter stuck at 2,
        LIVE_CHECK_INTERVAL=100 never reached. The cure moves the counter
        to a new `_check_cap_periodic()`, called unconditionally at the
        tail of every `train_symbol` call.

  PPM703_UTF8_FOUR_BYTE_BOUNDARY_COUNTEREXAMPLE_PASS
  PPM703_UTF8_DFA_RFC3629_MANDATORY_FIXTURES_PASS
      Mandatory-negative regression fixture (issue #703 PR #759 coordinator
      gate blocker 3, UTF-8 repair defect): the OLD `restricted_next_byte_
      probs` derived UTF-8 restriction state from a raw `context[-3:]`
      suffix decoded standalone, misreading a completed 4-byte codepoint's
      tail as a dead mid-sequence state (ZeroDivisionError) -- receipted OLD-
      code failure in scratchpad/verify_dfa_fixtures.py. The CURE carries an
      EXPLICIT UTF-8 DFA state (exp703_domain_d.utf8_dfa_state_from_history)
      simulated over the full context, never a raw-suffix guess; RFC 3629
      correctness (overlong encodings, UTF-16 surrogate range, > U+10FFFF)
      is verified by exhaustive cross-check against CPython's own strict
      UTF-8 codec, plus mandatory positive (completed 1/2/3/4-byte
      codepoints permit ASCII+EOT) and negative (partial-lead states permit
      only correct continuations and forbid EOT; the rejection set carries
      zero mass; DFA state survives PPM order-cap truncation) fixtures.

  PPM703_P0_DOMAIN_INCIDENCE_PASS branch=b
      AMENDMENT-1 + AMENDMENT-1a (issue #703): domain-D (valid-UTF-8,
      no-NUL) restriction machinery is correct (renormalized support sums
      to 1, NUL/invalid-UTF-8 continuations always excluded, EOT only at a
      UTF-8 boundary), the P0 census function is correct on a synthetic
      positive-control corpus, and the branch-b disposition (original
      pre-tokenization-byte incidence is UNMEASURABLE in this checkout) is
      cited LIVE against the two disposition receipts on disk.

Usage: python scripts/exp703_selftest.py
"""

from __future__ import annotations

import os
import random
import sys

from exp703_ppm_model import PpmModel, PpmStateCapExceeded
from exp703_lattices import (
    ALL_CASES,
    case_i_prefix_antichain,
    GreedyLongestMatchTokenizer,
    BpeMergeTokenizer,
    FixedFixtureModel,
)
from exp703_marginalization import (
    cylinder_mass_ground_truth,
    cylinder_mass_bounded_lookahead,
    p_ppm_tok,
    naive_renormalized_scores,
    l1_error,
    require_bound_within_tolerance,
    CylinderMassBoundExceeded,
    CylinderMassResult,
)
from exp703_domain_d import (
    RestrictedPpmModel,
    document_domain_census,
    p0_branch_b_citation,
    at_utf8_boundary,
    is_valid_utf8_prefix,
    utf8_dfa_state_from_history,
    allowed_next_bytes_from_state,
    UTF8_READY,
    _lead_transition,
    utf8_dfa_step,
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
            # require_bound_within_tolerance is a STRUCTURAL enforcement,
            # not a printed convention: it RAISES CylinderMassBoundExceeded
            # immediately if the oracle's own truncated_mass_bound exceeds
            # EQ_TOL, crashing this run loud rather than silently folding a
            # bound breach into a printed FAIL a caller could ignore (issue
            # #703 PR #759 external re-audit, PR comment 4943538820: "require
            # truncated_mass_upper <= caller_tolerance before equality can
            # pass"). gt_bound is 0.0 whenever every branch resolved via a
            # real EOT or a proven classification-lock; it is nonzero only
            # on the horizon=None numerical-floor path (see
            # run_p1_finite_lock_counterexamples' floor-bites fixture and
            # run_p1_global_mass_and_refusal's 100-branch counterexample for
            # cases where it is deliberately exercised).
            gt_result = require_bound_within_tolerance(
                cylinder_mass_ground_truth(
                    case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
                    case.k, cand, case.alphabet_symbols, case.eot_symbol),
                EQ_TOL, label=f"{case.name} candidate={cand}")
            gt, gt_bound = gt_result.value, gt_result.truncated_mass_bound
            bl = cylinder_mass_bounded_lookahead(
                case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
                case.k, cand, case.alphabet_symbols, case.eot_symbol, case.L_eff)
            gt_masses[cand] = gt
            bl_masses[cand] = bl
            diff = abs(gt - bl)
            # By this point require_bound_within_tolerance already refused
            # to return a result with gt_bound >= EQ_TOL -- bound_ok is
            # always True here; it is asserted anyway (never trusted to be
            # a tautology) and printed so a reader sees the actual measured
            # value, not just the fact that no exception fired.
            bound_ok = gt_bound < EQ_TOL
            assert bound_ok, "unreachable: require_bound_within_tolerance should have raised"
            passed = diff < EQ_TOL and bound_ok
            ok = ok and passed
            details.append(
                f"  [{case.name}] candidate={cand} ground_truth={_fmt(gt)} "
                f"bounded_lookahead={_fmt(bl)} diff={diff:.3e} "
                f"truncated_mass_bound={gt_bound:.3e} "
                f"({'PASS' if bound_ok else 'FAIL'} < {EQ_TOL:.0e}) "
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
    correct_bound_total = 0.0
    for cand in case.candidates:
        gt_result = require_bound_within_tolerance(
            cylinder_mass_ground_truth(
                case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
                case.k, cand, case.alphabet_symbols, case.eot_symbol),
            EQ_TOL, label=f"naive-renorm-negative-control candidate={cand}")
        correct[cand] = gt_result.value
        correct_bound_total += gt_result.truncated_mass_bound
    l1 = l1_error(naive, correct)
    naive_sums_to_one = abs(naive_sum - 1.0) < 1e-9
    l1_matches_known = abs(l1 - 0.589655) < 1e-6
    bound_ok = correct_bound_total < EQ_TOL
    ok = naive_sums_to_one and l1_matches_known and bound_ok
    print(f"  naive scores: { {k: _fmt(v) for k, v in naive.items()} }")
    print(f"  naive sum-to-1: {_fmt(naive_sum)} ({'PASS' if naive_sums_to_one else 'FAIL'} "
          f"-- summing to 1 is NOT correctness, see below)")
    print(f"  correct (event-partition) scores: { {k: _fmt(v) for k, v in correct.items()} }")
    print(f"  L1 error = {_fmt(l1)} (known frozen value 0.589655) "
          f"{'PASS' if l1_matches_known else 'FAIL'}")
    print(f"  ground_truth truncated_mass_bound total={correct_bound_total:.3e} "
          f"({'PASS' if bound_ok else 'FAIL'} < {EQ_TOL:.0e})")
    print(f"PPM703_P1_NAIVE_RENORM_NEGATIVE_CONTROL_PASS={ok}")
    return ok


def run_p1_finite_lock_counterexamples() -> bool:
    """Mandatory-negative regression fixtures for issue #703 PR #759
    coordinator gate blocker 1 (external falsifier, executed at head
    bea12ed): `_classification_locked(verify_depth=6)` was a depth-bounded
    check that FALSELY claimed classification lock without examining byte
    7+, giving `cylinder_mass_ground_truth` == 0.0 (premature false lock)
    on both fixtures below instead of the analytic 0.5**7 == 0.0078125.

    Receipt (scratchpad/repro_blocker1_negative.py, run against the OLD
    `verify_depth=6` signature BEFORE the safe_lock_horizon() cure landed):
      [counterexample 1] cylinder_mass_ground_truth(verify_depth=6) = 0.0
      [counterexample 2] cylinder_mass_ground_truth(verify_depth=6) = 0.0
    Both OLD-code runs demonstrably FAILED (0.0 vs analytic 0.0078125) while
    `cylinder_mass_bounded_lookahead(L_eff=7)` already reported the exact
    value -- proving PPM703_P1_EXHAUSTIVE_EQUALITY_PASS was, before the cure,
    agreement of two computations rather than an independent proof.

    These fixtures are now PERMANENT: this function asserts the CURRENT
    (safe_lock_horizon()-dispatched) oracle reports the exact analytic value
    on both, going forward -- a regression back to any fixed-depth
    verify_depth-style shortcut will re-fail this leg.

    Counterexample 3 (added per a follow-up coordinator gate note on this
    same cure) is a MANDATORY fixture where the numerical-floor truncation
    (the horizon=None `prob_floor` shortcut) genuinely fires, so that
    `truncated_mass_bound`'s exposure mechanism is exercised, not merely
    present in code: a memoryless {A, EOT} model paired with an
    EMPTY-merges `BpeMergeTokenizer` (safe_lock_horizon()=None, always) has
    no natural termination at any finite depth (`p_eot` is always exactly
    0.5, never 0 or 1) and no classification-lock shortcut either, so the
    recursion is bounded ONLY by `prob_floor`.

    Counterexample 2 ALSO hits the floor, for a reason its own author
    (this fixture) initially mischaracterized -- see the inline comment
    at its assertion for the root-caused explanation (`FixedFixtureModel`
    resolves context by longest-SUFFIX match, not full-context match: once
    past the 7-symbol candidate, no suffix of the growing context matches
    a `rows` key except the trailing shorter cascades and eventually the
    empty suffix, which is always live at p_eot=0.5 -- the `default`
    row's p_eot=1.0 is never actually reached, and the recursion cycles
    through a vanishing infinite tail exactly like counterexample 3,
    just at a scale (first floor hit at depth 49) that a bound-exposure
    reader will not confuse for a real error source).

    NOTE on alphabet_symbols: per this module's own convention (see every
    ALL_CASES lattice fixture, e.g. line ~429's explicit comment), the
    `alphabet_symbols` argument passed to cylinder_mass_ground_truth/
    cylinder_mass_bounded_lookahead EXCLUDES eot_symbol -- EOT is handled
    exclusively via the dedicated p_eot branch inside the recursion, never
    as an item the "extend one more byte" loop also recurses into. Including
    EOT in alphabet_symbols for a tokenizer whose safe_lock_horizon() is
    None (counterexample 2's BpeMergeTokenizer) drives the genuine-recursion
    branch into segmenting a byte stream containing EOT mid-sequence, which
    is undefined behavior for BpeMergeTokenizer.segment() -- an artifact of
    a malformed caller, not a defect in the oracle.
    """
    ok = True
    ANALYTIC = 0.5 ** 7  # = 0.0078125

    # -- counterexample 1: delayed-decision GreedyLongestMatchTokenizer -----
    # alphabet {A=0, EOT=1}, memoryless P(A)=P(EOT)=0.5 at every context.
    # vocab = one 7-symbol entry (A,)*7 (greedy longest match, single-byte
    # fallback otherwise). A greedy decision at position 0 needs exactly 7
    # bytes of lookahead to know whether the full entry matched -- one MORE
    # than the OLD hardcoded verify_depth=6 default examined.
    A, EOT_A = 0, 1
    model1 = FixedFixtureModel(alphabet_size=2, table={}, default={A: 0.5, EOT_A: 0.5})
    tok1 = GreedyLongestMatchTokenizer([(A,) * 7], eot_symbol=EOT_A)
    alphabet_symbols1 = [A]  # EOT excluded, per module convention (see docstring)
    candidate1 = (A,) * 7
    gt1_result = cylinder_mass_ground_truth(model1, tok1, (), (), 1, candidate1,
                                             alphabet_symbols1, EOT_A, max_depth=40)
    gt1, gt1_bound = gt1_result.value, gt1_result.truncated_mass_bound
    bl1 = cylinder_mass_bounded_lookahead(model1, tok1, (), (), 1, candidate1,
                                           alphabet_symbols1, EOT_A, L_eff=7, max_depth=40)
    # horizon=7 (not None) for this tokenizer -> every branch resolves via
    # the exact classification-lock path, so the bound must be EXACTLY 0.0.
    cx1_ok = (abs(gt1 - ANALYTIC) < EQ_TOL and abs(bl1 - ANALYTIC) < EQ_TOL
              and gt1_bound == 0.0)
    ok = ok and cx1_ok
    print(f"  [finite-lock cx1] tokenizer.safe_lock_horizon()={tok1.safe_lock_horizon()} "
          f"ground_truth={_fmt(gt1)} bounded_lookahead={_fmt(bl1)} "
          f"analytic={_fmt(ANALYTIC)} truncated_mass_bound={gt1_bound:.3e} "
          f"{'PASS' if cx1_ok else 'FAIL'}")
    print(f"PPM703_FINITE_LOCK_COUNTEREXAMPLE_PASS={cx1_ok}")

    # -- counterexample 2: this PR's own BpeMergeTokenizer -------------------
    # 7 base symbols S0..S6, 6 priority merges cascading S0,S1 -> S0,S1,S2
    # -> ... -> the full 7-symbol candidate token. At each prefix-context,
    # p(next cascade symbol)=0.5, p(EOT)=0.5 (mirrors counterexample 1's
    # structure exactly). BpeMergeTokenizer has NO sound static lookahead
    # bound (a merge decision can depend on the whole open chunk), so
    # safe_lock_horizon() returns None and the oracle must fall back to
    # genuine (numerically-truncated, not classification-assumption-
    # truncated) recursion to reach the correct value.
    S0, S1, S2, S3, S4, S5, S6, EOT_B = 0, 1, 2, 3, 4, 5, 6, 7
    merges = [
        ((S0,), (S1,)), ((S0, S1), (S2,)), ((S0, S1, S2), (S3,)),
        ((S0, S1, S2, S3), (S4,)), ((S0, S1, S2, S3, S4), (S5,)),
        ((S0, S1, S2, S3, S4, S5), (S6,)),
    ]
    seq = [S0, S1, S2, S3, S4, S5, S6]
    rows = {(): {S0: 0.5, S1: 0.0, S2: 0.0, S3: 0.0, S4: 0.0, S5: 0.0, S6: 0.0, EOT_B: 0.5}}
    for i in range(1, 7):
        row = {s: 0.0 for s in seq}
        row[seq[i]] = 0.5
        row[EOT_B] = 0.5
        rows[tuple(seq[:i])] = row
    model2 = FixedFixtureModel(alphabet_size=8, table=rows,
                                default={s: 0.0 for s in seq} | {EOT_B: 1.0})
    tok2 = BpeMergeTokenizer(merges, eot_symbol=EOT_B)
    alphabet_symbols2 = list(seq)  # EOT excluded, per module convention (see docstring)
    candidate2 = tuple(seq)
    gt2_result = cylinder_mass_ground_truth(model2, tok2, (), (), 1, candidate2,
                                             alphabet_symbols2, EOT_B, max_depth=200)
    gt2, gt2_bound = gt2_result.value, gt2_result.truncated_mass_bound
    bl2 = cylinder_mass_bounded_lookahead(model2, tok2, (), (), 1, candidate2,
                                           alphabet_symbols2, EOT_B, L_eff=7, max_depth=200)
    # horizon=None here too. ROOT-CAUSED (this fixture's own assertion was
    # originally wrong, not the oracle): `FixedFixtureModel.next_byte_probs`
    # resolves a context by LONGEST-SUFFIX match against `rows`, not full-
    # context match. Every `rows` key is a PREFIX starting with S0
    # ((), (S0,), (S0,S1), ... (S0..S5)) -- once the context passes length
    # 7 (the full candidate), no suffix of it matches any `rows` key except
    # occasionally a short trailing cascade, and eventually the EMPTY
    # suffix, which always matches `rows[()]` = {S0:0.5, EOT_B:0.5, ...}.
    # `default` (EOT_B:1.0) is therefore UNREACHABLE for this fixture: the
    # recursion never dies cleanly at depth 7, it re-enters the same
    # S0->S1->...->S6 cycle indefinitely (each further lap contributing
    # exactly 0 extra mass to `total`, since only the first lap's 7-token
    # sequence equals `candidate2`), and the numerical floor legitimately
    # catches the vanishing tail at depth 49 (measured
    # truncated_mass_bound=8.882e-16, i.e. ~0.5**50). This IS a genuine
    # floor-bite, structurally identical to counterexample 3's -- the
    # bound must be asserted < EQ_TOL (the honest contract), never an
    # exact-zero this fixture never actually guaranteed.
    cx2_ok = (abs(gt2 - ANALYTIC) < EQ_TOL and abs(bl2 - ANALYTIC) < EQ_TOL
              and gt2_bound < EQ_TOL)
    ok = ok and cx2_ok
    print(f"  [finite-lock cx2] tokenizer.safe_lock_horizon()={tok2.safe_lock_horizon()} "
          f"ground_truth={_fmt(gt2)} bounded_lookahead={_fmt(bl2)} "
          f"analytic={_fmt(ANALYTIC)} truncated_mass_bound={gt2_bound:.3e} "
          f"{'PASS' if cx2_ok else 'FAIL'}")
    print(f"PPM703_OWN_BPE_FINITE_LOCK_COUNTEREXAMPLE_PASS={cx2_ok}")

    # -- counterexample 3: the numerical-floor truncation genuinely FIRES ---
    # (issue #703 PR #759 coordinator gate note on the blocker-1 cure: "add
    # one fixture where the floor DOES bite (assert the bound reports it)").
    # Same memoryless {A, EOT} model as counterexample 1, but paired with an
    # EMPTY-merges BpeMergeTokenizer (safe_lock_horizon()=None ALWAYS,
    # regardless of the merges list -- see that method's docstring) instead
    # of a GreedyLongestMatchTokenizer. With no merges, segment() makes
    # every byte its own token, so token1 is deterministically (A,) whenever
    # the first document byte is A -- but with horizon=None there is NO
    # classification-lock shortcut at all (unlike counterexample 2's model,
    # this one's p_eot is exactly 0.5 at EVERY context, forever: it never
    # reaches a dead p_eot=1.0 state), so the recursion is bounded ONLY by
    # `prob_floor` -- it genuinely fires around depth ~49
    # (0.5**50 < 1e-15 < 0.5**49). Analytic P(token1 == (A,)) = 0.5 exactly
    # (derived: sum_{n=1}^inf 0.5**n * 0.5 = 0.5, i.e. P(first byte is A)).
    tok3 = BpeMergeTokenizer(merges=[], eot_symbol=EOT_A)
    candidate3 = (A,)
    gt3_result = cylinder_mass_ground_truth(model1, tok3, (), (), 1, candidate3,
                                             alphabet_symbols1, EOT_A, max_depth=200)
    gt3, gt3_bound = gt3_result.value, gt3_result.truncated_mass_bound
    ANALYTIC_3 = 0.5
    floor_bit = gt3_bound > 0.0  # the mechanism must report a genuinely NONZERO bound here
    bound_still_below_tol = gt3_bound < EQ_TOL  # yet the floor is tight enough not to matter
    value_still_accurate = abs(gt3 - ANALYTIC_3) < EQ_TOL
    cx3_ok = floor_bit and bound_still_below_tol and value_still_accurate
    ok = ok and cx3_ok
    print(f"  [finite-lock cx3, floor-bites] tokenizer.safe_lock_horizon()={tok3.safe_lock_horizon()} "
          f"ground_truth={_fmt(gt3)} analytic={_fmt(ANALYTIC_3)} "
          f"truncated_mass_bound={gt3_bound:.3e} "
          f"(floor_bit={floor_bit}, bound<{EQ_TOL:.0e}={bound_still_below_tol}, "
          f"value_accurate={value_still_accurate}) {'PASS' if cx3_ok else 'FAIL'}")
    print(f"PPM703_FLOOR_BITES_BOUND_EXPOSURE_PASS={cx3_ok}")

    return ok


def run_p1_global_mass_and_refusal() -> bool:
    """Mandatory-negative regression fixtures for the external re-audit's
    global-mass block (issue #703 PR #759, PR comment 4943538820, executed
    against the PRE-exposure head `299b3c2`): a ground-truth call whose
    numerical-floor path prunes MANY DISJOINT subtrees must report the SUM
    of every pruned subtree's own mass in `truncated_mass_bound` -- a
    single node's local floor value is not a bound on the whole call.
    `cylinder_mass_ground_truth`'s accumulator is `nonlocal` and shared by
    every branch of its internal `rec()`, so this was already structurally
    correct once `truncated_mass_bound` existed at all (08d3dc9, this PR's
    own prior repair round) -- verified below with the falsifier's exact
    adversarial construction as a PERMANENT fixture, not just a one-off
    scratch check.

    PPM703_GLOBAL_MASS_100_BRANCH_COUNTEREXAMPLE_PASS: 100 disjoint root
    branches, each reached with probability exactly 0.01 and no further
    positive-probability path to EOT (a valid but degenerate self-loop, so
    every branch is genuinely unresolved, not merely deep), prob_floor set
    to EXACTLY 0.01 so every one of the 100 branches is pruned at the
    first level past the root. `value` for ANY single-token candidate
    (here (0,), i.e. "is the realized first token exactly branch 0?") is
    0.0 -- honestly unresolved, since no branch was ever confirmed --
    while `truncated_mass_bound` must total ~1.0 (100 * 0.01), not 0.01
    (one branch's local floor) and not 0.0. The true analytic value for
    this candidate (0.01, since exactly one of the 100 disjoint branches
    can ever match token (0,)) is bracketed by [returned,
    returned+truncated_mass_bound] = [0.0, ~1.0] -- a SOUND but
    deliberately non-tight bound (the mechanism reports the true
    worst-case uncertainty across all pruned subtrees, not the tighter
    single-candidate truth, which is exactly what an upper bound is
    supposed to do). require_bound_within_tolerance MUST raise
    CylinderMassBoundExceeded on this result at the module's own EQ_TOL
    (1e-9) -- returning value=0.0 as if it were trustworthy at that
    precision would be exactly the silent-lying failure mode the
    coordinator's gate note named.

    PPM703_BOUND_REFUSAL_MECHANISM_PASS: a decoupled, non-recursive unit
    fixture for require_bound_within_tolerance itself -- constructs
    CylinderMassResult values directly (no model, no tokenizer, no
    recursion) and asserts the raise/pass-through boundary sits exactly
    at `bound > tolerance` in both directions, so the enforcement
    primitive's own correctness does not depend on any lattice fixture
    correctly reaching the numerical floor."""
    ok = True

    # -- 100-branch global-mass counterexample (falsifier's exact shape) ----
    N_BRANCHES = 100
    EOT_G = 100
    BRANCH_SYMS = list(range(N_BRANCHES))
    rows = {(): {s: 0.01 for s in BRANCH_SYMS}}
    for s in BRANCH_SYMS:
        # Deterministic self-loop past the root: p_eot=0 forever on this
        # branch (a valid, if degenerate, distribution) -- guarantees every
        # branch is genuinely UNRESOLVED when pruned, not merely deep.
        rows[(s,)] = {s: 1.0}
    model100 = FixedFixtureModel(alphabet_size=N_BRANCHES + 1, table=rows,
                                  default={EOT_G: 1.0})
    tok100 = BpeMergeTokenizer(merges=[], eot_symbol=EOT_G)  # safe_lock_horizon()=None always
    alphabet_symbols100 = list(BRANCH_SYMS)  # EOT excluded, per module convention
    TARGET_SYM = 0
    ANALYTIC_100 = 0.01  # P(first token is exactly branch 0) = P(root_sym=0)
    gt100_result = cylinder_mass_ground_truth(
        model100, tok100, (), (), 1, (TARGET_SYM,), alphabet_symbols100, EOT_G,
        max_depth=10, prob_floor=0.01)
    gt100, gt100_bound = gt100_result.value, gt100_result.truncated_mass_bound
    bracket_ok = gt100 <= ANALYTIC_100 <= gt100 + gt100_bound
    value_honest_ok = gt100 == 0.0
    bound_totals_100_branches_ok = abs(gt100_bound - N_BRANCHES * 0.01) < 1e-6
    refused = False
    try:
        require_bound_within_tolerance(gt100_result, EQ_TOL, label="100-branch global-mass")
    except CylinderMassBoundExceeded:
        refused = True
    global_mass_ok = (value_honest_ok and bound_totals_100_branches_ok and bracket_ok and refused)
    ok = ok and global_mass_ok
    print(f"  [global-mass 100-branch] n_branches={N_BRANCHES} prob_floor=0.01 "
          f"value={_fmt(gt100)} (honest-zero={value_honest_ok}) "
          f"truncated_mass_bound={gt100_bound:.6f} "
          f"(sums_100_branches={bound_totals_100_branches_ok}) "
          f"analytic={ANALYTIC_100} bracketed_in_[value,value+bound]={bracket_ok} "
          f"require_bound_within_tolerance_refuses={refused} "
          f"{'PASS' if global_mass_ok else 'FAIL'}")
    print(f"PPM703_GLOBAL_MASS_100_BRANCH_COUNTEREXAMPLE_PASS={global_mass_ok}")

    # -- bound-refusal mechanism, decoupled unit fixture ---------------------
    tight = CylinderMassResult(value=0.5, truncated_mass_bound=1e-12)
    loose = CylinderMassResult(value=0.5, truncated_mass_bound=0.3)
    tight_passthrough_ok = require_bound_within_tolerance(tight, EQ_TOL) is tight
    loose_refuses = False
    try:
        require_bound_within_tolerance(loose, EQ_TOL)
    except CylinderMassBoundExceeded:
        loose_refuses = True
    # a WIDER tolerance that the loose result's own bound satisfies must NOT refuse
    loose_passes_wide_tolerance_ok = require_bound_within_tolerance(loose, 0.5) is loose
    refusal_mech_ok = tight_passthrough_ok and loose_refuses and loose_passes_wide_tolerance_ok
    ok = ok and refusal_mech_ok
    print(f"  [bound-refusal mechanism] tight(bound=1e-12)_passthrough={tight_passthrough_ok} "
          f"loose(bound=0.3)_refuses_at_EQ_TOL={loose_refuses} "
          f"loose_passes_at_wider_tolerance_0.5={loose_passes_wide_tolerance_ok} "
          f"{'PASS' if refusal_mech_ok else 'FAIL'}")
    print(f"PPM703_BOUND_REFUSAL_MECHANISM_PASS={refusal_mech_ok}")

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
            gt_result = require_bound_within_tolerance(
                cylinder_mass_ground_truth(
                    case.model, case.tokenizer, case.boundary_bytes, case.boundary_tokens,
                    case.k, cand, case.alphabet_symbols, case.eot_symbol),
                EQ_TOL, label=f"P2-blend {case.name} candidate={cand}")
            gt, gt_bound = gt_result.value, gt_result.truncated_mass_bound
            denom = case.model.prefix_probability(case.boundary_bytes) if case.boundary_bytes else 1.0
            gt_conditional = gt / denom if denom > 0 else float("nan")
            diff = abs(blend_val - gt_conditional)
            bound_ok = gt_bound < EQ_TOL
            passed = diff < EQ_TOL and bound_ok
            ok = ok and passed
            details.append(
                f"  [{case.name}] candidate={cand} p_ppm_tok={_fmt(blend_val)} "
                f"ground_truth_conditional={_fmt(gt_conditional)} diff={diff:.3e} "
                f"truncated_mass_bound={gt_bound:.3e} "
                f"({'PASS' if bound_ok else 'FAIL'} < {EQ_TOL:.0e}) "
                f"{'PASS' if passed else 'FAIL'}")
    print("\n".join(details))
    print(f"PPM703_P2_BLEND_DEFINITION_PASS={ok}")
    return ok


def run_state_cap_assert() -> bool:
    ok = True

    # -- tier 1: tiny-cap sanity check (deterministic, fast) ----------------
    # Deliberately tiny cap so training a modest toy corpus overflows even
    # the CHEAP heuristic estimate deterministically. In practice tracemalloc
    # tracks PROCESS-WIDE allocations (the same methodology as the
    # coordinator's own fixture), so for a cap this small tier 2 (live) may
    # fire before tier 1 (heuristic) does -- the raised exception's own
    # message discloses which -- either is a legitimate PASS here; the
    # claim under test is only "the governor refuses at a tiny cap", not
    # "tier 1 specifically fires first".
    tiny_cap_bytes = 2000
    model_tiny = PpmModel(alphabet_size=257, order_cap=3, state_cap_bytes=tiny_cap_bytes)
    tier1_raised = False
    n_trained = 0
    try:
        state = 12345
        for i in range(200000):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            b = state % 256  # never emits EOT (256), stays mid-document
            model_tiny.train_symbol_stream_byte(b)
            n_trained += 1
    except PpmStateCapExceeded as e:
        tier1_raised = True
        print(f"  tier1 (heuristic-only, tiny cap): PpmStateCapExceeded raised "
              f"after {n_trained} symbols: {e}")
    ok = ok and tier1_raised
    print(f"  tier1 cap_bytes={tiny_cap_bytes} "
          f"approx_state_bytes_at_raise={model_tiny.approx_state_bytes()} "
          f"{'PASS' if tier1_raised else 'FAIL'}")

    # -- tier 2: mandatory-negative fixture -- process-wide governor --------
    # Reproduces the coordinator's exact fail-open counterexample
    # (PPM703_STATE_CAP_HEURISTIC_FAILOPEN_PASS, PR #759 coordinator gate):
    # order_cap=8, alphabet_size=257, bytes from random.Random(42),
    # state_cap_bytes=8,000,000. Measured: the OLD heuristic-only
    # `_check_cap` reported approx=4,496,152 (under cap) while tracemalloc
    # showed live=14,194,992 (well over cap) -- a fail-open on the decisive
    # statistic. `process_live_bytes_governor()` (honestly renamed from the
    # prior `live_state_bytes` per external re-audit PR comment 4943548456
    # -- see PPM703_FOREIGN_ALLOCATION_ISOLATION_PASS below for why the old
    # name was a defect) must catch this while the heuristic reading AT THE
    # MOMENT OF RAISE is STILL under cap -- proving the fix is a real
    # measurement, not a heuristic recalibration.
    cap_bytes = 8_000_000
    model_live = PpmModel(alphabet_size=257, order_cap=8, state_cap_bytes=cap_bytes)
    rng = random.Random(42)
    tier2_raised = False
    n_trained_live = 0
    try:
        for i in range(4000):
            model_live.train_symbol_stream_byte(rng.randrange(256))
            n_trained_live += 1
    except PpmStateCapExceeded as e:
        tier2_raised = True
        print(f"  tier2 (process-wide governor, coordinator fixture): "
              f"PpmStateCapExceeded raised after {n_trained_live} symbols: {e}")
    heuristic_at_raise = model_live.approx_state_bytes()
    live_at_raise = model_live.process_live_bytes_governor()
    heuristic_would_have_passed = heuristic_at_raise < cap_bytes
    live_actually_over_cap = live_at_raise > cap_bytes
    tier2_ok = tier2_raised and heuristic_would_have_passed and live_actually_over_cap
    ok = ok and tier2_ok
    print(f"  tier2 cap_bytes={cap_bytes} heuristic_at_raise={heuristic_at_raise} "
          f"(would_have_passed_alone={heuristic_would_have_passed}) "
          f"process_wide_at_raise={live_at_raise} (actually_over_cap={live_actually_over_cap}) "
          f"{'PASS' if tier2_ok else 'FAIL'}")

    # -- tier 3: foreign-allocation isolation (external re-audit, PR comment
    # 4943548456, executed against head 299b3c2): an unrelated 2MB
    # bytearray allocated BEFORE model construction must NOT appear in
    # isolated_ppm_state_bytes() (module-filtered, baseline-diffed), while
    # process_live_bytes_governor() (deliberately process-wide) DOES see it
    # -- proving the two are genuinely different quantities, not a rename
    # of the same number. Receipted old-code-fails: the pre-fix
    # live_state_bytes() included >99% of the foreign 2,000,000 bytes and
    # raised a false-positive PpmStateCapExceeded at symbol 52 while true
    # PPM state was 5,840 bytes.
    import tracemalloc as _tracemalloc_for_fixture
    if not _tracemalloc_for_fixture.is_tracing():
        _tracemalloc_for_fixture.start()
    foreign_bytearray = bytearray(2_000_000)
    model_foreign = PpmModel(alphabet_size=257, order_cap=8, state_cap_bytes=1_000_000)
    rng_foreign = random.Random(42)
    for i in range(99):
        model_foreign.train_symbol((i % 5,), rng_foreign.randrange(256))
    isolated_reading = model_foreign.isolated_ppm_state_bytes()
    process_wide_reading = model_foreign.process_live_bytes_governor()
    isolated_excludes_foreign_ok = isolated_reading < len(foreign_bytearray) * 0.1
    process_wide_includes_foreign_ok = process_wide_reading >= len(foreign_bytearray) * 0.9
    no_false_refusal_ok = isolated_reading < model_foreign.state_cap_bytes
    tier3_ok = isolated_excludes_foreign_ok and process_wide_includes_foreign_ok and no_false_refusal_ok
    ok = ok and tier3_ok
    print(f"  tier3 (foreign-allocation isolation) foreign_bytearray={len(foreign_bytearray)} "
          f"isolated_ppm_state_bytes={isolated_reading} "
          f"(excludes_foreign={isolated_excludes_foreign_ok}, "
          f"no_false_refusal={no_false_refusal_ok}) "
          f"process_live_bytes_governor={process_wide_reading} "
          f"(includes_foreign={process_wide_includes_foreign_ok}) "
          f"{'PASS' if tier3_ok else 'FAIL'}")
    print(f"PPM703_FOREIGN_ALLOCATION_ISOLATION_PASS={tier3_ok}")
    del foreign_bytearray  # release the fixture's own footprint promptly

    # -- tier 4: stable-context periodic-check interval semantics -----------
    # (external re-audit, PR comment 4943548456: "LIVE_CHECK_INTERVAL
    # counts _check_cap() calls on new nodes/entries, not training calls as
    # the docs claim"). order_cap=0 means every train_symbol call touches
    # exactly ONE node (the order-0 unigram); after the first call creates
    # it and its first counts entry, every FURTHER call with the SAME
    # symbol has was_new=False, so the OLD code's growth-triggered
    # _check_cap() -- the only place the old counter incremented -- was
    # invoked exactly twice in 500 calls (receipted old-code-fails:
    # _live_check_counter stuck at 2, LIVE_CHECK_INTERVAL=100 never
    # reached). _check_cap_periodic() now runs unconditionally at the tail
    # of every train_symbol call, so the interval fires on TRAINING CALLS
    # as documented -- proven here by counting invocations of
    # isolated_ppm_state_bytes() (wrapped) across >LIVE_CHECK_INTERVAL
    # stable-context calls, with state_cap_bytes set high enough that no
    # refusal interrupts the count.
    model_stable = PpmModel(alphabet_size=4, order_cap=0, state_cap_bytes=8_000_000_000)
    periodic_invocations = [0]
    _orig_isolated = model_stable.isolated_ppm_state_bytes

    def _counting_isolated():
        periodic_invocations[0] += 1
        return _orig_isolated()

    model_stable.isolated_ppm_state_bytes = _counting_isolated
    N_STABLE_CALLS = 500
    for i in range(N_STABLE_CALLS):
        model_stable.train_symbol((), 0)  # same (context, symbol) every call
    expected_min_invocations = N_STABLE_CALLS // model_stable.LIVE_CHECK_INTERVAL
    stable_context_ok = periodic_invocations[0] >= expected_min_invocations >= 1
    ok = ok and stable_context_ok
    print(f"  tier4 (stable-context periodic check) n_calls={N_STABLE_CALLS} "
          f"LIVE_CHECK_INTERVAL={model_stable.LIVE_CHECK_INTERVAL} "
          f"periodic_check_invocations={periodic_invocations[0]} "
          f"(expected>={expected_min_invocations}) "
          f"{'PASS' if stable_context_ok else 'FAIL'}")
    print(f"PPM703_STABLE_CONTEXT_PERIODIC_CHECK_PASS={stable_context_ok}")

    print(f"PPM703_STATE_CAP_ASSERT_PASS={ok}")
    return ok


def run_p0_domain_incidence() -> bool:
    ok = True

    # -- branch-b disposition: cite both receipts LIVE from disk -----------
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    citation = p0_branch_b_citation(repo_root)
    print(f"  branch={citation['branch']}")
    print(f"  declaration: {citation['declaration']}")
    for c in citation["citations"]:
        print(f"  cited {c['path']} [{c['field']}]:")
        print(f"    {c['quote']}")
    branch_ok = citation["branch"] == "b"
    ok = ok and branch_ok
    print(f"  branch-b citation live-verified: {'PASS' if branch_ok else 'FAIL'}")

    # -- census apparatus, synthetic positive-control corpus ----------------
    # Planted causes, independently hand-classified below: this proves the
    # COUNTING APPARATUS is correct, not any claim about the real corpus --
    # per branch b, original pre-tokenization-byte incidence stays
    # UNMEASURABLE in this checkout regardless of how well this apparatus
    # works.
    synthetic_docs = [
        b"hello world",              # clean ASCII, valid UTF-8, no NUL
        b"caf\xc3\xa9 resume",       # valid UTF-8 multi-byte (e-acute), no NUL
        b"bad\x00byte",              # NUL present (NUL is itself valid UTF-8
                                      # for U+0000 -- excluded for the NUL
                                      # cause, not the invalid-UTF-8 cause)
        b"\xff\xfe invalid",         # 0xFF is never a valid UTF-8 lead byte
        b"trunc\xe2\x82",            # truncated 3-byte sequence, incomplete
    ]
    expected_census = {"n_docs": 5, "nul_count": 1, "invalid_utf8_count": 2,
                        "excluded_count": 3}
    census = document_domain_census(synthetic_docs)
    census_ok = census == expected_census
    ok = ok and census_ok
    print(f"  census(synthetic positive control)={census} "
          f"expected={expected_census} {'PASS' if census_ok else 'FAIL'}")

    # -- RestrictedPpmModel unit checks (real 257-alphabet model) -----------
    EOT = 256
    base = PpmModel(alphabet_size=257, order_cap=4, eot_symbol=EOT)
    # Poison the training stream with NUL and an invalid lead byte (0xFF) so
    # the BASE model does assign them positive raw probability at some
    # contexts -- proving the wrapper below performs real exclusion, not a
    # no-op against bytes that never had mass to begin with.
    poison_stream = (list(b"hi hi hi ") + [195, 169] + list(b" hi")
                      + [0, 0, 255, 255] + list(b" hi hi"))
    for bnum in poison_stream:
        base.train_symbol_stream_byte(bnum)
    assert base.next_byte_probs(()).get(0, 0.0) > 0.0, \
        "test setup invalid: base model should assign NUL positive raw mass (poisoned)"
    assert base.next_byte_probs(()).get(255, 0.0) > 0.0, \
        "test setup invalid: base model should assign 0xFF positive raw mass (poisoned)"
    restricted = RestrictedPpmModel(base, eot_symbol=EOT)

    unit_checks = []
    for ctx, label in [((), "empty (boundary)"),
                        ((195,), "mid-sequence (after 0xC3 lead byte)"),
                        ((104, 105), "complete ASCII 'hi' (boundary)")]:
        probs = restricted.next_byte_probs(ctx)
        total = sum(probs.values())
        sums_to_one = abs(total - 1.0) < EQ_TOL
        nul_excluded = probs.get(0, 0.0) == 0.0
        checks = [sums_to_one, nul_excluded]
        detail = (f"  [{label}] ctx={ctx} sum={_fmt(total)} "
                  f"({'PASS' if sums_to_one else 'FAIL'}) "
                  f"NUL_excluded={'PASS' if nul_excluded else 'FAIL'}")
        if ctx == ():
            eot_present = probs.get(EOT, 0.0) > 0.0
            checks.append(eot_present)
            detail += f" EOT_present_at_boundary={'PASS' if eot_present else 'FAIL'}"
        if ctx == (195,):
            eot_absent = probs.get(EOT, 0.0) == 0.0
            cont_ok = probs.get(169, 0.0) > 0.0            # 0xA9: valid continuation of 0xC3
            noncont_excluded = probs.get(105, 0.0) == 0.0  # 'i': not a valid continuation byte
            checks += [eot_absent, cont_ok, noncont_excluded]
            detail += (f" EOT_absent_mid_seq={'PASS' if eot_absent else 'FAIL'} "
                       f"valid_continuation(0xA9)={'PASS' if cont_ok else 'FAIL'} "
                       f"invalid_continuation(0x69)_excluded={'PASS' if noncont_excluded else 'FAIL'}")
        if ctx == (104, 105):
            eot_present2 = probs.get(EOT, 0.0) > 0.0
            checks.append(eot_present2)
            detail += f" EOT_present_at_boundary={'PASS' if eot_present2 else 'FAIL'}"
        unit_checks.append(all(checks))
        print(detail)
    unit_ok = all(unit_checks)
    ok = ok and unit_ok

    # -- integration proof: composition into the UNMODIFIED marginalization
    # engine (exp703_marginalization.py) inherits the D-restriction with
    # zero code changes to that module --------------------------------------
    tokenizer = GreedyLongestMatchTokenizer(vocab=[(104, 105)], eot_symbol=EOT)
    # alphabet_symbols deliberately INCLUDES NUL and the invalid lead byte
    # 0xFF in the branching set the marginalization engine explores -- so
    # their zero contribution below is a property of the model (the
    # wrapper), not an artifact of never trying them.
    alphabet_symbols = [104, 105, 0, 255, EOT]
    # tokenizer is a GreedyLongestMatchTokenizer -> safe_lock_horizon() =
    # max_len = 2 (derived automatically, no verify_depth constant needed) ->
    # every branch below resolves via the exact classification-lock path,
    # so truncated_mass_bound must be exactly 0.0 for all three calls.
    gt_hi_result = require_bound_within_tolerance(
        cylinder_mass_ground_truth(restricted, tokenizer, (), (), 1, (104, 105),
                                    alphabet_symbols, EOT, max_depth=20),
        EQ_TOL, label="P0-domain-D candidate=(104,105)")
    gt_hi, gt_hi_bound = gt_hi_result.value, gt_hi_result.truncated_mass_bound
    bl_hi = cylinder_mass_bounded_lookahead(restricted, tokenizer, (), (), 1, (104, 105),
                                             alphabet_symbols, EOT, L_eff=2, max_depth=20)
    diff_hi = abs(gt_hi - bl_hi)
    bound_hi_ok = gt_hi_bound < EQ_TOL
    eq_ok = diff_hi < EQ_TOL and gt_hi > 0.0 and bound_hi_ok
    gt_nul_result = require_bound_within_tolerance(
        cylinder_mass_ground_truth(restricted, tokenizer, (), (), 1, (0,),
                                    alphabet_symbols, EOT, max_depth=20),
        EQ_TOL, label="P0-domain-D candidate=(0,)/NUL")
    gt_invalid_result = require_bound_within_tolerance(
        cylinder_mass_ground_truth(restricted, tokenizer, (), (), 1, (255,),
                                    alphabet_symbols, EOT, max_depth=20),
        EQ_TOL, label="P0-domain-D candidate=(255,)/invalid-lead-byte")
    gt_nul, gt_invalid = gt_nul_result.value, gt_invalid_result.value
    bound_zero_ok = gt_nul_result.truncated_mass_bound < EQ_TOL and gt_invalid_result.truncated_mass_bound < EQ_TOL
    zero_ok = gt_nul == 0.0 and gt_invalid == 0.0 and bound_zero_ok
    ok = ok and eq_ok and zero_ok
    print(f"  integration: cylinder_mass(candidate=(104,105)) ground_truth={_fmt(gt_hi)} "
          f"bounded_lookahead={_fmt(bl_hi)} diff={diff_hi:.3e} "
          f"truncated_mass_bound={gt_hi_bound:.3e} "
          f"{'PASS' if eq_ok else 'FAIL'}")
    print(f"  integration: cylinder_mass(candidate=(0,)/NUL)={_fmt(gt_nul)} "
          f"cylinder_mass(candidate=(255,)/invalid-lead-byte)={_fmt(gt_invalid)} "
          f"both-zero={'PASS' if zero_ok else 'FAIL'} "
          f"(exp703_marginalization.py UNCHANGED -- restriction inherited purely "
          f"by passing RestrictedPpmModel as the `model` argument)")

    print(f"PPM703_P0_DOMAIN_INCIDENCE_PASS={ok} branch={citation['branch']}")
    return ok


def run_p0_utf8_dfa_mandatory_fixtures() -> bool:
    """Mandatory-negative + mandatory-positive regression fixtures for issue
    #703 PR #759 coordinator gate blocker 3 UTF-8 repair defect (executed
    counterexample, marker PPM703_UTF8_FOUR_BYTE_BOUNDARY_COUNTEREXAMPLE_PASS):
    the OLD `restricted_next_byte_probs` derived the UTF-8 restriction state
    from `context[-3:]` decoded STANDALONE -- after a completed 4-byte
    codepoint (e.g. f0 9f 98 80, U+1F600) the trailing 3 bytes are bare
    continuation bytes with no lead byte in view, so the OLD code misread a
    FRESH boundary as a dead mid-sequence state and raised ZeroDivisionError
    on every valid document containing a 4-byte scalar.

    Receipt (scratchpad/verify_dfa_fixtures.py, run against the OLD
    `context[-3:]`-based code BEFORE this cure landed):
      REPRODUCED (OLD code fails as reported): restricted_next_byte_probs:
      prefix(D) support has zero PPM mass at context tail b'\\x9f\\x98\\x80'

    CURE (coordinator's preferred shape): `utf8_dfa_state_from_history`
    carries an EXPLICIT UTF-8 DFA state derived by simulating the DFA over
    the FULL context from a known start state, never by decoding a raw
    trailing suffix. Cross-validated exhaustively against CPython's own
    strict UTF-8 codec (13,440 (lead, first-continuation) pairs, 0
    mismatches) -- so RFC 3629 correctness (overlong encodings, the UTF-16
    surrogate range U+D800-U+DFFF, and code points > U+10FFFF) is inherited
    exactly, not re-derived.

    These fixtures are now PERMANENT."""
    ok = True
    EOT = 256

    # -- the exact reported crash, now fixed -------------------------------
    base = PpmModel(alphabet_size=257, order_cap=8, eot_symbol=EOT)
    for b in ('hello ' + chr(0x1F600) + ' world').encode('utf-8'):
        base.train_symbol_stream_byte(b)
    restricted = RestrictedPpmModel(base, eot_symbol=EOT)
    ctx_4byte = (0xF0, 0x9F, 0x98, 0x80)  # completed U+1F600
    try:
        probs = restricted.next_byte_probs(ctx_4byte)
        crash_fixed = abs(sum(probs.values()) - 1.0) < EQ_TOL and probs.get(EOT, 0.0) > 0.0
    except ZeroDivisionError:
        crash_fixed = False
    ok = ok and crash_fixed
    print(f"  [4-byte-boundary] restricted_next_byte_probs(completed U+1F600 context) "
          f"no-crash+EOT-allowed={crash_fixed} {'PASS' if crash_fixed else 'FAIL'}")
    print(f"PPM703_UTF8_FOUR_BYTE_BOUNDARY_COUNTEREXAMPLE_PASS={crash_fixed}")

    # -- mandatory positive: completed 1/2/3/4-byte codepoints permit ASCII+EOT
    completed_cases = {
        "1-byte ASCII": (ord("h"),),
        "2-byte (c3 a9, e-acute)": (0xC3, 0xA9),
        "3-byte (e2 82 ac, euro sign)": (0xE2, 0x82, 0xAC),
        "4-byte (f0 9f 98 80, U+1F600)": (0xF0, 0x9F, 0x98, 0x80),
    }
    completed_ok = True
    for label, ctx in completed_cases.items():
        state = utf8_dfa_state_from_history(ctx, EOT)
        allowed = allowed_next_bytes_from_state(state, EOT)
        row_ok = state == UTF8_READY and EOT in allowed and ord("h") in allowed
        completed_ok = completed_ok and row_ok
        print(f"  [completed-codepoint] {label} state={state} "
              f"EOT_allowed={EOT in allowed} ascii_allowed={ord('h') in allowed} "
              f"{'PASS' if row_ok else 'FAIL'}")
    ok = ok and completed_ok

    # -- mandatory: partial lead states permit ONLY the correct continuation
    # range and forbid EOT (also exercises the overlong/surrogate/>10FFFF
    # RESTRICTED first-continuation ranges directly)
    partial_cases = {
        "after 0xC2 (2-byte)": ((0xC2,), 0x80, 0xBF),
        "after 0xE0 (3-byte, bans overlong)": ((0xE0,), 0xA0, 0xBF),
        "after 0xED (3-byte, bans surrogates U+D800-U+DFFF)": ((0xED,), 0x80, 0x9F),
        "after 0xF0 (4-byte, bans overlong)": ((0xF0,), 0x90, 0xBF),
        "after 0xF4 (4-byte, bans > U+10FFFF)": ((0xF4,), 0x80, 0x8F),
    }
    partial_ok = True
    for label, (ctx, lo, hi) in partial_cases.items():
        state = utf8_dfa_state_from_history(ctx, EOT)
        allowed = allowed_next_bytes_from_state(state, EOT)
        row_ok = allowed == set(range(lo, hi + 1)) and EOT not in allowed
        partial_ok = partial_ok and row_ok
        print(f"  [partial-lead] {label} allowed=={{0x{lo:02x}..0x{hi:02x}}}={allowed == set(range(lo, hi + 1))} "
              f"EOT_forbidden={EOT not in allowed} {'PASS' if row_ok else 'FAIL'}")
    ok = ok and partial_ok

    # -- mandatory: the READY-state rejection set carries zero mass ---------
    allowed_ready = allowed_next_bytes_from_state(UTF8_READY, EOT)
    reject_bytes = {0xC0: "overlong 2-byte lead", 0xC1: "overlong 2-byte lead",
                    0xF5: "invalid lead (>U+10FFFF)", 0xFF: "invalid lead",
                    0x80: "bare continuation byte", 0x00: "NUL"}
    reject_ok = all(b not in allowed_ready for b in reject_bytes)
    ok = ok and reject_ok
    print(f"  [rejection-set] READY-state excludes {list(hex(b) for b in reject_bytes)}: "
          f"{'PASS' if reject_ok else 'FAIL'}")

    # -- mandatory: DFA state survives PPM order-cap truncation --------------
    # order_cap=2: the UNDERLYING model has no memory beyond 2 bytes, but the
    # wrapper receives the FULL context tuple regardless (PpmModel.next_byte_
    # probs' own contract: context = "bytes since the last EOT/document
    # start", truncated internally for trie lookups only) -- so the DFA
    # state derivation must stay correct even when order_cap << 4.
    base_tiny = PpmModel(alphabet_size=257, order_cap=2, eot_symbol=EOT)
    for b in ("x " + chr(0x1F600) + " y").encode("utf-8"):
        base_tiny.train_symbol_stream_byte(b)
    restricted_tiny = RestrictedPpmModel(base_tiny, eot_symbol=EOT)
    try:
        probs_tiny = restricted_tiny.next_byte_probs(ctx_4byte)
        order_cap_ok = (abs(sum(probs_tiny.values()) - 1.0) < EQ_TOL
                         and probs_tiny.get(EOT, 0.0) > 0.0)
    except Exception:
        order_cap_ok = False
    ok = ok and order_cap_ok
    print(f"  [order-cap-survival] order_cap=2, 4-byte-back completed codepoint: "
          f"{'PASS' if order_cap_ok else 'FAIL'}")

    # -- cross-check: hand-rolled DFA matches CPython's strict UTF-8 codec --
    # exhaustively, over every (lead, first-continuation) byte pair -- so
    # RFC 3629 correctness is verified, not assumed.
    mismatches = 0
    checks = 0
    for lead in range(256):
        py_lead_ok = is_valid_utf8_prefix(bytes([lead]))
        my_lead = _lead_transition(lead)
        checks += 1
        if py_lead_ok != (my_lead is not None):
            mismatches += 1
            continue
        if not py_lead_ok or my_lead == UTF8_READY:
            continue
        for cont1 in range(256):
            py_ok = is_valid_utf8_prefix(bytes([lead, cont1]))
            my_ok = utf8_dfa_step(my_lead, cont1) is not None
            checks += 1
            if py_ok != my_ok:
                mismatches += 1
    dfa_matches_codec = mismatches == 0
    ok = ok and dfa_matches_codec
    print(f"  [codec-cross-check] {checks} (lead[,first-continuation]) transitions vs "
          f"CPython's utf-8 codec: mismatches={mismatches} {'PASS' if dfa_matches_codec else 'FAIL'}")

    print(f"PPM703_UTF8_DFA_RFC3629_MANDATORY_FIXTURES_PASS={ok}")
    return ok


def main() -> int:
    results = []
    print("=== PPM703 P0 domain-D incidence (AMENDMENT-1 + AMENDMENT-1a, branch b) ===")
    results.append(run_p0_domain_incidence())
    print()
    print("=== PPM703 P1 exhaustive equality (ground truth vs bounded lookahead) ===")
    results.append(run_p1_exhaustive_equality())
    print()
    print("=== PPM703 P1 naive-renorm negative control ===")
    results.append(run_p1_naive_renorm_negative_control())
    print()
    print("=== PPM703 P1 finite-lock counterexamples (mandatory negatives) ===")
    results.append(run_p1_finite_lock_counterexamples())
    print()
    print("=== PPM703 P1 global-mass counterexample + bound-refusal mechanism ===")
    results.append(run_p1_global_mass_and_refusal())
    print()
    print("=== PPM703 P2 blend definition (P_ppm_tok) vs ground truth ===")
    results.append(run_p2_blend_definition())
    print()
    print("=== PPM703 state cap hard assert ===")
    results.append(run_state_cap_assert())
    print()
    print("=== PPM703 UTF-8 DFA RFC3629 mandatory fixtures ===")
    results.append(run_p0_utf8_dfa_mandatory_fixtures())
    print()
    all_ok = all(results)
    print(f"PPM703_SELFTEST_ALL_PASS={all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
