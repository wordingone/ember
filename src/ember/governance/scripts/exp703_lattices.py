#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
#703 PPM apparatus, stage 1: toy tokenizers + the P2 adversarial-lattice
fixtures (issue #703 coordinator comment 4942030643, section 4 "P2
Adversarial-lattice normalization proof").

Frozen prereg text requires, by name:
  (i)   nested vocab tokens (prefix-antichain case)
  (ii)  boundary-spanning tokens
  (iii) the EOF/EOT case
  (iv)  a pre-splitter case if P1 finds one
  (v)   a toy BPE-WITH-MERGES lattice matching the real tokenizer's class
        (tiny vocab + tiny merge table, seg(.) = the real merge-order
        algorithm, exhaustively enumerated)

Case (i)'s numeric fixture is NOT invented here: it is the coordinator's own
"BLOCK_NAIVE_BYTE_STRING_RENORMALIZATION / CLEAR_TOKENIZER_EVENT_LATTICE"
fixture, re-derived verbatim from issue #703 (pre-implementation amendment
comment): vocab {a, ab, b}; byte LM P(a)=.5, P(b)=.5, P(a|a)=.1, P(b|a)=.9;
naive per-token renormalization L1 error = 0.589655. This module builds the
exact FixedFixtureModel + GreedyLongestMatchTokenizer reproducing those
numbers so exp703_marginalization.py / exp703_selftest.py can assert against
them directly rather than against a re-derived approximation.

Cases (ii)-(v) are original toy constructions (this fixture set did not
pre-exist in the repo/issue thread beyond case (i); confirmed by search).
Case (iv) is a GENERIC pre-splitter construction, not tied to any specific
real-tokenizer finding -- AMENDMENT-1 to the frozen prereg (2026-07-11)
states "P1/P2 toy-lattice machinery is unaffected (toy tokenizers are fully
specified constructions)", so this generic construction is in-contract; the
real tokenizer's own pre-splitter behaviour is a separate P1-tokenizer-
contract deliverable outside this PR's scope (no eval pass, no real
tokenizer read here).

All toy alphabets use symbol 0 = EOT is NOT assumed; each lattice defines its
own `eot_symbol` explicitly (kept out-of-band from the "readable" a/b/x/y/z
symbols for clarity in comments below).
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Toy conditional byte model with an explicit, hand-specified lookup table.
# Implements the SAME `next_byte_probs(context) -> dict[int, float]` protocol
# as exp703_ppm_model.PpmModel, so the marginalization engine is agnostic to
# whether it is fed a trained PPM or a fixed fixture table.
# ---------------------------------------------------------------------------
class FixedFixtureModel:
    def __init__(self, alphabet_size: int, table: dict, default: dict | None = None,
                 tol: float = 1e-9):
        self.alphabet_size = alphabet_size
        self.table = table
        self.default = default if default is not None else {
            s: 1.0 / alphabet_size for s in range(alphabet_size)
        }
        for ctx, row in table.items():
            total = sum(row.values())
            if abs(total - 1.0) > tol:
                raise ValueError(f"fixture row for context {ctx} sums to {total}, not 1.0")
            for s in row:
                if not (0 <= s < alphabet_size):
                    raise ValueError(f"fixture row {ctx} references out-of-range symbol {s}")
        dtotal = sum(self.default.values())
        if abs(dtotal - 1.0) > tol:
            raise ValueError(f"default row sums to {dtotal}, not 1.0")

    def next_byte_probs(self, context: tuple) -> dict:
        for L in range(len(context), -1, -1):
            key = context[len(context) - L:]
            if key in self.table:
                return self.table[key]
        return self.default

    def prefix_probability(self, byte_seq) -> float:
        """Same interface as PpmModel.prefix_probability: exact chain-rule
        probability of `byte_seq` from an empty context (no per-document
        EOT reset mid-sequence -- lattice tests never need it)."""
        context: tuple = ()
        prob = 1.0
        for b in byte_seq:
            probs = self.next_byte_probs(context)
            p = probs.get(b, 0.0)
            prob *= p
            if prob == 0.0:
                return 0.0
            context = context + (b,)
        return prob


# ---------------------------------------------------------------------------
# Toy tokenizers
# ---------------------------------------------------------------------------
class GreedyLongestMatchTokenizer:
    """Standard greedy-longest-match segmenter over a fixed vocab of symbol
    tuples. Operates on a COMPLETE finite symbol sequence that must end in
    `eot_symbol`; returns the list of tokens (each a tuple of symbols) with a
    final single-element EOT token appended."""

    def __init__(self, vocab: list[tuple], eot_symbol: int):
        self.vocab = sorted(set(vocab), key=len, reverse=True)
        self.eot_symbol = eot_symbol
        self.max_len = max((len(v) for v in self.vocab), default=1)

    def safe_lock_horizon(self) -> int:
        """PROVEN sufficient lookahead depth for classification-locking: a
        greedy-longest-match decision at any position is made within
        `max_len` bytes of examination (either a vocab entry of length
        <= max_len matches, or matching fails at every length down to 1 and
        falls back to a single byte) and, once made, is NEVER revisited by
        later bytes (greedy matching is strictly left-to-right, no
        backtracking). So verifying `is_target` is constant across every
        continuation up to `max_len` MORE bytes is a complete proof, not a
        depth-limited sample -- this is what
        exp703_marginalization.cylinder_mass_ground_truth uses in place of
        a fixed `verify_depth` constant (issue #703 PR #759 coordinator gate
        blocker 1, PPM703_FINITE_LOCK_COUNTEREXAMPLE_PASS: a 7-symbol vocab
        entry needs exactly 7 bytes of lookahead; a fixed default of 6
        undershoots by one and produces a premature false lock)."""
        return self.max_len

    def segment(self, symbols: tuple) -> list:
        assert symbols and symbols[-1] == self.eot_symbol, \
            "GreedyLongestMatchTokenizer.segment requires an EOT-terminated input"
        body = symbols[:-1]
        tokens = []
        i = 0
        n = len(body)
        while i < n:
            matched = None
            for length in range(min(self.max_len, n - i), 0, -1):
                cand = body[i:i + length]
                if cand in self.vocab:
                    matched = cand
                    break
            if matched is None:
                # byte-fallback: every single symbol is assumed a valid
                # unigram token (toy vocabs below always include singletons).
                matched = body[i:i + 1]
            tokens.append(matched)
            i += len(matched)
        tokens.append((self.eot_symbol,))
        return tokens


class BpeMergeTokenizer:
    """Toy BPE-with-merges segmenter: starts from atomic base symbols and
    repeatedly applies the HIGHEST-PRIORITY (earliest-listed) mergeable
    adjacent pair present anywhere in the sequence, merging ALL non-
    overlapping leftmost occurrences of that pair per pass, until no listed
    merge applies. This is seg(.) = the real merge-order algorithm the
    frozen prereg names as mandatory for lattice (v) -- priority is
    global-pair-first, not local/greedy-longest-match, so it can (and here
    deliberately does) diverge from a longest-match tokenizer over the same
    surface vocab. An optional `pre_splitter` set of symbols blocks merges
    from crossing a pre-token boundary (lattice iv), matching the frozen
    prereg's "L_eff clips at the pre-token boundary" note for the real
    tokenizer's class."""

    def __init__(self, merges: list[tuple], eot_symbol: int,
                 pre_splitter_symbols: frozenset = frozenset()):
        # merges: ordered list of (left, right) merge rules, left/right are
        # symbol-tuples (atomic or already-merged), highest priority first.
        self.merges = list(merges)
        self.eot_symbol = eot_symbol
        self.pre_splitter_symbols = pre_splitter_symbols

    def safe_lock_horizon(self):
        """NO sound static bound in general: merge priority is evaluated
        over the WHOLE open chunk (everything since the last pre-splitter
        symbol or document start), and a chunk can grow arbitrarily long
        before a pre-splitter or EOT closes it -- a merge decision at
        position 0 can depend on bytes arbitrarily far ahead (issue #703 PR
        #759 coordinator gate blocker 1,
        PPM703_OWN_BPE_FINITE_LOCK_COUNTEREXAMPLE_PASS: a 7-base-symbol,
        6-merge cascade needs exactly 7 bytes of lookahead, and there is no
        vocab-length-style constant to derive it from ahead of time).
        Returning None tells the exhaustive oracle to apply NO
        depth-limited lock shortcut and instead recurse genuinely until
        each branch reaches a real, materialized token-boundary-closing
        event (a real pre-splitter emission or a real EOT) -- exactly the
        module's own documented 'dumb, unpruned, recurse to true EOT'
        design goal, for the tokenizer class it was always meant for."""
        return None

    def _pre_split(self, body: tuple) -> list[list]:
        chunks: list[list] = [[]]
        for s in body:
            if s in self.pre_splitter_symbols:
                chunks.append([(s,)])
                chunks.append([])
            else:
                chunks[-1].append((s,))
        return [c for c in chunks if c]

    def _merge_chunk(self, symbols: list) -> list:
        seq = list(symbols)
        changed = True
        while changed:
            changed = False
            for (left, right) in self.merges:
                i = 0
                out = []
                merged_here = False
                while i < len(seq):
                    if i + 1 < len(seq) and seq[i] == left and seq[i + 1] == right:
                        out.append(left + right)
                        i += 2
                        merged_here = True
                    else:
                        out.append(seq[i])
                        i += 1
                seq = out
                if merged_here:
                    changed = True
                    break  # restart from highest priority after any merge (standard BPE)
        return seq

    def segment(self, symbols: tuple) -> list:
        assert symbols and symbols[-1] == self.eot_symbol, \
            "BpeMergeTokenizer.segment requires an EOT-terminated input"
        body = symbols[:-1]
        tokens: list = []
        for chunk in self._pre_split(body):
            tokens.extend(self._merge_chunk(chunk))
        tokens.append((self.eot_symbol,))
        return tokens


# ---------------------------------------------------------------------------
# Lattice case definitions
# ---------------------------------------------------------------------------
@dataclass
class LatticeCase:
    name: str
    alphabet_size: int
    eot_symbol: int
    alphabet_symbols: list  # non-EOT symbols, for enumeration convenience
    model: object
    tokenizer: object
    boundary_bytes: tuple      # bytes since document start fixing F_{k-1}
    boundary_tokens: tuple     # the k-1 tokens realized by boundary_bytes
    k: int                     # position being tested
    candidates: list           # list of token-tuples to test at position k
    L_eff: int                 # bounded-lookahead depth bound for this case
    expected: dict | None = None  # optional known-exact expected masses


def case_i_prefix_antichain() -> LatticeCase:
    """(i) nested vocab tokens / prefix-antichain -- the frozen coordinator
    fixture, reproduced verbatim: vocab {a, ab, b}, byte LM P(a)=.5, P(b)=.5,
    P(a|a)=.1, P(b|a)=.9. a=0, b=1, EOT=2."""
    A, B, EOT = 0, 1, 2
    model = FixedFixtureModel(
        alphabet_size=3,
        table={
            (): {A: 0.5, B: 0.5, EOT: 0.0},
            (A,): {A: 0.1, B: 0.9, EOT: 0.0},
        },
        default={A: 1.0 / 3, B: 1.0 / 3, EOT: 1.0 / 3},
    )
    vocab = [(A,), (A, B), (B,)]
    tok = GreedyLongestMatchTokenizer(vocab, eot_symbol=EOT)
    return LatticeCase(
        name="i_prefix_antichain",
        alphabet_size=3, eot_symbol=EOT, alphabet_symbols=[A, B],
        model=model, tokenizer=tok,
        boundary_bytes=(), boundary_tokens=(), k=1,
        candidates=[(A,), (A, B), (B,)],
        L_eff=2,
        expected={(A,): 0.05, (A, B): 0.45, (B,): 0.50},
    )


def case_ii_boundary_spanning() -> LatticeCase:
    """(ii) boundary-spanning tokens: vocab {a, b, ab, ba, aba}. A document
    prefix realizes token1="ab" via greedy longest match (which requires the
    3rd byte to NOT be 'a', else "aba" -- the longer, boundary-SPANNING
    token -- would have been chosen instead). Token2 is then tested over the
    remaining bytes, verifying F_1's conditioning correctly excludes the
    continuations where the spanning token "aba" would have applied.
    a=0, b=1, EOT=2."""
    A, B, EOT = 0, 1, 2
    model = FixedFixtureModel(
        alphabet_size=3,
        table={
            (): {A: 0.4, B: 0.6, EOT: 0.0},
            (A,): {A: 0.3, B: 0.7, EOT: 0.0},
            (A, B): {A: 0.0, B: 1.0, EOT: 0.0},  # byte 3 forced != A for F_1="ab" to hold
        },
        default={A: 0.3, B: 0.3, EOT: 0.4},
    )
    vocab = [(A,), (B,), (A, B), (B, A), (A, B, A)]
    tok = GreedyLongestMatchTokenizer(vocab, eot_symbol=EOT)
    # boundary: token1 = "ab" (A,B) -- realized by bytes (A,B) with byte3 != A
    # (guaranteed since table[(A,B)] forces B with prob 1.0, EOT 0).
    boundary_bytes = (A, B)
    boundary_tokens = ((A, B),)
    return LatticeCase(
        name="ii_boundary_spanning",
        alphabet_size=3, eot_symbol=EOT, alphabet_symbols=[A, B],
        model=model, tokenizer=tok,
        boundary_bytes=boundary_bytes, boundary_tokens=boundary_tokens, k=2,
        candidates=[(B,), (B, A)],
        L_eff=2,
        expected=None,  # verified via ground-truth cross-check, not hand-derived
    )


def case_iii_eot_event() -> LatticeCase:
    """(iii) the EOF/EOT case: candidate at position k is EOT itself (the
    document ends exactly there), testing that EOT is scored as its own
    terminal event with zero further lookahead. a=0, b=1, EOT=2."""
    A, B, EOT = 0, 1, 2
    model = FixedFixtureModel(
        alphabet_size=3,
        table={
            (): {A: 0.45, B: 0.45, EOT: 0.10},
            (A,): {A: 0.2, B: 0.3, EOT: 0.5},
        },
        default={A: 0.3, B: 0.3, EOT: 0.4},
    )
    vocab = [(A,), (B,)]
    tok = GreedyLongestMatchTokenizer(vocab, eot_symbol=EOT)
    boundary_bytes = (A,)
    boundary_tokens = ((A,),)
    return LatticeCase(
        name="iii_eot_event",
        alphabet_size=3, eot_symbol=EOT, alphabet_symbols=[A, B],
        model=model, tokenizer=tok,
        boundary_bytes=boundary_bytes, boundary_tokens=boundary_tokens, k=2,
        candidates=[(A,), (B,), (EOT,)],  # full event partition at position k=2:
        # a regular vocab token, the other regular vocab token, and the
        # "document ends at k" terminal event -- all three needed for the
        # Sigma_t P_ppm_tok(t|F) = 1 completeness check.
        L_eff=2,
        # expected values are JOINT masses P_ppm(E_k(t) n F_{k-1}), i.e.
        # P_ppm(F_1) * P_ppm(EOT | context=A) = 0.45 * 0.5 = 0.225 -- NOT
        # the conditional P_ppm_tok (0.5), which is checked separately in
        # run_p2_blend_definition.
        expected={(EOT,): 0.225},
    )


def case_iv_v_bpe_with_presplitter() -> LatticeCase:
    """(iv)+(v) combined: a toy BPE-with-merges lattice under a regex-style
    pre-splitter (a reserved delimiter symbol 'DELIM' that merges never cross
    -- matching the real tokenizer's documented class per the frozen prereg's
    P1 note "dependence clips at the pre-token boundary"), with a genuine
    PRIORITY-ORDER merge cascade that a greedy-longest-match reading of the
    same surface vocab would get WRONG (the prereg's named failure mode).

    Base alphabet: x=0, y=1, z=2, DELIM=3, EOT=4.
    Merge table (priority order, highest first):
      1. (y,)+(z,) -> (y,z)      ["yz" merges before "xy"]
      2. (x,)+(y,) -> (x,y)      [lower priority]
    For "xyz": merge (y,z) fires first (present, highest priority) -> [x, yz].
    No further merge ((x,yz) is not a listed rule) -> final tokens [x, yz].
    A greedy-longest-match reader using surface vocab {x,y,z,xy,yz} would
    instead pick the LONGEST match at position 0 ("xy", since it matches),
    yielding [xy, z] -- a DIFFERENT (wrong, if applied to this tokenizer's
    output) segmentation. This is the exact failure class named in the
    prereg: "a trie-frontier fast path correct for greedy segmentation and
    wrong under merge order would otherwise pass every named lattice and
    ship self-consistent wrong numbers no downstream kill can catch."
    """
    X, Y, Z, DELIM, EOT = 0, 1, 2, 3, 4
    model = FixedFixtureModel(
        alphabet_size=5,
        table={
            (): {X: 0.6, Y: 0.0, Z: 0.0, DELIM: 0.0, EOT: 0.4},
            (X,): {X: 0.0, Y: 0.7, Z: 0.0, DELIM: 0.0, EOT: 0.3},
            (X, Y): {X: 0.0, Y: 0.0, Z: 0.8, DELIM: 0.0, EOT: 0.2},
        },
        default={X: 0.2, Y: 0.2, Z: 0.2, DELIM: 0.2, EOT: 0.2},
    )
    merges = [((Y,), (Z,)), ((X,), (Y,))]
    tok = BpeMergeTokenizer(merges, eot_symbol=EOT, pre_splitter_symbols=frozenset([DELIM]))
    return LatticeCase(
        name="iv_v_bpe_presplitter",
        alphabet_size=5, eot_symbol=EOT, alphabet_symbols=[X, Y, Z, DELIM],
        model=model, tokenizer=tok,
        boundary_bytes=(), boundary_tokens=(), k=1,
        candidates=[(X,), (X, Y), (Y, Z)],
        L_eff=3,
        expected=None,  # verified via ground-truth cross-check
    )


ALL_CASES = [
    case_i_prefix_antichain,
    case_ii_boundary_spanning,
    case_iii_eot_event,
    case_iv_v_bpe_with_presplitter,
]
